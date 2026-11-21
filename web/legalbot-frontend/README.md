# JustAi — Legal AI assistant frontend

Next.js 14 (App Router, TypeScript) frontend for the `anshujain1/legalbot` backend.

## Screens

| Route | Screen |
|-------|--------|
| `/` | Landing — hero, "Start Talking!" and "Learn More" |
| `/learn` | Capabilities / Limitations cards |
| `/chat` | Chat — suggestions, history sidebar (menu / chat icon), composer, message actions |

Chat history is kept in `localStorage`.

## Run

```bash
npm install
npm run dev        # http://localhost:3000
```

## Connect to the legalbot backend

Copy `.env.example` to `.env.local` and set:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

The UI then calls `POST {NEXT_PUBLIC_API_URL}/chat` with
`{ "message": string, "history": [{ "role": "user" | "ai", "text": string }] }`
and reads `raw_answer`, `sources[]`, `verified`, `insufficient`, `warnings[]`, `notes[]`
and `disclaimer` (falling back to `reply`). That endpoint ships with the LegalBot backend
(`src/legalbot/api.py`). With the variable unset, a mock reply is shown.

Each answer shows a verification badge, expandable source sections and the disclaimer.
Run the backend with `legalbot serve`; its default CORS settings already allow
`http://localhost:3000`. For a public deployment, don't call the backend straight from the
browser with an API key: proxy it from a server route instead (see the backend's `docs/API.md`).

## Hero image

The landing page uses an SVG placeholder. Put your own photo at `public/hero.jpg`
and it will be shown automatically.
