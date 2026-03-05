"""The 'Sankalan' compilation of an Act: index + IPC comparison table + the Act with headings ABOVE the numbers.

tests/fixtures/sankalan_excerpt.txt is a verbatim excerpt of such a text (trimmed). Before the index-driven scan,
the parser built stub sections out of the index/table rows and lost the real bodies.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from legalbot.chunking import parse_statute, qa_report
from legalbot.chunking.statute import _scan, clean_lines
from legalbot.registry import ActInfo
from legalbot.schema import Status

FIXTURE = Path(__file__).parent / "fixtures" / "sankalan_excerpt.txt"
EXPECTED = ["1", "2", "3", "4", "5", "6", "7", "59", "60", "61", "62", "63", "64", "80", "206", "358"]


@pytest.fixture(scope="module")
def act():
    return ActInfo("bns", "Bharatiya Nyaya Sanhita, 2023", "BNS", 2023, Status.IN_FORCE)


@pytest.fixture(scope="module")
def parsed(act):
    diag: dict = {}
    chunks = parse_statute(FIXTURE.read_text(encoding="utf-8"), act, diagnostics=diag)
    return chunks, diag


def sec(chunks, no):
    return [c for c in chunks if c.section_no == no]


def text(chunks, no):
    return "\n".join(c.text for c in sec(chunks, no))


def test_exactly_the_indexed_sections_and_no_ipc_leftovers(parsed):
    chunks, diag = parsed
    assert diag["layout"] == "indexed"
    assert sorted({c.section_no for c in chunks if c.section_no}, key=lambda n: int(n)) == EXPECTED  # no 120A / 108A / 511


def test_bodies_come_from_the_act_not_from_index_or_table_rows(parsed):
    chunks, _ = parsed
    assert text(chunks, "61").startswith("(1) When two or more persons agree with the common object")
    assert "(2) Whoever is a party to a criminal conspiracy" in text(chunks, "61")
    assert "Whoever, being a public servant" in text(chunks, "59")
    assert text(chunks, "80").startswith("(1) Where the death of a woman is caused by any burns")
    assert "Indian Penal Code" not in text(chunks, "6") and "57." not in text(chunks, "6")


def test_titles_and_chapters(parsed):
    chunks, _ = parsed
    assert sec(chunks, "61")[0].section_title == "Criminal conspiracy"
    assert sec(chunks, "7")[0].section_title.startswith("Sentence may be (in certain cases of imprisonment)")
    assert (sec(chunks, "61")[0].chapter_no, sec(chunks, "64")[0].chapter_no) == ("IV", "V")
    assert sec(chunks, "6")[0].chapter_no == "II"
    assert sec(chunks, "206")[0].chapter_title.upper() == "OF CONTEMPTS OF THE LAWFUL AUTHORITY OF PUBLIC SERVANTS"  # wrapped title


def test_headings_above_the_next_number_are_stripped_from_the_previous_section(parsed):
    chunks, diag = parsed
    t60 = text(chunks, "60")
    assert "Of criminal conspiracy" not in t60 and "Criminal conspiracy" not in t60
    t6 = text(chunks, "6")
    assert t6.endswith("unless otherwise provided.") and "Sentences may be" not in t6  # plural heading still matched
    assert "Of attempt" not in text(chunks, "61") and "Punishment for attempting" not in text(chunks, "61")
    assert "Of offences relating to marriage" not in text(chunks, "64")
    assert diag["heading_unmatched"] == []


def test_last_section_stops_at_the_closing_rule_and_nav_debris_is_gone(parsed):
    chunks, _ = parsed
    t358 = text(chunks, "358")
    assert t358.rstrip().endswith("with regard to the effect of the repeal.")
    assert "HomePage" not in t358 and "For Reference only" not in t358 and "—————" not in t358


def test_qa_report_is_clean(parsed, act):
    chunks, diag = parsed
    report = qa_report(chunks, expected_sections=16, diagnostics=diag)
    assert report["stub_sections"] == [] and report["no_chapter"] == [] and report["tiny_chunks"] == []
    assert report["sections_match_expected"] is True


def test_preamble_is_not_made_of_website_navigation(parsed):
    chunks, _ = parsed
    assert not any(c.chunk_id.endswith("preamble:0") for c in chunks)


def _inline_act(n=120, footnote_after=50, pad=""):
    index = ["ARRANGEMENT OF SECTIONS", "CHAPTER I", "PRELIMINARY"] + [f"{i}. Punishment for offence number {i} of the kind." for i in range(1, n + 1)]
    body = ["CHAPTER I", "PRELIMINARY"]
    for i in range(1, n + 1):
        body.append(f"{i}. Punishment for offence number {i} of the kind.—Whoever does thing {i} shall be punished with imprisonment up to {i} years.{pad}")
        if i == footnote_after:
            body.append("1. Subs. by Act 12 of 2024, s. 5, for certain words (w.e.f. 1-7-2024).")
    return "\n".join(index + body)


def test_stray_footnote_numbered_1_does_not_swallow_the_rest_of_the_act(act):
    chunks = parse_statute(_inline_act(), act)
    assert text(chunks, "119").startswith("Whoever does thing 119")
    assert text(chunks, "1").startswith("Whoever does thing 1 ")
    assert qa_report(chunks)["stub_sections"] == []


def test_legacy_scan_also_rejects_a_footnote_restart():
    pad = " The offender shall also be liable to fine." * 6  # real bodies are longer than a one-liner
    sections, _ = _scan(clean_lines(_inline_act(pad=pad).split("ARRANGEMENT OF SECTIONS", 1)[1]))
    by_no = {s.no: s for s in sections}
    assert "thing 119" in " ".join(by_no["119"].lines)


def test_repeated_body_lines_are_not_treated_as_running_headers(act):
    clause = "be paid to the victim."
    body = "\n".join(f"{i}. Title {i}.—Provided that any fine shall\n{clause}" for i in range(1, 8))
    index = "ARRANGEMENT OF SECTIONS\n" + "\n".join(f"{i}. Title {i}." for i in range(1, 8))
    chunks = parse_statute(index + "\n" + body, act)
    assert all(clause in text(chunks, str(i)) for i in range(1, 8))
