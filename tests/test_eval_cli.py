import json

import pytest
from qdrant_client import QdrantClient

from legalbot.chunking import parse_statute
from legalbot.cli import main
from legalbot.concordance import Concordance
from legalbot.config import Settings
from legalbot.embeddings import HashEmbedder
from legalbot.evaluate import evaluate, format_report, load_gold
from legalbot.pipeline import LegalBot
from legalbot.registry import ActRegistry
from legalbot.store import QdrantStore


@pytest.fixture()
def bot(sample_text, sample_act):
    store = QdrantStore(Settings(collection="t"), HashEmbedder(), client=QdrantClient(":memory:"))
    store.upsert(parse_statute(sample_text, sample_act))
    return LegalBot(store, ActRegistry([sample_act]), Concordance.load())


@pytest.fixture()
def gold_file(tmp_path):
    rows = [
        {"question": "punishment for theft", "expected": [{"act": "sample", "section": "4"}], "category": "offence"},
        {"question": "aggravated theft with preparation to cause hurt", "expected": [{"act": "sample", "section": "3A"}], "category": "offence"},
        {"question": "something nobody wrote about", "expected": [{"act": "sample", "section": "1"}], "category": "other"},
    ]
    p = tmp_path / "gold.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


def test_evaluate_reports_all_modes_and_categories(bot, gold_file):
    report = evaluate(bot, load_gold(gold_file), k=3)
    assert set(report) == {"dense", "sparse", "hybrid"}
    hyb = report["hybrid"]
    assert hyb["overall"]["n"] == 3
    assert hyb["overall"]["hit@3"] >= 2 / 3
    assert set(hyb["by_category"]) == {"offence", "other"}
    assert "mrr" in format_report(report, 3)


def test_load_gold_rejects_bad_rows(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"question": "no expected"}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_gold(p)


def test_shipped_gold_set_is_valid_and_references_known_acts():
    rows = load_gold("eval/gold_set.jsonl")
    registry = ActRegistry.load()
    assert len(rows) >= 10
    assert all(e["act"] in registry for r in rows for e in r["expected"])


def test_cli_ingest_dry_run_writes_chunks(tmp_path, capsys):
    out = tmp_path / "bns.jsonl"
    src = "tests/fixtures/sample_act.txt"
    assert main(["ingest", src, "--act", "bns", "--dry-run", "--out", str(out)]) == 0
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 6  # preamble + sections 1, 2, 3, 3A, 4
    assert json.loads(lines[1])["act_id"] == "bns"
    assert "missing_section_numbers" in capsys.readouterr().out
