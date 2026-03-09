"""Regressions found by running the chunker on the real BNS text."""
from legalbot.chunking.statute import _hard_split, pack, reflow


def test_wrapped_reference_does_not_start_a_paragraph():
    # real BNS s.358(2): the line wrap lands right before "(1),"
    paras = reflow([
        "(2) Notwithstanding the repeal of the Code referred to in sub-section",
        "(1), it shall not affect,—",
        "(a) the previous operation of the Code;",
    ])
    assert paras == [
        "(2) Notwithstanding the repeal of the Code referred to in sub-section (1), it shall not affect,—",
        "(a) the previous operation of the Code;",
    ]


def test_real_clause_markers_still_start_paragraphs():
    paras = reflow(["(1) First clause", "continues here;", "(a) item", "(b)item without space", "(i) roman", "(2) Second"])
    assert [p[:3] for p in paras] == ["(1)", "(a)", "(b)", "(i)", "(2)"]


def test_hard_split_prefers_paragraph_boundaries():
    unit = "(1) Whoever cheats.\n" + "\n".join(
        f"({chr(97 + i % 26)}) A intentionally deceives Z number {i} and thereby dishonestly induces Z to lend. A cheats."
        for i in range(30)
    )
    pieces = _hard_split(unit, 500)
    assert len(pieces) > 3
    # no piece begins with the orphaned tail "A cheats." of the previous paragraph
    assert not any(p.startswith("A cheats.") for p in pieces)
    assert all(p.startswith("(") for p in pieces)
    assert "".join(pieces).replace("\n", "").count("A cheats.") == 30  # nothing lost


def test_oversized_clause_parts_keep_the_intro_and_start_cleanly():
    intro = "In this Sanhita, unless the context otherwise requires,—"
    unit = "(1) " + "\n".join(f"(a) Illustration {i}: A does a thing to Z. A is guilty." for i in range(40))
    parts = pack([intro, unit], 600)
    assert len(parts) > 2
    for text, _ in parts:
        assert text.startswith(intro)
        assert not text.split("\n", 1)[1].startswith("A is guilty.")
