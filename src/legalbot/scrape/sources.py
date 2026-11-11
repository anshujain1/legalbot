"""Source adapters: find the file for an Act, download it, validate it, record where it came from."""
from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin

import yaml

from .. import __version__
from ..config import DATA_DIR
from .http import PoliteClient, ScrapeError

# Matches ".pdf" links and DSpace-style "/bitstream/" download links (India Code is DSpace based).
DEFAULT_LINK_PATTERN = r"\.pdf(?:$|[?#])|/bitstream/"
MIN_TEXT_CHARS = 200  # fewer extractable characters in the sample pages => probably a scan


class AmbiguousLinks(ScrapeError):
    def __init__(self, links: list["Link"]):
        super().__init__(f"{len(links)} candidate files found; choose one with --pick N")
        self.links = links


class NoLinksFound(ScrapeError):
    pass


@dataclass(frozen=True)
class Link:
    url: str
    text: str


@dataclass
class SourceSpec:
    url: str
    kind: str = "pdf"  # "pdf": fetch directly | "page": crawl the page for file links
    link_pattern: str | None = None
    include: str | None = None
    exclude: str | None = None
    pick: int | None = None
    note: str = ""


@dataclass
class PdfCheck:
    ok: bool
    pages: int = 0
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class Saved:
    path: Path
    meta_path: Path
    url: str
    sha256: str
    bytes: int
    pages: int
    warnings: list[str]
    text_path: Path | None = None


# ---------------------------------------------------------------- link discovery


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.anchors.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def find_links(
    html: str,
    base_url: str,
    pattern: str | None = None,
    include: str | None = None,
    exclude: str | None = None,
) -> list[Link]:
    """File links on a page, absolute, de-duplicated, in page order."""
    parser = _AnchorParser()
    parser.feed(html)
    want = re.compile(pattern or DEFAULT_LINK_PATTERN, re.IGNORECASE)
    inc = re.compile(include, re.IGNORECASE) if include else None
    exc = re.compile(exclude, re.IGNORECASE) if exclude else None
    out: list[Link] = []
    seen: set[str] = set()
    for href, text in parser.anchors:
        if not href or href.startswith(("mailto:", "javascript:")):
            continue
        absolute, _ = urldefrag(urljoin(base_url, href))
        haystack = f"{absolute} {text}"
        if not want.search(href) and not want.search(absolute):
            continue
        if inc and not inc.search(haystack):
            continue
        if exc and exc.search(haystack):
            continue
        if absolute not in seen:
            seen.add(absolute)
            out.append(Link(absolute, text))
    return out


# ---------------------------------------------------------------- validation


def validate_pdf(content: bytes) -> PdfCheck:
    if b"%PDF-" not in content[:1024]:
        return PdfCheck(False, reason="response is not a PDF (the site may have served an HTML page)")
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        pages = len(reader.pages)
        sample = "".join((reader.pages[i].extract_text() or "") for i in range(min(3, pages)))
    except Exception as exc:  # corrupt or encrypted
        return PdfCheck(False, reason=f"could not read PDF: {exc}")
    warnings: list[str] = []
    if len(sample.strip()) < MIN_TEXT_CHARS:
        warnings.append("very little extractable text in the first pages: this looks like a scan and needs OCR before ingesting")
    return PdfCheck(True, pages=pages, warnings=warnings)


# ---------------------------------------------------------------- manifest


def load_manifest(path: str | Path | None = None) -> dict[str, list[SourceSpec]]:
    path = Path(path) if path else DATA_DIR / "sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, list[SourceSpec]] = {}
    for act_id, entries in raw.items():
        out[act_id] = [
            SourceSpec(
                url=e["url"],
                kind=e.get("kind", "pdf"),
                link_pattern=e.get("link_pattern"),
                include=e.get("include"),
                exclude=e.get("exclude"),
                pick=e.get("pick"),
                note=e.get("note", ""),
            )
            for e in (entries or [])
        ]
    return out


# ---------------------------------------------------------------- scraper


class Scraper:
    def __init__(self, client: PoliteClient, out_dir: str | Path = "data/raw"):
        self.client = client
        self.out_dir = Path(out_dir)

    def discover(self, spec: SourceSpec, refresh: bool = False) -> list[Link]:
        """Candidate file links for a spec (for 'pdf' specs, just the URL itself)."""
        if spec.kind == "pdf":
            return [Link(spec.url, "")]
        page = self.client.get(spec.url, refresh=refresh)
        html = page.content.decode("utf-8", errors="replace")
        links = find_links(html, page.final_url, spec.link_pattern, spec.include, spec.exclude)
        if not links:
            raise NoLinksFound(
                f"No file links found on {spec.url}. The page may load its files with JavaScript. "
                "Open it in a browser, copy the PDF link, and rerun with --url <pdf-url>."
            )
        return links

    def fetch(
        self,
        act_id: str,
        spec: SourceSpec,
        pick: int | None = None,
        refresh: bool = False,
        write_text: bool = False,
    ) -> Saved:
        links = self.discover(spec, refresh=refresh)
        choice = pick or spec.pick
        if len(links) > 1 and choice is None:
            raise AmbiguousLinks(links)
        if choice is not None and not 1 <= choice <= len(links):
            raise ScrapeError(f"--pick {choice} is out of range (1..{len(links)})")
        target = links[(choice or 1) - 1]

        res = self.client.get(target.url, refresh=refresh)
        check = validate_pdf(res.content)
        if not check.ok:
            raise ScrapeError(f"{target.url}: {check.reason}")

        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{act_id}.pdf"
        path.write_bytes(res.content)

        meta_path = path.with_suffix(".pdf.meta.json")
        meta_path.write_text(
            json.dumps(
                {
                    "act_id": act_id,
                    "source_url": target.url,
                    "final_url": res.final_url,
                    "page_url": spec.url if spec.kind == "page" else None,
                    "link_text": target.text,
                    "fetched_at": res.fetched_at,
                    "served_from_cache": res.from_cache,
                    "sha256": hashlib.sha256(res.content).hexdigest(),
                    "bytes": len(res.content),
                    "content_type": res.content_type,
                    "pages": check.pages,
                    "warnings": check.warnings,
                    "user_agent": self.client.user_agent,
                    "legalbot_version": __version__,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        text_path = None
        if write_text:
            from ..ingest import read_document

            text_path = path.with_suffix(".txt")
            text_path.write_text(read_document(path), encoding="utf-8")

        return Saved(
            path=path,
            meta_path=meta_path,
            url=target.url,
            sha256=hashlib.sha256(res.content).hexdigest(),
            bytes=len(res.content),
            pages=check.pages,
            warnings=check.warnings,
            text_path=text_path,
        )
