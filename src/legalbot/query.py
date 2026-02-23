"""Query analysis: detect acts and section references, expand old-code references via the
concordance, and decide the metadata filters for retrieval."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .concordance import Concordance
from .registry import ActRegistry
from .schema import SearchFilters, Status

_NUM = r"(?<![\d.])(\d{1,3}[A-Z]{0,2})(?![\dA-Za-z])"
_SEC = r"(?:\bsections?\b|\bsec\.?|§)"


class QueryPlan(BaseModel):
    original: str
    search_query: str
    filters: SearchFilters = Field(default_factory=SearchFilters)
    mentioned_acts: list[str] = Field(default_factory=list)
    explicit_sections: list[tuple[str, str]] = Field(default_factory=list)  # (act_id, section_no) to pin
    mapped_refs: list[tuple[str, str]] = Field(default_factory=list)  # old and new refs from the concordance
    removed_refs: list[tuple[str, str]] = Field(default_factory=list)  # old sections deleted with no successor
    notes: list[str] = Field(default_factory=list)


class QueryAnalyzer:
    def __init__(self, registry: ActRegistry, concordance: Concordance):
        self.registry = registry
        self.concordance = concordance
        act = registry.alias_pattern
        flags = re.IGNORECASE
        self._p_sec_first = re.compile(
            rf"{_SEC}\s*{_NUM}(?:\s*\([^)]+\))*(?:\s*(?:of|under|in)\s+(?:the\s+)?(?P<act>{act}))?", flags
        )
        self._p_act_first = re.compile(rf"(?P<act>{act})\s*(?:{_SEC})?\s*{_NUM}", flags)
        self._p_num_first = re.compile(rf"{_NUM}(?:\s*\([^)]+\))*\s*(?:of\s+)?(?P<act>{act})", flags)

    def _section_refs(self, query: str, mentioned: list[str]) -> list[tuple[str | None, str]]:
        found: list[tuple[str | None, str]] = []
        for pattern in (self._p_sec_first, self._p_act_first, self._p_num_first):
            for m in pattern.finditer(query):
                num = next(g for g in m.groups() if g and re.match(r"\d", g)).upper()
                alias = m.group("act")
                act_id = self.registry.resolve(re.sub(r"\s+", " ", alias)) if alias else None
                found.append((act_id, num))
        # bare "section 103" with exactly one act in the query belongs to that act
        resolved = [(a or (mentioned[0] if len(mentioned) == 1 else None), n) for a, n in found]
        out: list[tuple[str | None, str]] = []
        for ref in resolved:
            if ref not in out and not (ref[0] is None and any(n == ref[1] and a for a, n in resolved)):
                out.append(ref)
        return out

    def plan(self, query: str) -> QueryPlan:
        mentioned = self.registry.find_in_text(query)
        refs = self._section_refs(query, mentioned)

        explicit: list[tuple[str, str]] = []
        mapped: list[tuple[str, str]] = []
        removed: list[tuple[str, str]] = []
        notes: list[str] = []
        extra_terms: list[str] = []
        target_acts: list[str] = []

        for act_id, sec in refs:
            if act_id is None:
                continue
            if (act_id, sec) not in explicit:
                explicit.append((act_id, sec))
            for m in self.concordance.forward(act_id, sec):
                old = self.registry.get(m.old_act).short
                new = self.registry.get(m.new_act).short
                flag = "" if m.verified else " (unverified mapping)"
                notes.append(f"{old} §{m.old_section} corresponds to {new} §{m.new_ref}: {m.note}{flag}.")
                if (m.new_act, m.new_section) not in explicit:
                    explicit.append((m.new_act, m.new_section))
                mapped += [(m.old_act, m.old_section), (m.new_act, m.new_section)]
                extra_terms.append(f"{new} section {m.new_section} {m.note}")
                if m.new_act not in target_acts:
                    target_acts.append(m.new_act)
            gone = self.concordance.removed(act_id, sec)
            if gone is not None:
                old = self.registry.get(gone.old_act).short
                label = f" ({gone.title})" if gone.title else ""
                flag = "" if gone.verified else " (unverified)"
                notes.append(
                    f"{old} §{gone.old_section}{label} has no equivalent in the new code: the official comparison "
                    f"table lists it as deleted{flag}. Do not present another section as its replacement unless a source says so."
                )
                removed.append((gone.old_act, gone.old_section))
                mapped.append((gone.old_act, gone.old_section))
            for m in self.concordance.backward(act_id, sec):
                old = self.registry.get(m.old_act).short
                new = self.registry.get(m.new_act).short
                flag = "" if m.verified else " (unverified mapping)"
                notes.append(f"{new} §{m.new_ref} replaced {old} §{m.old_section}{flag}.")
                mapped += [(m.old_act, m.old_section), (m.new_act, m.new_section)]

        # Filters: if the user names acts, stay inside them (plus their modern equivalents);
        # otherwise search only provisions that are currently in force.
        act_filter = [a for a in [*mentioned, *target_acts] if a in self.registry]
        act_filter = list(dict.fromkeys(act_filter))
        filters = SearchFilters(act_ids=act_filter) if act_filter else SearchFilters(statuses=[Status.IN_FORCE])

        search_query = " ".join([query, *extra_terms]).strip()
        return QueryPlan(
            original=query,
            search_query=search_query,
            filters=filters,
            mentioned_acts=mentioned,
            explicit_sections=explicit,
            mapped_refs=list(dict.fromkeys(mapped)),
            removed_refs=list(dict.fromkeys(removed)),
            notes=notes,
        )
