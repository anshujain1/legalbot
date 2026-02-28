"""IPC -> BNS comparison table extraction."""
import csv
from pathlib import Path

from legalbot.crosswalk import extract_crosswalk, write_csv

FIXTURE = Path(__file__).parent / "fixtures" / "sankalan_excerpt.txt"

# Every layout quirk seen in the real BNS text, in one synthetic table.
SYNTHETIC = """ARRANGEMENT OF SECTIONS
1. Alpha thing.
2. Beta thing.
3. Gamma thing.
4. Delta thing.
5. Epsilon thing.
Note: For Reference only.
CORRESPONDING SECTION TABLE OF BNS WITH REPEALED ACT
Bharatiya Nyaya Sanhita, 2023
Indian Penal Code, 1860
1. Alpha thing.  10. Alpha thing.
Deleted 11A. Removed thing.
2. Beta thing.
2 (1)
20. Beta thing part one.
2 (2), 2 (3) 21. Beta thing part two.
Gamma thing.
3(1)
171-I. Gamma thing.
4. Delta thing. New Section
5. Epsilon thing.
216A.Epsilon thing.
  Chapters and Sections              HomePage
1. (1) The real Act starts here and must never be read as table rows. 99. Not a row.
"""


def pairs(cw):
    return [(r.old_section, r.new_ref) for r in cw.rows]


def test_real_excerpt_rows_and_subclauses():
    cw = extract_crosswalk(FIXTURE.read_text(encoding="utf-8"))
    got = dict(pairs(cw))
    assert got["53"] == "4" and got["57"] == "6" and got["511"] == "62" and got["375"] == "63" and got["376"] == "64"
    assert got["304B"] == "80" and got["119"] == "59" and got["120"] == "60"
    assert got["120A"] == "61(1)" and got["120B"] == "61(2)"  # sub-clause markers become new_ref
    assert got["54"] == "5(a)"
    assert cw.new_provisions == ["358"]


def test_layout_quirks():
    cw = extract_crosswalk(SYNTHETIC)
    assert pairs(cw) == [
        ("10", "1"),
        ("20", "2(1)"),
        ("21", "2(2)"),  # "2 (2), 2 (3) 21." : one IPC section, two BNS sub-clauses
        ("21", "2(3)"),
        ("171I", "3(1)"),  # BNS head printed without its number; hyphenated IPC number normalised
        ("216A", "5"),  # no space after the full stop
    ]
    assert cw.deleted_ipc == ["11A"] and cw.new_provisions == ["4"]
    assert cw.bns_without_row == [] and cw.bns_found == 5
    assert all(r.new_section.isdigit() for r in cw.rows)  # the Act text after the table is never parsed


def test_csv_keeps_curated_rows_and_marks_machine_rows_unverified(tmp_path):
    cw = extract_crosswalk(SYNTHETIC)
    curated = [{"old_act": "ipc", "old_section": "10", "new_act": "bns", "new_section": "1", "new_ref": "1(9)", "note": "hand", "verified": "true"}]
    out = tmp_path / "x.csv"
    n = write_csv(cw, out, keep=curated)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert n == len(rows) == 6  # the curated 10->1 row replaces the extracted one, never duplicates it
    assert rows[0]["new_ref"] == "1(9)" and rows[0]["verified"] == "true" and rows[0]["source"] == "curated"
    assert all(r["verified"] == "false" and r["source"] == "auto" for r in rows[1:])


def test_packaged_concordance_still_loads():
    from legalbot.concordance import Concordance

    assert Concordance.load().forward("ipc", "302")[0].new_section == "103"


def test_deleted_sections_keep_their_titles_and_are_written_separately(tmp_path):
    from legalbot.crosswalk import write_deleted_csv

    cw = extract_crosswalk(SYNTHETIC)
    assert cw.deleted_titles == {"11A": "Removed thing"}
    out = tmp_path / "d.csv"
    assert write_deleted_csv(cw, out) == 1
    row = next(csv.DictReader(out.open(encoding="utf-8")))
    assert (row["old_act"], row["old_section"], row["title"], row["source"]) == ("ipc", "11A", "Removed thing", "auto")
