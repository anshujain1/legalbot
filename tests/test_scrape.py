"""Scraper tests. All HTTP goes through httpx.MockTransport: no network, no real sites."""
import io
import json

import httpx
import pytest

from legalbot.cli import main
from legalbot.scrape import (
    AmbiguousLinks,
    FetchError,
    NoLinksFound,
    PoliteClient,
    RobotsBlocked,
    Scraper,
    ScrapeError,
    SourceSpec,
    find_links,
    load_manifest,
    validate_pdf,
)

HOST = "https://laws.example.gov.in"


def make_pdf(text: str = "") -> bytes:
    """Minimal one-page PDF; `text` becomes extractable page text."""
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=300, height=300)
    buf = io.BytesIO()
    w.write(buf)
    data = buf.getvalue()
    return data


class Site:
    """Tiny fake website: path -> (status, headers, body). Records every request."""

    def __init__(self, routes: dict[str, tuple[int, dict, bytes]]):
        self.routes = routes
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        status, headers, body = self.routes.get(request.url.path, (404, {}, b"nope"))
        return httpx.Response(status, headers=headers, content=body, request=request)


def client_for(site: Site, tmp_path, **kw) -> tuple[PoliteClient, list[float]]:
    naps: list[float] = []
    clock = {"t": 0.0}

    def sleep(s: float) -> None:
        naps.append(s)
        clock["t"] += s

    c = PoliteClient(
        cache_dir=tmp_path / "cache",
        user_agent="legalbot-test (test@example.com)",
        transport=httpx.MockTransport(site),
        sleep=sleep,
        clock=lambda: clock["t"],
        **kw,
    )
    return c, naps


ROBOTS_OK = (200, {}, b"User-agent: *\nDisallow: /private/\n")


# ---------------------------------------------------------------- link discovery


def test_find_links_resolves_relative_dedupes_and_filters():
    html = """
      <a href="/bitstream/123/45/1/act.pdf">English</a>
      <a href="/bitstream/123/45/1/act.pdf#page=2">English again</a>
      <a href="../../files/hindi.pdf">हिन्दी</a>
      <a href="/about">About us</a>
      <a href="mailto:x@y.z">mail</a>
    """
    links = find_links(html, f"{HOST}/handle/1/2")
    assert [l.url for l in links] == [f"{HOST}/bitstream/123/45/1/act.pdf", f"{HOST}/files/hindi.pdf"]
    assert find_links(html, f"{HOST}/handle/1/2", exclude="हिन्दी|hindi")[0].text == "English"
    assert [l.text for l in find_links(html, f"{HOST}/handle/1/2", include="English")] == ["English"]


# ---------------------------------------------------------------- polite client


def test_robots_disallow_blocks_without_fetching_the_page(tmp_path):
    site = Site({"/robots.txt": ROBOTS_OK, "/private/act.pdf": (200, {}, b"%PDF-1.4")})
    c, _ = client_for(site, tmp_path)
    with pytest.raises(RobotsBlocked):
        c.get(f"{HOST}/private/act.pdf")
    assert all("/private/" not in u for u in site.requests)


def test_robots_server_error_means_disallow(tmp_path):
    site = Site({"/robots.txt": (503, {}, b""), "/a.pdf": (200, {}, b"%PDF-1.4")})
    c, _ = client_for(site, tmp_path, retries=0)
    with pytest.raises(RobotsBlocked):
        c.get(f"{HOST}/a.pdf")


def test_robots_error_message_says_why(tmp_path):
    site = Site({"/robots.txt": (503, {}, b""), "/a.pdf": (200, {}, b"%PDF-1.4")})
    c, _ = client_for(site, tmp_path, retries=0)
    with pytest.raises(RobotsBlocked, match="HTTP 503"):
        c.get(f"{HOST}/a.pdf")


def test_unreachable_robots_message_says_why(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("proxy said no", request=request)

    c = PoliteClient(cache_dir=tmp_path / "c", transport=httpx.MockTransport(handler), sleep=lambda s: None, retries=0)
    with pytest.raises(RobotsBlocked, match="could not fetch"):
        c.get(f"{HOST}/a.pdf")


def test_robots_404_means_allowed(tmp_path):
    site = Site({"/a.pdf": (200, {"content-type": "application/pdf"}, b"%PDF-1.4 hi")})
    c, _ = client_for(site, tmp_path)
    assert c.get(f"{HOST}/a.pdf").content.startswith(b"%PDF")


def test_rate_limit_spaces_requests_per_host(tmp_path):
    site = Site({"/robots.txt": ROBOTS_OK, "/a": (200, {}, b"a"), "/b": (200, {}, b"b")})
    c, naps = client_for(site, tmp_path, min_delay=2.0)
    c.get(f"{HOST}/a")
    c.get(f"{HOST}/b")
    assert naps and all(n == pytest.approx(2.0) for n in naps)  # robots.txt->a, a->b, ...


def test_crawl_delay_from_robots_is_respected(tmp_path):
    site = Site({"/robots.txt": (200, {}, b"User-agent: *\nCrawl-delay: 7\n"), "/a": (200, {}, b"a"), "/b": (200, {}, b"b")})
    c, naps = client_for(site, tmp_path, min_delay=1.0)
    c.get(f"{HOST}/a")
    c.get(f"{HOST}/b")
    assert max(naps) == pytest.approx(7.0)


def test_cache_prevents_second_request_unless_refresh(tmp_path):
    site = Site({"/robots.txt": ROBOTS_OK, "/a": (200, {}, b"hello")})
    c, _ = client_for(site, tmp_path)
    assert not c.get(f"{HOST}/a").from_cache
    n = len(site.requests)
    again = c.get(f"{HOST}/a")
    assert again.from_cache and again.content == b"hello" and len(site.requests) == n
    assert not c.get(f"{HOST}/a", refresh=True).from_cache


def test_retries_5xx_then_succeeds_and_honours_retry_after(tmp_path):
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404, request=request)
        state["n"] += 1
        if state["n"] < 3:
            return httpx.Response(503, headers={"retry-after": "5"}, request=request)
        return httpx.Response(200, content=b"ok", request=request)

    naps: list[float] = []
    c = PoliteClient(cache_dir=tmp_path / "c", transport=httpx.MockTransport(handler), sleep=naps.append, min_delay=0)
    assert c.get(f"{HOST}/x").content == b"ok"
    assert state["n"] == 3 and naps.count(5.0) == 2


def test_gives_up_after_retries(tmp_path):
    site = Site({"/robots.txt": ROBOTS_OK, "/x": (500, {}, b"")})
    c, _ = client_for(site, tmp_path, retries=2)
    with pytest.raises(FetchError, match="500"):
        c.get(f"{HOST}/x")


def test_redirect_is_followed_and_each_hop_checked_against_robots(tmp_path):
    routes = {
        "/robots.txt": ROBOTS_OK,
        "/old": (302, {"location": "/private/new.pdf"}, b""),
        "/private/new.pdf": (200, {}, b"%PDF-1.4"),
    }
    site = Site(routes)
    c, _ = client_for(site, tmp_path)
    with pytest.raises(RobotsBlocked):
        c.get(f"{HOST}/old")
    assert all("/private/" not in u for u in site.requests)


def test_redirect_loop_is_cut_off(tmp_path):
    site = Site({"/robots.txt": ROBOTS_OK, "/a": (302, {"location": "/a"}, b"")})
    c, _ = client_for(site, tmp_path)
    with pytest.raises(FetchError, match="redirect"):
        c.get(f"{HOST}/a")


def test_non_http_scheme_rejected(tmp_path):
    c, _ = client_for(Site({}), tmp_path)
    with pytest.raises(ScrapeError):
        c.get("file:///etc/passwd")


def test_size_limit(tmp_path):
    site = Site({"/robots.txt": ROBOTS_OK, "/big": (200, {}, b"x" * 100)})
    c, _ = client_for(site, tmp_path, max_bytes=50)
    with pytest.raises(FetchError, match="limit"):
        c.get(f"{HOST}/big")


def test_user_agent_is_sent(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["user-agent"])
        return httpx.Response(404 if request.url.path == "/robots.txt" else 200, content=b"x", request=request)

    c = PoliteClient(cache_dir=tmp_path / "c", user_agent="legalbot-test (me@example.com)", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    c.get(f"{HOST}/x")
    assert set(seen) == {"legalbot-test (me@example.com)"}


# ---------------------------------------------------------------- validation


def test_validate_pdf_rejects_html_and_garbage():
    assert not validate_pdf(b"<html>Captcha</html>").ok
    assert not validate_pdf(b"%PDF-1.4 but not really a pdf").ok


def test_validate_pdf_flags_scans():
    check = validate_pdf(make_pdf())
    assert check.ok and check.pages == 1
    assert any("OCR" in w for w in check.warnings)


# ---------------------------------------------------------------- scraper end to end


def test_scrape_direct_pdf_saves_file_and_provenance(tmp_path):
    site = Site({"/robots.txt": ROBOTS_OK, "/bns.pdf": (200, {"content-type": "application/pdf"}, make_pdf())})
    c, _ = client_for(site, tmp_path)
    saved = Scraper(c, out_dir=tmp_path / "raw").fetch("bns", SourceSpec(url=f"{HOST}/bns.pdf"))
    assert saved.path == tmp_path / "raw" / "bns.pdf" and saved.path.read_bytes().startswith(b"%PDF")
    meta = json.loads(saved.meta_path.read_text())
    assert meta["source_url"] == f"{HOST}/bns.pdf" and meta["sha256"] == saved.sha256
    assert meta["user_agent"].startswith("legalbot-test") and meta["pages"] == 1


def test_scrape_rejects_html_masquerading_as_pdf(tmp_path):
    site = Site({"/robots.txt": ROBOTS_OK, "/bns.pdf": (200, {"content-type": "text/html"}, b"<html>please log in</html>")})
    c, _ = client_for(site, tmp_path)
    with pytest.raises(ScrapeError, match="not a PDF"):
        Scraper(c, out_dir=tmp_path / "raw").fetch("bns", SourceSpec(url=f"{HOST}/bns.pdf"))
    assert not (tmp_path / "raw" / "bns.pdf").exists()


def test_scrape_page_with_single_link(tmp_path):
    page = b'<html><a href="/files/bns.pdf">Download</a></html>'
    site = Site({"/robots.txt": ROBOTS_OK, "/handle/1": (200, {}, page), "/files/bns.pdf": (200, {}, make_pdf())})
    c, _ = client_for(site, tmp_path)
    saved = Scraper(c, out_dir=tmp_path / "raw").fetch("bns", SourceSpec(url=f"{HOST}/handle/1", kind="page"))
    assert saved.url == f"{HOST}/files/bns.pdf"
    assert json.loads(saved.meta_path.read_text())["page_url"] == f"{HOST}/handle/1"


def test_scrape_page_with_several_links_requires_a_choice(tmp_path):
    page = b'<a href="/a.pdf">English</a> <a href="/b.pdf">Hindi</a>'
    site = Site({"/robots.txt": ROBOTS_OK, "/h": (200, {}, page), "/b.pdf": (200, {}, make_pdf())})
    c, _ = client_for(site, tmp_path)
    scraper = Scraper(c, out_dir=tmp_path / "raw")
    spec = SourceSpec(url=f"{HOST}/h", kind="page")
    with pytest.raises(AmbiguousLinks) as exc:
        scraper.fetch("bns", spec)
    assert len(exc.value.links) == 2
    assert scraper.fetch("bns", spec, pick=2).url == f"{HOST}/b.pdf"
    with pytest.raises(ScrapeError, match="out of range"):
        scraper.fetch("bns", spec, pick=9)


def test_scrape_page_without_links_explains_javascript_fallback(tmp_path):
    site = Site({"/robots.txt": ROBOTS_OK, "/h": (200, {}, b"<html><div id='app'></div></html>")})
    c, _ = client_for(site, tmp_path)
    with pytest.raises(NoLinksFound, match="JavaScript"):
        Scraper(c, out_dir=tmp_path / "raw").fetch("bns", SourceSpec(url=f"{HOST}/h", kind="page"))


# ---------------------------------------------------------------- manifest + CLI


def test_shipped_manifest_is_valid_and_references_known_acts():
    from legalbot.registry import ActRegistry

    manifest = load_manifest()
    registry = ActRegistry.load()
    assert manifest and all(act in registry for act in manifest)
    assert all(s.kind in {"pdf", "page"} and s.url.startswith("https://") for specs in manifest.values() for s in specs)


def test_cli_scrape_unknown_act(capsys):
    assert main(["scrape", "--act", "nope", "--url", "https://x.test/a.pdf"]) == 2
    assert "unknown act" in capsys.readouterr().err


def test_cli_scrape_act_without_manifest_entry(capsys):
    assert main(["scrape", "--act", "bsa"]) == 2
    assert "--url" in capsys.readouterr().err
