# Running on Windows

PowerShell, from the repo folder:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -e ".[ml,llm,dev]"
copy .env.example .env              # then open .env and set GROQ_API_KEY
pytest
```

Everything else in the README works as written; only paths differ (`data\raw\bns.txt`). Environment variables for one session: `$env:LEGALBOT_CONTACT = "you@example.com"`.

Quality checks:

```powershell
legalbot eval -k 8                                  # retrieval, no key needed
legalbot eval-answers --sleep 3 --md answer_review.md   # answers + refusals, needs GROQ_API_KEY
```

`eval-answers` writes `answer_review.md`: read the answers against their cited sections and grade them. The machine numbers only say whether answers were cited, verified and refused when they should be; they cannot say the law was explained correctly.
