"""Retrieval-time context expansion.

Ranking decides WHICH sections are relevant; expansion decides what else the model must see to
read them correctly. It runs after search and never changes the ranked list itself, so
`legalbot eval` keeps measuring search quality and nothing else.

Three kinds of extra context, each tagged on the Hit (`source` + `via`) so the prompt, the API
and the UI can say why a section is there:

  sibling     - the other parts of a section that was split at ingest time
  xref        - a section the hit explicitly points to ("as provided in section 101")
  definition  - the single clause of the Act's definitions section that defines a term the hit uses

Extras are added only while they fit in `max_chars`, in that order of priority.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .chunking.statute import NUM_RE, UNIT_START_RE, XREF_RE
from .registry import ActRegistry
from .schema import Hit, LegalChunk
from .store import QdrantStore

# "section 6 of the General Clauses Act, 1897" / "section 474 of the Bharatiya Nagarik Suraksha Sanhita"
_OTHER_ACT_RE = re.compile(
    r"^\s*(?:,\s*)?(?:sub-?sections?\s*\([^)]*\)\s*)?of\s+(?:the\s+)?"
    r"(?P<name>[A-Z][A-Za-z’' ]{2,80}?(?:Act|Sanhita|Adhiniyam|Code|Constitution)\b(?:,?\s*\d{4})?)"
)
_THIS_ACT_RE = re.compile(r"^\s*(?:,\s*)?of\s+this\s+(?:Act|Sanhita|Adhiniyam|Code)\b", re.IGNORECASE)
_DEF_RE = re.compile(r"^\((\d+[A-Za-z]?)\)\s*[“\"']([^”\"']{2,60})[”\"']")

# Defined words so common that matching them would drag the definitions in for every section.
DEFAULT_STOP_TERMS = frozenset(
    {"act", "person", "man", "woman", "number", "life", "will", "year", "month", "offence",
     "court", "public", "illegal", "gender", "government", "document", "death"}
)


@dataclass
class ExpansionConfig:
    siblings: bool = True
    siblings_from_top: int = 3        # complete only the best N sections; every extra section costs prompt tokens
    max_sibling_parts: int = 6        # a section split into more parts than this: hit parts +/- 1 neighbour
    xrefs: bool = True
    xref_from_top: int = 3            # follow references only from the best N sections
    max_xrefs: int = 3
    definitions: bool = True
    definitions_from_top: int = 3
    max_definitions: int = 2
    definitions_section: str = "2"
    stop_terms: frozenset[str] = DEFAULT_STOP_TERMS
    max_chars: int = 14_000           # ~3.5k tokens; ranked hits are always kept, extras fill what is left
    extra: dict = field(default_factory=dict)


def _key(c: LegalChunk) -> tuple[str, str | None]:
    return c.act_id, c.section_no


def references(chunk: LegalChunk, registry: ActRegistry | None = None) -> list[tuple[str, str]]:
    """(act_id, section_no) pairs this chunk points to, in order of appearance.

    Refs followed by "of the <Other Act>" are NOT same-act refs: "section 6 of the General Clauses
    Act" must not pull BNS §6. They are resolved through the registry when the other Act is indexed
    (BNSS -> BNS) and dropped otherwise.
    """
    out: list[tuple[str, str]] = []
    text = chunk.text
    for m in XREF_RE.finditer(text):
        tail = text[m.end(): m.end() + 120]
        target = chunk.act_id
        if not _THIS_ACT_RE.match(tail):
            other = _OTHER_ACT_RE.match(tail)
            if other:
                target = None
                if registry is not None:
                    found = registry.find_in_text(other.group("name"))
                    target = found[0] if found else None
        if target is None:
            continue
        for n in NUM_RE.findall(m.group(1)):
            ref = (target, n.upper())
            if ref not in out and not (target == chunk.act_id and n.upper() == (chunk.section_no or "").upper()):
                out.append(ref)
    return out


class ContextExpander:
    def __init__(self, store: QdrantStore, registry: ActRegistry | None = None, config: ExpansionConfig | None = None):
        self.store = store
        self.registry = registry
        self.cfg = config or ExpansionConfig()
        self._defs: dict[str, list[tuple[str, str, LegalChunk]]] = {}  # act_id -> [(term, clause_no, part)]

    # ------------------------------------------------------------ public

    def expand(self, hits: list[Hit]) -> list[Hit]:
        if not hits:
            return []
        out = self._with_siblings(hits) if self.cfg.siblings else list(hits)
        budget = self.cfg.max_chars - sum(len(h.chunk.text) for h in out)
        seen = {h.chunk.chunk_id for h in out}
        have = {_key(h.chunk) for h in out}

        extras = []
        if self.cfg.xrefs:
            extras += self._xrefs(hits, have)
        if self.cfg.definitions:
            extras += self._definitions(hits)
        for h in extras:
            if h.chunk.chunk_id in seen or len(h.chunk.text) > budget:
                continue
            seen.add(h.chunk.chunk_id)
            budget -= len(h.chunk.text)
            out.append(h)
        return out

    # ------------------------------------------------------------ siblings

    def _with_siblings(self, hits: list[Hit]) -> list[Hit]:
        """Group every section's parts together, right after its best-ranked hit."""
        by_id = {h.chunk.chunk_id: h for h in hits}
        out: list[Hit] = []
        done: set[tuple[str, str | None]] = set()
        for h in hits:
            c = h.chunk
            k = _key(c)
            if c.part_count <= 1 or c.section_no is None:
                if c.chunk_id not in {x.chunk.chunk_id for x in out}:
                    out.append(h)
                continue
            if k in done:
                continue
            if len(done) >= self.cfg.siblings_from_top:
                out.append(h)
                continue
            done.add(k)
            parts = self.store.lookup(c.act_id, c.section_no, limit=max(12, c.part_count))
            if not parts:
                out.append(h)
                continue
            hit_idx = {p.chunk.part_index for p in parts if p.chunk.chunk_id in by_id}
            keep = {p.chunk.part_index for p in parts}
            if len(parts) > self.cfg.max_sibling_parts:
                keep = {i + d for i in hit_idx for d in (-1, 0, 1)}
            for p in sorted(parts, key=lambda x: x.chunk.part_index):
                if p.chunk.part_index not in keep:
                    continue
                if p.chunk.chunk_id in by_id:
                    out.append(by_id[p.chunk.chunk_id])
                else:
                    out.append(Hit(chunk=p.chunk, score=0.0, source="sibling", via=c.label))
        return out

    # ------------------------------------------------------------ cross-references

    def _xrefs(self, hits: list[Hit], have: set) -> list[Hit]:
        out: list[Hit] = []
        wanted: set[tuple[str, str]] = set()
        tops = []
        for h in hits:
            if _key(h.chunk) not in {_key(t.chunk) for t in tops}:
                tops.append(h)
            if len(tops) >= self.cfg.xref_from_top:
                break
        for h in tops:
            for act_id, no in references(h.chunk, self.registry):
                if (act_id, no) in have or (act_id, no) in wanted:
                    continue
                if len(wanted) >= self.cfg.max_xrefs:
                    return out
                parts = self.store.lookup(act_id, no, limit=4)
                if not parts:
                    continue
                wanted.add((act_id, no))
                out.extend(Hit(chunk=p.chunk, score=0.0, source="xref", via=h.chunk.label) for p in parts)
        return out

    # ------------------------------------------------------------ definitions

    def _definitions_for(self, act_id: str) -> list[tuple[str, str, LegalChunk]]:
        if act_id not in self._defs:
            rows: list[tuple[str, str, LegalChunk]] = []
            for p in self.store.lookup(act_id, self.cfg.definitions_section, limit=20):
                for line in p.chunk.text.split("\n"):
                    m = _DEF_RE.match(line.strip())
                    if m:
                        rows.append((m.group(2).strip().lower(), m.group(1), p.chunk))
            self._defs[act_id] = rows
        return self._defs[act_id]

    @staticmethod
    def _clause(part: LegalChunk, clause_no: str) -> str:
        """The part's intro sentence plus just the one clause that defines the term."""
        units: list[str] = []
        for line in part.text.split("\n"):
            if UNIT_START_RE.match(line) or not units:
                units.append(line)
            else:
                units[-1] += "\n" + line
        intro = units[0] if not UNIT_START_RE.match(units[0]) else ""
        body = next((u for u in units if u.startswith(f"({clause_no})")), "")
        return f"{intro}\n{body}".strip()

    def _definitions(self, hits: list[Hit]) -> list[Hit]:
        out: list[Hit] = []
        picked: set[tuple[str, str]] = set()
        tops: list[Hit] = []
        for h in hits:
            if _key(h.chunk) not in {_key(t.chunk) for t in tops}:
                tops.append(h)
            if len(tops) >= self.cfg.definitions_from_top:
                break
        for h in tops:
            c = h.chunk
            if c.section_no is None or c.section_no == self.cfg.definitions_section:
                continue
            text = c.text
            found = []
            for term, clause_no, part in self._definitions_for(c.act_id):
                if term in self.cfg.stop_terms:
                    continue
                if re.search(rf"(?<![A-Za-z]){re.escape(term)}(?:s|es|ed)?(?![A-Za-z])", text, re.IGNORECASE):
                    found.append((term, clause_no, part))
            for term, clause_no, part in sorted(found, key=lambda t: -len(t[0])):
                if (c.act_id, clause_no) in picked:
                    continue
                if len(picked) >= self.cfg.max_definitions:
                    return out
                picked.add((c.act_id, clause_no))
                text_clause = self._clause(part, clause_no)
                if not text_clause:
                    continue
                out.append(
                    Hit(
                        chunk=part.model_copy(update={"text": text_clause, "clause_range": f"({clause_no})",
                                                      "chunk_id": f"{part.chunk_id}#{clause_no}", "part_count": 1, "part_index": 0}),
                        score=0.0, source="definition", via=f"{c.label} uses “{term}”",
                    )
                )
        return out
