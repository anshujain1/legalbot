import pytest
from qdrant_client import QdrantClient

from legalbot.chunking import parse_statute
from legalbot.config import Settings
from legalbot.embeddings import HashEmbedder
from legalbot.retrieval import Retriever, rrf_fuse
from legalbot.schema import Hit, SearchFilters, Status
from legalbot.sparse import sparse_vector
from legalbot.store import QdrantStore


@pytest.fixture()
def store(sample_text, sample_act):
    s = QdrantStore(Settings(collection="test"), HashEmbedder(), client=QdrantClient(":memory:"))
    s.upsert(parse_statute(sample_text, sample_act))
    return s


def test_sparse_vector_is_sorted_and_weighted():
    idx, val = sparse_vector("punishment for theft theft")
    assert idx == sorted(idx)
    assert len(idx) == len(val) > 0
    assert max(val) > 1.0  # repeated term gets log-tf boost


def test_upsert_is_idempotent(store, sample_text, sample_act):
    before = store.count()
    store.upsert(parse_statute(sample_text, sample_act))
    assert store.count() == before


@pytest.mark.parametrize("mode", ["dense", "sparse", "hybrid"])
def test_modes_find_the_right_section(store, mode):
    hits = Retriever(store).search("what is the punishment for theft", k=3, mode=mode)
    assert "4" in [h.chunk.section_no for h in hits]


def test_hybrid_ranks_exact_term_match_first(store):
    hits = Retriever(store).search("aggravated theft preparation for causing hurt", k=3)
    assert hits[0].chunk.section_no == "3A"


def test_metadata_filter_excludes_other_acts(store):
    r = Retriever(store)
    assert r.search("theft", SearchFilters(act_ids=["bns"]), k=5) == []
    assert r.search("theft", SearchFilters(act_ids=["sample"]), k=5)


def test_status_and_chapter_filters(store):
    r = Retriever(store)
    assert r.search("theft", SearchFilters(statuses=[Status.REPEALED]), k=5) == []
    hits = r.search("short title", SearchFilters(chapter_nos=["II"]), k=10)
    assert hits and all(h.chunk.chapter_no == "II" for h in hits)


def test_year_range_filter(store):
    r = Retriever(store)
    assert r.search("theft", SearchFilters(year_min=2100), k=5) == []
    assert r.search("theft", SearchFilters(year_min=2000, year_max=2100), k=5)


def test_explicit_sections_are_pinned_first(store):
    hits = Retriever(store).search("completely unrelated words", k=3, explicit_sections=[("sample", "3A")])
    assert hits[0].chunk.section_no == "3A"
    assert hits[0].source == "lookup"


def test_lookup_returns_parts_in_order(store):
    hits = store.lookup("sample", "3A")
    assert [h.chunk.part_index for h in hits] == [0]
    assert store.lookup("sample", "999") == []


def test_delete_act_removes_chunks(store):
    store.delete_act("sample")
    assert store.count() == 0


def test_dimension_mismatch_is_caught(store):
    other = QdrantStore(Settings(collection="test"), HashEmbedder(dim=64), client=store.client)
    with pytest.raises(ValueError, match="dim"):
        other.ensure_collection()


def test_rrf_prefers_items_ranked_well_in_both_lists(sample_text, sample_act):
    chunks = {c.section_no: c for c in parse_statute(sample_text, sample_act) if c.section_no}
    h = lambda no: Hit(chunk=chunks[no])
    fused = rrf_fuse({"a": [h("1"), h("3"), h("4")], "b": [h("3"), h("4"), h("1")]})
    assert fused[0].chunk.section_no == "3"
    assert all(x.source == "hybrid" for x in fused)
