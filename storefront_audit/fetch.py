"""A polite HTTP client: honours robots.txt, rate-limits per host and records timings."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import requests

from . import USER_AGENT

MAX_BYTES = 5_000_000


@dataclass
class Response:
    url: str                     # requested URL
    final_url: str               # after redirects
    status: int                  # 0 when the request failed
    headers: dict = field(default_factory=dict)
    text: str = ""
    elapsed: float = 0.0         # seconds until headers arrived (server response time)
    size: int = 0                # bytes of body read
    redirects: list[str] = field(default_factory=list)
    error: str = ""
    blocked_by_robots: bool = False

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class Fetcher:
    def __init__(self, delay: float = 0.5, timeout: float = 20.0, respect_robots: bool = True, retries: int = 1):
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en"})
        self._last: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()
        self.requests_made = 0

    def _wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            ready = self._last.get(host, 0.0) + self.delay
            self._last[host] = max(now, ready)
        if ready > now:
            time.sleep(ready - now)

    def robots(self, base: str) -> robotparser.RobotFileParser | None:
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(base))
        if origin not in self._robots:
            parser = None
            res = self.get(urljoin(origin, "/robots.txt"), check_robots=False)
            if res.ok and res.text:
                parser = robotparser.RobotFileParser()
                parser.parse(res.text.splitlines())
            self._robots[origin] = parser
        return self._robots[origin]

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parser = self.robots(url)
        return parser.can_fetch(USER_AGENT, url) if parser else True

    RETRY_STATUSES = (0, 429, 502, 503, 504)

    def get(self, url: str, check_robots: bool = True, method: str = "GET",
            allow_redirects: bool = True) -> Response:
        if check_robots and not self.allowed(url):
            return Response(url, url, 0, blocked_by_robots=True, error="disallowed by robots.txt")
        res = self._request(url, method, allow_redirects)
        for attempt in range(self.retries):
            if res.status not in self.RETRY_STATUSES:
                break
            # a dropped connection or rate limit is not a broken page: back off and ask again
            wait = res.headers.get("retry-after", "")
            time.sleep(min(float(wait), 10.0) if wait.isdigit() else 2.0 * (attempt + 1))
            res = self._request(url, method, allow_redirects)
        return res

    def _request(self, url: str, method: str, allow_redirects: bool) -> Response:
        self._wait(urlsplit(url).netloc)
        self.requests_made += 1
        started = time.monotonic()
        try:
            raw = self.session.request(method, url, timeout=self.timeout, stream=True,
                                       allow_redirects=allow_redirects)
            elapsed = time.monotonic() - started
            body = b""
            if method == "GET":
                for chunk in raw.iter_content(65536):
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
            raw.close()
            encoding = raw.encoding or "utf-8"
            return Response(
                url=url, final_url=raw.url, status=raw.status_code,
                headers={k.lower(): v for k, v in raw.headers.items()},
                text=body.decode(encoding, errors="replace"), elapsed=elapsed, size=len(body),
                redirects=[r.url for r in raw.history],
            )
        except requests.RequestException as exc:
            return Response(url, url, 0, elapsed=time.monotonic() - started, error=type(exc).__name__)

    def check_link(self, url: str) -> Response:
        """HEAD first; some servers reject HEAD, so fall back to GET."""
        res = self.get(url, method="HEAD")
        if res.status in (0, 403, 405, 501) and not res.blocked_by_robots:
            res = self.get(url)
        return res
