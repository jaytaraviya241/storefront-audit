from storefront_audit.discover import sample_pages
from storefront_audit.page import classify, normalize_url, parse_page
from storefront_audit.platform import detect

HTML = """<html lang="sv"><head><title>  Lira 3 |
  Shop </title><meta name="description" content="Desc"><meta name="robots" content="NOINDEX,follow">
<meta name="viewport" content="width=device-width"><meta property="og:title" content="T">
<link rel="canonical" href="/products/lira-3"><script src="/blocking.js"></script>
<script src="https://x.com/a.js" async></script><script type="module" src="/m.js"></script>
<script type="application/ld+json">{"@type":["Product","Thing"],"offers":{"price":"1"}}</script>
<script type="application/ld+json">{broken</script></head>
<body><h1> Lira  3 </h1><script src="/late.js"></script>
<img src="/a.jpg" alt="A" width="1" height="1" loading="lazy"><img data-src="/b.jpg"><img src="http://insecure.com/c.jpg" alt="">
<a href="/products/lira-3#reviews">same</a><a href="/products/lira-3">dupe</a><a href="https://other.com/">ext</a>
<a href="mailto:x@y.z">m</a><a href="/collections/speakers">c</a></body></html>"""


def test_parse_page_extracts_the_facts():
    p = parse_page("https://shop.example.com/products/lira-3", HTML)
    assert p.kind == "product" and p.title == "Lira 3 | Shop" and p.meta_description == "Desc"
    assert p.robots_meta == "noindex,follow" and p.viewport and p.lang == "sv"
    assert p.h1 == ["Lira 3"] and p.canonical == "https://shop.example.com/products/lira-3"
    assert [(s.src.rsplit("/", 1)[-1], s.in_head, s.deferred) for s in p.scripts] == [
        ("blocking.js", True, False), ("a.js", True, True), ("m.js", True, True), ("late.js", False, False)]
    assert [i.alt for i in p.images] == ["A", None, ""]
    assert [i.has_dimensions for i in p.images] == [True, False, False]
    assert p.internal_links == ["https://shop.example.com/products/lira-3", "https://shop.example.com/collections/speakers"]
    assert p.jsonld_errors == 1 and "Product" in p.schema_types()
    assert p.insecure_resources == ["http://insecure.com/c.jpg"]


def test_classify_and_normalize():
    assert classify("https://s.com/") == "home"
    assert classify("https://s.com/products/x") == "product"
    assert classify("https://s.com/collections/all/products/x") == "product"
    assert classify("https://s.com/collections/all") == "collection"
    assert classify("https://s.com/pages/about") == "page"
    assert normalize_url("https://S.com/a#frag") == "https://s.com/a"


def test_sample_pages_spreads_across_page_types():
    urls = [f"https://s.com/products/p{i}" for i in range(20)] + \
           [f"https://s.com/collections/c{i}" for i in range(20)] + [f"https://s.com/pages/x{i}" for i in range(20)]
    chosen = sample_pages("https://s.com/", urls, [], 10)
    kinds = [classify(u) for u in chosen]
    assert chosen[0] == "https://s.com/" and len(chosen) == 10
    assert kinds.count("product") == 4 and kinds.count("collection") == 3 and kinds.count("page") == 2


def test_detect_shopify_theme_and_apps():
    html = 'cdn.shopify.com Shopify.theme = {"name":"Dawn","id":12};'
    srcs = ["https://cdn.shopify.com/a.js", "https://static.klaviyo.com/k.js",
            "https://www.googletagmanager.com/gtm.js", "https://shop.example.com/own.js"]
    p = detect(html, "https://shop.example.com/", srcs)
    assert p.name == "Shopify" and p.theme == "Dawn"
    assert p.apps == ["Google Tag Manager", "Klaviyo"]
    assert p.third_party_hosts == ["static.klaviyo.com", "www.googletagmanager.com"]


def test_detect_magento():
    assert detect('<script type="text/x-magento-init">Magento_Ui</script>', "https://m.com/", []).name == "Magento"


def test_microdata_product_counts_as_product_schema():
    html = """<html><body><div itemscope itemtype="http://schema.org/Product">
    <span itemprop="name">Toy Box</span><img itemprop="image" src="/box.jpg">
    <div itemprop="offers" itemscope itemtype="http://schema.org/Offer">
    <meta itemprop="price" content="49.00"><link itemprop="availability" href="http://schema.org/InStock"></div>
    </div><div itemscope itemtype="https://schema.org/Organization"></div></body></html>"""
    p = parse_page("https://s.com/products/toy-box", html)
    assert {"Product", "Organization"} <= p.schema_types()
    node = p.schema_nodes("Product")[0]
    assert node["image"] == "/box.jpg" and node["offers"] == {"price": "49.00", "availability": "http://schema.org/InStock"}


def test_commented_out_h1_is_not_counted():
    p = parse_page("https://s.com/collections/all", "<html><body><!-- <h1>Best Sellers</h1> --></body></html>")
    assert p.h1 == []
