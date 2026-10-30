import time

from storefront_audit.audit import AuditResult
from storefront_audit.checks import Finding
from storefront_audit.fetch import Fetcher
from storefront_audit.page import PageData
from storefront_audit.platform import Platform
from storefront_audit.report import write_reports


def test_report_escapes_content_taken_from_audited_sites(tmp_path):
    hostile = '<script>alert(1)</script>'
    finding = Finding("title_length", "medium", "seo", "Titles too short", "why", "fix", [f"https://s.com/{hostile}"], 1)
    result = AuditResult("https://s.com/", "now", Platform(name="Shopify", theme=hostile),
                         [PageData(url="https://s.com/", kind="home")], [finding],
                         {"overall": 90, "technical": 90, "seo": 90, "structured_data": 90, "performance": 90,
                          "accessibility": 90}, 1, 0, 1, 0.1)
    html = write_reports(result, tmp_path)["html"].read_text()
    assert hostile not in html and "&lt;script&gt;" in html


def test_robots_txt_blocks_disallowed_pages(fake_store):
    fetcher = Fetcher(delay=0)
    assert fetcher.get(f"{fake_store}/private/admin").blocked_by_robots
    assert fetcher.get(f"{fake_store}/products/good-pie").ok


def test_requests_to_one_host_are_spaced_out(fake_store):
    fetcher = Fetcher(delay=0.2)
    fetcher.get(f"{fake_store}/robots.txt", check_robots=False)
    started = time.monotonic()
    fetcher.get(f"{fake_store}/", check_robots=False)
    fetcher.get(f"{fake_store}/", check_robots=False)
    assert time.monotonic() - started >= 0.35


def test_transient_failures_are_retried_not_reported_as_broken(monkeypatch):
    fetcher = Fetcher(delay=0, retries=1)
    calls = []
    from storefront_audit.fetch import Response

    def flaky(url, method, allow_redirects):
        calls.append(url)
        return Response(url, url, 0, error="ConnectionError") if len(calls) == 1 else Response(url, url, 200)

    monkeypatch.setattr(fetcher, "_request", flaky)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert fetcher.get("https://s.com/", check_robots=False).ok and len(calls) == 2
