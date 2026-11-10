"""Qdrant-backed chunk store: dense + sparse vectors and payload filters in one collection."""
from __future__ import annotations

from qdrant_client import QdrantClient, models

from .config import Settings
from .embeddings import Embedder
from .schema import Hit, LegalChunk, SearchFilters
from .sparse import sparse_vector

DENSE = "dense"
SPARSE = "sparse"

_KEYWORD_INDEXES = ["act_id", "status", "doc_type", "section_no", "chapter_no", "role"]


class QdrantStore:
    def __init__(
        self,
        settings: Settings,
        embedder: Embedder,
        client: QdrantClient | None = None,
        local: bool | None = None,
    ):
        self.settings = settings
        self.embedder = embedder
        self.collection = settings.collection
        if client is not None:
            self.client = client
            self._local = True if local is None else local
        elif settings.qdrant_url:
            self.client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
            self._local = False
        else:
            self.client = QdrantClient(path=settings.qdrant_path)
            self._local = True

    # ------------------------------------------------------------ collection

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection):
            self._check_dim()
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                DENSE: models.VectorParams(size=self.embedder.dim, distance=models.Distance.COSINE),
            },
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        if not self._local:
            for name in _KEYWORD_INDEXES:
                self.client.create_payload_index(self.collection, name, models.PayloadSchemaType.KEYWORD)
            self.client.create_payload_index(self.collection, "year", models.PayloadSchemaType.INTEGER)

    def _check_dim(self) -> None:
        try:
            vectors = self.client.get_collection(self.collection).config.params.vectors
            size = vectors[DENSE].size  # type: ignore[index]
        except Exception:  # pragma: no cover - best-effort guard
            return
        if size != self.embedder.dim:
            raise ValueError(
                f"Collection '{self.collection}' has {size}-dim vectors but the embedder produces "
                f"{self.embedder.dim}. Use the same embedder you ingested with, or delete the index and re-ingest."
            )

    def count(self) -> int:
        if not self.client.collection_exists(self.collection):
            return 0
        return self.client.count(self.collection, exact=True).count

    # ------------------------------------------------------------ writes

    def upsert(self, chunks: list[LegalChunk], batch_size: int = 64) -> int:
        self.ensure_collection()
        total = 0
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            dense = self.embedder.embed([c.embed_text for c in batch])
            points = []
            for chunk, vec in zip(batch, dense):
                idx, val = sparse_vector(chunk.embed_text)
                points.append(
                    models.PointStruct(
                        id=chunk.point_id,
                        vector={DENSE: vec, SPARSE: models.SparseVector(indices=idx, values=val)},
                        payload=chunk.payload(),
                    )
                )
            self.client.upsert(self.collection, points=points)
            total += len(points)
        return total

    def delete_act(self, act_id: str) -> None:
        if not self.client.collection_exists(self.collection):
            return
        self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(filter=self._filter(SearchFilters(act_ids=[act_id]))),
        )

    # ------------------------------------------------------------ reads

    def search_dense(self, query: str, filters: SearchFilters | None, limit: int) -> list[Hit]:
        res = self.client.query_points(
            self.collection,
            query=self.embedder.embed_query(query),
            using=DENSE,
            query_filter=self._filter(filters),
            limit=limit,
            with_payload=True,
        )
        return self._hits(res.points, "dense")

    def search_sparse(self, query: str, filters: SearchFilters | None, limit: int) -> list[Hit]:
        idx, val = sparse_vector(query)
        if not idx:
            return []
        res = self.client.query_points(
            self.collection,
            query=models.SparseVector(indices=idx, values=val),
            using=SPARSE,
            query_filter=self._filter(filters),
            limit=limit,
            with_payload=True,
        )
        return self._hits(res.points, "sparse")

    def lookup(self, act_id: str, section_no: str, limit: int = 8) -> list[Hit]:
        """Exact fetch of one section (all its parts), in order."""
        flt = self._filter(SearchFilters(act_ids=[act_id], section_nos=[section_no.upper()]))
        points, _ = self.client.scroll(self.collection, scroll_filter=flt, limit=limit, with_payload=True)
        hits = self._hits(points, "lookup")
        return sorted(hits, key=lambda h: h.chunk.part_index)

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _hits(points, source: str) -> list[Hit]:
        return [
            Hit(chunk=LegalChunk.model_validate(p.payload), score=float(getattr(p, "score", 0.0) or 0.0), source=source)
            for p in points
        ]

    @staticmethod
    def _filter(f: SearchFilters | None) -> models.Filter | None:
        if f is None or f.is_empty():
            return None
        must: list[models.Condition] = []

        def match_any(key: str, values) -> None:
            vals = [v.value if hasattr(v, "value") else v for v in values]
            must.append(models.FieldCondition(key=key, match=models.MatchAny(any=vals)))

        if f.act_ids:
            match_any("act_id", f.act_ids)
        if f.statuses:
            match_any("status", f.statuses)
        if f.doc_types:
            match_any("doc_type", f.doc_types)
        if f.section_nos:
            match_any("section_no", [s.upper() for s in f.section_nos])
        if f.chapter_nos:
            match_any("chapter_no", f.chapter_nos)
        if f.year_min is not None or f.year_max is not None:
            must.append(models.FieldCondition(key="year", range=models.Range(gte=f.year_min, lte=f.year_max)))
        return models.Filter(must=must) if must else None
