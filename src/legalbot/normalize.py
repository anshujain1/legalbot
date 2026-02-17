"""Repair stray spaces that PDF-to-text extraction puts inside words ("t he", "organis ed").

These break keyword search ("organised" never matches "organis ed") and weaken embeddings.
The repair is deliberately conservative, because joining the wrong words in a law text is worse
than leaving a glitch in. A pair "a b" is joined into "ab" only if "ab" already occurs as a normal
word elsewhere in the same document AND one of these holds:

  R1  one half is a lone lowercase letter other than "a"        ("t he", "cast e", "wit h")
  R2  both halves are rare fragments in this document            ("syndi cate", "organis ed")
  R3  "ab" is very frequent and the spaced form is rare          ("per son", "with out")

Legal phrases that merely look like split words are protected by those conditions: "do or omit"
(door is rare) and "any one of" (anyone is not frequent enough relative to "any one") stay intact.
Every repair is returned so it can be reviewed; the CLI prints a sample.
"""
from __future__ import annotations

import re
from collections import Counter

_TOKEN = re.compile(r"[A-Za-z]+")
_PIECE = re.compile(r"([a-z]{1,12})([,.;:)\]]*)")  # lowercase word, optional trailing punctuation
_PURE = re.compile(r"[a-z]{1,12}")

# Ordinary short words are never "fragments", however rarely they occur in a small document
# (otherwise "do or omit" -> "door omit" and "any one of" -> "anyone of" in short Acts).
COMMON = frozenset(
    "a an and any are as at be been but by can do does for from had has have he her him his if in into is it "
    "its may me my no nor not of on one or our out per she shall so such than that the their them then there "
    "these they this those to two three up us was we were what when where which who whom will with within act all "
    "any each every case person law".split()
)

SHORT_JOINED = 3  # results this short must be common words...
SHORT_JOINED_MIN = 10  # ...seen at least this often in the document
RARE_FRAGMENT_MAX = 5  # R2: a half that occurs at most this often as a standalone word is a fragment
R3_MIN_JOINED = 30  # R3: the joined word must be common...
R3_RATIO = 10  # ...and at least this many times more frequent than the spaced pair


def repair_spacing(text: str) -> tuple[str, Counter]:
    """Return (repaired_text, Counter of (spaced_form, joined_form) -> times repaired).

    Works line by line on space-separated pieces and steps one piece at a time, so overlapping
    candidates ("words as t he": first "as t", then "t he") each get examined. Uppercase words,
    numbers and anything with leading punctuation are never touched.
    """
    words = Counter(t.lower() for t in _TOKEN.findall(text))
    lines = [ln.split(" ") for ln in text.split("\n")]

    pairs: Counter = Counter()
    for pcs in lines:
        for x, y in zip(pcs, pcs[1:]):
            my = _PIECE.fullmatch(y)
            if _PURE.fullmatch(x) and my:
                pairs[(x, my.group(1))] += 1
    repairs: Counter = Counter()

    def should_join(a: str, b: str, before: str | None, after: str | None) -> bool:
        joined = a + b
        if words.get(joined, 0) < 1:
            return False
        if len(joined) <= SHORT_JOINED and words[joined] < SHORT_JOINED_MIN:
            return False  # "a c" -> "ac", "to p" -> "top": short results must be genuinely common words
        lone_left, lone_right = len(a) == 1 and a != "a", len(b) == 1 and b != "a"
        if lone_right and after and words.get(b + after, 0) >= words[joined]:
            return False  # the lone letter fits the NEXT word better ("to p unishment")
        if lone_left and before and words.get(before + a, 0) >= words[joined]:
            return False  # ...or the PREVIOUS word ("wag e scape")
        if lone_left or lone_right:  # R1
            return True
        if (
            len(a) >= 2
            and len(b) >= 2
            and a not in COMMON
            and b not in COMMON
            and words[a] <= RARE_FRAGMENT_MAX
            and words[b] <= RARE_FRAGMENT_MAX
        ):  # R2
            return True
        n = pairs.get((a, b), 1)
        return words[joined] >= R3_MIN_JOINED and words[joined] >= R3_RATIO * n  # R3

    out_lines: list[str] = []
    for pcs in lines:
        out: list[str] = []
        i = 0
        while i < len(pcs):
            a = pcs[i]
            mb = _PIECE.fullmatch(pcs[i + 1]) if i + 1 < len(pcs) else None
            if mb and _PURE.fullmatch(a):
                b, trail = mb.group(1), mb.group(2)
                before = out[-1] if out and _PURE.fullmatch(out[-1]) else None
                ma = _PIECE.fullmatch(pcs[i + 2]) if i + 2 < len(pcs) else None
                after = ma.group(1) if ma and not trail else None
                if should_join(a, b, before, after):
                    out.append(a + b + trail)
                    repairs[(f"{a} {b}", a + b)] += 1
                    i += 2
                    continue
            out.append(a)
            i += 1
        out_lines.append(" ".join(out))
    return "\n".join(out_lines), repairs


def summarize(repairs: Counter, limit: int = 25) -> list[str]:
    """Human-readable 'spaced -> joined (xN)' lines, most frequent first."""
    return [f"{spaced} -> {joined} (x{n})" for (spaced, joined), n in repairs.most_common(limit)]
