"""A polite HTTP client for fetching public legal texts.

Rules it enforces, with no switch to turn them off:
  * robots.txt is fetched and obeyed for every host and every redirect hop. A robots.txt that
    answers 4xx means "no rules" (allow); one that errors or answers 5xx means "disallow" (RFC 9309).
  * at most one request per `min_delay` seconds per host (or the site's Crawl-delay if larger).
  * identifies itself with a User-Agent carrying a contact (set LEGALBOT_CONTACT).
  * retries 429/5xx and network errors with backoff, honouring Retry-After.
  * everything fetched is cached on disk, so re-running never hits the site again unless asked.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .. import __version__

MAX_REDIRECTS = 5
RETRY_STATUSES = {429, 500, 502, 503, 504}


class ScrapeError(Exception):
    pass


class RobotsBlocked(ScrapeError):
    pass


class FetchError(ScrapeError):
    pass


def default_user_agent() -> str:
    contact = os.getenv("LEGALBOT_CONTACT", "contact-not-set")
    return f"legalbot/{__version__} (research crawler; {contact})"


@dataclass
class Fetched:
    url: str
    final_url: str
    status: int
    content_type: str
    content: bytes
    from_cache: bool
    fetched_at: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


class PoliteClient:
    def __init__(
        self,
        cache_dir: str | Path = ".cache/http",
        user_agent: str | None = None,
        min_delay: float = 2.0,
        timeout: float = 30.0,
        retries: int = 3,
        max_bytes: int = 100 * 1024 * 1024,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.user_agent = user_agent or default_user_agent()
        self.min_delay = min_delay
        self.retries = retries
        self.max_bytes = max_bytes
        self.cache_dir = Path(cache_dir)
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser] = {}
        self._robots_note: dict[str, str] = {}  # why a host is fully blocked, when it is
        self._http = httpx.Client(
            transport=transport,
            follow_redirects=False,  # redirects are followed by hand so every hop is checked
            timeout=timeout,
            headers={"User-Agent": self.user_agent, "Accept": "*/*"},
        )

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------ public

    def get(self, url: str, *, refresh: bool = False) -> Fetched:
        if not refresh:
            cached = self._cache_read(url)
            if cached is not None:
                return cached

        current = url
        for _ in range(MAX_REDIRECTS + 1):
            self._require_http(current)
            self._check_robots(current)
            resp = self._send(current)
            if resp.status_code in {301, 302, 303, 307, 308} and resp.headers.get("location"):
                current = urljoin(current, resp.headers["location"])
                continue
            break
        else:
            raise FetchError(f"Too many redirects starting at {url}")

        if resp.status_code != 200:
            raise FetchError(f"{current} -> HTTP {resp.status_code}")
        if len(resp.content) > self.max_bytes:
            raise FetchError(f"{current} is {len(resp.content)} bytes, over the {self.max_bytes} byte limit")

        fetched = Fetched(
            url=url,
            final_url=current,
            status=resp.status_code,
            content_type=resp.headers.get("content-type", ""),
            content=resp.content,
            from_cache=False,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._cache_write(fetched)
        return fetched

    # ------------------------------------------------------------ robots

    @staticmethod
    def _origin(url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"

    def _check_robots(self, url: str) -> None:
        origin = self._origin(url)
        rp = self._robots.get(origin)
        if rp is None:
            rp = self._load_robots(origin)
            self._robots[origin] = rp
        if not rp.can_fetch(self.user_agent, url):
            note = self._robots_note.get(origin)
            if note:
                raise RobotsBlocked(f"{url} not fetched: {note}")
            raise RobotsBlocked(f"robots.txt on {origin} disallows fetching {url}")

    def _load_robots(self, origin: str) -> RobotFileParser:
        rp = RobotFileParser()
        try:
            resp = self._send(f"{origin}/robots.txt")
        except FetchError as exc:
            rp.disallow_all = True  # unreachable robots.txt: be conservative
            self._robots_note[origin] = f"could not fetch {origin}/robots.txt ({exc}); treating the site as off-limits"
        else:
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            elif 400 <= resp.status_code < 500:
                rp.allow_all = True
            else:
                rp.disallow_all = True
                self._robots_note[origin] = (
                    f"{origin}/robots.txt answered HTTP {resp.status_code}; treating the site as off-limits"
                )
        rp.modified()  # marks it as checked; can_fetch() refuses otherwise
        return rp

    # ------------------------------------------------------------ transport

    @staticmethod
    def _require_http(url: str) -> None:
        if urlparse(url).scheme not in {"http", "https"}:
            raise ScrapeError(f"Only http(s) URLs are supported: {url}")

    def _delay_for(self, origin: str) -> float:
        rp = self._robots.get(origin)
        crawl = rp.crawl_delay(self.user_agent) if rp is not None else None
        return max(self.min_delay, float(crawl)) if crawl else self.min_delay

    def _throttle(self, origin: str) -> None:
        last = self._last_request.get(origin)
        if last is not None:
            wait = self._delay_for(origin) - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[origin] = self._clock()

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float | None:
        value = resp.headers.get("retry-after", "")
        return min(float(value), 60.0) if value.isdigit() else None

    def _send(self, url: str) -> httpx.Response:
        origin = self._origin(url)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._throttle(origin)
            try:
                resp = self._http.get(url)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt < self.retries:
                    self._sleep(2.0**attempt)
                continue
            if resp.status_code in RETRY_STATUSES and attempt < self.retries:
                self._sleep(self._retry_after(resp) or 2.0**attempt)
                continue
            return resp
        raise FetchError(f"Could not fetch {url}: {last_error}")

    # ------------------------------------------------------------ cache

    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / f"{key}.body", self.cache_dir / f"{key}.json"

    def _cache_read(self, url: str) -> Fetched | None:
        body, meta = self._cache_paths(url)
        if not (body.exists() and meta.exists()):
            return None
        info = json.loads(meta.read_text(encoding="utf-8"))
        return Fetched(
            url=url,
            final_url=info["final_url"],
            status=200,
            content_type=info["content_type"],
            content=body.read_bytes(),
            from_cache=True,
            fetched_at=info["fetched_at"],
        )

    def _cache_write(self, f: Fetched) -> None:
        body, meta = self._cache_paths(f.url)
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_bytes(f.content)
        meta.write_text(
            json.dumps(
                {"url": f.url, "final_url": f.final_url, "content_type": f.content_type, "fetched_at": f.fetched_at}
            ),
            encoding="utf-8",
        )
