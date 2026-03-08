import pytest
from qdrant_client import QdrantClient

from legalbot.chunking import parse_statute
from legalbot.concordance import Concordance
from legalbot.config import Settings
from legalbot.embeddings import HashEmbedder
from legalbot.evaluate_answers import grade
from legalbot.generate import build_prompt
from legalbot.pipeline import LegalBot
from legalbot.registry import ActRegistry
from legalbot.store import QdrantStore
from legalbot.verify import normalize_citations, verify


@pytest.fixture(scope="module")
def reg():
    return ActRegistry.load()


@pytest.mark.parametrize(
    "raw,want",
    [
        ("Defamation is punished【BNS §356】.", "[BNS §356]"),
        ("Kidnapping [​BNS §137​].", "[BNS §137]"),
        ("Trafficking [**BNS §143 (2)**]", "[BNS §143 (2)]"),
        ("This is **BNS §309** (Robbery).", "[BNS §309] (Robbery)"),
        ("See BNS §318(4) for cheating.", "[BNS §318]"),
        ("Already fine [BNS §103].", "[BNS §103]"),
    ],
)
def test_citation_styles_are_normalised(reg, raw, want):
    assert want in normalize_citations(raw, reg)


def test_normalised_text_verifies_and_does_not_double_wrap(reg):
    out = normalize_citations("Murder【BNS §103】 and **BNS §101**; again [BNS §103].", reg)
    assert "[[" not in out and out.count("[BNS §103]") == 2
    assert verify(out, [], reg, [("bns", "103"), ("bns", "101")]).ok


def test_deleted_section_is_answered_from_the_table_even_when_search_finds_other_sections(sample_text, sample_act):
    class Exploding:
        def complete(self, system, user):
            raise AssertionError("the model must not be asked about a deleted section")

    store = QdrantStore(Settings(collection="d2"), HashEmbedder(), client=QdrantClient(":memory:"))
    store.upsert(parse_statute(sample_text, sample_act))
    bot = LegalBot(store, ActRegistry.load(), Concordance.load(), llm=Exploding())
    # the sample Act is not filtered out for this phrasing, so search returns hits; the answer must still come from the table
    _, hits = bot.search("What is the BNS equivalent of IPC 124A sedition?", filters=None)
    ans = bot.ask("What is the BNS equivalent of IPC 124A sedition?")
    assert "no equivalent" in ans.answer and ans.verified and not ans.sources
    assert hits is not None


def test_prompt_lists_the_indexed_acts(sample_text, sample_act):
    store = QdrantStore(Settings(collection="d3"), HashEmbedder(), client=QdrantClient(":memory:"))
    store.upsert(parse_statute(sample_text, sample_act))
    hits = store.lookup(sample_act.act_id, "1")
    assert "Indexed Acts: Sample Penal Act, 2099" in build_prompt("q", hits, [])


def test_plain_refusal_sentence_counts_as_refusal_for_unsafe_requests():
    row = {"question": "q", "kind": "injection"}
    ans = {"answer": "I’m sorry, but I can’t help with that.", "verified": False, "insufficient": False}
    assert grade(row, ans, {})["pass"]
    assert not grade({"question": "q", "kind": "in_scope", "expected": [{"act": "bns", "section": "1"}]}, ans, {})["pass"]
