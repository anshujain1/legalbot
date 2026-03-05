from legalbot.chunking import parse_statute
from legalbot.chunking.statute import repair_split_words
from legalbot.registry import ActInfo
from legalbot.schema import Status

ACT = ActInfo("t", "Test Act, 2000", "TST", 2000, Status.IN_FORCE)


def test_split_words_are_rejoined_only_when_the_document_uses_the_joined_word():
    ok = "property and imprisonment for life"
    lines = [ok] * 4 + ["pr operty and impriso nment f or life", "any one may go in to the house", "sub -section (1)"]
    out = repair_split_words(lines)
    assert out[4] == "property and imprisonment for life"
    assert out[5] == "any one may go in to the house"  # both halves are real words here: left alone
    assert out[6] == "sub-section (1)"


def test_heading_wrapped_over_two_lines_is_not_left_on_the_previous_section():
    idx = "ARRANGEMENT OF SECTIONS\n1. First thing.\n2. Second thing.\n3. Third thing.\n"
    body = (
        "CHAPTER I\nPRELIMINARY\nFirst thing.\n1. Whoever does the first thing shall be punished with fine.\n"
        "Of breach of contract to attend on and supply wants of helpless\nperson\n"
        "Second thing.\n2. Whoever does the second thing shall be punished with fine.\n"
        "Third thing.\n3. Whoever does the third thing shall be punished with fine.\n"
    )
    chunks = parse_statute(idx + body, ACT)
    assert chunks[0].text.endswith("punished with fine.") and "Of breach" not in chunks[0].text
