# storefront-audit

Evidence-based technical, SEO and performance audits for **Shopify** and other ecommerce storefronts. Run one store, or a whole client list in parallel, and get a client-ready HTML report, an issue CSV and JSON.

Agencies and freelancers produce these audits by hand, page by page, before a sales call or a theme release. `storefront-audit` samples the store the way a crawler sees it and reports only what it measured. Every finding names the page and shows the evidence.

```
store URL ─► robots.txt + sitemap ─► sample home / products / collections / pages ─► parse ─► 32 checks ─► score ─► HTML · CSV · JSON
                                                                         └─► check internal links ─┘
```

## Tested on live stores

Run against 20 live Shopify storefronts in one batch:

| | |
|---|---|
| Pages audited | 274 |
| Internal links checked | 380 |
| HTTP requests | 860, at most 2 per second per store |
| Wall time | under 2 minutes for all 20 (10 workers) |
| Findings | 119: 1 critical, 26 high, 92 medium |

Findings were spot-checked against the live pages. That uncovered two false positives, both fixed and now covered by tests:
- Product schema written as microdata was being missed.
- A dropped connection was being reported as a broken page.

Spot-checking also confirmed less obvious findings, such as a theme whose H1 is inside an HTML comment, and a sitemap that lists a page returning 404.

See [`examples/sample-report.html`](examples/sample-report.html) for the report format (generated from the test store, not a real client).

## What it checks

| Area | Checks |
|---|---|
| Technical | HTTPS and HTTP→HTTPS redirect, HSTS, robots.txt, XML sitemap, sitemap pages returning errors, broken internal links, mixed content, unreachable pages |
| SEO | missing, short, long and duplicate titles; missing and duplicate meta descriptions; missing or multiple H1; canonical; accidental `noindex`; Open Graph tags |
| Structured data | invalid JSON-LD; Product schema on product pages (JSON-LD or microdata) with price, availability and image; Organization schema on the homepage |
| Performance | server response time, render-blocking scripts in `<head>`, very large HTML, third-party script hosts, images without width/height, eager below-the-fold images |
| Accessibility | images without alt text (`alt=""` is accepted as decorative), language attribute, mobile viewport |

It also detects the platform (Shopify, Magento, WooCommerce, BigCommerce), the Shopify theme name, and recognisable third-party tools such as Klaviyo, Judge.me, Recharge, Meta Pixel and Google Tag Manager.

Each finding has a severity that maps to an action plan: **critical** (fix now), **high** (fix next), **medium** (improve). Category scores start at 100 and drop by a fixed amount per finding, so a score is always explainable.

## Polite by design

- Honours `robots.txt` for its own user agent, and never fetches cart, checkout, account or search pages.
- Identifies itself (`storefront-audit/0.1.0 (+repo URL)`) and rate-limits per host (`--delay`, default 0.5 s).
- Retries a dropped connection or `429`/`5xx` once, honouring `Retry-After`, before reporting anything.
- Reads public pages only; no logins, no form submissions.

## Quick start

```bash
pip install -e ".[dev]"

storefront-audit site https://example-store.com --prepared-by "Your Agency"
storefront-audit batch clients.txt --workers 8 --out audits/
```

`clients.txt` holds one URL per line (`#` for comments). A batch run writes one report per store plus `PORTFOLIO.md`, which ranks stores by score and lists the most common findings across all of them.

| Option | Default | |
|---|---|---|
| `--max-pages` | 15 | pages sampled per store (spread across products, collections and content) |
| `--link-limit` | 30 | internal links checked per store |
| `--delay` | 0.5 | seconds between requests to one host |
| `--fail-on` | never | `critical` or `high`: exit 1 when such a finding exists, for CI or a pre-launch gate |

Exit codes: `0` done, `1` a finding at the `--fail-on` level, `2` the site or input file could not be read.

## Use in a release pipeline

```yaml
# block a theme deploy that introduces critical issues on the preview store
- run: storefront-audit site "$PREVIEW_URL" --fail-on critical --out audit/
```

## Project layout

```
storefront_audit/
  fetch.py      robots-aware, rate-limited HTTP client with retry
  discover.py   sitemap index parsing and page sampling
  page.py       HTML parsing: meta, headings, images, scripts, JSON-LD and microdata
  platform.py   platform, theme and app detection
  checks.py     the checks and scoring
  audit.py      one end-to-end audit
  report.py     HTML, CSV, JSON and portfolio summary
  cli.py        command line
tests/          20 tests, including a full audit of a fake store served on localhost
```

## License

MIT
