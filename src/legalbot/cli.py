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


def _cmd_scrape(args: argparse.Namespace) -> int:
    from .scrape import (
        AmbiguousLinks,
        PoliteClient,
        RobotsBlocked,
        Scraper,
        ScrapeError,
        SourceSpec,
        load_manifest,
    )

    registry = ActRegistry.load()
    if args.act not in registry:
        print(f"error: unknown act '{args.act}'. Add it to acts.yaml first.", file=sys.stderr)
        return 2

    if args.url:
        specs = [SourceSpec(url=args.url, kind="page" if args.page else "pdf")]
    else:
        specs = load_manifest(args.manifest).get(args.act, [])
        if not specs:
            print(
                f"error: no source for '{args.act}' in the manifest. Find the official PDF, then run:\n"
                f"  legalbot scrape --act {args.act} --url <pdf-url>",
                file=sys.stderr,
            )
            return 2

    client = PoliteClient(cache_dir=args.cache_dir, min_delay=args.delay)
    scraper = Scraper(client, out_dir=args.out_dir)
    try:
        for spec in specs:
            if args.list:
                for i, link in enumerate(scraper.discover(spec, refresh=args.refresh), 1):
                    print(f"{i}. {link.url}  {link.text}")
                continue
            try:
                saved = scraper.fetch(args.act, spec, pick=args.pick, refresh=args.refresh, write_text=args.text)
            except AmbiguousLinks as exc:
                print(f"{exc}\n", file=sys.stderr)
                for i, link in enumerate(exc.links, 1):
                    print(f"  {i}. {link.url}  {link.text}", file=sys.stderr)
                return 3
            print(f"Saved {saved.path} ({saved.bytes:,} bytes, {saved.pages} pages) from {saved.url}")
            print(f"Provenance: {saved.meta_path}")
            for w in saved.warnings:
                print(f"WARNING: {w}")
            print(f"Next: legalbot ingest {saved.text_path or saved.path} --act {args.act} --dry-run")
            return 0
        return 0
    except RobotsBlocked as exc:
        print(f"Blocked by robots.txt, not fetching: {exc}", file=sys.stderr)
        return 4
    except ScrapeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


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

    sc = sub.add_parser("scrape", help="download an Act's official PDF into data/raw (obeys robots.txt, rate-limited, cached)")
    sc.add_argument("--act", required=True, help="act id from acts.yaml, e.g. bns")
    sc.add_argument("--url", default=None, help="fetch this URL instead of the manifest entry (PDF link by default)")
    sc.add_argument("--page", action="store_true", help="with --url: treat it as a page and look for PDF links on it")
    sc.add_argument("--list", action="store_true", help="only list candidate file links, download nothing")
    sc.add_argument("--pick", type=int, default=None, help="choose the Nth candidate when a page has several")
    sc.add_argument("--refresh", action="store_true", help="ignore the on-disk cache and fetch again")
    sc.add_argument("--text", action="store_true", help="also write extracted text next to the PDF for inspection")
    sc.add_argument("--delay", type=float, default=2.0, help="minimum seconds between requests to one host")
    sc.add_argument("--manifest", default=None, help="sources.yaml path (default: the packaged one)")
    sc.add_argument("--out-dir", default="data/raw")
    sc.add_argument("--cache-dir", default=".cache/http")
    sc.set_defaults(fn=_cmd_scrape)

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
