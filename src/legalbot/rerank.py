"""Optional cross-encoder reranking of the fused candidate list."""
from __future__ import annotations

from typing import Protocol

from .schema import Hit


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]: ...


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("sentence-transformers is not installed. Run: pip install -e '.[ml]'") from exc
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        if not hits:
            return hits
        scores = self.model.predict([(query, h.chunk.embed_text) for h in hits])
        ranked = sorted(zip(hits, scores), key=lambda pair: float(pair[1]), reverse=True)
        return [Hit(chunk=h.chunk, score=float(s), source=h.source) for h, s in ranked]
