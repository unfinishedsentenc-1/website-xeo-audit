"""Polite page fetching.

The fetcher follows three rules.
1. It reads robots.txt first and never requests a page the site disallows.
2. It waits between requests to the same site, and longer if robots.txt asks.
3. It never tries to get around a block. A block is recorded and reported.
"""

from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse, urlunparse, urldefrag

import requests

# Text that shows up on bot-challenge pages from common firewalls.
CHALLENGE_MARKERS = (
    "cf-chl",
    "challenge-platform",
    "just a moment...",
    "attention required! | cloudflare",
    "checking your browser",
    "px-captcha",
    "_incapsula_resource",
    "access denied</title>",
    "request unsuccessful. incapsula",
    "datadome",
)


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None
    headers: dict = field(default_factory=dict)
    text: str = ""
    elapsed: float | None = None  # seconds until the first response arrived
    redirects: list = field(default_factory=list)  # [(from_url, status)]
    error: str | None = None
    blocked: str | None = None  # plain reason when the site blocked us

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    @property
    def is_html(self) -> bool:
        ctype = self.headers.get("content-type", "")
        return "html" in ctype.lower() or (not ctype and "<html" in self.text[:2000].lower())


def normalize_url(url: str) -> str:
    """Drop the #fragment, lowercase the host and remove default ports."""
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    scheme = (p.scheme or "https").lower()
    host = (p.hostname or "").lower()
    port = p.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = p.path or "/"
    return urlunparse((scheme, netloc, path, "", p.query, ""))


def same_site(a: str, b: str) -> bool:
    """True when both URLs are on the same site. www and bare hosts count as one."""

    def bare(u: str) -> str:
        h = (urlparse(u).netloc or "").lower()
        return h[4:] if h.startswith("www.") else h

    return bare(a) == bare(b)


def detect_block(status: int | None, text: str) -> str | None:
    lowered = text[:20000].lower()
    if status in (401, 403) or any(m in lowered for m in CHALLENGE_MARKERS):
        if any(m in lowered for m in CHALLENGE_MARKERS):
            return "The site showed a bot check page instead of its content."
        return f"The site refused the request (status {status})."
    if status == 429:
        return "The site said we sent too many requests (status 429)."
    return None


class Fetcher:
    def __init__(self, settings: dict):
        crawl = settings["crawl"]
        self.delay = float(crawl["delay_seconds"])
        self.timeout = float(crawl["timeout_seconds"])
        self.max_redirects = int(crawl["max_redirects"])
        self.user_agent = crawl["user_agent"]
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en",
            }
        )
        self._last_hit: dict[str, float] = {}
        self._extra_delay: dict[str, float] = {}

    def set_crawl_delay(self, host: str, seconds: float | None) -> None:
        if seconds:
            self._extra_delay[host] = min(float(seconds), 30.0)

    def _wait(self, host: str) -> None:
        delay = max(self.delay, self._extra_delay.get(host, 0.0))
        last = self._last_hit.get(host)
        if last is not None:
            gap = time.monotonic() - last
            if gap < delay:
                time.sleep(delay - gap)
        self._last_hit[host] = time.monotonic()

    def get(self, url: str, method: str = "GET") -> FetchResult:
        """Fetch a URL, following redirects by hand so each hop is recorded."""
        current = url
        redirects = []
        first_elapsed = None
        for _ in range(self.max_redirects + 1):
            host = urlparse(current).netloc
            self._wait(host)
            try:
                resp = self.session.request(
                    method, current, timeout=self.timeout, allow_redirects=False, stream=False
                )
            except requests.RequestException as exc:
                return FetchResult(url, current, None, error=type(exc).__name__, redirects=redirects)
            if first_elapsed is None:
                first_elapsed = resp.elapsed.total_seconds()
            if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    break
                redirects.append((current, resp.status_code))
                current = normalize_url(urljoin(current, location))
                continue
            headers = {k.lower(): v for k, v in resp.headers.items()}
            text = ""
            if method == "GET":
                ctype = headers.get("content-type", "")
                if not ctype or any(t in ctype for t in ("html", "xml", "text")):
                    resp.encoding = resp.encoding or resp.apparent_encoding
                    text = resp.text
            result = FetchResult(
                url, current, resp.status_code, headers, text, first_elapsed, redirects
            )
            result.blocked = detect_block(resp.status_code, text)
            return result
        return FetchResult(url, current, None, error="TooManyRedirects", redirects=redirects)


class Robots:
    """robots.txt rules for one site, plus the raw text for the AI crawler checks."""

    def __init__(self, base_url: str, fetcher: Fetcher):
        self.url = urljoin(base_url, "/robots.txt")
        self.result = fetcher.get(self.url)
        self.exists = bool(self.result.ok and self.result.text.strip())
        self.text = self.result.text if self.exists else ""
        self.parser = urllib.robotparser.RobotFileParser()
        if self.exists:
            self.parser.parse(self.text.splitlines())
        elif self.result.status in (401, 403):
            # Same rule search engines follow. A forbidden robots.txt means stay out.
            self.parser.disallow_all = True
        else:
            self.parser.allow_all = True
        self.user_agent = fetcher.user_agent
        host = urlparse(base_url).netloc
        fetcher.set_crawl_delay(host, self.crawl_delay())

    def crawl_delay(self) -> float | None:
        try:
            return self.parser.crawl_delay(self.user_agent.split("/")[0]) or None
        except Exception:
            return None

    def allows(self, url: str, agent: str | None = None) -> bool:
        agent = agent or self.user_agent.split("/")[0]
        return self.parser.can_fetch(agent, url)

    def names_agent(self, agent: str) -> bool:
        """True when robots.txt has a group written for this exact crawler."""
        for line in self.text.splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() == "user-agent" and value.strip().lower() == agent.lower():
                return True
        return False

    def sitemaps(self) -> list[str]:
        try:
            return list(self.parser.site_maps() or [])
        except Exception:
            return []
