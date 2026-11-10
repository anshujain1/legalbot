from legalbot.chunking import parse_statute, qa_report


def by_id(chunks):
    return {c.chunk_id: c for c in chunks}


def test_sections_found_in_order_and_toc_ignored(sample_text, sample_act):
    chunks = parse_statute(sample_text, sample_act)
    sections = [c.section_no for c in chunks if c.section_no]
    assert sections == ["1", "2", "3", "3A", "4"]


def test_index_entry_replaced_by_real_text(sample_text, sample_act):
    chunks = by_id(parse_statute(sample_text, sample_act))
    assert "said to commit theft" in chunks["sample:3:0"].text
    assert len(chunks["sample:3:0"].text) > 100  # not just the one-line index entry


def test_chapter_metadata_attached(sample_text, sample_act):
    chunks = by_id(parse_statute(sample_text, sample_act))
    assert chunks["sample:1:0"].chapter_no == "I"
    assert chunks["sample:1:0"].chapter_title == "Preliminary"
    assert chunks["sample:3:0"].chapter_no == "II"
    assert chunks["sample:3:0"].chapter_title == "Of Offences Against Property"
    assert chunks["sample:4:0"].chapter_no == "II"


def test_header_carries_context_and_is_embedded(sample_text, sample_act):
    c = by_id(parse_statute(sample_text, sample_act))["sample:4:0"]
    assert c.header == "Sample Penal Act, 2099 | Chapter II: Of Offences Against Property | Section 4: Punishment for theft"
    assert c.embed_text.startswith(c.header)
    assert c.label == "SMP §4"


def test_running_headers_and_page_numbers_removed(sample_text, sample_act):
    for c in parse_statute(sample_text, sample_act):
        assert "GAZETTE" not in c.text


def test_wrapped_lines_are_reflowed_but_clauses_stay_separate(sample_text, sample_act):
    chunks = by_id(parse_statute(sample_text, sample_act))
    s1 = chunks["sample:1:0"].text
    assert "such date as the Central Government may, by notification, appoint." in s1
    assert s1.count("\n") == 1  # clause (1) and clause (2) on separate lines


def test_proviso_and_illustration_stay_with_parent_section(sample_text, sample_act):
    chunks = by_id(parse_statute(sample_text, sample_act))
    assert "Provided that" in chunks["sample:4:0"].text
    assert "Explanation 1" in chunks["sample:3:0"].text
    assert "Illustration" in chunks["sample:3:0"].text


def test_cross_refs_extracted_and_self_excluded(sample_text, sample_act):
    chunks = by_id(parse_statute(sample_text, sample_act))
    assert chunks["sample:3A:0"].cross_refs == ["4"]
    assert chunks["sample:4:0"].cross_refs == ["3", "3A"]


def test_long_section_splits_by_clause_and_repeats_intro(sample_text, sample_act):
    chunks = parse_statute(sample_text, sample_act, max_chars=330)
    parts = [c for c in chunks if c.section_no == "2"]
    assert len(parts) >= 2
    assert all(c.part_count == len(parts) for c in parts)
    assert [c.part_index for c in parts] == list(range(len(parts)))
    for c in parts:
        assert c.text.startswith("In this Act, unless the context otherwise requires,")
        assert c.clause_range and c.clause_range.startswith("(")
        assert "clauses" in c.header
    joined = " ".join(c.text for c in parts)
    for n in range(1, 6):
        assert f"({n})" in joined  # nothing lost


def test_short_section_not_split(sample_text, sample_act):
    parts = [c for c in parse_statute(sample_text, sample_act, max_chars=330) if c.section_no == "4"]
    assert len(parts) == 1


def test_schedule_text_dropped(sample_text, sample_act):
    for c in parse_statute(sample_text, sample_act):
        assert "Form of notice" not in c.text


def test_preamble_chunk(sample_text, sample_act):
    pre = [c for c in parse_statute(sample_text, sample_act) if c.section_no is None]
    assert len(pre) == 1
    assert "consolidation of sample offences" in pre[0].text


def test_qa_report(sample_text, sample_act):
    report = qa_report(parse_statute(sample_text, sample_act))
    assert report["sections"] == 5
    assert report["missing_section_numbers"] == []
    assert report["no_chapter"] == []


def test_qa_report_flags_gaps(sample_act):
    text = (
        "CHAPTER I\nPRELIMINARY\n"
        "1. Short title.—This Act is the Gap Act, applicable to the whole of India.\n"
        "4. Fourth.—Some text about a fourth thing that is long enough to count.\n"
    )
    report = qa_report(parse_statute(text, sample_act))
    assert report["missing_section_numbers"] == [2, 3]
