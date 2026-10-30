"""Audit one storefront end to end."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .checks import Finding, SiteContext, run_checks, scores
from .discover import discover, sample_pages
from .fetch import Fetcher, Response
from .page import PageData, normalize_url, parse_page
from .platform import Platform, detect

SKIP_LINK_PARTS = ("/cart", "/account", "/checkout", "/search", "/password", "/apps/", "/cdn/")


@dataclass
class AuditResult:
    site: str
    audited_at: str
    platform: Platform
    pages: list[PageData]
    findings: list[Finding]
    scores: dict[str, int]
    sitemap_count: int
    links_checked: int
    requests: int
    seconds: float
    error: str = ""
    skipped: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        result = {"critical": 0, "high": 0, "medium": 0}
        for f in self.findings:
            result[f.severity] += 1
        return result


def _origin(url: str) -> str:
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc.lower()}/"


def _is_html(res: Response) -> bool:
    return res.ok and "html" in res.headers.get("content-type", "html")


def audit_site(url: str, max_pages: int = 15, link_limit: int = 30,
               fetcher: Fetcher | None = None) -> AuditResult:
    fetcher = fetcher or Fetcher()
    started = time.monotonic()
    base = _origin(url)
    home_res = fetcher.get(base)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not _is_html(home_res):
        return AuditResult(base, stamp, Platform(), [], [], {}, 0, 0, fetcher.requests_made,
                           time.monotonic() - started, error=home_res.error or f"homepage returned {home_res.status}")
    base = _origin(home_res.final_url)     # follow e.g. example.com -> www.example.com
    responses = {normalize_url(base): home_res}

    found = discover(fetcher, base)
    http_probe = None
    if base.startswith("https://"):
        http_probe = fetcher.get("http://" + base[len("https://"):], check_robots=False)
    else:
        http_probe = home_res

    home = parse_page(normalize_url(base), home_res.text)
    platform = detect(home_res.text, base, [s.src for s in home.scripts])
    pages = [home]
    skipped = []
    for page_url in sample_pages(base, found.sitemap_urls, home.internal_links, max_pages)[1:]:
        res = fetcher.get(page_url)
        if res.blocked_by_robots:
            skipped.append(page_url)
            continue
        responses[page_url] = res
        if _is_html(res):
            pages.append(parse_page(page_url, res.text))

    audited = set(responses)
    candidates = []
    for p in pages:
        for link in p.internal_links:
            path = urlsplit(link).path
            if link in audited or any(part in path for part in SKIP_LINK_PARTS) or urlsplit(link).query:
                continue
            candidates.append((link, p.url))
    broken, checked, seen = [], 0, set()
    for link, source in candidates:
        if checked >= link_limit:
            break
        if link in seen:
            continue
        seen.add(link)
        res = fetcher.check_link(link)
        if res.blocked_by_robots:
            continue
        checked += 1
        if res.status >= 400:
            broken.append((link, res.status, source))

    ctx = SiteContext(base=base, pages=pages, responses=responses, platform=platform,
                      robots_found=found.robots_found, sitemap_url=found.sitemap_url,
                      sitemap_count=len(found.sitemap_urls), http_probe=http_probe,
                      broken_links=broken, links_checked=checked)
    findings = run_checks(ctx)
    return AuditResult(base, stamp, platform, pages, findings, scores(findings), len(found.sitemap_urls),
                       checked, fetcher.requests_made, round(time.monotonic() - started, 1), skipped=skipped)
