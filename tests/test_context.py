"""Retrieval-time context expansion: siblings, cross-references, definitions."""
import pytest
from qdrant_client import QdrantClient

from legalbot.chunking import parse_statute
from legalbot.config import Settings
from legalbot.context import ContextExpander, ExpansionConfig, references
from legalbot.embeddings import HashEmbedder
from legalbot.generate import build_prompt
from legalbot.registry import ActInfo, ActRegistry
from legalbot.schema import Hit, LegalChunk, Status
from legalbot.store import QdrantStore


@pytest.fixture()
def store(sample_text, sample_act):
    s = QdrantStore(Settings(collection="ctx"), HashEmbedder(), client=QdrantClient(":memory:"))
    s.upsert(parse_statute(sample_text, sample_act, max_chars=330))  # forces §2 (definitions) to split
    return s


def first(store, act, no, part=0):
    return next(h for h in store.lookup(act, no) if h.chunk.part_index == part)


def ids(hits):
    return [h.chunk.chunk_id for h in hits]


def test_sibling_parts_are_added_in_order_right_after_the_hit(store):
    parts = store.lookup("sample", "2")
    assert len(parts) >= 2
    got = ContextExpander(store, config=ExpansionConfig(xrefs=False, definitions=False)).expand([first(store, "sample", "2", 1)])
    assert [h.chunk.part_index for h in got] == list(range(len(parts)))
    ranked = first(store, "sample", "2", 1)
    assert [h.source for h in got if h.chunk.part_index == 1] == [ranked.source]  # the ranked hit keeps its own identity
    assert all(h.source == "sibling" and h.via == "SMP §2" for h in got if h.chunk.part_index != 1)


def test_two_hits_in_one_section_do_not_duplicate_parts(store):
    parts = store.lookup("sample", "2")
    got = ContextExpander(store, config=ExpansionConfig(xrefs=False, definitions=False)).expand([Hit(chunk=p.chunk) for p in parts[:2]])
    assert len(set(ids(got))) == len(got) == len(parts)


def test_long_sections_only_pull_neighbours_of_the_hit_part(store):
    parts = store.lookup("sample", "2")
    cfg = ExpansionConfig(xrefs=False, definitions=False, max_sibling_parts=1)
    got = ContextExpander(store, config=cfg).expand([first(store, "sample", "2", 0)])
    assert [h.chunk.part_index for h in got] == [0, 1]
    assert len(parts) > 2


def test_cross_reference_pulls_the_cited_section(store):
    got = ContextExpander(store, config=ExpansionConfig(definitions=False)).expand([first(store, "sample", "3A")])
    extra = [h for h in got if h.source == "xref"]
    assert {h.chunk.section_no for h in extra} == {"4"}
    assert extra[0].via == "SMP §3A"


def test_cross_reference_already_retrieved_is_not_repeated(store):
    hits = [first(store, "sample", "3A"), first(store, "sample", "4")]
    got = ContextExpander(store, config=ExpansionConfig(definitions=False)).expand(hits)
    assert {h.chunk.section_no for h in got if h.source == "xref"} == {"3"}  # §4 cites 3 and 3A; 3A and 4 are already hits


def test_reference_to_another_act_is_not_followed_as_same_act(sample_act):
    def chunk(text):
        return LegalChunk(chunk_id="x", act_id="bns", act_name="BNS", act_short="BNS", section_no="5", header="h", text=text)

    c = chunk("See section 6 of the General Clauses Act, 1897 and section 474 of the Bharatiya Nagarik Suraksha Sanhita, 2023, and section 101.")
    assert references(c) == [("bns", "101")]  # the other-Act refs are dropped, not read as BNS §6 / §474
    reg = ActRegistry([ActInfo("bnss", "Bharatiya Nagarik Suraksha Sanhita, 2023", "BNSS", 2023, Status.IN_FORCE, ("bharatiya nagarik suraksha sanhita",))])
    assert references(c, reg) == [("bnss", "474"), ("bns", "101")]
    assert references(chunk("as in section 3 of this Sanhita")) == [("bns", "3")]
    assert references(chunk("section 5 applies")) == []  # self reference


def test_definition_clause_is_added_for_a_term_the_hit_uses(store):
    got = ContextExpander(store, config=ExpansionConfig(xrefs=False)).expand([first(store, "sample", "3")])
    defs = [h for h in got if h.source == "definition"]
    assert defs and all(h.chunk.section_no == "2" for h in defs)
    assert any("dishonestly" in h.via for h in defs)
    d = next(h for h in defs if "dishonestly" in h.via)
    assert d.chunk.text.startswith("In this Act, unless the context otherwise requires,")  # intro kept
    assert '(2) "dishonestly" means' in d.chunk.text and "(3)" not in d.chunk.text  # only the one clause
    assert d.chunk.clause_range == "(2)"


def test_no_definitions_for_the_definitions_section_itself_or_stop_terms(store):
    got = ContextExpander(store).expand([first(store, "sample", "2", 0)])
    assert not [h for h in got if h.source == "definition"]
    cfg = ExpansionConfig(xrefs=False, stop_terms=frozenset({"dishonestly", "movable property"}))
    assert not [h for h in ContextExpander(store, config=cfg).expand([first(store, "sample", "3")]) if h.source == "definition"]


def test_extras_respect_the_character_budget_but_ranked_hits_never_dropped(store):
    hit = first(store, "sample", "3")
    got = ContextExpander(store, config=ExpansionConfig(max_chars=1, siblings=False)).expand([hit])
    assert ids(got) == [hit.chunk.chunk_id]  # no room for xref/definition extras; the ranked hit stays
    assert len(ContextExpander(store, config=ExpansionConfig(siblings=False)).expand([hit])) > 1


def test_prompt_merges_parts_and_says_why_extras_are_there(store):
    got = ContextExpander(store).expand([first(store, "sample", "3A")])
    prompt = build_prompt("q", got, [])
    assert "[context: referred to by SMP §3A]" in prompt
    parts = store.lookup("sample", "2")
    prompt2 = build_prompt("q", [Hit(chunk=p.chunk) for p in parts], [])
    assert prompt2.count("[SMP §2]") == 1 and "(5)" in prompt2  # one block, every part present


def test_expand_empty():
    assert ContextExpander(None).expand([]) == []  # type: ignore[arg-type]


def test_siblings_only_for_the_best_sections(store):
    hits = [first(store, "sample", "2"), first(store, "sample", "3"), first(store, "sample", "4")]
    cfg = ExpansionConfig(xrefs=False, definitions=False, siblings_from_top=1)
    got = ContextExpander(store, config=cfg).expand(hits)
    assert len([h for h in got if h.chunk.section_no == "2"]) == len(store.lookup("sample", "2"))  # best section: complete
    assert [h.chunk.chunk_id for h in got if h.chunk.section_no == "3"] == ["sample:3:0"]  # the rest: as retrieved
