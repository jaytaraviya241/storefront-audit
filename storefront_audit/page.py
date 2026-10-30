"""Extract the facts the checks need from one HTML page."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


@dataclass
class Image:
    src: str
    alt: str | None          # None when the attribute is absent
    has_dimensions: bool
    loading: str


@dataclass
class Script:
    src: str
    in_head: bool
    deferred: bool           # async, defer or type=module


@dataclass
class PageData:
    url: str
    kind: str = "page"                       # home | product | collection | page
    title: str = ""
    meta_description: str | None = None
    h1: list[str] = field(default_factory=list)
    canonical: str = ""
    robots_meta: str = ""
    lang: str = ""
    viewport: bool = False
    og: dict[str, str] = field(default_factory=dict)
    images: list[Image] = field(default_factory=list)
    scripts: list[Script] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    jsonld: list[dict] = field(default_factory=list)
    jsonld_errors: int = 0
    microdata: list[dict] = field(default_factory=list)   # schema.org itemscope blocks, JSON-LD shaped
    insecure_resources: list[str] = field(default_factory=list)
    html_bytes: int = 0

    def schema_types(self) -> set[str]:
        types: set[str] = set()

        def walk(node):
            if isinstance(node, dict):
                t = node.get("@type")
                if isinstance(t, str):
                    types.add(t)
                elif isinstance(t, list):
                    types.update(x for x in t if isinstance(x, str))
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(self.jsonld)
        walk(self.microdata)
        return types

    def schema_nodes(self, type_name: str) -> list[dict]:
        found = []

        def walk(node):
            if isinstance(node, dict):
                t = node.get("@type")
                if t == type_name or (isinstance(t, list) and type_name in t):
                    found.append(node)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(self.jsonld)
        walk(self.microdata)
        return found


def normalize_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))


def classify(url: str) -> str:
    path = urlsplit(url).path.rstrip("/")
    if path in ("", "/"):
        return "home"
    if re.search(r"/products?/", path + "/") and not path.endswith(("/products", "/product")):
        return "product"
    if "/collections/" in path + "/" or "/category/" in path:
        return "collection"
    return "page"


def _parse_jsonld(text: str):
    text = text.strip()
    if not text:
        raise ValueError("empty")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # themes often leave trailing commas or control characters; accept only a strict parse
        return json.loads(re.sub(r"[\x00-\x1f]", " ", text))


def parse_page(url: str, html: str) -> PageData:
    soup = BeautifulSoup(html, "lxml")
    page = PageData(url=url, kind=classify(url), html_bytes=len(html.encode("utf-8", "ignore")))
    host = urlsplit(url).netloc.lower()

    if soup.title and soup.title.string:
        page.title = re.sub(r"\s+", " ", soup.title.string).strip()
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower()
        prop = (meta.get("property") or "").lower()
        content = (meta.get("content") or "").strip()
        if name == "description":
            page.meta_description = content
        elif name == "robots":
            page.robots_meta = content.lower()
        elif name == "viewport":
            page.viewport = True
        elif prop.startswith("og:"):
            page.og[prop] = content
    page.h1 = [re.sub(r"\s+", " ", h.get_text(" ")).strip() for h in soup.find_all("h1")]
    canonical = soup.find("link", rel=lambda v: v and "canonical" in (v if isinstance(v, list) else [v]))
    page.canonical = urljoin(url, canonical.get("href", "")) if canonical and canonical.get("href") else ""
    if soup.html:
        page.lang = (soup.html.get("lang") or "").strip()

    head = soup.head
    for s in soup.find_all("script"):
        stype = (s.get("type") or "").lower()
        if stype == "application/ld+json":
            try:
                data = _parse_jsonld(s.string or s.get_text())
                page.jsonld.append(data)
            except (ValueError, json.JSONDecodeError):
                page.jsonld_errors += 1
            continue
        src = s.get("src")
        if src:
            deferred = s.has_attr("async") or s.has_attr("defer") or stype == "module"
            in_head = head is not None and s in head.descendants
            page.scripts.append(Script(urljoin(url, src), in_head, deferred))

    for scope in soup.find_all(attrs={"itemtype": True}):
        itemtype = scope.get("itemtype", "").rstrip("/").rsplit("/", 1)[-1]
        if itemtype != "Product":
            if itemtype and scope.find_parent(attrs={"itemtype": True}) is None:
                page.microdata.append({"@type": itemtype})
            continue
        node: dict = {"@type": "Product", "offers": {}}
        for prop in scope.find_all(attrs={"itemprop": True}):
            name = prop.get("itemprop")
            value = prop.get("content") or prop.get("href") or prop.get("src") or prop.get_text(" ", strip=True)
            if name == "image" and value:
                node["image"] = value
            elif name == "name" and value:
                node.setdefault("name", value)
            elif name in ("price", "lowPrice") and value:
                node["offers"]["price"] = value
            elif name == "availability" and value:
                node["offers"]["availability"] = value
        page.microdata.append(node)

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        page.images.append(Image(
            src=urljoin(url, src) if src else "",
            alt=img.get("alt"),
            has_dimensions=bool(img.get("width") and img.get("height")),
            loading=(img.get("loading") or "").lower(),
        ))

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = normalize_url(urljoin(url, href))
        if urlsplit(absolute).netloc.lower() == host and absolute not in seen:
            seen.add(absolute)
            page.internal_links.append(absolute)

    if url.startswith("https://"):
        for tag, attr in (("script", "src"), ("img", "src"), ("link", "href"), ("iframe", "src")):
            for el in soup.find_all(tag):
                value = el.get(attr) or ""
                if value.startswith("http://") and not (tag == "link" and "stylesheet" not in (el.get("rel") or [])):
                    page.insecure_resources.append(value)
    return page
