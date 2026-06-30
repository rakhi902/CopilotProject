"""Tests for the JD URL scraping service (app.services.jd_scraping)."""

import socket

import pytest
import requests

import app.services.jd_scraping as jd
from app.services.jd_scraping import JDScrapingError, scrape_jd_text


class _FakeResponse:
    """A minimal stand-in for a ``requests`` response used by the scraper."""

    def __init__(self, html, status_code=200, content_type="text/html; charset=utf-8"):
        self._html = html.encode("utf-8")
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def iter_content(self, chunk_size=16384):
        midpoint = len(self._html) // 2  # deliberately split across two chunks
        yield self._html[:midpoint]
        yield self._html[midpoint:]

    def close(self):
        pass


def _public_addrinfo(host, port, *args, **kwargs):
    """Pretend any host resolves to a public IP (so the SSRF guard passes)."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def test_scrapes_visible_text_and_strips_boilerplate(monkeypatch):
    html = (
        "<html><head><style>.x{color:red}</style></head><body>"
        "<nav>home about</nav>"
        "<h1>Senior Backend Engineer</h1>"
        "<p>We need strong FastAPI and SQL experience to build APIs at scale.</p>"
        "<script>var tracking = 1;</script>"
        "<footer>copyright</footer></body></html>"
    )
    monkeypatch.setattr(jd.socket, "getaddrinfo", _public_addrinfo)
    monkeypatch.setattr(jd.requests, "get", lambda *a, **k: _FakeResponse(html))

    text = scrape_jd_text("https://example.com/jobs/123")

    assert "Senior Backend Engineer" in text
    assert "FastAPI" in text
    assert "tracking" not in text   # <script> removed
    assert "home about" not in text  # <nav> removed
    assert "copyright" not in text   # <footer> removed


def test_rejects_non_http_scheme():
    with pytest.raises(JDScrapingError):
        scrape_jd_text("ftp://example.com/job")


def test_rejects_private_loopback_address():
    # An IP literal resolves locally (no network) -> the SSRF guard must reject it.
    with pytest.raises(JDScrapingError):
        scrape_jd_text("http://127.0.0.1:8000/internal")


def test_rejects_too_little_usable_text(monkeypatch):
    monkeypatch.setattr(jd.socket, "getaddrinfo", _public_addrinfo)
    monkeypatch.setattr(jd.requests, "get", lambda *a, **k: _FakeResponse("<html><body>hi</body></html>"))
    with pytest.raises(JDScrapingError):
        scrape_jd_text("https://example.com/blocked")
