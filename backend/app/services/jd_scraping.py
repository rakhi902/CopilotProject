"""Scrape a job description from a URL into clean plain text.

When the user gives a JD link (a careers page, say) instead of pasting the text,
the backend fetches that page server-side with ``requests`` and boils it down to
readable text with ``beautifulsoup4``.

Two safeguards matter here:

  * SSRF guard: the URL is resolved and rejected if it points at a private,
    loopback, link-local, or otherwise non-public address, so this endpoint can't
    be tricked into making the server fetch internal services.
  * Size and timeout caps: the download is bounded and time-limited so a huge or
    slow page can't exhaust resources.

Some sites (LinkedIn in particular) hide their JD behind a login wall or block
automated access; in that case little usable text comes back and we raise a clear
error telling the user to paste the JD instead.
"""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("job_copilot")


class JDScrapingError(Exception):
    """Raised when a JD URL can't be safely fetched or parsed into usable text."""


_REQUEST_TIMEOUT_SECONDS = 12
_MAX_DOWNLOAD_BYTES = 3 * 1024 * 1024  # 3 MB of HTML is plenty for any JD page
_MAX_JD_CHARS = 20000                  # trim to keep prompts (and bills) bounded
_MIN_USABLE_CHARS = 60                 # below this we assume a block / login wall
_USER_AGENT = "Mozilla/5.0 (compatible; JobCopilotBot/1.0)"
# Structural / boilerplate elements that never carry the JD itself.
_STRIP_TAGS = [
    "script", "style", "noscript", "template", "svg",
    "nav", "header", "footer", "aside", "form",
]


def _assert_safe_public_url(url: str) -> None:
    """Reject anything that isn't an http(s) URL pointing at a public address.

    Raises ``JDScrapingError`` if the scheme is unsupported, the host is missing or
    can't be resolved, or it resolves to a private/internal address (the SSRF
    guard).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise JDScrapingError("The JD URL must start with http:// or https://.")
    host = parsed.hostname
    if not host:
        raise JDScrapingError("The JD URL is missing a host name.")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addr_infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise JDScrapingError(f"Could not resolve the host '{host}'.") from exc

    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            raise JDScrapingError("Refusing to fetch a non-public (internal) address.")


def _download_html(url: str) -> str:
    """Fetch the page HTML, bounded by a timeout and a maximum download size.

    Takes an already-validated URL and returns the decoded HTML (possibly
    truncated at the size cap). Raises ``JDScrapingError`` on any network error, a
    non-2xx status, or a non-HTML body.
    """
    headers = {"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/*"}
    try:
        response = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT_SECONDS, stream=True)
    except requests.RequestException as exc:
        raise JDScrapingError(f"Could not reach the JD URL: {exc}") from exc

    try:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise JDScrapingError(f"The JD URL returned an error ({response.status_code}).") from exc

        content_type = response.headers.get("Content-Type", "")
        if content_type and "html" not in content_type and "text" not in content_type:
            raise JDScrapingError(f"The JD URL did not return a web page (got '{content_type}').")

        chunks, total = [], 0
        for chunk in response.iter_content(chunk_size=16384):
            if not chunk:
                continue
            total += len(chunk)
            if total > _MAX_DOWNLOAD_BYTES:
                break  # stop once we have enough; don't download unbounded data
            chunks.append(chunk)
        encoding = response.encoding or "utf-8"
        return b"".join(chunks).decode(encoding, errors="replace")
    finally:
        response.close()


def scrape_jd_text(url: str) -> str:
    """Fetch ``url`` and return the job description as clean plain text.

    Raises ``JDScrapingError`` if the URL is unsafe or unreachable, or yields too
    little usable text (for example a login wall).
    """
    url = (url or "").strip()
    if not url:
        raise JDScrapingError("No JD URL was provided.")

    _assert_safe_public_url(url)
    html = _download_html(url)

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    # Join on newlines, then drop blank lines so paragraphs stay readable.
    raw_text = soup.get_text(separator="\n")
    cleaned = "\n".join(line.strip() for line in raw_text.splitlines() if line.strip())
    cleaned = cleaned.strip()[:_MAX_JD_CHARS]

    if len(cleaned) < _MIN_USABLE_CHARS:
        raise JDScrapingError(
            "Could not extract a usable job description from that page (it may require "
            "login or block automated access). Please paste the JD text instead."
        )
    logger.info("Scraped %d chars of JD text from %s", len(cleaned), url)
    return cleaned
