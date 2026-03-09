from pathlib import Path

from legalbot.chunking import parse_statute
from legalbot.normalize import repair_spacing
from legalbot.registry import ActInfo
from legalbot.schema import Status

FIXTURE = Path(__file__).parent / "fixtures" / "sankalan_excerpt.txt"


def pad(words: dict[str, int]) -> str:
    """A document in which each word occurs the given number of times (so frequencies are controlled)."""
    return " ".join(w for w, n in words.items() for _ in range(n))


def fixed(text: str) -> str:
    return repair_spacing(text)[0]


def test_lone_letter_fragments_are_joined_when_the_word_exists_elsewhere():
    doc = pad({"the": 12, "caste": 2, "shall": 2}) + " | t he court, on the ground of cast e or community, s hall"
    out = fixed(doc)
    assert "the court" in out and "caste or community" in out and "shall" in out.split("|")[1]


def test_two_rare_fragments_are_joined():
    doc = pad({"organised": 6, "crime": 3}) + " | an organis ed crime"
    assert "organised crime" in fixed(doc).split("|")[1]


def test_frequent_word_beats_a_rare_spaced_pair():
    doc = pad({"person": 40}) + " | any per son who"
    assert "any person who" in fixed(doc).split("|")[1]


def test_legal_phrases_that_look_like_split_words_are_untouched():
    doc = pad({"door": 3, "anyone": 5}) + " | to do or omit; any one of the following; no one may"
    out = fixed(doc).split("|")[1]
    assert "do or omit" in out and "any one of" in out and "no one" in out


def test_word_that_never_appears_whole_is_not_invented():
    assert "syndi cate" in fixed("a criminal syndi cate")  # 'syndicate' appears nowhere else: leave it


def test_short_results_must_be_common_words():
    # "a c" -> "ac" and "to p" -> "top" were real false joins found on the BNS text
    doc = pad({"ac": 1, "top": 1, "to": 20, "punishment": 10}) + " | such a c ommittee; to p unishment"
    out = fixed(doc).split("|")[1]
    assert "a c " in out and "top" not in out and "to punishment" in out


def test_lone_letter_goes_to_the_word_it_fits_best():
    doc = pad({"punishment": 12, "top": 2}) + " | liable to p unishment"
    assert "to punishment" in fixed(doc).split("|")[1]


def test_uppercase_variables_and_possessives_are_never_touched():
    doc = pad({"consent": 4, "ab": 3}) + " | A cheats Z; a person’s consent; B s consent"
    assert fixed(doc).split("|")[1] == " A cheats Z; a person’s consent; B s consent"


def test_returns_a_report_of_every_repair():
    _, rep = repair_spacing(pad({"the": 12}) + " t he t he")
    assert rep[("t he", "the")] == 2


def test_parser_sees_repaired_text(tmp_path):
    act = ActInfo("bns", "Bharatiya Nyaya Sanhita, 2023", "BNS", 2023, Status.IN_FORCE)
    text, rep = repair_spacing(FIXTURE.read_text(encoding="utf-8"))
    chunks = parse_statute(text, act)
    body = " ".join(c.text for c in chunks)
    assert "on such date as the Central Government" in body  # was "as t he" in the source
    assert "t he Central" not in body and sum(rep.values()) > 0
