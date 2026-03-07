"""Citation verification: every act/section the answer cites must exist in the retrieved sources.

In legal answers a confident wrong citation is worse than no answer, so anything the model cites
that was not retrieved (or mapped by the concordance) is flagged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .generate import INSUFFICIENT
from .registry import ActRegistry
from .schema import Hit

_BRACKET = re.compile(r"\[\s*([A-Za-z.]+)\s*§\s*(\d{1,3}[A-Za-z]{0,2})[^\]]*\]")


@dataclass
class Verification:
    cited: list[tuple[str, str]] = field(default_factory=list)
    unsupported: list[tuple[str, str]] = field(default_factory=list)
    insufficient: bool = False
    has_citation: bool = False

    @property
    def ok(self) -> bool:
        if self.unsupported:
            return False
        return self.insufficient or self.has_citation


_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))
_BRACKETED = re.compile(r"(\[[^\]]*\])")


def normalize_citations(text: str, registry: ActRegistry | None = None) -> str:
    """Make model citation styles uniform so they can be verified and linked: some models emit
    full-width brackets (【BNS §356】), zero-width spaces, bold inside brackets ([**BNS §143**]) or a bare
    'BNS §309'. All become '[BNS §309]'. Text outside citations is left alone."""
    text = text.translate(_ZERO_WIDTH).replace("【", "[").replace("】", "]")
    shorts = sorted((re.escape(s) for s in registry.shorts()), key=len, reverse=True) if registry else []
    bare = re.compile(rf"\b({'|'.join(shorts)})\s*§\s*(\d{{1,3}}[A-Za-z]{{0,2}})\b(?:\s*\((?:\d+|[a-z])\))*") if shorts else None
    out: list[str] = []
    for part in _BRACKETED.split(text):
        if part.startswith("[") and part.endswith("]"):
            out.append(part.replace("*", "").replace("_", " ").strip() if "§" in part else part)
        elif bare is not None:
            out.append(bare.sub(lambda m: f"[{m.group(1).upper()} §{m.group(2)}]", part.replace("**", "")))
        else:
            out.append(part)
    return "".join(out)


def _free_text_pattern(registry: ActRegistry) -> re.Pattern:
    shorts = "|".join(sorted((re.escape(s) for s in registry.shorts()), key=len, reverse=True))
    return re.compile(rf"\b({shorts})\b\s*(?:sections?|sec\.?|§)?\s*(\d{{1,3}}[A-Za-z]{{0,2}})(?![\d])", re.IGNORECASE)


def verify(
    answer: str,
    hits: list[Hit],
    registry: ActRegistry,
    extra_allowed: list[tuple[str, str]] | None = None,
) -> Verification:
    """`extra_allowed` holds (act_id, section) pairs the concordance legitimately introduced."""
    allowed = {(h.chunk.act_short.lower(), (h.chunk.section_no or "").upper()) for h in hits}
    for act_id, sec in extra_allowed or []:
        if act_id in registry:
            allowed.add((registry.get(act_id).short.lower(), sec.upper()))

    result = Verification(insufficient=answer.strip().startswith(INSUFFICIENT))
    seen: set[tuple[str, str]] = set()

    for m in _BRACKET.finditer(answer):
        result.has_citation = True
        seen.add((m.group(1).lower(), m.group(2).upper()))
    for m in _free_text_pattern(registry).finditer(answer):
        seen.add((m.group(1).lower(), m.group(2).upper()))

    result.cited = sorted(seen)
    result.unsupported = [ref for ref in result.cited if ref not in allowed]
    return result
