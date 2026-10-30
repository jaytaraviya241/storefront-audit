"""Command line: `storefront-audit site URL` or `storefront-audit batch FILE`."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .audit import audit_site
from .fetch import Fetcher
from .report import write_portfolio, write_reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="storefront-audit", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("site", "batch"):
        p = sub.add_parser(name)
        p.add_argument("target", help="store URL" if name == "site" else "text file with one URL per line")
        p.add_argument("--out", default="audits")
        p.add_argument("--max-pages", type=int, default=15)
        p.add_argument("--link-limit", type=int, default=30)
        p.add_argument("--delay", type=float, default=0.5, help="seconds between requests to one host")
        p.add_argument("--prepared-by", default="")
        p.add_argument("--fail-on", choices=["critical", "high", "never"], default="never",
                       help="exit 1 when a finding of this severity or worse exists")
        if name == "batch":
            p.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)

    if args.command == "site":
        urls = [args.target]
    else:
        path = Path(args.target)
        if not path.exists():
            print(f"error: {path} not found", file=sys.stderr)
            return 2
        urls = [u.strip() for u in path.read_text().splitlines() if u.strip() and not u.startswith("#")]

    def one(url):
        result = audit_site(url, args.max_pages, args.link_limit, Fetcher(delay=args.delay))
        write_reports(result, args.out, args.prepared_by)
        c = result.counts
        status = result.error or f"score {result.scores['overall']}, {c['critical']} critical, {c['high']} high, {c['medium']} medium, {len(result.pages)} pages, {result.seconds}s"
        print(f"{result.site}: {status}", flush=True)
        return result

    workers = getattr(args, "workers", 1)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(one, urls))
    if args.command == "batch":
        print(f"summary: {write_portfolio(results, args.out)}")

    if any(r.error for r in results) and len(results) == 1:
        return 2
    levels = {"critical": ("critical",), "high": ("critical", "high"), "never": ()}[args.fail_on]
    return 1 if any(f.severity in levels for r in results for f in r.findings) else 0


if __name__ == "__main__":
    sys.exit(main())
