"""Dense embedders. The sentence-transformers import is lazy so tests run without it."""
from __future__ import annotations

import math
import re
import zlib
from typing import Protocol

from .config import Settings

_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashEmbedder:
    """Deterministic hashed bag-of-words vectors. For tests and offline smoke runs only."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in _TOKEN.findall(text.lower()):
            v[zlib.crc32(tok.encode()) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, query_prefix: str | None = None):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("sentence-transformers is not installed. Run: pip install -e '.[ml]'") from exc
        self.model = SentenceTransformer(model_name)
        self.dim = int(self.model.get_sentence_embedding_dimension())
        name = model_name.lower()
        if query_prefix is None and "bge" in name and name.rstrip("-v1.5").endswith("-en"):
            query_prefix = "Represent this sentence for searching relevant passages: "
        self.query_prefix = query_prefix or ""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed([self.query_prefix + text])[0]


def get_embedder(settings: Settings) -> Embedder:
    if settings.embedder == "hash":
        return HashEmbedder()
    return SentenceTransformerEmbedder(settings.embed_model)
