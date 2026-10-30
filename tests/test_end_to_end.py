import json

from storefront_audit.audit import audit_site
from storefront_audit.cli import main
from storefront_audit.fetch import Fetcher
from storefront_audit.report import write_portfolio, write_reports


def audit(base):
    return audit_site(base, max_pages=10, link_limit=20, fetcher=Fetcher(delay=0))


def test_full_audit_finds_every_planted_problem(fake_store):
    r = audit(fake_store)
    checks = {f.check: f for f in r.findings}
    urls = {p.url for p in r.pages}

    assert r.platform.name == "Shopify" and r.platform.theme == "Dawn" and r.platform.apps == ["Klaviyo"]
    assert r.sitemap_count == 5                            # image:loc and other-host URLs excluded
    assert f"{fake_store}/private/admin" not in urls       # robots.txt honoured
    assert checks["https_missing"].severity == "critical"
    assert checks["noindex"].evidence == [f"{fake_store}/pages/hidden"]
    assert checks["broken_links"].evidence[0].startswith(f"{fake_store}/pages/gone returned 404")
    assert checks["jsonld_invalid"].evidence == [f"{fake_store}/products/bad-pie (1 block(s))"]
    assert f"{fake_store}/products/bad-pie" in checks["product_schema_missing"].evidence
    assert checks["h1_multiple"].affected == 1
    assert checks["img_alt_missing"].affected == 2          # alt="" is valid for decoration
    assert checks["render_blocking_scripts"].affected == 1
    assert checks["lang_missing"].evidence == [f"{fake_store}/pages/about"]
    assert checks["meta_description_missing"].evidence == [f"{fake_store}/products/bad-pie"]
    assert checks["title_length"].evidence == [f"{fake_store}/collections/all (3 chars)"]
    assert "organization_schema_missing" not in checks
    assert "product_schema_incomplete" not in checks      # the good product is complete
    severities = [f.severity for f in r.findings]
    assert severities == sorted(severities, key=["critical", "high", "medium"].index)


def test_reports_are_written(tmp_path, fake_store):
    r = audit(fake_store)
    files = write_reports(r, tmp_path, prepared_by="Webseek Infotech")
    html = files["html"].read_text()
    assert "Storefront audit" in html and "Prepared by Webseek Infotech" in html and "Fix now" in html
    data = json.loads(files["json"].read_text())
    assert data["counts"]["critical"] >= 2 and data["platform"] == "Shopify"
    assert files["csv"].read_text().splitlines()[0] == "severity,category,check,title,affected,evidence"
    summary = write_portfolio([r], tmp_path).read_text()
    assert "1 of 1 sites audited" in summary and "Most common findings" in summary


def test_unreachable_site_is_reported_not_raised(tmp_path):
    r = audit_site("http://127.0.0.1:9", fetcher=Fetcher(delay=0, timeout=2, retries=0))
    assert r.error and r.pages == []
    assert "html" not in write_reports(r, tmp_path)


def test_cli_batch_and_exit_codes(tmp_path, fake_store, capsys):
    sites = tmp_path / "sites.txt"
    sites.write_text(f"# portfolio\n{fake_store}\n")
    assert main(["batch", str(sites), "--out", str(tmp_path / "o"), "--delay", "0"]) == 0
    assert main(["batch", str(sites), "--out", str(tmp_path / "o"), "--delay", "0", "--fail-on", "critical"]) == 1
    assert main(["batch", str(tmp_path / "missing.txt")]) == 2
    assert (tmp_path / "o" / "PORTFOLIO.md").exists()
    assert "score" in capsys.readouterr().out
