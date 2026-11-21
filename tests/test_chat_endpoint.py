"""The /chat wrapper: what chat-style frontends send and read."""
import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from legalbot.api import create_app
from legalbot.chunking import parse_statute
from legalbot.concordance import Concordance
from legalbot.config import Settings
from legalbot.embeddings import HashEmbedder
from legalbot.pipeline import LegalBot
from legalbot.registry import ActRegistry
from legalbot.store import QdrantStore


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, user):
        return self.reply


def make_client(sample_text, sample_act, llm):
    store = QdrantStore(Settings(collection="t"), HashEmbedder(), client=QdrantClient(":memory:"))
    store.upsert(parse_statute(sample_text, sample_act))
    bot = LegalBot(store, ActRegistry([sample_act]), Concordance.load(), llm=llm)
    return TestClient(create_app(bot, Settings()))


@pytest.mark.parametrize("path", ["/chat", "/api/chat"])
def test_chat_returns_reply_and_titled_sources(sample_text, sample_act, path):
    c = make_client(sample_text, sample_act, FakeLLM("Theft is punished under [SMP §4]."))
    body = {"message": "punishment for theft", "history": [{"role": "user", "text": "hi"}, {"role": "ai", "text": "hello"}]}
    r = c.post(path, json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["reply"] == data["answer"] and "[SMP §4]" in data["reply"]
    assert data["raw_answer"] == "Theft is punished under [SMP §4]."
    assert data["disclaimer"] in data["reply"]
    assert data["sources"] and all(s["title"] and s["snippet"] for s in data["sources"])
    labels = [s["label"] for s in data["sources"]]
    assert len(labels) == len(set(labels))  # parts of a split section are listed once


def test_chat_accepts_content_style_history(sample_text, sample_act):
    c = make_client(sample_text, sample_act, FakeLLM("Theft is punished under [SMP §4]."))
    body = {"message": "punishment for theft", "history": [{"role": "user", "content": "hi"}], "conversation_id": "abc"}
    assert c.post("/api/chat", json=body).status_code == 200


def test_chat_without_llm_is_503_with_a_readable_detail(sample_text, sample_act):
    r = make_client(sample_text, sample_act, None).post("/chat", json={"message": "punishment for theft"})
    assert r.status_code == 503 and "GROQ_API_KEY" in r.json()["detail"]


def test_chat_respects_the_api_key(sample_text, sample_act):
    store = QdrantStore(Settings(collection="t"), HashEmbedder(), client=QdrantClient(":memory:"))
    store.upsert(parse_statute(sample_text, sample_act))
    bot = LegalBot(store, ActRegistry([sample_act]), Concordance.load(), llm=FakeLLM("x [SMP §4]"))
    c = TestClient(create_app(bot, Settings(api_key="k")))
    assert c.post("/chat", json={"message": "theft"}).status_code == 401
