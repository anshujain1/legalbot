"""Retrieval evaluation against a gold set, with a dense / sparse / hybrid / pipeline ablation.

Gold file: JSONL, one object per line:
  {"question": "...", "expected": [{"act": "bns", "section": "103"}], "category": "offence"}

A question counts as a hit if ANY expected section appears in the top-k. For dense / sparse / hybrid,
explicit section lookup (and the IPC->BNS pinning) is switched off so the numbers reflect search quality,
not regex matching. The extra "pipeline" row is hybrid WITH lookup, i.e. what a user actually gets:
"IPC 302" is pinned to BNS 103 before ranking. Read it as a test of the concordance, not of the embeddings.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .pipeline import LegalBot

MODES = ("dense", "sparse", "hybrid", "pipeline")


def load_gold(path: str | Path) -> list[dict]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    for r in rows:
        if "question" not in r or not r.get("expected"):
            raise ValueError(f"Bad gold row (needs 'question' and 'expected'): {r}")
    return rows


def _rank_of_first_expected(hits, expected: set[tuple[str, str]]) -> int | None:
    for rank, h in enumerate(hits, start=1):
        if (h.chunk.act_id, (h.chunk.section_no or "").upper()) in expected:
            return rank
    return None


def _summarise(ranks: list[int | None], k: int) -> dict:
    n = len(ranks) or 1
    return {
        "n": len(ranks),
        "hit@1": sum(1 for r in ranks if r == 1) / n,
        f"hit@{k}": sum(1 for r in ranks if r is not None) / n,
        "mrr": sum(1 / r for r in ranks if r) / n,
    }


def evaluate(bot: LegalBot, gold: list[dict], k: int = 8, modes=MODES) -> dict:
    report: dict = {}
    for mode in modes:
        overall: list[int | None] = []
        by_cat: dict[str, list[int | None]] = defaultdict(list)
        misses: list[dict] = []
        for row in gold:
            expected = {(e["act"], str(e["section"]).upper()) for e in row["expected"]}
            real_mode, lookup = ("hybrid", True) if mode == "pipeline" else (mode, False)
            _, hits = bot.search(row["question"], k=k, mode=real_mode, use_lookup=lookup)
            rank = _rank_of_first_expected(hits, expected)
            overall.append(rank)
            by_cat[row.get("category", "uncategorised")].append(rank)
            if rank is None:
                misses.append({"question": row["question"], "expected": sorted(expected)})
        report[mode] = {
            "overall": _summarise(overall, k),
            "by_category": {c: _summarise(r, k) for c, r in sorted(by_cat.items())},
            "misses": misses,
        }
    return report


def format_report(report: dict, k: int) -> str:
    lines = [f"{'mode':<8} {'n':>4} {'hit@1':>7} {f'hit@{k}':>7} {'mrr':>7}"]
    for mode, data in report.items():
        o = data["overall"]
        lines.append(f"{mode:<8} {o['n']:>4} {o['hit@1']:>7.2f} {o[f'hit@{k}']:>7.2f} {o['mrr']:>7.2f}")
    best = "hybrid" if "hybrid" in report else next(iter(report))
    cats = report[best]["by_category"]
    if len(cats) > 1:
        lines.append(f"\nby category ({best}):")
        for c, m in cats.items():
            lines.append(f"  {c:<14} n={m['n']:<3} hit@1={m['hit@1']:.2f} hit@{k}={m[f'hit@{k}']:.2f} mrr={m['mrr']:.2f}")
    for name in (best, "pipeline"):
        misses = report.get(name, {}).get("misses", [])
        if misses:
            lines.append(f"\nmisses ({name}):")
            for m in misses:
                lines.append(f"  - {m['question']}  (expected {m['expected']})")
    return "\n".join(lines)
