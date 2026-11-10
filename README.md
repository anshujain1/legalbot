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
pytest                        # 59 tests, no model downloads needed

mkdir -p data/raw             # your law data goes here (gitignored)

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

## Known limitations (read before trusting it)

- **The parser is validated on a synthetic fixture only.** Real India Code PDFs will surface edge cases; expect a round of fixes after your first real ingest. That is what `--dry-run` and the QA report are for.
- **The IPC→BNS concordance is starter data, every row `verified=false`.** Check each row against the government's official comparison tables, then flip the flag. Answers that use an unverified mapping carry a warning.
- **The gold set is 12 seed questions.** Verify the expected sections against your corpus and grow it to 50 to 100 before quoting any metric.
- Sections that were amended or repealed *within* an Act are not tracked yet; status is per-Act.
- No parent expansion yet: if only one part of a long section matches, only that part is returned.
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
