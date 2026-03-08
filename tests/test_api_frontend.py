"""What a browser frontend needs from the API: CORS, an optional API key, and a stable response shape."""
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

ORIGIN = "https://legalbot.example.com"


@pytest.fixture()
def bot(sample_text, sample_act):
    store = QdrantStore(Settings(collection="t"), HashEmbedder(), client=QdrantClient(":memory:"))
    store.upsert(parse_statute(sample_text, sample_act))
    return LegalBot(store, ActRegistry([sample_act]), Concordance.load())


def make_client(bot, **kw):
    return TestClient(create_app(bot, Settings(**kw)))


def test_preflight_allows_configured_origin(bot):
    c = make_client(bot, cors_origins=(ORIGIN,))
    r = c.options(
        "/search",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-api-key"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "x-api-key" in r.headers["access-control-allow-headers"].lower()


def test_unlisted_origin_gets_no_cors_header(bot):
    c = make_client(bot, cors_origins=(ORIGIN,))
    r = c.post("/search", json={"query": "theft"}, headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in r.headers


def test_actual_response_carries_cors_header(bot):
    c = make_client(bot, cors_origins=(ORIGIN,))
    r = c.post("/search", json={"query": "theft"}, headers={"Origin": ORIGIN})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == ORIGIN


def test_default_origins_cover_local_dev(bot):
    c = make_client(bot)
    r = c.get("/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_api_key_is_enforced_when_set_but_health_and_preflight_stay_open(bot):
    c = make_client(bot, cors_origins=(ORIGIN,), api_key="s3cret")
    assert c.get("/health").status_code == 200
    assert c.options("/search", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"}).status_code == 200
    assert c.post("/search", json={"query": "theft"}).status_code == 401
    assert c.post("/search", json={"query": "theft"}, headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/search", json={"query": "theft"}, headers={"X-API-Key": "s3cret"}).status_code == 200
    assert c.get("/acts").status_code == 401
    assert c.get("/sections/sample/4").status_code == 401
    assert c.get("/sections/sample/4", headers={"X-API-Key": "s3cret"}).status_code == 200


def test_no_key_configured_means_open(bot):
    assert make_client(bot).post("/search", json={"query": "theft"}).status_code == 200


def test_source_shape_is_what_the_frontend_documents(bot):
    body = make_client(bot).post("/search", json={"query": "punishment for theft", "k": 2}).json()
    src = body["results"][0]
    assert set(src) == {
        "chunk_id", "label", "act_id", "act", "status", "year", "section_no", "section_title", "chapter",
        "clause_range", "part", "text", "source", "via", "score",
    }
    assert src["part"] == "1/1" and src["status"] == "in_force" and src["label"].startswith("SMP §")


def test_openapi_schema_is_served_for_type_generation(bot):
    spec = make_client(bot).get("/openapi.json").json()
    assert {"/search", "/ask", "/sections/{act_id}/{section_no}", "/acts", "/health"} <= set(spec["paths"])
    assert "Source" in spec["components"]["schemas"] and "Answer" in spec["components"]["schemas"]
