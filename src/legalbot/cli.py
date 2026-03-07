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


def _cmd_crosswalk(args: argparse.Namespace) -> int:
    import csv

    from .config import DATA_DIR
    from .crosswalk import extract_crosswalk, write_csv, write_deleted_csv
    from .ingest import read_document

    out = Path(args.out) if args.out else DATA_DIR / "ipc_to_bns.csv"
    cw = extract_crosswalk(read_document(args.file))
    keep: list[dict] = []
    if out.exists():  # hand-checked rows survive a re-run; machine-read rows are regenerated
        with out.open(encoding="utf-8", newline="") as f:
            keep = [r for r in csv.DictReader(f) if (r.get("source") or "curated") != "auto"]
    n = write_csv(cw, out, keep=keep)
    del_out = out.with_name("ipc_deleted.csv")
    keep_del: list[dict] = []
    if del_out.exists():
        with del_out.open(encoding="utf-8", newline="") as f:
            keep_del = [r for r in csv.DictReader(f) if (r.get("source") or "curated") != "auto"]
    n_del = write_deleted_csv(cw, del_out, keep=keep_del)
    weak = sum(1 for r in cw.rows if r.similarity < 0.75)
    print(json.dumps({
        "bns_sections_seen": cw.bns_found,
        "bns_sections_without_ipc_row": cw.bns_without_row,
        "rows_extracted": len(cw.rows),
        "rows_to_spot_check (IPC/BNS titles differ)": weak,
        "bns_provisions_new_in_2023": cw.new_provisions,
        "ipc_sections_deleted_no_successor": cw.deleted_ipc,
        "rows_written": n,
        "deleted_rows_written": n_del,
    }, indent=2))
    print(f"\nWrote {n} rows to {out}. Rows with source=auto are machine-read and verified=false: spot-check them.")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    settings = get_settings()
    registry = ActRegistry.load()
    act = registry.get(args.act)
    diag: dict = {}
    chunks = chunk_statute_file(
        args.file,
        act,
        max_chars=args.max_chars or settings.max_chunk_chars,
        diagnostics=diag,
        repair=not args.no_repair,
    )
    report = qa_report(chunks, expected_sections=act.expected_sections, diagnostics=diag)

    out = Path(args.out) if args.out else Path("data/processed") / f"{act.act_id}.chunks.jsonl"
    write_jsonl(chunks, out)
    print(json.dumps(report, indent=2))
    print(f"\nWrote {len(chunks)} chunks to {out} (open it and spot-check before indexing).")

    if report["missing_section_numbers"]:
        print(f"WARNING: {len(report['missing_section_numbers'])} section numbers missing, e.g. "
              f"{report['missing_section_numbers'][:10]}. Check the source text or the parser.")
    if report.get("stub_sections"):
        print(f"WARNING: {len(report['stub_sections'])}+ sections contain only their title (body not captured), e.g. "
              f"{report['stub_sections'][:10]}. Do not index this parse.")
    if report.get("sections_match_expected") is False:
        print(f"WARNING: parsed {report['sections']} sections but {act.short} has {report['expected_sections']}.")
    if report.get("spacing_repairs"):
        print(f"NOTE: repaired {report['spacing_repairs']} words split by extraction spacing (e.g. "
              f"{', '.join(report['spacing_examples'][:5])}). Skim the full list with --show-repairs; "
              f"turn it off with --no-repair.")
        if args.show_repairs:
            print("\n".join(f"  {line}" for line in report["spacing_examples"]))
    if report.get("heading_unmatched"):
        print(f"NOTE: heading not found above sections {report['heading_unmatched'][:10]}; "
              f"their neighbours may carry a stray heading line.")
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


def _cmd_eval_answers(args: argparse.Namespace) -> int:
    from .evaluate_answers import format_markdown, format_summary, load_answer_set, run
    from .pipeline import build_bot

    bot = build_bot()
    if bot.llm is None:
        print("No LLM configured: set GROQ_API_KEY in .env (and pip install -e '.[llm]').")
        return 2
    rows = load_answer_set(args.set)
    if args.limit:
        rows = rows[: args.limit]
    report = run(bot, rows, k=args.k, sleep=args.sleep, progress=lambda i, n, q: print(f"[{i}/{n}] {q[:70]}", flush=True))
    print("\n" + format_summary(report))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.md:
        Path(args.md).write_text(format_markdown(report), encoding="utf-8")
        print(f"\nWrote {args.md}: read it and grade the answers yourself (or ask a lawyer to).")
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
    ing.add_argument("--no-repair", action="store_true", help="do not repair words split by extraction spaces")
    ing.add_argument("--show-repairs", action="store_true", help="print the repairs made (to check for false joins)")
    ing.set_defaults(fn=_cmd_ingest)

    cx = sub.add_parser("crosswalk", help="extract the IPC->BNS comparison table from a Sankalan-style BNS text into ipc_to_bns.csv")
    cx.add_argument("file")
    cx.add_argument("--out", default=None, help="CSV path (default: the packaged src/legalbot/data/ipc_to_bns.csv)")
    cx.set_defaults(fn=_cmd_crosswalk)

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

    ea = sub.add_parser("eval-answers", help="answer quality + refusal test (needs GROQ_API_KEY); writes a markdown review file")
    ea.add_argument("--set", default="eval/answer_set.jsonl")
    ea.add_argument("-k", type=int, default=8)
    ea.add_argument("--sleep", type=float, default=2.0, help="seconds between questions (Groq free tier rate limits)")
    ea.add_argument("--limit", type=int, default=0, help="only the first N questions (quick trial)")
    ea.add_argument("--json", default=None)
    ea.add_argument("--md", default="answer_review.md")
    ea.set_defaults(fn=_cmd_eval_answers)

    sv = sub.add_parser("serve", help="run the FastAPI server")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    sv.set_defaults(fn=_cmd_serve)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
