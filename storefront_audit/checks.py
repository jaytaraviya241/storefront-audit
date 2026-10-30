"""Every check returns findings with evidence: which page, and what was measured."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field

from .fetch import Response
from .page import PageData
from .platform import Platform

CRITICAL, HIGH, MEDIUM = "critical", "high", "medium"
SEVERITY_RANK = {CRITICAL: 0, HIGH: 1, MEDIUM: 2}


@dataclass
class Finding:
    check: str
    severity: str
    category: str            # seo | structured_data | performance | accessibility | technical
    title: str
    why: str
    fix: str
    evidence: list[str] = field(default_factory=list)
    affected: int = 0        # pages or items affected

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SiteContext:
    base: str
    pages: list[PageData]
    responses: dict[str, Response]
    platform: Platform
    robots_found: bool
    sitemap_url: str
    sitemap_count: int
    http_probe: Response | None = None
    broken_links: list[tuple[str, int, str]] = field(default_factory=list)  # (url, status, found on)
    links_checked: int = 0


def _f(findings, check, severity, category, title, why, fix, evidence, affected=None):
    if evidence:
        findings.append(Finding(check, severity, category, title, why, fix, evidence[:8],
                                affected if affected is not None else len(evidence)))


def run_checks(ctx: SiteContext) -> list[Finding]:
    out: list[Finding] = []
    pages = ctx.pages
    home = next((p for p in pages if p.kind == "home"), pages[0] if pages else None)
    products = [p for p in pages if p.kind == "product"]

    # ---------- technical ----------
    if ctx.base.startswith("http://") and ctx.http_probe and not ctx.http_probe.final_url.startswith("https://"):
        _f(out, "https_missing", CRITICAL, "technical", "Site is not served over HTTPS",
           "Browsers label HTTP pages 'Not secure' at checkout, and search engines favour HTTPS.",
           "Install a TLS certificate and redirect every HTTP request to HTTPS.", [ctx.base])
    elif ctx.http_probe is not None and ctx.http_probe.status and not ctx.http_probe.final_url.startswith("https://"):
        _f(out, "https_redirect_missing", CRITICAL, "technical", "HTTP does not redirect to HTTPS",
           "Visitors and links using http:// stay on an insecure, duplicate copy of the site.",
           "Add a permanent (301) redirect from HTTP to HTTPS.", [ctx.http_probe.url])
    home_res = ctx.responses.get(home.url) if home else None
    if home_res and ctx.base.startswith("https://") and "strict-transport-security" not in home_res.headers:
        _f(out, "hsts_missing", MEDIUM, "technical", "No HSTS header",
           "Without HSTS a first visit can be downgraded to HTTP on hostile networks.",
           "Send Strict-Transport-Security with a long max-age.", [home.url])
    if not ctx.robots_found:
        _f(out, "robots_missing", MEDIUM, "technical", "robots.txt is missing",
           "Crawlers get no guidance on what to skip or where the sitemap is.",
           "Publish a robots.txt that lists the sitemap.", [ctx.base.rstrip('/') + "/robots.txt"])
    if not ctx.sitemap_url:
        _f(out, "sitemap_missing", HIGH, "technical", "No XML sitemap found",
           "Search engines discover new products more slowly without a sitemap.",
           "Generate sitemap.xml and reference it from robots.txt and Search Console.", [ctx.base])
    _f(out, "broken_links", HIGH, "technical", "Broken internal links",
       "Dead links waste crawl budget and send shoppers to error pages.",
       "Fix or redirect each link; add redirects when products are removed.",
       [f"{u} returned {s or 'no response'} (linked from {src})" for u, s, src in ctx.broken_links])
    _f(out, "mixed_content", HIGH, "technical", "Insecure (http://) resources on HTTPS pages",
       "Browsers block or warn about insecure scripts and images on secure pages.",
       "Load every resource over HTTPS.",
       [f"{p.url}: {r}" for p in pages for r in p.insecure_resources])
    errors = [f"{u} returned {r.status}" for u, r in ctx.responses.items() if r.status >= 400]
    _f(out, "page_errors", CRITICAL, "technical", "Pages in the sitemap return errors",
       "The store tells search engines these pages exist, but they error out for shoppers and crawlers.",
       "Restore the pages or redirect them and remove them from the sitemap.", errors)
    unreachable = [f"{u} ({r.error or 'no response'})" for u, r in ctx.responses.items()
                   if r.status == 0 and not r.blocked_by_robots]
    _f(out, "pages_unreachable", MEDIUM, "technical", "Pages could not be reached during the audit",
       "The connection failed twice; this can be a temporary network issue or a firewall blocking automated checks.",
       "Re-run the audit; if it repeats, check the hosting and any bot-protection rules.", unreachable)

    # ---------- seo ----------
    _f(out, "title_missing", HIGH, "seo", "Pages without a title",
       "The title is the headline shown in search results.", "Give every page a unique, descriptive <title>.",
       [p.url for p in pages if not p.title])
    _f(out, "title_length", MEDIUM, "seo", "Titles too short or too long",
       "Titles under 15 characters waste the slot; over 70 get cut off in results.",
       "Keep titles roughly 30-60 characters with the product or topic first.",
       [f"{p.url} ({len(p.title)} chars)" for p in pages if p.title and not 15 <= len(p.title) <= 70])
    _f(out, "meta_description_missing", MEDIUM, "seo", "Pages without a meta description",
       "Search engines then improvise a snippet, often from navigation text.",
       "Write a 70-160 character description for each template and key page.",
       [p.url for p in pages if not p.meta_description])
    for attr, check, label in (("title", "title_duplicate", "title"), ("meta_description", "description_duplicate", "meta description")):
        groups = defaultdict(list)
        for p in pages:
            value = getattr(p, attr)
            if value:
                groups[value.strip().lower()].append(p.url)
        dupes = [f"'{k[:60]}' on {len(v)} pages: {', '.join(v[:3])}" for k, v in groups.items() if len(v) > 1]
        _f(out, check, MEDIUM, "seo", f"Duplicate {label}s",
           "Identical snippets make pages compete with each other in search.",
           f"Make each {label} specific to the page.", dupes,
           sum(len(v) for v in groups.values() if len(v) > 1))
    _f(out, "h1_missing", HIGH, "seo", "Pages without an H1 heading",
       "The H1 tells search engines and screen readers what the page is about.",
       "Give each template exactly one H1, normally the product or page name.",
       [p.url for p in pages if not p.h1])
    _f(out, "h1_multiple", MEDIUM, "seo", "Pages with more than one H1",
       "Several H1s blur the page's main topic.", "Keep one H1 and demote the rest to H2/H3.",
       [f"{p.url} ({len(p.h1)} H1s)" for p in pages if len(p.h1) > 1])
    _f(out, "canonical_missing", MEDIUM, "seo", "Pages without a canonical URL",
       "Filtered and tagged URLs can be indexed as duplicates.", "Add a self-referencing canonical link.",
       [p.url for p in pages if not p.canonical])
    noindex = [p.url for p in pages if "noindex" in p.robots_meta
               or "noindex" in ctx.responses.get(p.url, Response(p.url, p.url, 0)).headers.get("x-robots-tag", "").lower()]
    _f(out, "noindex", CRITICAL, "seo", "Important pages are set to noindex",
       "These pages are in the sitemap but tell search engines not to index them.",
       "Remove noindex from pages meant to rank, or drop them from the sitemap.", noindex)
    _f(out, "og_missing", MEDIUM, "seo", "Missing social sharing tags",
       "Links shared on social and messaging apps show no image or a generic title.",
       "Add og:title, og:description and og:image to every template.",
       [p.url for p in pages if not (p.og.get("og:title") and p.og.get("og:image"))])
    _f(out, "lang_missing", MEDIUM, "accessibility", "Missing language attribute",
       "Screen readers and translation tools cannot tell which language the page is in.",
       'Set <html lang="..."> in the theme layout.', [p.url for p in pages if not p.lang])

    # ---------- structured data ----------
    _f(out, "jsonld_invalid", HIGH, "structured_data", "Broken structured data",
       "Search engines ignore JSON-LD that fails to parse.", "Fix the JSON syntax in the theme snippet.",
       [f"{p.url} ({p.jsonld_errors} block(s))" for p in pages if p.jsonld_errors])
    _f(out, "product_schema_missing", HIGH, "structured_data", "Product pages without Product schema",
       "Without it products are not eligible for price and availability in search results.",
       "Output Product JSON-LD with name, image, offers.price, priceCurrency and availability.",
       [p.url for p in products if "Product" not in p.schema_types() and "ProductGroup" not in p.schema_types()])
    incomplete = []
    for p in products:
        for node in p.schema_nodes("Product")[:1]:
            offers = node.get("offers")
            offer = (offers[0] if isinstance(offers, list) and offers else offers) or {}
            if isinstance(offer, dict) and offer.get("@type") == "AggregateOffer":
                price = offer.get("lowPrice") or offer.get("price")
            else:
                price = offer.get("price") if isinstance(offer, dict) else None
            missing = [k for k, ok in (("image", node.get("image")), ("offers.price", price),
                                       ("availability", isinstance(offer, dict) and offer.get("availability"))) if not ok]
            if missing:
                incomplete.append(f"{p.url} missing {', '.join(missing)}")
    _f(out, "product_schema_incomplete", MEDIUM, "structured_data", "Product schema is incomplete",
       "Rich results need price, availability and an image.", "Complete the Product JSON-LD fields.", incomplete)
    if home and not ({"Organization", "WebSite", "OnlineStore", "Store"} & home.schema_types()):
        _f(out, "organization_schema_missing", MEDIUM, "structured_data", "Homepage has no Organization schema",
           "Search engines get no confirmed brand name, logo or social profiles.",
           "Add Organization (and WebSite) JSON-LD to the homepage.", [home.url])

    # ---------- performance ----------
    _f(out, "slow_server_response", HIGH, "performance", "Slow server response",
       "Time to first byte above 1.5 s delays everything else on the page.",
       "Reduce apps and Liquid work on the template; check app proxies and redirects.",
       [f"{u} {r.elapsed:.2f}s" for u, r in ctx.responses.items() if r.ok and r.elapsed > 1.5])
    blocking = []
    for p in pages:
        names = [s.src for s in p.scripts if s.in_head and not s.deferred]
        if names:
            blocking.append(f"{p.url}: {len(names)} blocking script(s), e.g. {names[0]}")
    _f(out, "render_blocking_scripts", HIGH, "performance", "Render-blocking scripts in <head>",
       "The browser stops drawing the page until each one downloads and runs.",
       "Add defer or async, or move the script to the end of the body.", blocking)
    heavy = [f"{p.url} {p.html_bytes // 1024} KB" for p in pages if p.html_bytes > 400 * 1024]
    _f(out, "heavy_html", MEDIUM, "performance", "Very large HTML documents",
       "Large inline JSON and markup slow down parsing on mobile.",
       "Move inline data and unused sections out of the template.", heavy)
    if home and len(ctx.platform.third_party_hosts) > 12:
        _f(out, "many_third_party", MEDIUM, "performance", "Many third-party script hosts",
           "Each extra host adds DNS, connection and script cost on every visit.",
           "Remove apps that are no longer used and consolidate tracking through one tag manager.",
           [f"{len(ctx.platform.third_party_hosts)} hosts: {', '.join(ctx.platform.third_party_hosts[:10])}"], 1)
    no_dims = [p for p in pages if sum(1 for i in p.images if not i.has_dimensions) > 3]
    _f(out, "img_dimensions_missing", MEDIUM, "performance", "Images without width and height",
       "The layout jumps as images load (Cumulative Layout Shift).",
       "Output width and height attributes for every image.",
       [f"{p.url}: {sum(1 for i in p.images if not i.has_dimensions)} of {len(p.images)} images" for p in no_dims],
       sum(sum(1 for i in p.images if not i.has_dimensions) for p in no_dims))
    eager = []
    for p in pages:
        late = [i for i in p.images[4:] if i.loading != "lazy"]
        if len(late) > 5:
            eager.append(f"{p.url}: {len(late)} below-the-fold images load eagerly")
    _f(out, "lazy_loading", MEDIUM, "performance", "Below-the-fold images are not lazy-loaded",
       "Shoppers download images they may never scroll to.",
       'Add loading="lazy" to images after the first screen.', eager)

    # ---------- accessibility ----------
    total = sum(len(p.images) for p in pages)
    no_alt = [(p, [i for i in p.images if i.alt is None]) for p in pages]
    missing = sum(len(x) for _, x in no_alt)
    severity = HIGH if total and missing / total > 0.2 else MEDIUM
    _f(out, "img_alt_missing", severity, "accessibility", "Images without alt text",
       "Screen-reader users hear nothing, and image search has no description to index.",
       "Add descriptive alt text to product and content images; use alt=\"\" only for decoration.",
       [f"{p.url}: {len(x)} of {len(p.images)} images" for p, x in no_alt if x], missing)
    _f(out, "viewport_missing", CRITICAL, "accessibility", "No mobile viewport tag",
       "Phones render the desktop layout zoomed out.", 'Add <meta name="viewport" content="width=device-width, initial-scale=1">.',
       [p.url for p in pages if not p.viewport])

    out.sort(key=lambda f: (SEVERITY_RANK[f.severity], -f.affected, f.check))
    return out


CATEGORY_WEIGHTS = {CRITICAL: 25, HIGH: 12, MEDIUM: 5}
CATEGORIES = ("technical", "seo", "structured_data", "performance", "accessibility")


def scores(findings: list[Finding]) -> dict[str, int]:
    """100 per category minus a fixed penalty per finding; overall is the mean."""
    result = {}
    for cat in CATEGORIES:
        penalty = sum(CATEGORY_WEIGHTS[f.severity] for f in findings if f.category == cat)
        result[cat] = max(0, 100 - penalty)
    result["overall"] = round(sum(result[c] for c in CATEGORIES) / len(CATEGORIES))
    return result
