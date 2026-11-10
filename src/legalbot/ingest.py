"""Read source documents and turn them into chunks."""
from __future__ import annotations

import json
from pathlib import Path

from .chunking import parse_statute
from .registry import ActInfo
from .schema import LegalChunk


def read_document(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    raise ValueError(f"Unsupported file type '{suffix}'. Use .txt, .md or .pdf")


def chunk_statute_file(path: str | Path, act: ActInfo, max_chars: int = 1800) -> list[LegalChunk]:
    text = read_document(path)
    return parse_statute(text, act, source_file=Path(path).name, max_chars=max_chars)


def write_jsonl(chunks: list[LegalChunk], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.payload(), ensure_ascii=False) + "\n")
