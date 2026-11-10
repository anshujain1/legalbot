"""Grounded answer generation: the model sees only retrieved sections and must cite them."""
from __future__ import annotations

import os
from typing import Protocol

from .config import Settings
from .schema import Hit

INSUFFICIENT = "INSUFFICIENT_CONTEXT:"

SYSTEM_PROMPT = f"""You are LegalBot, a research assistant for Indian law. Answer ONLY from the numbered sources provided.

Rules:
1. Cite every legal statement with the exact label of its source in square brackets, e.g. [BNS §103].
2. Never cite or mention a section that does not appear in the sources.
3. If the sources do not contain enough to answer, reply with exactly "{INSUFFICIENT}" followed by one sentence saying what is missing.
4. If the Notes say an older code's section corresponds to a current one, state that clearly.
5. Be concise and use plain language. Do not give personalised legal advice."""


class LLM(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class GroqLLM:
    def __init__(self, model: str, api_key: str | None = None):
        try:
            from groq import Groq
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("groq is not installed. Run: pip install -e '.[llm]'") from exc
        self.model = model
        self.client = Groq(api_key=api_key or os.environ["GROQ_API_KEY"])

    def complete(self, system: str, user: str) -> str:
        res = self.client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return (res.choices[0].message.content or "").strip()


def get_llm(settings: Settings) -> LLM | None:
    """Groq client if a key is configured, else None (search still works, /ask returns 503)."""
    if not os.getenv("GROQ_API_KEY"):
        return None
    try:
        return GroqLLM(settings.groq_model)
    except RuntimeError:
        return None


def build_prompt(question: str, hits: list[Hit], notes: list[str]) -> str:
    blocks = []
    for h in hits:
        c = h.chunk
        where = f" ({c.chapter_title})" if c.chapter_title else ""
        title = f" {c.section_title}" if c.section_title else ""
        blocks.append(f"[{c.label}]{title}{where}\n{c.text}")
    note_block = "\n".join(f"- {n}" for n in notes) if notes else "- none"
    return f"Question: {question}\n\nNotes:\n{note_block}\n\nSources:\n\n" + "\n\n".join(blocks)
