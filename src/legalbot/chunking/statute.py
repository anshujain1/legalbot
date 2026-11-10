"""Structure-aware chunker for Indian statutes (Acts, Sanhitas, Adhiniyams).

One section = one chunk, with its Chapter / Section context attached as a header
that is embedded together with the text. Long sections (e.g. definitions) are split
at top-level clause boundaries "(1)", "(2)", ... and the intro sentence is repeated
in every part, so no chunk is ever an orphaned fragment.

Supported section layouts (as produced by India Code / gazette text extraction):

    103. Punishment for murder.—(1) Whoever commits murder ...
    103. Punishment for murder.
    (1) Whoever commits murder ...

Section numbers must increase through the Act. That monotonic check is what lets the
parser ignore stray numbers, and it also handles the "Arrangement of Sections" index
at the top of most Acts: its entries are parsed too, then replaced by the real text
(the longest body wins when the same section number appears twice).

Schedules and statements of objects after the last section are dropped in phase 1.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from statistics import median

from ..registry import ActInfo
from ..schema import ChunkRole, DocType, LegalChunk

CHAPTER_RE = re.compile(r"^\s*CHAPTER\s+([IVXLCDM]+|\d+[A-Z]?)\b[\s:.\-—–]*(.*)$")
SECTION_INLINE_RE = re.compile(
    r"^\s*(\d{1,3}[A-Z]{0,2})\.\s+(?P<title>\S[^\n]{1,220}?)\.\s*[—–-]{1,2}\s*(?P<rest>.*)$"
)
SECTION_TITLE_RE = re.compile(r"^\s*(\d{1,3}[A-Z]{0,2})\.\s+(?P<title>[A-Z\[][^\n]{1,200}?)\.?\s*$")
SCHEDULE_RE = re.compile(
    r"^(THE\s+)?(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH)\s+SCHEDULE\.?\s*$"
    r"|^(THE\s+)?SCHEDULE\.?\s*$|^STATEMENT OF OBJECTS",
    re.IGNORECASE,
)
PARA_START_RE = re.compile(
    r"^(\(\d+[A-Za-z]?\)|\([a-z]{1,4}\)|\([ivxlc]+\)|Provided\b|Explanation\b|Illustrations?\b|Exceptions?\b|Note\b)"
)
UNIT_START_RE = re.compile(r"^\((\d+[A-Za-z]?)\)\s")
XREF_RE = re.compile(r"\bsections?\s+(\d{1,3}[A-Z]{0,2}(?:\s*(?:,|and|or|to)\s*\d{1,3}[A-Z]{0,2})*)")
NUM_RE = re.compile(r"\d{1,3}[A-Z]{0,2}")


@dataclass
class _Sec:
    no: str
    title: str
    lines: list[str]
    chapter_no: str | None
    chapter_title: str | None

    @property
    def body_len(self) -> int:
        return sum(len(line) for line in self.lines)


# ---------------------------------------------------------------- text cleanup


def clean_lines(text: str) -> list[str]:
    """Normalise whitespace, drop page numbers and repeated running headers."""
    text = text.replace("\r\n", "\n").replace(" ", " ")
    raw = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    counts = Counter(line for line in raw if len(line) >= 15 and not line.startswith("("))
    out: list[str] = []
    for line in raw:
        if re.fullmatch(r"\d{1,3}", line):  # bare page number
            continue
        if counts.get(line, 0) >= 5:  # running header/footer
            continue
        out.append(line)
    return out


def reflow(lines: list[str]) -> list[str]:
    """Join hard-wrapped lines into paragraphs; sub-clauses, provisos etc. start new ones."""
    paras: list[str] = []
    for line in lines:
        if not line:
            continue
        if paras and not PARA_START_RE.match(line):
            prev = paras[-1]
            paras[-1] = prev + line if prev.endswith("-") else prev + " " + line
        else:
            paras.append(line)
    return paras


# ---------------------------------------------------------------- section scan


def _base(no: str) -> int:
    return int(re.match(r"\d+", no).group())  # type: ignore[union-attr]


def _sort_key(no: str) -> tuple[int, str]:
    m = re.match(r"(\d+)([A-Z]*)", no)
    return int(m.group(1)), m.group(2)  # type: ignore[union-attr]


def _match_section(line: str) -> tuple[str, str, str] | None:
    m = SECTION_INLINE_RE.match(line)
    if m:
        return m.group(1), m.group("title").strip(), m.group("rest").strip()
    m = SECTION_TITLE_RE.match(line)
    if m:
        return m.group(1), m.group("title").strip(), ""
    return None


def _accept(no: str, last_no: str | None) -> tuple[bool, bool]:
    """Is `no` a plausible next section? Returns (accepted, is_restart)."""
    if last_no is None:
        return True, False
    b, lb = _base(no), _base(last_no)
    if b == lb:
        return no > last_no, False  # 3 -> 3A
    if b > lb:
        return b - lb <= 40, False
    return (b <= 2), (b <= 2)  # numbering restarts after the arrangement-of-sections index


def _scan(lines: list[str]) -> tuple[list[_Sec], list[str]]:
    sections: list[_Sec] = []
    preamble: list[str] = []
    chapter_no: str | None = None
    chapter_title: str | None = None
    cur: _Sec | None = None
    last_no: str | None = None
    in_schedule = False
    chapter_fresh = False  # a chapter heading was read since the last section started
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line:
            continue

        cm = CHAPTER_RE.match(line)
        if cm:
            chapter_no = cm.group(1)
            title = cm.group(2).strip(" .—–-")
            if not title:
                j = i
                while j < len(lines) and not lines[j]:
                    j += 1
                if j < len(lines):
                    cand = lines[j]
                    if len(cand) <= 120 and not _match_section(cand) and not CHAPTER_RE.match(cand):
                        title = cand.strip(" .—–-")
                        i = j + 1
            chapter_title = title or None
            chapter_fresh = True
            cur = None
            continue

        if SCHEDULE_RE.match(line):
            in_schedule = True
            cur = None
            continue

        sm = _match_section(line)
        if sm:
            ok, restart = _accept(sm[0], last_no)
            if ok:
                if restart and not chapter_fresh:
                    # new pass with no chapter heading yet: don't inherit the index's last chapter
                    chapter_no = chapter_title = None
                no, title, rest = sm
                cur = _Sec(no, title, [rest] if rest else [], chapter_no, chapter_title)
                sections.append(cur)
                last_no = no
                in_schedule = False
                chapter_fresh = False
                continue

        if in_schedule:
            continue
        if cur is not None:
            cur.lines.append(line)
        elif not sections:
            preamble.append(line)
    return sections, preamble


# ---------------------------------------------------------------- splitting


def split_units(paras: list[str]) -> list[str]:
    """Group paragraphs into units that start at top-level numbered clauses."""
    units: list[str] = []
    for p in paras:
        if UNIT_START_RE.match(p) or not units:
            units.append(p)
        else:
            units[-1] += "\n" + p
    return units


def _range(units: list[str]) -> str | None:
    marks = [m.group(1) for u in units if (m := UNIT_START_RE.match(u))]
    if not marks:
        return None
    if len(marks) == 1:
        return f"({marks[0]})"
    return f"({marks[0]})–({marks[-1]})"


def _hard_split(text: str, limit: int) -> list[str]:
    pieces: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = max(rest.rfind(". ", 0, limit), rest.rfind("; ", 0, limit), rest.rfind(": ", 0, limit))
        cut = cut + 1 if cut > limit * 0.4 else limit
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        pieces.append(rest)
    return pieces


def pack(units: list[str], max_chars: int) -> list[tuple[str, str | None]]:
    """Pack units into parts of at most ~max_chars, repeating the intro sentence in each."""
    if sum(len(u) + 1 for u in units) <= max_chars:
        return [("\n".join(units), _range(units))]

    prefix = ""
    if len(units) > 1 and not UNIT_START_RE.match(units[0]) and len(units[0]) <= 400:
        prefix, units = units[0], units[1:]
    budget = max(200, max_chars - len(prefix) - 1)

    groups: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0

    def flush() -> None:
        nonlocal cur, cur_len
        if cur:
            groups.append(cur)
        cur, cur_len = [], 0

    for u in units:
        if len(u) > budget:
            flush()
            groups.extend([piece] for piece in _hard_split(u, budget))
            continue
        if cur and cur_len + len(u) + 1 > budget:
            flush()
        cur.append(u)
        cur_len += len(u) + 1
    flush()

    return [("\n".join(([prefix] if prefix else []) + g), _range(g)) for g in groups]


# ---------------------------------------------------------------- chunk building


def _pretty(title: str | None) -> str | None:
    if not title:
        return None
    return title.title() if title.isupper() else title


def _header(act: ActInfo, sec: _Sec, clause_range: str | None) -> str:
    bits = [act.name]
    if sec.chapter_no:
        chap = f"Chapter {sec.chapter_no}"
        if sec.chapter_title:
            chap += f": {_pretty(sec.chapter_title)}"
        bits.append(chap)
    bits.append(f"Section {sec.no}: {sec.title}")
    if clause_range:
        bits.append(f"clauses {clause_range}")
    return " | ".join(bits)


def _cross_refs(text: str, own: str) -> list[str]:
    refs: list[str] = []
    for m in XREF_RE.finditer(text):
        for n in NUM_RE.findall(m.group(1)):
            if n != own and n not in refs:
                refs.append(n)
    return refs


def parse_statute(
    text: str,
    act: ActInfo,
    source_file: str | None = None,
    max_chars: int = 1800,
) -> list[LegalChunk]:
    sections, preamble = _scan(clean_lines(text))

    # Same section number twice (index entry + real text): keep the longer body.
    best: dict[str, _Sec] = {}
    for s in sections:
        prev = best.get(s.no)
        if prev is None or s.body_len >= prev.body_len:
            best[s.no] = s

    chunks: list[LegalChunk] = []

    pre_text = "\n".join(reflow(preamble))[:1500].strip()
    if len(pre_text) >= 40:
        chunks.append(
            LegalChunk(
                chunk_id=f"{act.act_id}:preamble:0",
                act_id=act.act_id,
                act_name=act.name,
                act_short=act.short,
                year=act.year,
                status=act.status,
                role=ChunkRole.PREAMBLE,
                header=f"{act.name} | Preamble",
                text=pre_text,
                source_file=source_file,
            )
        )

    for no in sorted(best, key=_sort_key):
        sec = best[no]
        paras = reflow(sec.lines)
        parts = pack(split_units(paras), max_chars) if paras else [(sec.title, None)]
        for idx, (body, clause_range) in enumerate(parts):
            chunks.append(
                LegalChunk(
                    chunk_id=f"{act.act_id}:{sec.no}:{idx}",
                    doc_type=DocType.STATUTE,
                    act_id=act.act_id,
                    act_name=act.name,
                    act_short=act.short,
                    year=act.year,
                    status=act.status,
                    chapter_no=sec.chapter_no,
                    chapter_title=_pretty(sec.chapter_title),
                    section_no=sec.no,
                    section_title=sec.title,
                    clause_range=clause_range,
                    part_index=idx,
                    part_count=len(parts),
                    role=ChunkRole.SECTION,
                    header=_header(act, sec, clause_range),
                    text=body,
                    cross_refs=_cross_refs(body, sec.no),
                    source_file=source_file,
                )
            )
    return chunks


# ---------------------------------------------------------------- QA


def qa_report(chunks: list[LegalChunk]) -> dict:
    """Sanity numbers to eyeball after ingesting a new Act (gaps usually mean parse problems)."""
    secs = sorted({c.section_no for c in chunks if c.section_no}, key=_sort_key)
    bases = {_base(s) for s in secs}
    missing = [n for n in range(1, max(bases) + 1) if n not in bases] if bases else []
    sizes = [len(c.text) for c in chunks if c.section_no]
    return {
        "chunks": len(chunks),
        "sections": len(secs),
        "split_sections": len({c.section_no for c in chunks if c.part_count > 1}),
        "missing_section_numbers": missing,
        "no_chapter": [c.section_no for c in chunks if c.section_no and not c.chapter_no][:20],
        "tiny_chunks": [c.chunk_id for c in chunks if c.section_no and len(c.text) < 40][:20],
        "chars_min": min(sizes) if sizes else 0,
        "chars_median": int(median(sizes)) if sizes else 0,
        "chars_max": max(sizes) if sizes else 0,
    }
