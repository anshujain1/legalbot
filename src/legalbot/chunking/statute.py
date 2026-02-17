"""Structure-aware chunker for Indian statutes (Acts, Sanhitas, Adhiniyams).

One section = one chunk, with its Chapter / Section context attached as a header
that is embedded together with the text. Long sections (e.g. definitions) are split
at top-level clause boundaries "(1)", "(2)", ... and the intro sentence is repeated
in every part, so no chunk is ever an orphaned fragment.

Supported section layouts (as produced by India Code / gazette text extraction):

    103. Punishment for murder.—(1) Whoever commits murder ...
    103. Punishment for murder.
    (1) Whoever commits murder ...
    Punishment for murder.                      <- heading ABOVE the number (gazette / Sankalan text)
    103. (1) Whoever commits murder ...

When the text has an "Arrangement of Sections" index, the parser reads the expected section
numbers and titles from it and then looks for those numbers *in order* in the body. That is what
makes the heading-above layout work, and it stops comparison tables, footnotes ("1. Subs. by ...")
and stray numbered lines from being mistaken for sections. Without an index the older
monotonic-number scan is used.

Section numbers must increase through the Act. That monotonic check is what lets the
parser ignore stray numbers, and it also handles the "Arrangement of Sections" index
at the top of most Acts: its entries are parsed too, then replaced by the real text
(the longest body wins when the same section number appears twice).

Schedules and statements of objects after the last section are dropped in phase 1.
"""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
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
# A clause marker starts a paragraph only when it is a marker, not a wrapped reference such as
# "...in sub-section" / "(1), it shall not affect": a marker is never followed by , . ; or :
PARA_START_RE = re.compile(
    r"^(\(\d+[A-Za-z]?\)(?![,.;:])|\([a-z]{1,4}\)(?![,.;:])|\([A-Z]\)(?![,.;:])|\([ivxlc]+\)(?![,.;:])"
    r"|Provided\b|Explanation\b|Illustrations?\b|Exceptions?\b|Note\b)"
)
NAV_RE = re.compile(r"\bHomePage\b|^\s*Note:\s*For Reference only", re.IGNORECASE)  # website navigation debris
RULE_RE = re.compile(r"^[\s—–\-_=*]{3,}$")  # "—————" line that closes an Act
INDEX_HEAD_RE = re.compile(r"^\s*ARRANGEMENT\s+OF\s+(THE\s+)?SECTIONS\b", re.IGNORECASE)
ENTRY_RE = re.compile(r"^\s*(\d{1,3}[A-Z]{0,2})\.\s+(\S.*)$")
# Marginal sub-headings such as "Of abetment" that sit above a section heading.
SUBHEAD_RE = re.compile(r"^\s*(Of\s+\S.{0,88}|of\s+\S.{0,58})$")
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


def _is_running_header_candidate(line: str) -> bool:
    """Only shouting, header-like lines are candidates for the repeated-line filter.

    Mixed-case lines are never removed: legal boilerplate wraps to identical lines all the time
    (e.g. "be paid to the victim." occurs in many sections) and deleting those corrupts the text.
    """
    return (
        len(line) >= 15
        and len(line) <= 100
        and line.isupper()
        and not line.startswith(("(", "CHAPTER", "OF "))
    )


def repair_split_words(lines: list[str]) -> list[str]:
    """Undo PDF-extraction damage: 'f or', 'pr operty', 'public ser vant', 'sub -section'.

    Two neighbouring tokens are merged only when their concatenation is a word this very document
    uses at least 3 times AND at least one half is not itself a word it uses (so 'any one' and
    'in to' are left alone). The vocabulary covers the whole file, index included, because the
    index is usually cleaner than the body.
    """
    vocab: Counter = Counter()
    for line in lines:
        vocab.update(w.lower() for w in re.findall(r"[A-Za-z]{2,}", line))
    known = {w for w, c in vocab.items() if c >= 4}
    tail = re.compile(r"([A-Za-z]+)(\W*)$")

    def fix(line: str) -> str:
        line = re.sub(r"(\w) -(?=[a-z])", r"\1-", line)  # "sub -section"
        out: list[str] = []
        for tok in line.split(" "):
            m = tail.match(tok)
            if out and m and out[-1].isalpha() and not (len(out[-1]) == 1 and out[-1].isupper()):
                a, b = out[-1].lower(), m.group(1).lower()
                need = 1 if (a not in known and b not in known) else 3  # two non-words: one sighting of the joined word is enough
                if not (a in known and b in known) and vocab.get(a + b, 0) >= need and a + b not in {"ing", "ion"}:
                    out[-1] += tok
                    continue
            out.append(tok)
        return " ".join(out)

    return [fix(line) for line in lines]


def clean_lines(text: str) -> list[str]:
    """Normalise whitespace, drop page numbers, website debris and repeated running headers."""
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    raw = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    raw = [line for line in raw if not NAV_RE.search(line)]
    counts = Counter(line for line in raw if _is_running_header_candidate(line))
    out: list[str] = []
    for line in raw:
        if re.fullmatch(r"\d{1,3}", line):  # bare page number
            continue
        if counts.get(line, 0) >= 5:  # running header/footer
            continue
        out.append(line)
    return repair_split_words(out)


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
    pass_start = 0  # index in `sections` where the current numbering pass began
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
            this_pass = sections[pass_start:]
            if restart and this_pass and sum(x.body_len for x in this_pass) / len(this_pass) >= 200:
                ok = False  # the current pass has real bodies: this "1."/"2." is a footnote or list item
            if ok:
                if restart:
                    pass_start = len(sections)
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


# ---------------------------------------------------------------- index-driven scan


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _similar(a: str, b: str, threshold: float = 0.8) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    return na == nb or SequenceMatcher(None, na, nb).ratio() >= threshold


@lru_cache(maxsize=None)
def _start_re(no: str) -> re.Pattern:
    """A line that starts section `no`: '61. (1) When ...', '115.(1) Whoever', '103. Title.—...'."""
    return re.compile(rf"^\s*{re.escape(no)}\.(?=[\s(\[]|$)\s*(.*)$")


def _join(prev: str, nxt: str) -> str:
    return prev + nxt if prev.endswith("-") else prev + " " + nxt


def _is_upper_title(line: str) -> bool:
    t = line.strip()
    return bool(t) and len(t) <= 120 and t.upper() == t and any(c.isalpha() for c in t) and not t[0].isdigit()


def _read_chapter(lines: list[str], i: int) -> tuple[str, str | None, int]:
    """Parse a CHAPTER heading at lines[i]; its title may sit on the same line or wrap over 1-3 upper-case lines."""
    cm = CHAPTER_RE.match(lines[i])
    assert cm is not None
    parts = [p for p in [cm.group(2).strip(" .—–-")] if p]
    j = i + 1
    while j < len(lines) and len(parts) < 3:
        if not lines[j].strip():
            j += 1
            continue
        if CHAPTER_RE.match(lines[j]) or not _is_upper_title(lines[j]):
            break
        parts.append(lines[j].strip(" .—–-"))
        j += 1
    title = ""
    for part in parts:
        title = _join(title, part) if title else part
    return cm.group(1), (title or None), j


def _parse_index(lines: list[str]) -> tuple[list[tuple[str, str]], int] | None:
    """Read (section_no, title) pairs from the 'Arrangement of Sections'. Returns (order, heading_line)."""
    head = next((i for i, line in enumerate(lines) if INDEX_HEAD_RE.match(line)), None)
    if head is None:
        return None
    order: list[tuple[str, str]] = []
    open_title = False  # last title has no closing full stop, so the next plain line continues it
    skip_caps = False
    i = head + 1
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip():
            continue
        if CHAPTER_RE.match(line):
            _, _, j = _read_chapter(lines, i - 1)
            i, open_title = j, False
            continue
        m = ENTRY_RE.match(line)
        if m:
            no = m.group(1)
            if order and _sort_key(no) <= _sort_key(order[-1][0]):
                break  # numbering restarted: the index is over (a comparison table or the Act itself follows)
            if not order and _base(no) > 2:
                continue
            order.append((no, m.group(2).strip()))
            open_title = not order[-1][1].endswith(".")
            continue
        if open_title and order and not SUBHEAD_RE.match(line):
            order[-1] = (order[-1][0], _join(order[-1][1], line.strip()))
            open_title = not order[-1][1].endswith(".")
    if len(order) < 3:
        return None
    return [(no, title.rstrip(" .")) for no, title in order], head


def _title_above(lines: list[str], i: int, title: str) -> int:
    """How many non-blank lines directly above lines[i] form `title` (0 if none do)?"""
    above: list[str] = []
    j = i - 1
    while j >= 0 and len(above) < 4:
        if lines[j].strip():
            above.append(lines[j].strip())
        j -= 1
    best, best_ratio = 0, 0.0
    for n in range(1, len(above) + 1):
        cand = _norm(" ".join(reversed(above[:n])))
        ref = _norm(title)
        if not cand or not ref:
            continue
        ratio = SequenceMatcher(None, cand, ref).ratio()
        if ratio >= 0.8 and ratio > best_ratio:
            best, best_ratio = n, ratio
    return best


def _strip_heading(body: list[str], title: str) -> bool:
    """Remove the next section's heading (and 'Of ...' sub-headings) from the tail of this body."""
    while body and not body[-1].strip():
        body.pop()
    found = False
    tail = [line for line in body[-4:]]
    best, best_ratio = 0, 0.0
    for n in range(1, len(tail) + 1):
        cand, ref = _norm(" ".join(tail[-n:])), _norm(title)
        if cand and ref:
            ratio = SequenceMatcher(None, cand, ref).ratio()
            if ratio >= 0.8 and ratio > best_ratio:
                best, best_ratio = n, ratio
    if best:
        del body[-best:]
        found = True
    while body:
        if SUBHEAD_RE.match(body[-1]) and not (body[-1].rstrip().endswith((".", ";", ":", ",")) and body[-1][:1].islower()):
            body.pop()
        elif (  # a sub-heading wrapped over two lines: "Of breach of contract ... helpless" / "person"
            len(body) >= 2
            and SUBHEAD_RE.match(body[-2])
            and not body[-2].rstrip().endswith((".", ";", ":", ","))
            and not body[-1].rstrip().endswith((".", ";", ":", ",", "—"))
            and not UNIT_START_RE.match(body[-1])
            and SUBHEAD_RE.match(body[-2] + " " + body[-1])
        ):
            del body[-2:]
        else:
            break
    return found


def _segment(lines: list[str], start: int, order: list[tuple[str, str]], leaks: list[str]) -> list[_Sec]:
    """One pass through the text collecting the index's sections in order, beginning at lines[start]."""
    sections: list[_Sec] = []
    chapter_no: str | None = None
    chapter_title: str | None = None
    for j in range(start - 1, max(-1, start - 9), -1):  # chapter heading right above section 1
        if CHAPTER_RE.match(lines[j]):
            chapter_no, chapter_title, _ = _read_chapter(lines, j)
            break
    cur: _Sec | None = None
    k = 0
    i = start
    while i < len(lines):  # keep going after the last section so its body is collected
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if CHAPTER_RE.match(line):
            chapter_no, chapter_title, i = _read_chapter(lines, i)
            cur = None
            continue
        if SCHEDULE_RE.match(line) or RULE_RE.match(line):
            cur = None
            i += 1
            continue
        hit = None
        for off in range(0, 3):  # tolerate up to two sections missing from the extracted text
            if k + off >= len(order):
                break
            m = _start_re(order[k + off][0]).match(line)
            if m and (off == 0 or _title_above(lines, i, order[k + off][1]) or _similar(m.group(1), order[k + off][1])):
                hit = (k + off, m)
                break
        if hit is None:
            if cur is not None:
                cur.lines.append(line)
            i += 1
            continue
        idx, m = hit
        no, title = order[idx]
        im = SECTION_INLINE_RE.match(line)
        rest = m.group(1).strip()
        inline = False
        if im and _similar(im.group("title"), title):
            rest, inline = im.group("rest").strip(), True
        elif rest and _similar(rest, title):
            rest, inline = "", True
        if cur is not None and not _strip_heading(cur.lines, title) and not inline and cur.lines:
            leaks.append(no)  # heading-above layout, but this section's heading was not found above its number
        cur = _Sec(no, title, [rest] if rest else [], chapter_no, chapter_title)
        sections.append(cur)
        k = idx + 1
        i += 1
    return sections


def _indexed_scan(lines: list[str]) -> tuple[list[_Sec], list[str], list[str]] | None:
    parsed = _parse_index(lines)
    if parsed is None:
        return None
    order, head = parsed
    best: tuple[int, list[_Sec], list[str]] | None = None
    for i, line in enumerate(lines):
        if _start_re(order[0][0]).match(line):
            leaks: list[str] = []
            secs = _segment(lines, i, order, leaks)
            # A pass that starts in the index runs on into the Act inside its LAST section, so ignore the
            # last body and cap the rest: the real pass is the one with many sections that have real bodies.
            score = sum(min(sec.body_len, 8000) for sec in secs[:-1])
            if best is None or score > best[0]:
                best = (score, secs, leaks)
    if best is None or len(best[1]) < 0.5 * len(order):
        return None
    return best[1], lines[:head], best[2]


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
        # prefer a paragraph boundary (an illustration or clause ends there), then a sentence end,
        # so a piece never starts with the orphaned tail of the previous paragraph ("A cheats.")
        para = rest.rfind("\n", 0, limit)
        if para > limit * 0.4:
            pieces.append(rest[:para].strip())
            rest = rest[para:].strip()
            continue
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
    diagnostics: dict | None = None,
) -> list[LegalChunk]:
    lines = clean_lines(text)
    indexed = _indexed_scan(lines)
    if indexed is not None:
        sections, preamble, leaks = indexed
        layout = "indexed"
    else:
        sections, preamble = _scan(lines)
        leaks, layout = [], "legacy"
    if diagnostics is not None:
        diagnostics.update(layout=layout, heading_unmatched=leaks[:20])

    # Same section number twice (index entry + real text): keep the longer body.
    best: dict[str, _Sec] = {}
    for s in sections:
        prev = best.get(s.no)
        if prev is None or s.body_len >= prev.body_len:
            best[s.no] = s

    chunks: list[LegalChunk] = []

    pre_text = "\n".join(reflow(preamble))[:1500].strip()
    if len(pre_text) >= 40 and re.search(r"\b(An Act|enacted|WHEREAS)\b", pre_text, re.IGNORECASE):
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


def qa_report(
    chunks: list[LegalChunk],
    expected_sections: int | None = None,
    diagnostics: dict | None = None,
) -> dict:
    """Sanity numbers to eyeball after ingesting a new Act (gaps usually mean parse problems)."""
    secs = sorted({c.section_no for c in chunks if c.section_no}, key=_sort_key)
    bases = {_base(s) for s in secs}
    missing = [n for n in range(1, max(bases) + 1) if n not in bases] if bases else []
    sizes = [len(c.text) for c in chunks if c.section_no]
    stubs = [
        c.section_no
        for c in chunks
        if c.section_no and c.part_index == 0 and (len(c.text) <= len(c.section_title or "") + 3 or _norm(c.text) == _norm(c.section_title or ""))
    ]
    report = {
        "chunks": len(chunks),
        "sections": len(secs),
        "split_sections": len({c.section_no for c in chunks if c.part_count > 1}),
        "missing_section_numbers": missing,
        "stub_sections": stubs[:20],  # section whose whole text is just its title: the body was not captured
        "no_chapter": [c.section_no for c in chunks if c.section_no and not c.chapter_no][:20],
        "tiny_chunks": [c.chunk_id for c in chunks if c.section_no and len(c.text) < 40][:20],
        "chars_min": min(sizes) if sizes else 0,
        "chars_median": int(median(sizes)) if sizes else 0,
        "chars_max": max(sizes) if sizes else 0,
    }
    if expected_sections is not None:
        report["expected_sections"] = expected_sections
        report["sections_match_expected"] = len(secs) == expected_sections
    if diagnostics:
        report.update(diagnostics)
    return report
