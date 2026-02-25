"""Extract the IPC <-> BNS comparison table that ships inside the Sankalan / MHA compilation text.

The compilation bundles three things: the Arrangement of Sections, a two-column comparison table
(BNS section | IPC section it replaced) and the Act. After PDF text extraction the table is a flat
stream of entries, so rows are rebuilt by walking it in BNS order:

    6. Fractions of terms of punishment.  57. Fractions of terms of punishment.
    61. Criminal conspiracy.   61(1)  120A. Definition of ...   61(2)  120B. Punishment of ...
    1(2) New Section                                  <- BNS provision with no IPC ancestor
    Deleted 53A. Construction of reference ...        <- IPC provision with no BNS successor

An entry is a BNS row head when its number is the next expected BNS section AND its title matches
the index title; any other numbered entry is an IPC section that belongs to the current BNS row.
Rows are written with verified=false: this is a machine reading of a PDF, to be spot-checked.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .chunking.statute import NAV_RE, _norm, _parse_index, clean_lines

CHAPTER_JUNK_RE = re.compile(r"(?:CHAPTER|Chapter)\s+[IVXLCDM]+[A-Z]?\s*(?:[–—-]\s*)?(?:[A-Z][A-Z ,’'()\-]*[A-Z](?![a-z]))?")
EVENT_RE = re.compile(
    r"(?<![\w(§])(?P<num>\d{1,3}(?:-?[A-Z]{1,2})?)(?P<sub>(?:\s?\([0-9A-Za-z]{1,3}\))*)(?P<dot>\.)?(?=[\s,A-Z“]|$)"
)
HEADER_RE = re.compile(r"Bharatiya Nyaya Sanhita,\s*2023\s+Indian Penal Code,\s*1860", re.I)
TITLE_START_RE = re.compile(r"^[A-Z“\"\[(]")


@dataclass
class CrosswalkRow:
    old_section: str
    new_section: str
    new_ref: str
    note: str  # BNS section title (clean, from the index)
    old_title: str
    similarity: float  # IPC title vs BNS title, 0..1: a cheap sanity signal


@dataclass
class Crosswalk:
    rows: list[CrosswalkRow] = field(default_factory=list)
    new_provisions: list[str] = field(default_factory=list)  # BNS refs with no IPC ancestor
    deleted_ipc: list[str] = field(default_factory=list)  # IPC sections dropped without successor
    deleted_titles: dict[str, str] = field(default_factory=dict)  # IPC section -> its title
    bns_without_row: list[str] = field(default_factory=list)
    bns_found: int = 0


def _sim(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    n = min(len(na), len(nb))
    return SequenceMatcher(None, na[: n + 6], nb[: n + 6]).ratio()


def _table_text(raw: str) -> str:
    """Slice the comparison table out of the RAW text (clean_lines strips the navigation markers
    that delimit it), then normalise just that slice."""
    raw = raw.replace("\r\n", "\n")
    m = re.search(r"CORRESPONDING SECTION TABLE OF BNS WITH REPEALED ACT", raw)  # upper-case: the real heading, not the menu entry
    if m is None:
        raise ValueError("No 'Corresponding Section Table' found in this text.")
    ends = [e.start() for e in re.finditer(r"Chapters and Sections\s+HomePage", raw) if e.start() > m.end()]
    piece = raw[m.end() : (ends[0] if ends else len(raw))]
    text = " ".join(clean_lines(piece))
    text = CHAPTER_JUNK_RE.sub(" ", HEADER_RE.sub(" ", text))
    return re.sub(r"\s+", " ", text).strip()


def extract_crosswalk(text: str) -> Crosswalk:
    lines = clean_lines(text)
    parsed = _parse_index(lines)
    if parsed is None:
        raise ValueError("No 'Arrangement of Sections' index found; it is needed to recognise the BNS column.")
    order, _ = parsed
    bns_title = dict(order)
    nos = [n for n, _ in order]

    table = _table_text(text)
    events = [m for m in EVENT_RE.finditer(table) if m.group("sub") or (m.group("dot") and TITLE_START_RE.match(table[m.end() :].lstrip()))]
    cw = Crosswalk()
    ptr = 0  # next expected BNS section
    cur_no: str | None = None
    cur_refs: list[str] = []  # BNS refs the next IPC entry maps to: '351(2), 351(3)' -> both
    fresh = True  # an IPC entry was consumed since the last sub-ref, so the next sub-ref starts a new list
    deleted_next = False
    row_has_ipc: dict[str, bool] = {}
    seen: set[tuple[str, str]] = set()

    def chunk_after(i: int) -> str:
        end = events[i + 1].start() if i + 1 < len(events) else len(table)
        return table[events[i].end() : end].strip()

    for i, ev in enumerate(events):
        num, sub, dot = ev.group("num").replace("-", ""), ev.group("sub").replace(" ", ""), ev.group("dot")
        title = chunk_after(i)
        if sub and not dot:  # "61(2)" -> sub-clause marker of the BNS row; "228A (3)" -> an IPC section with a sub-clause
            if ptr < len(nos) and num == nos[ptr] and cur_no != num:  # BNS head printed without its "N." (title only)
                ptr += 1
                cur_no, cur_refs, fresh = num, [num + sub], False
                cw.bns_found += 1
                row_has_ipc.setdefault(num, False)
                if re.search(r"\bNew Section\b", title):
                    cw.new_provisions.append(cur_refs[-1])
                    row_has_ipc[num] = True
            elif cur_no and num == cur_no:
                cur_refs = [num + sub] if fresh else cur_refs + [num + sub]
                fresh = False
                if re.search(r"\bNew Section\b", title):
                    cw.new_provisions.append(cur_refs[-1])
                    row_has_ipc[cur_no] = True
            elif cur_no and (num, cur_no) not in seen:
                seen.add((num, cur_no))
                cw.rows.append(CrosswalkRow(num, cur_no, (cur_refs or [cur_no])[-1], bns_title[cur_no], "", 0.0))
                row_has_ipc[cur_no] = True
            continue
        # a numbered entry: BNS head or IPC section?
        head = None
        for off in range(0, 3):
            if ptr + off < len(nos) and nos[ptr + off] == num and _sim(title, bns_title[num]) >= 0.6:
                head = ptr + off
                break
        if head is not None:
            ptr = head + 1
            cur_no, cur_refs, fresh = num, [num], True
            row_has_ipc.setdefault(num, False)
            cw.bns_found += 1
            if re.search(r"\bNew Section\b", title):
                cw.new_provisions.append(num)
                row_has_ipc[num] = True
            deleted_next = False
            continue
        if cur_no is None:
            continue
        clean_title = re.sub(r"\s*\bDeleted\b\s*$", "", re.sub(r"\bNew Section\b", "", title)).strip(" .")
        if deleted_next:
            cw.deleted_ipc.append(num)
            cw.deleted_titles[num] = re.sub(r"\s+", " ", clean_title).strip()
            deleted_next = False
        else:
            for ref in cur_refs or [cur_no]:
                key = (num, ref)
                if key not in seen:
                    seen.add(key)
                    cw.rows.append(CrosswalkRow(num, cur_no, ref, bns_title[cur_no], clean_title, _sim(clean_title, bns_title[cur_no])))
                    row_has_ipc[cur_no] = True
            fresh = True
        if re.search(r"\bDeleted\s*$", title):
            deleted_next = True

    cw.bns_without_row = [n for n in nos if not row_has_ipc.get(n)]
    return cw


FIELDS = ["old_act", "old_section", "new_act", "new_section", "new_ref", "note", "verified", "source", "confidence"]


def write_csv(cw: Crosswalk, path: str | Path, new_act: str = "bns", keep: list[dict] | None = None) -> int:
    """Write curated rows first (kept verbatim), then extracted rows that do not duplicate them."""
    keep = keep or []
    have = {(r["old_section"].upper(), r["new_section"].upper()) for r in keep}
    out = [{**{k: r.get(k, "") for k in FIELDS}, "source": r.get("source") or "curated", "confidence": r.get("confidence") or "curated"} for r in keep]
    for r in cw.rows:
        if (r.old_section.upper(), r.new_section.upper()) in have:
            continue
        out.append(
            {
                "old_act": "ipc", "old_section": r.old_section, "new_act": new_act, "new_section": r.new_section,
                "new_ref": r.new_ref, "note": r.note, "verified": "false", "source": "auto",
                "confidence": "title_match" if r.similarity >= 0.75 else "check",
            }
        )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    return len(out)


DELETED_FIELDS = ["old_act", "old_section", "title", "note", "source"]


def write_deleted_csv(cw: Crosswalk, path: str | Path, old_act: str = "ipc", keep: list[dict] | None = None) -> int:
    """IPC sections the comparison table lists as deleted, i.e. with no BNS successor."""
    keep = keep or []
    have = {r["old_section"].upper() for r in keep}
    out = [{k: r.get(k, "") for k in DELETED_FIELDS} for r in keep]
    for no in cw.deleted_ipc:
        if no.upper() in have:
            continue
        out.append({"old_act": old_act, "old_section": no, "title": cw.deleted_titles.get(no, ""),
                    "note": "Listed as deleted in the BNS comparison table", "source": "auto"})
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DELETED_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    return len(out)
