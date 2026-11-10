"""Runtime settings, read from environment variables with sane defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value else default


@dataclass(frozen=True)
class Settings:
    collection: str = "legalbot_chunks"

    # Vector store: local on-disk unless QDRANT_URL is set.
    qdrant_path: str = field(default_factory=lambda: _env("LEGALBOT_QDRANT_PATH", ".qdrant") or ".qdrant")
    qdrant_url: str | None = field(default_factory=lambda: _env("QDRANT_URL"))
    qdrant_api_key: str | None = field(default_factory=lambda: _env("QDRANT_API_KEY"))

    # Embeddings and optional reranker.
    embedder: str = field(default_factory=lambda: _env("LEGALBOT_EMBEDDER", "sentence-transformers") or "sentence-transformers")
    embed_model: str = field(default_factory=lambda: _env("LEGALBOT_EMBED_MODEL", "BAAI/bge-small-en-v1.5") or "BAAI/bge-small-en-v1.5")
    reranker_model: str | None = field(default_factory=lambda: _env("LEGALBOT_RERANKER"))

    # Generation.
    groq_model: str = field(default_factory=lambda: _env("LEGALBOT_GROQ_MODEL", "llama-3.3-70b-versatile") or "llama-3.3-70b-versatile")

    # Retrieval / chunking.
    top_k: int = 8
    max_chunk_chars: int = 1800


def get_settings() -> Settings:
    return Settings()
