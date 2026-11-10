"""Hybrid retrieval: dense + sparse search under metadata filters, fused with RRF."""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Literal

from .rerank import Reranker
from .schema import Hit, SearchFilters
from .store import QdrantStore

Mode = Literal["hybrid", "dense", "sparse"]

MAX_PARTS_PER_LOOKUP = 4


def rrf_fuse(rankings: dict[str, list[Hit]], k: int = 60) -> list[Hit]:
    """Reciprocal Rank Fusion over named ranked lists."""
    scores: dict[str, float] = defaultdict(float)
    first: dict[str, Hit] = {}
    for hits in rankings.values():
        for rank, hit in enumerate(hits, start=1):
            cid = hit.chunk.chunk_id
            scores[cid] += 1.0 / (k + rank)
            first.setdefault(cid, hit)
    ordered = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    return [Hit(chunk=first[cid].chunk, score=scores[cid], source="hybrid") for cid in ordered]


class Retriever:
    def __init__(self, store: QdrantStore, reranker: Reranker | None = None):
        self.store = store
        self.reranker = reranker

    def search(
        self,
        query: str,
        filters: SearchFilters | None = None,
        k: int = 8,
        mode: Mode = "hybrid",
        explicit_sections: Iterable[tuple[str, str]] | None = None,
    ) -> list[Hit]:
        pool = max(20, k * 4)

        if mode == "dense":
            ranked = self.store.search_dense(query, filters, pool)
        elif mode == "sparse":
            ranked = self.store.search_sparse(query, filters, pool)
        else:
            ranked = rrf_fuse(
                {
                    "dense": self.store.search_dense(query, filters, pool),
                    "sparse": self.store.search_sparse(query, filters, pool),
                }
            )

        if self.reranker is not None:
            ranked = self.reranker.rerank(query, ranked[:pool])

        # Sections the user named explicitly (or that the concordance maps to) always come first.
        pinned: list[Hit] = []
        for act_id, section_no in explicit_sections or []:
            pinned.extend(self.store.lookup(act_id, section_no)[:MAX_PARTS_PER_LOOKUP])

        out: list[Hit] = []
        seen: set[str] = set()
        for hit in [*pinned, *ranked]:
            if hit.chunk.chunk_id in seen:
                continue
            seen.add(hit.chunk.chunk_id)
            out.append(hit)
            if len(out) >= max(k, len(pinned)):
                break
        return out[: max(k, len(pinned))]
