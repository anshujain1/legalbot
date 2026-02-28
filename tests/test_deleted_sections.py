"""IPC sections the comparison table lists as deleted: say so instead of 'nothing found'."""
import pytest
from qdrant_client import QdrantClient

from legalbot.chunking import parse_statute
from legalbot.concordance import Concordance
from legalbot.config import Settings
from legalbot.embeddings import HashEmbedder
from legalbot.pipeline import LegalBot
from legalbot.query import QueryAnalyzer
from legalbot.registry import ActRegistry
from legalbot.store import QdrantStore


class ExplodingLLM:  # a deleted section must be answered from the table, never by asking the model
    def complete(self, system, user):
        raise AssertionError("LLM should not be called")


@pytest.fixture(scope="module")
def conc():
    return Concordance.load()


def test_packaged_data_knows_the_headline_deletions(conc):
    for no, word in [("124A", "Sedition"), ("497", "Adultery"), ("377", "Unnatural")]:
        r = conc.removed("ipc", no)
        assert r is not None and word in r.title and r.verified is False
    assert conc.removed("ipc", "302") is None and conc.removed("bns", "124A") is None
    assert conc.forward("ipc", "124A") == []  # deleted sections have no mapping row


def test_custom_mapping_path_does_not_silently_load_packaged_removals(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("old_act,old_section,new_act,new_section\nipc,1,bns,1\n", encoding="utf-8")
    assert Concordance.load(p).removed("ipc", "124A") is None


def test_plan_says_there_is_no_equivalent(conc):
    plan = QueryAnalyzer(ActRegistry.load(), conc).plan("what replaced IPC 124A sedition?")
    assert plan.removed_refs == [("ipc", "124A")]
    note = next(n for n in plan.notes if "124A" in n)
    assert "no equivalent" in note and "Sedition" in note and "unverified" in note
    assert ("ipc", "124A") in plan.mapped_refs  # citing the deleted IPC section is allowed


def test_a_normal_mapping_is_not_reported_as_deleted(conc):
    plan = QueryAnalyzer(ActRegistry.load(), conc).plan("IPC 420")
    assert plan.removed_refs == [] and any("BNS §318" in n for n in plan.notes)


def test_ask_answers_a_deleted_section_without_the_model(conc, sample_act, sample_text):
    store = QdrantStore(Settings(collection="d"), HashEmbedder(), client=QdrantClient(":memory:"))
    store.upsert(parse_statute(sample_text, sample_act))
    bot = LegalBot(store, ActRegistry.load(), conc, llm=ExplodingLLM())
    ans = bot.ask("what replaced IPC 124A sedition?")
    assert not ans.insufficient and ans.verified
    assert "no equivalent" in ans.answer and "124A" in ans.answer
    assert "Do not present" not in ans.answer  # that sentence is an instruction for the model, not for the user


def test_system_prompt_forbids_inventing_a_replacement():
    from legalbot.generate import SYSTEM_PROMPT

    assert "deleted with no equivalent" in SYSTEM_PROMPT
