"""Find which pages to audit: sitemap first, homepage links as a fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .fetch import Fetcher
from .page import classify, normalize_url

SITEMAP_CHILD_LIMIT = 6


@dataclass
class Discovery:
    robots_found: bool = False
    sitemap_url: str = ""
    sitemap_urls: list[str] = field(default_factory=list)


def _locs(xml: str) -> list[str]:
    """Page URLs only: <url><loc> or <sitemap><loc>, never <image:loc> entries."""
    soup = BeautifulSoup(xml, "xml")
    locs = []
    for parent in soup.find_all(["url", "sitemap"]):
        loc = parent.find("loc", recursive=False)
        if loc is not None and not loc.prefix:
            locs.append(loc.get_text(strip=True))
    return locs


def discover(fetcher: Fetcher, base: str) -> Discovery:
    found = Discovery()
    robots = fetcher.get(urljoin(base, "/robots.txt"), check_robots=False)
    candidates = []
    if robots.ok and robots.text.strip():
        found.robots_found = True
        candidates = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots.text)
    candidates.append(urljoin(base, "/sitemap.xml"))

    for candidate in dict.fromkeys(candidates):
        res = fetcher.get(candidate)
        if not res.ok or "<" not in res.text:
            continue
        found.sitemap_url = candidate
        locs = _locs(res.text)
        if "<sitemapindex" in res.text:
            pages = []
            # Shopify splits by type (products, collections, pages, blogs); read a few of each
            for child in locs[:SITEMAP_CHILD_LIMIT]:
                child_res = fetcher.get(child)
                if child_res.ok:
                    pages.extend(_locs(child_res.text))
            locs = pages
        host = urlsplit(base).netloc.lower()
        found.sitemap_urls = [normalize_url(u) for u in locs if urlsplit(u).netloc.lower() == host]
        break
    return found


def sample_pages(base: str, sitemap_urls: list[str], home_links: list[str], max_pages: int) -> list[str]:
    """Home plus an even spread of product, collection and content pages."""
    home = normalize_url(base)
    # the sitemap is the store's own list of pages; homepage links are only a fallback,
    # otherwise a dead link would be audited as a page instead of reported as broken
    source = sitemap_urls or home_links
    pool = [u for u in dict.fromkeys(source) if u != home]
    buckets = {"product": [], "collection": [], "page": []}
    for url in pool:
        kind = classify(url)
        if kind in buckets:
            buckets[kind].append(url)
    chosen = [home]
    quotas = {"product": max_pages * 4 // 10, "collection": max_pages * 3 // 10}
    quotas["page"] = max_pages - 1 - quotas["product"] - quotas["collection"]
    for kind in ("product", "collection", "page"):
        chosen.extend(buckets[kind][: quotas[kind]])
    # fill any unused quota from whatever is left
    for url in pool:
        if len(chosen) >= max_pages:
            break
        if url not in chosen and classify(url) in buckets:
            chosen.append(url)
    return chosen[:max_pages]
