"""Command line: ingest a statute, search, ask, evaluate, serve."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .chunking import qa_report
from .config import get_settings
from .evaluate import evaluate, format_report, load_gold
from .ingest import chunk_statute_file, write_jsonl
from .registry import ActRegistry


def _cmd_ingest(args: argparse.Namespace) -> int:
    settings = get_settings()
    registry = ActRegistry.load()
    act = registry.get(args.act)
    chunks = chunk_statute_file(args.file, act, max_chars=args.max_chars or settings.max_chunk_chars)
    report = qa_report(chunks)

    out = Path(args.out) if args.out else Path("data/processed") / f"{act.act_id}.chunks.jsonl"
    write_jsonl(chunks, out)
    print(json.dumps(report, indent=2))
    print(f"\nWrote {len(chunks)} chunks to {out} (open it and spot-check before indexing).")

    if report["missing_section_numbers"]:
        print(f"WARNING: {len(report['missing_section_numbers'])} section numbers missing, e.g. "
              f"{report['missing_section_numbers'][:10]}. Check the source text or the parser.")
    if args.dry_run:
        return 0

    from .pipeline import build_bot

    bot = build_bot(settings)
    bot.store.ensure_collection()
    bot.store.delete_act(act.act_id)  # re-ingest replaces the act cleanly
    n = bot.store.upsert(chunks)
    print(f"Indexed {n} chunks for {act.short}. Collection now holds {bot.store.count()} chunks.")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    from .pipeline import build_bot

    plan, hits = build_bot().search(args.query, k=args.k, mode=args.mode)
    for note in plan.notes:
        print(f"note: {note}")
    for i, h in enumerate(hits, 1):
        c = h.chunk
        print(f"{i}. [{c.label}] {c.section_title or ''}  ({h.source}, {h.score:.4f})")
        print(f"   {c.text[:160].replace(chr(10), ' ')}...")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    from .pipeline import LLMNotConfigured, build_bot

    try:
        ans = build_bot().ask(args.question, k=args.k)
    except LLMNotConfigured as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(ans.answer)
    for w in ans.warnings:
        print(f"\nWARNING: {w}")
    print("\nSources: " + ", ".join(dict.fromkeys(s.label for s in ans.sources)))
    print(f"\n{ans.disclaimer}")
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    from .pipeline import build_bot

    report = evaluate(build_bot(), load_gold(args.gold), k=args.k)
    print(format_report(report, args.k))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("legalbot.api:create_app", factory=True, host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="legalbot", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    ing = sub.add_parser("ingest", help="parse a statute file (.txt/.pdf), write chunks.jsonl, index into Qdrant")
    ing.add_argument("file")
    ing.add_argument("--act", required=True, help="act id from src/legalbot/data/acts.yaml, e.g. bns")
    ing.add_argument("--max-chars", type=int, default=None)
    ing.add_argument("--out", default=None, help="chunks.jsonl path (default data/processed/<act>.chunks.jsonl)")
    ing.add_argument("--dry-run", action="store_true", help="chunk and report only; do not embed or index")
    ing.set_defaults(fn=_cmd_ingest)

    se = sub.add_parser("search", help="retrieve sections for a query")
    se.add_argument("query")
    se.add_argument("-k", type=int, default=8)
    se.add_argument("--mode", choices=["hybrid", "dense", "sparse"], default="hybrid")
    se.set_defaults(fn=_cmd_search)

    ask = sub.add_parser("ask", help="answer a question with verified citations (needs GROQ_API_KEY)")
    ask.add_argument("question")
    ask.add_argument("-k", type=int, default=8)
    ask.set_defaults(fn=_cmd_ask)

    ev = sub.add_parser("eval", help="retrieval metrics on a gold set, dense vs sparse vs hybrid")
    ev.add_argument("--gold", default="eval/gold_set.jsonl")
    ev.add_argument("-k", type=int, default=8)
    ev.add_argument("--json", default=None, help="also write the full report as JSON")
    ev.set_defaults(fn=_cmd_eval)

    sv = sub.add_parser("serve", help="run the FastAPI server")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    sv.set_defaults(fn=_cmd_serve)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
