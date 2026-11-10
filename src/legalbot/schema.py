"""Metadata schema shared by chunking, indexing, retrieval and evaluation.

Every filterable field here is also a Qdrant payload field, so adding a field
means: add it here, populate it in the chunker, and (if filterable) register a
payload index in store.py.
"""
from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field

_POINT_NS = uuid.UUID("6f1c1f0e-3b7a-4c55-9a43-0d6c5f3f6a10")


class DocType(str, Enum):
    STATUTE = "statute"
    JUDGMENT = "judgment"
    NOTIFICATION = "notification"
    RULE = "rule"


class Status(str, Enum):
    IN_FORCE = "in_force"
    REPEALED = "repealed"
    AMENDED = "amended"
    NOT_YET_IN_FORCE = "not_yet_in_force"


class ChunkRole(str, Enum):
    # statutes
    SECTION = "section"
    PREAMBLE = "preamble"
    # judgments (phase 3: rhetorical-role chunking)
    FACTS = "facts"
    ISSUES = "issues"
    ARGUMENTS = "arguments"
    REASONING = "reasoning"
    ORDER = "order"


class LegalChunk(BaseModel):
    chunk_id: str
    doc_type: DocType = DocType.STATUTE
    act_id: str
    act_name: str
    act_short: str
    year: int | None = None
    status: Status = Status.IN_FORCE
    jurisdiction: str = "IN"

    chapter_no: str | None = None
    chapter_title: str | None = None
    section_no: str | None = None
    section_title: str | None = None
    clause_range: str | None = None  # e.g. "(7)–(9)" for split definition sections
    part_index: int = 0
    part_count: int = 1
    role: ChunkRole = ChunkRole.SECTION

    header: str  # context line prepended to the text before embedding
    text: str
    cross_refs: list[str] = Field(default_factory=list)  # section numbers mentioned; act not resolved
    source_file: str | None = None

    @property
    def embed_text(self) -> str:
        return f"{self.header}\n{self.text}"

    @property
    def point_id(self) -> str:
        return str(uuid.uuid5(_POINT_NS, self.chunk_id))

    @property
    def label(self) -> str:
        """Citation label, e.g. 'BNS §103'."""
        return f"{self.act_short} §{self.section_no}" if self.section_no else self.act_short

    def payload(self) -> dict:
        return self.model_dump(mode="json")


class SearchFilters(BaseModel):
    act_ids: list[str] | None = None
    statuses: list[Status] | None = None
    doc_types: list[DocType] | None = None
    section_nos: list[str] | None = None
    chapter_nos: list[str] | None = None
    year_min: int | None = None
    year_max: int | None = None

    def is_empty(self) -> bool:
        return not any(v is not None for v in self.model_dump().values())


class Hit(BaseModel):
    chunk: LegalChunk
    score: float = 0.0
    source: str = "hybrid"  # dense | sparse | hybrid | lookup
