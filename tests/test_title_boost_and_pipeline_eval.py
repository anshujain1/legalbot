import pytest
from qdrant_client import QdrantClient

from legalbot.chunking import parse_statute
from legalbot.concordance import Concordance
from legalbot.config import Settings
from legalbot.embeddings import HashEmbedder
from legalbot.evaluate import evaluate
from legalbot.pipeline import LegalBot
from legalbot.registry import ActRegistry
from legalbot.registry import ActInfo
from legalbot.schema import LegalChunk, Status
from legalbot.store import QdrantStore


def chunk(no, title, body):
    return LegalChunk(
        chunk_id=f"x:{no}:0", act_id="x", act_name="X Act", act_short="X", section_no=no,
        section_title=title, header=f"X Act | Section {no}: {title}", text=body,
    )


def test_sparse_text_repeats_the_title_but_dense_text_does_not():
    c = chunk("1", "Grievous hurt", "kinds of hurt designated as grievous")
    assert c.sparse_text.count("Grievous hurt") == 3 + 1  # 3 boosts + the header's own mention
    assert c.embed_text.count("Grievous hurt") == 1  # dense embedding text is unchanged


def _top(rep, monkeypatch):
    import legalbot.schema as schema

    monkeypatch.setattr(schema, "SPARSE_TITLE_REPEAT", rep)
    store = QdrantStore(Settings(collection=f"tb{rep}"), HashEmbedder(), client=QdrantClient(":memory:"))
    spam = "The offender may also cause grievous hurt in such a case. " * 3  # a body that mentions the phrase a few times
    store.upsert([
        chunk("116", "Grievous hurt", "The following kinds of hurt only are designated as grievous: emasculation; loss of sight."),
        chunk("200", "Punishment for assault", spam),
    ])
    return store.search_sparse("What is grievous hurt?", None, 2)[0].chunk.section_no


def test_a_title_match_beats_a_body_that_merely_repeats_the_words(monkeypatch):
    """Without the boost the section that only MENTIONS the phrase wins; with it the section TITLED by it does.
    Limits, measured: the boost is logarithmic, so a body repeating the phrase 6+ times still wins, and it does not
    separate two sections that are both titled with the phrase (BNS s.116 vs s.117)."""
    assert _top(0, monkeypatch) == "200"  # the failure the boost exists to fix
    assert _top(3, monkeypatch) == "116"


def test_pipeline_row_measures_the_concordance_while_the_other_rows_do_not(tmp_path):
    from pathlib import Path

    act = ActRegistry.load().get("bns")
    text = (Path(__file__).parent / "fixtures" / "sankalan_excerpt.txt").read_text(encoding="utf-8")
    store = QdrantStore(Settings(collection="pe"), HashEmbedder(), client=QdrantClient(":memory:"))
    store.upsert(parse_statute(text, act))
    bot = LegalBot(store, ActRegistry.load(), Concordance.load())
    gold = [{"question": "IPC 376 equivalent in BNS", "expected": [{"act": "bns", "section": "64"}], "category": "oldref"}]
    report = evaluate(bot, gold, k=3)
    assert report["pipeline"]["overall"]["hit@1"] == 1.0  # IPC 376 -> BNS 64 is pinned before ranking
    assert report["pipeline"]["misses"] == []
