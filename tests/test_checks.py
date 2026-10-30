from storefront_audit.checks import SiteContext, run_checks, scores
from storefront_audit.fetch import Response
from storefront_audit.page import Image, PageData, Script
from storefront_audit.platform import Platform


def ctx(pages, **kw):
    responses = {p.url: Response(p.url, p.url, 200, {"strict-transport-security": "max-age=1"}, elapsed=0.2) for p in pages}
    responses.update(kw.pop("responses", {}))
    base = dict(base="https://s.com/", pages=pages, responses=responses, platform=Platform(),
                robots_found=True, sitemap_url="https://s.com/sitemap.xml", sitemap_count=5,
                http_probe=Response("http://s.com/", "https://s.com/", 200))
    base.update(kw)
    return SiteContext(**base)


def good(url="https://s.com/", kind="home"):
    return PageData(url=url, kind=kind, title="A good page title for the shop",
                    meta_description="x" * 100, h1=["Heading"], canonical=url, lang="en", viewport=True,
                    og={"og:title": "t", "og:image": "i"}, jsonld=[{"@type": "Organization"}])


def checks(findings):
    return {f.check: f for f in findings}


def test_clean_site_has_no_findings_and_full_scores():
    found = run_checks(ctx([good()]))
    assert found == []
    assert scores(found)["overall"] == 100


def test_problems_are_reported_with_evidence_and_severity():
    product = good("https://s.com/products/p", "product")
    product.jsonld = []
    product.h1 = []
    product.images = [Image("a", None, False, "")] * 12
    product.scripts = [Script("https://x.com/block.js", True, False)]
    product.title = "Pie"
    noindex = good("https://s.com/pages/n", "page")
    noindex.robots_meta = "noindex"
    slow = Response("https://s.com/pages/n", "https://s.com/pages/n", 200, elapsed=2.4)
    found = checks(run_checks(ctx([good(), product, noindex], responses={noindex.url: slow},
                                  http_probe=Response("http://s.com/", "http://s.com/", 200),
                                  broken_links=[("https://s.com/old", 404, "https://s.com/")])))
    assert found["https_redirect_missing"].severity == "critical"
    assert found["noindex"].evidence == ["https://s.com/pages/n"]
    assert found["product_schema_missing"].severity == "high"
    assert found["h1_missing"].affected == 1
    assert found["img_alt_missing"].severity == "high" and found["img_alt_missing"].affected == 12
    assert "block.js" in found["render_blocking_scripts"].evidence[0]
    assert found["title_length"].evidence == ["https://s.com/products/p (3 chars)"]
    assert "404" in found["broken_links"].evidence[0]
    assert "2.40s" in found["slow_server_response"].evidence[0]
    assert found["lazy_loading"].affected == 1


def test_duplicates_and_incomplete_product_schema():
    a, b = good("https://s.com/products/a", "product"), good("https://s.com/products/b", "product")
    a.jsonld = [{"@type": "Product", "image": "x", "offers": {"price": "1", "availability": "InStock"}}]
    b.jsonld = [{"@type": "Product", "offers": [{"@type": "Offer"}]}]
    found = checks(run_checks(ctx([good(), a, b])))
    assert found["title_duplicate"].affected == 3
    assert found["product_schema_incomplete"].evidence == ["https://s.com/products/b missing image, offers.price, availability"]


def test_findings_sort_critical_first_and_scores_drop():
    page = good()
    page.viewport = False
    found = run_checks(ctx([page], robots_found=False))
    assert found[0].severity == "critical"
    s = scores(found)
    assert s["accessibility"] == 75 and s["technical"] == 95 and s["overall"] < 100


def test_http_errors_are_critical_but_network_failures_are_only_flagged():
    page = good()
    responses = {"https://s.com/gone": Response("https://s.com/gone", "https://s.com/gone", 404),
                 "https://s.com/flaky": Response("https://s.com/flaky", "https://s.com/flaky", 0, error="ConnectionError")}
    found = checks(run_checks(ctx([page], responses=responses)))
    assert found["page_errors"].severity == "critical" and found["page_errors"].evidence == ["https://s.com/gone returned 404"]
    assert found["pages_unreachable"].severity == "medium"
