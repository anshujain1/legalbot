import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from legalbot.api import create_app
from legalbot.chunking import parse_statute
from legalbot.concordance import Concordance
from legalbot.config import Settings
from legalbot.embeddings import HashEmbedder
from legalbot.generate import INSUFFICIENT, build_prompt
from legalbot.pipeline import LegalBot, LLMNotConfigured
from legalbot.registry import ActInfo, ActRegistry
from legalbot.schema import Hit, Status
from legalbot.store import QdrantStore
from legalbot.verify import verify


class FakeLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[str] = []

    def complete(self, system, user):
        self.calls.append(user)
        return self.replies.pop(0)


@pytest.fixture()
def registry(sample_act):
    shorts = {"bns": ActInfo("bns", "Bharatiya Nyaya Sanhita, 2023", "BNS", 2023, Status.IN_FORCE, ("bns",))}
    return ActRegistry([sample_act, *shorts.values()])


@pytest.fixture()
def hits(sample_text, sample_act):
    chunks = parse_statute(sample_text, sample_act)
    return [Hit(chunk=c) for c in chunks if c.section_no in {"3", "4"}]


def make_bot(sample_text, sample_act, registry, llm):
    store = QdrantStore(Settings(collection="t"), HashEmbedder(), client=QdrantClient(":memory:"))
    store.upsert(parse_statute(sample_text, sample_act))
    return LegalBot(store, registry, Concordance.load(), llm=llm)


# ---------------------------------------------------------------- verify


def test_verify_accepts_citations_present_in_sources(hits, registry):
    v = verify("Theft is defined in [SMP §3] and punished under [SMP §4].", hits, registry)
    assert v.ok and v.unsupported == []


def test_verify_flags_citation_not_in_sources(hits, registry):
    v = verify("See [SMP §3] and [SMP §99].", hits, registry)
    assert v.unsupported == [("smp", "99")]
    assert not v.ok


def test_verify_flags_free_text_mentions_too(hits, registry):
    v = verify("Under BNS section 303 this is theft [SMP §3].", hits, registry)
    assert ("bns", "303") in v.unsupported


def test_verify_allows_concordance_refs(hits, registry):
    v = verify("IPC §420 corresponds to BNS §318 [SMP §3].", hits, registry, [("ipc", "420"), ("bns", "318")])
    assert v.unsupported == []


def test_verify_requires_a_citation_unless_insufficient(hits, registry):
    assert not verify("Theft is a crime.", hits, registry).ok
    assert verify(f"{INSUFFICIENT} the sources do not cover this.", hits, registry).ok


# ---------------------------------------------------------------- pipeline


def test_prompt_contains_labels_notes_and_text(hits):
    p = build_prompt("What is theft?", hits, ["IPC §379 corresponds to BNS §303"])
    assert "[SMP §3]" in p and "[SMP §4]" in p
    assert "- IPC §379 corresponds to BNS §303" in p
    assert "said to commit theft" in p


def test_ask_happy_path(sample_text, sample_act, registry):
    bot = make_bot(sample_text, sample_act, registry, FakeLLM("Theft is punishable by up to three years [SMP §4]."))
    ans = bot.ask("What is the punishment for theft?")
    assert ans.verified and not ans.warnings
    assert any(s.label == "SMP §4" for s in ans.sources)


def test_ask_retries_once_on_bad_citation_then_succeeds(sample_text, sample_act, registry):
    llm = FakeLLM("It is covered by [SMP §77].", "Up to three years [SMP §4].")
    ans = make_bot(sample_text, sample_act, registry, llm).ask("What is the punishment for theft?")
    assert len(llm.calls) == 2 and "SMP §77" in llm.calls[1]
    assert ans.verified and ans.warnings == []


def test_ask_surfaces_unverified_citation_after_failed_retry(sample_text, sample_act, registry):
    llm = FakeLLM("See [SMP §77].", "Still [SMP §77].")
    ans = make_bot(sample_text, sample_act, registry, llm).ask("What is the punishment for theft?")
    assert not ans.verified
    assert "SMP §77" in ans.warnings[0]


def test_ask_insufficient_context(sample_text, sample_act, registry):
    llm = FakeLLM(f"{INSUFFICIENT} the sources do not mention bail.")
    ans = make_bot(sample_text, sample_act, registry, llm).ask("Tell me about theft")
    assert ans.insufficient and ans.verified
    assert ans.answer.startswith("the sources do not mention bail")


def test_ask_without_llm_raises(sample_text, sample_act, registry):
    with pytest.raises(LLMNotConfigured):
        make_bot(sample_text, sample_act, registry, None).ask("anything")


# ---------------------------------------------------------------- API


@pytest.fixture()
def client(sample_text, sample_act, registry):
    bot = make_bot(sample_text, sample_act, registry, FakeLLM("Up to three years [SMP §4]."))
    return TestClient(create_app(bot))


def test_api_health_and_acts(client):
    assert client.get("/health").json()["status"] == "ok"
    assert {a["act_id"] for a in client.get("/acts").json()} == {"sample", "bns"}


def test_api_search_returns_plan_and_results(client):
    body = client.post("/search", json={"query": "punishment for theft", "k": 3}).json()
    assert body["results"] and body["plan"]["original"] == "punishment for theft"
    assert any(r["section_no"] == "4" for r in body["results"])


def test_api_search_with_filters_and_mode(client):
    body = client.post(
        "/search", json={"query": "theft", "mode": "sparse", "filters": {"act_ids": ["bns"]}}
    ).json()
    assert body["results"] == []


def test_api_ask(client):
    body = client.post("/ask", json={"question": "What is the punishment for theft?"}).json()
    assert body["verified"] is True and "SMP §4" in body["answer"]
    assert body["disclaimer"]


def test_api_ask_503_without_llm(sample_text, sample_act, registry):
    c = TestClient(create_app(make_bot(sample_text, sample_act, registry, None)))
    assert c.post("/ask", json={"question": "theft?"}).status_code == 503


def test_api_section_lookup(client):
    assert client.get("/sections/sample/4").json()[0]["section_title"] == "Punishment for theft"
    assert client.get("/sections/sample/999").status_code == 404
    assert client.get("/sections/nope/1").status_code == 404
