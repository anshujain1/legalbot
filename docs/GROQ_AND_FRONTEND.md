# Groq key and your frontend

## 1. The Groq key (backend only)

The key is for **Groq** (console.groq.com → API Keys → Create). It lives in the *backend's* `.env`, never in frontend code, never in git, never pasted into a chat.

```
# .env  (next to pyproject.toml; already in .gitignore)
GROQ_API_KEY=gsk_...your key...
```

Check it works:

```
legalbot ask "What is the punishment for theft?"
```

No key set: `/search` still works, `/ask` returns 503. If a key ever leaks (screenshot, chat, commit), delete it in the Groq console and make a new one.

Free-tier limits are per minute and per day. If you see 429 errors: use `legalbot eval-answers --sleep 6`, or lower `max_chars` / `siblings_from_top` in `ExpansionConfig` (`context.py`) to send fewer tokens per question.

## 2. Run the API

```
legalbot serve        # http://127.0.0.1:8000  (docs at /docs)
```

## 3. Connect your frontend

Your frontend never sees the Groq key. It only talks to LegalBot's API.

**Local development (simplest):** call `http://127.0.0.1:8000/ask` straight from the browser. Allow your dev origin in `.env`:

```
LEGALBOT_CORS_ORIGINS=http://localhost:3000
```

```ts
const res = await fetch("http://127.0.0.1:8000/ask", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ question, k: 8 }),
});
const data = await res.json();   // { answer, verified, warnings, notes, sources[], disclaimer, insufficient }
```

**Anything public:** `/ask` spends your Groq quota, so put a key on the API and call it from your server side.

1. `.env` (backend): `LEGALBOT_API_KEY=some-long-random-string`
2. Frontend `.env.local` (server-only, no `NEXT_PUBLIC_` prefix): `LEGALBOT_URL=http://127.0.0.1:8000` and the same `LEGALBOT_API_KEY`.
3. `app/api/ask/route.ts` (Next.js App Router), see `docs/API.md` for the code. The browser then calls your own `/api/ask`.

## 4. What to render

- `answer`, with `[BNS §103]` citations linked to `/sections/bns/103`.
- `warnings` and `verified === false`: show them, don't hide them.
- `sources` grouped by `label`; for `source` of `xref` / `definition` show `via`.
- `notes` (IPC→BNS mappings) as small print, and `disclaimer` on every answer.
- `insufficient === true`: show the answer text as "not covered by the indexed law", not as an error.

Full types are in `docs/API.md`.
