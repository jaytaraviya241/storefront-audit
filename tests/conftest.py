"""A tiny fake store served on localhost, with known problems planted in it."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

PRODUCT_SCHEMA = """<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Good Pie","image":"/img/pie.jpg",
 "offers":{"@type":"Offer","price":"12.00","priceCurrency":"USD","availability":"https://schema.org/InStock"}}
</script>"""


def page(title, body, head="", lang='lang="en"', desc="A perfectly reasonable description for this page of the store."):
    meta = f'<meta name="description" content="{desc}">' if desc else ""
    return f"""<!doctype html><html {lang}><head><title>{title}</title>{meta}
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta property="og:title" content="{title}"><meta property="og:image" content="/og.jpg">
<link rel="canonical" href="/">{head}</head><body>{body}</body></html>"""


def routes(base):
    return {
        "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private\nSitemap: " + base + "/sitemap.xml\n"),
        "/sitemap.xml": ("application/xml", f"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>{base}/sitemap_products.xml</loc></sitemap><sitemap><loc>{base}/sitemap_pages.xml</loc></sitemap></sitemapindex>"""),
        "/sitemap_products.xml": ("application/xml", f"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
<url><loc>{base}/products/good-pie</loc><image:image><image:loc>https://cdn.example.com/pie.jpg</image:loc></image:image></url>
<url><loc>{base}/products/bad-pie</loc></url><url><loc>{base}/collections/all</loc></url></urlset>"""),
        "/sitemap_pages.xml": ("application/xml", f"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{base}/pages/about</loc></url><url><loc>{base}/pages/hidden</loc></url><url><loc>https://other.example.com/x</loc></url></urlset>"""),
        "/": ("text/html", page("Fake Pies | Fresh pies delivered", """<h1>Fake Pies</h1>
<a href="/products/good-pie">Good</a><a href="/pages/gone">Old page</a><a href="/private/admin">Admin</a>
<a href="/cart">Cart</a><img src="/hero.jpg" alt="Pies" width="10" height="10">""",
            head='<script type="application/ld+json">{"@type":"Organization","name":"Fake Pies"}</script>'
                 '<script src="https://cdn.shopify.com/s/x.js" defer></script>'
                 '<script src="https://static.klaviyo.com/onsite.js" async></script>'
                 '<script>var Shopify = Shopify || {}; Shopify.theme = {"name":"Dawn","id":1};</script>')),
        "/products/good-pie": ("text/html", page("Good Pie | Fake Pies", "<h1>Good Pie</h1>", head=PRODUCT_SCHEMA)),
        "/products/bad-pie": ("text/html", page("Bad Pie | Fake Pies", """<h1>Bad Pie</h1><h1>Again</h1>
<img src="/a.jpg"><img src="/b.jpg"><img src="/c.jpg" alt="">""",
            head='<script src="https://widgets.example-reviews.com/w.js"></script>'
                 '<script type="application/ld+json">{"@type": "Product", oops}</script>', desc="")),
        "/collections/all": ("text/html", page("All", "<h1>All pies</h1>")),
        "/pages/about": ("text/html", page("About us | Fake Pies", "<h1>About</h1>", lang="")),
        "/pages/hidden": ("text/html", page("Hidden | Fake Pies", "<h1>Hidden</h1>", head='<meta name="robots" content="noindex">')),
        "/private/admin": ("text/html", page("Admin", "<h1>Admin</h1>")),
    }


@pytest.fixture(scope="session")
def fake_store():
    holder = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = holder["routes"].get(self.path.split("?")[0])
            if route is None:
                self.send_response(404)
                self.end_headers()
                return
            ctype, body = route
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_HEAD(self):
            route = holder["routes"].get(self.path)
            self.send_response(200 if route else 404)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    holder["routes"] = routes(base)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield base
    server.shutdown()
