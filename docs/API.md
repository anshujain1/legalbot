# LegalBot HTTP API (for your frontend)

Run it: `legalbot serve` (default http://127.0.0.1:8000). Interactive docs at `/docs`, machine-readable schema at `/openapi.json`.

## Connecting a browser frontend

1. Put your frontend's origin(s) in `.env` (exact origin, no trailing slash, comma separated):
   ```
   LEGALBOT_CORS_ORIGINS=http://localhost:3000,https://your-site.example
   ```
   Defaults already cover `localhost:3000` and `localhost:5173`. Use `*` only for throwaway demos.
2. **Do not ship an API key in browser code.** Anything in client-side JavaScript is visible to every visitor.
   If you deploy this publicly (the `/ask` route spends your Groq quota), set `LEGALBOT_API_KEY` and call LegalBot
   from your frontend's *server side* (a Next.js route handler / API route), which adds the `X-API-Key` header.
   Example (Next.js App Router, `app/api/ask/route.ts`):
   ```ts
   export async function POST(req: Request) {
     const body = await req.json();
     const r = await fetch(`${process.env.LEGALBOT_URL}/ask`, {
       method: "POST",
       headers: { "Content-Type": "application/json", "X-API-Key": process.env.LEGALBOT_API_KEY! },
       body: JSON.stringify({ question: body.question, k: 8 }),
     });
     return new Response(await r.text(), { status: r.status, headers: { "Content-Type": "application/json" } });
   }
   ```
   Your browser then calls your own `/api/ask`, and CORS and the key stop being a concern.
3. Generate types straight from the schema instead of hand-writing them:
   `npx openapi-typescript http://127.0.0.1:8000/openapi.json -o src/legalbot.d.ts`

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness + number of indexed chunks (never needs a key) |
| GET | `/acts` | acts the bot knows: `{act_id, name, short, year, status}[]` |
| POST | `/search` | retrieval only, no LLM. Fast and free; good for a search box |
| POST | `/ask` | grounded answer with verified citations (needs `GROQ_API_KEY`; 503 otherwise) |
| GET | `/sections/{act_id}/{section_no}` | exact section text (all parts), e.g. `/sections/bns/103` |

Errors are `{ "detail": string }` with status 401 (bad key), 404 (unknown act/section), 422 (bad request body), 503 (no LLM configured).

## Types

```ts
type Filters = {
  act_ids?: string[];            // ["bns"]
  statuses?: ("in_force" | "repealed" | "amended" | "not_yet_in_force")[];
  doc_types?: ("statute" | "judgment" | "notification" | "rule")[];
  section_nos?: string[];        // ["103", "304B"]
  chapter_nos?: string[];        // ["VI"]
  year_min?: number; year_max?: number;
};

type SearchRequest = { query: string; k?: number /*1-30, default 8*/; mode?: "hybrid" | "dense" | "sparse"; filters?: Filters };
type AskRequest    = { question: string; k?: number; filters?: Filters };

type Source = {
  chunk_id: string;              // stable; use as React key
  label: string;                 // citation label, "BNS §103"
  act_id: string;                // "bns"
  act: string;                   // "Bharatiya Nyaya Sanhita, 2023"
  status: string;                // "in_force" ...
  year: number | null;
  section_no: string | null;
  section_title: string | null;
  chapter: string | null;        // "Chapter VI: Of Offences Affecting The Human Body"
  clause_range: string | null;   // "(1)–(3)" when a long section was split
  part: string;                  // "2/3"
  text: string;
  source: "dense" | "sparse" | "hybrid" | "lookup" | "sibling" | "xref" | "definition";
                                 // "lookup" = pinned because the user named the section;
                                 // sibling/xref/definition = extra context added after ranking (/ask only)
  via: string | null;            // for those extras: why they are here, e.g. "BNS §103"
  score: number;
};

type QueryPlan = {
  original: string; search_query: string; filters: Filters;
  mentioned_acts: string[]; explicit_sections: [string, string][];
  mapped_refs: [string, string][];
  removed_refs: [string, string][];   // old sections deleted with no successor, e.g. ["ipc","124A"]
  notes: string[];               // e.g. "IPC §420 corresponds to BNS §318(4) ... (unverified mapping)"
};

type SearchResponse = { plan: QueryPlan; results: Source[] };

type Answer = {
  question: string;
  answer: string;
  insufficient: boolean;         // true: the sources did not cover the question; show `answer` as an explanation, not a ruling
  verified: boolean;             // false: a citation could not be checked against the sources; show a warning
  warnings: string[];
  notes: string[];
  sources: Source[];
  disclaimer: string;            // always show it
};
```

## Rendering `/ask`

- The answer text contains citations like `[BNS §103]`. Match them to `sources[].label` and link each to
  `/sections/{act_id}/{section_no}` (or open the source's `text` in a side panel).
- Group `sources` by `label`: a long section can appear as several parts. Sources with `source` of `xref` or `definition` were added as context; show `via` ("referred to by BNS §103").
- If `verified` is false or `warnings` is non-empty, show the warning next to the answer; do not hide it.
- Show `disclaimer` on every answer.
- `notes` explain IPC to BNS mappings; show them as small print under the answer.

## Not built yet

Streaming (`/ask` returns one JSON response; answers take a couple of seconds), rate limiting, and conversation memory
(each request is independent, so send the full question each time).
