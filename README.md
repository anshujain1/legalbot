# LegalBot

Retrieval-grounded legal assistant over Indian law. Statutes first (BNS / BNSS / BSA, with IPC / CrPC / IEA mapping), case law next. Every answer is generated only from retrieved sections and every citation is verified against what was retrieved.

**Status: Phase 1 (statute RAG).** Drafting and case-law corpus are planned, see [Roadmap](#roadmap).

## What's in Phase 1

| Piece | What it does |
|---|---|
| Structure-aware chunker | One section = one chunk with its Chapter/Section header embedded alongside the text. Long sections split at clause boundaries `(1) (2)...` with the intro repeated in every part. Provisos, explanations and illustrations stay with their section. |
| Metadata schema | act, year, status (in force / repealed), chapter, section, clause range, part index, cross-refs, doc type. All filterable in Qdrant. |
| Hybrid retrieval | Dense + sparse (hashed uni/bigram, IDF in Qdrant) searched under metadata filters, fused with RRF. Optional cross-encoder reranker. |
| Query analysis | Detects acts and section references ("IPC 420", "section 103 of BNS"), pins those sections to the top, maps old-code references to the current code, defaults to in-force provisions. |
| Concordance | IPC to BNS table (starter set, **unverified**, see below). |
| Grounded generation | Groq / Llama 3.3. Model sees only retrieved sections and must cite `[BNS §103]` style labels. |
| Citation verifier | Any cited section not in the retrieved set is flagged; one corrective retry, then the problem is surfaced in `warnings` rather than hidden. |
| Eval harness | Recall@k / MRR, dense vs sparse vs hybrid ablation, per-category breakdown. |
| API + CLI | FastAPI (`/search`, `/ask`, `/sections/{act}/{no}`) and a `legalbot` CLI. |

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ml,llm,dev]"
cp .env.example .env          # add GROQ_API_KEY
pytest                        # offline, no model downloads needed

# get the law text (see "Getting the law text" below), or drop your own files into data/raw/
legalbot scrape --act bns --list

# 1. chunk only, inspect the output and the QA report first
legalbot ingest data/raw/bns.pdf --act bns --dry-run
#    -> data/processed/bns.chunks.jsonl  (open it, spot-check sections)

# 2. index into local Qdrant
legalbot ingest data/raw/bns.pdf --act bns

# 3. use it
legalbot search "punishment for dowry death"
legalbot ask "What is the punishment for cheating?"
legalbot eval -k 8
legalbot serve                # http://127.0.0.1:8000/docs
```

Add new Acts in `src/legalbot/data/acts.yaml` before ingesting them.

## Getting the law text: `legalbot scrape`

```bash
export LEGALBOT_CONTACT="you@example.com"      # goes into the User-Agent so site admins can reach you

legalbot scrape --act bns --list                # preview candidate PDF links, downloads nothing
legalbot scrape --act bns                       # fetch via data/sources.yaml  -> data/raw/bns.pdf
legalbot scrape --act bnss --url https://.../bnss.pdf          # you found the PDF yourself
legalbot scrape --act bnss --url https://.../act-page --page --pick 1   # crawl a page for PDF links
legalbot scrape --act bns --text                # also write extracted text to inspect before ingesting
```

What it does, and will not skip:
- **Obeys robots.txt** on every host and every redirect hop. If robots.txt can't be fetched, the site is treated as off-limits (the error says which case you hit).
- **Rate-limited** to one request per 2 s per host (or the site's `Crawl-delay`), retries with backoff, honours `Retry-After`.
- **Cached** on disk (`.cache/http`), so re-running never re-hits the site; `--refresh` overrides.
- **Validates** that the download is a real PDF (not a login or captcha page) and warns if it looks scanned and needs OCR.
- **Writes provenance** next to the file (`bns.pdf.meta.json`: source URL, time, SHA-256, user agent), so you can cite where every Act came from.

Stick to official sources (India Code, legislative.gov.in, MHA, egazette.gov.in). Read each site's terms before bulk downloading. Court judgments for Phase 3 will need their own adapters (and their own terms checks).

**Not tested against live sites.** The scraper's tests run against mocked HTTP only, and `data/sources.yaml` has one unconfirmed entry (the India Code BNS page: confirmed to be the right Act, but not confirmed to expose a PDF link in plain HTML; India Code builds some pages with JavaScript). If `--list` shows nothing, open the page in your browser, copy the PDF link, and use `--url`.

## Data format the chunker expects

`.txt`, `.md` or text-based `.pdf` (scanned PDFs need OCR first). Sections must look like either:

```
103. Punishment for murder.—(1) Whoever commits murder ...
```
```
103. Punishment for murder.
(1) Whoever commits murder ...
```

with `CHAPTER VI` headings (title on the same or next line). The "Arrangement of Sections" index at the top is handled automatically. Schedules after the last section are dropped in Phase 1.

**Always run `--dry-run` first.** The QA report lists missing section numbers, sections with no chapter and tiny chunks; any of those usually means the parser and your source text disagree. Fix the parser (`chunking/statute.py`) rather than the data.

## Architecture

```
raw .pdf/.txt ──► chunker ──► LegalChunk (+metadata) ──► Qdrant (dense + sparse vectors, payload filters)
                                                              ▲
question ──► QueryAnalyzer ──► filters + pinned sections ─────┤
              (acts, sections, IPC→BNS)                       │
                                       hybrid search (RRF) ◄──┘ ──► [reranker] ──► top-k sections
                                                                                       │
                                               grounded prompt ──► LLM ──► verifier ◄──┘
                                                                              │
                                                       answer + sources + warnings
```

### Source text formats the parser understands

- `103. Punishment for murder.—(1) ...` and `103. Punishment for murder.` + body on the next line.
- **Heading above the number** (gazette / MHA "Sankalan" text): `Punishment for murder.` then `103. (1) ...`.
- Compilations that bundle the *Arrangement of Sections*, an IPC comparison table and the Act: the parser reads the
  expected numbers/titles from the index, then collects them **in order**, so table rows, footnotes and stray
  numbered lines are ignored. `acts.yaml` carries the official section count (`sections:`); `legalbot ingest --dry-run`
  warns on a mismatch, on sections that contain only their title (`stub_sections`) and on headings it could not place.

## Using your own frontend

See [docs/API.md](docs/API.md): CORS setup, optional API key, TypeScript types, and how to render cited answers.

## Known limitations (read before trusting it)

- **The parser is validated on one real compilation (BNS, India Code export):** 358/358 sections, no stubs, no leaked headings. BNSS (531 sections) and BSA (170) have not been run yet; expect small fixes on each new Act. `--dry-run` and the QA report are how you find them.
- **Extraction spacing glitches are repaired conservatively** (`t he` to `the`: 375 repairs on the BNS, none found wrong on review). A few may remain; `--show-repairs` lists every change and `--no-repair` turns it off.
- **The IPC→BNS concordance has 547 rows.** 19 were hand-checked against the India Code "Corresponding Section Table" (`verified=true`); the other 528 were read from that table by `legalbot crosswalk` and are `verified=false` until someone spot-checks them (the `confidence` column marks the ones where the IPC and BNS titles differ). 15 IPC sections the table lists as deleted are in `ipc_deleted.csv`: asking about one says so instead of returning "nothing found".
- **The gold set is 55 questions** (offence / definition / colloquial / old-IPC-reference). Every expected section was checked against the real BNS text. It is a retrieval test, not a legal-correctness test; no retrieval numbers are published here until you have run `legalbot eval` with the real embedding model.
- Sections that were amended or repealed *within* an Act are not tracked yet; status is per-Act.
- Context expansion (`legalbot/context.py`, used by `ask`): the other parts of a split section, sections it cross-references, and the single clause of the definitions section for terms it uses. Limits are in `ExpansionConfig`. It adds prompt tokens: lower `max_chars` / `siblings_from_top` if Groq rate-limits you.
- Not legal advice. Answers always carry a disclaimer.

## Roadmap

1. **Phase 1 (this repo):** BNS / BNSS / BSA statute RAG, hybrid retrieval, verified citations, eval.
2. **Phase 2:** drafting. Template-driven (legal notice, bail application, RTI, complaint), asks for missing facts, pulls sections from the retriever, cites them in the draft.
3. **Phase 3:** case-law corpus with rhetorical-role chunking (facts / issues / arguments / reasoning / order), then a citation graph in Neo4j ("follows / distinguishes / overrules") for "is this still good law?".

## Layout

```
src/legalbot/
  chunking/statute.py   section/chapter parser, clause splitting, QA report
  schema.py             LegalChunk, SearchFilters, enums
  registry.py + data/   acts.yaml, act alias matching
  store.py              Qdrant collection, upsert, filtered search, exact lookup
  retrieval.py          hybrid search + RRF + pinned sections
  query.py              query analysis and planning
  concordance.py        IPC↔BNS mapping
  generate.py           prompt + Groq client
  verify.py             citation verification
  pipeline.py           LegalBot: search / ask
  api.py  cli.py        FastAPI app, command line
  evaluate.py           retrieval metrics
tests/                  59 tests, run offline (hash embedder, in-memory Qdrant)
eval/gold_set.jsonl     seed evaluation questions
```
