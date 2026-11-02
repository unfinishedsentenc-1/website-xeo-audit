"""Run one audit from the command line.

    python -m audit.run --site example.com --brand "Example" \
        --competitor rival-one.com --competitor rival-two.com \
        --out results/audit.json

The output is one JSON file with every page, every check, the scores and
the fix list. The dashboard reads this file.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .checks import CHECKS
from .crawl import crawl_site
from .fetch import normalize_url
from .fixes import build_issues
from .scoring import pass_rates, score_page, score_site

ROOT = Path(__file__).resolve().parent.parent
BLOCK_ADVICE = [
    "Open the site in your own browser to confirm it loads.",
    "Some sites block cloud computers like the one this audit runs on. Run the audit from your own computer to compare.",
    "If the site is yours, ask your developer to allow the crawler named in Setup.",
]


def load_settings(path: str | None = None) -> dict:
    with open(path or ROOT / "config" / "settings.json") as f:
        return json.load(f)


def bare(url: str) -> str:
    h = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def audit_site(url: str, brand: str, settings: dict, max_pages: int, competitor_hosts: set, now, log=print) -> dict:
    log(f"Crawling {url}")
    site = crawl_site(url, settings, max_pages, log=log)
    site["brand"] = brand
    site["site_checks"] = {}
    if site["blocked"] and not site["pages"]:
        site["block_advice"] = BLOCK_ADVICE
        site.pop("robots_obj", None)
        site["scores"] = {}
        site["issues"] = []
        return site

    titles, metas = defaultdict(list), defaultdict(list)
    for p in site["pages"]:
        if p.get("title"):
            titles[p["title"].lower()].append(p["url"])
        if p.get("meta_description"):
            metas[p["meta_description"].lower()].append(p["url"])

    ctx = {
        "settings": settings,
        "titles": titles,
        "metas": metas,
        "linked_from": site.get("linked_from", {}),
        "statuses": site["statuses"],
        "home_url": normalize_url(site["home_url"]),
        "start_url": site["start_url"],
        "competitor_hosts": competitor_hosts - {bare(url)},
        "now": now,
    }

    for p in site["pages"]:
        p["checks"] = {}
        if "headings" not in p:  # page did not load; only the load check applies
            p["checks"]["seo.indexable"] = {"status": "fail", "current": f"Status {p['status']}"}
            p["scores"] = score_page(p, settings)
            continue
        for check_id, _, scope, _, _, fn in CHECKS:
            if scope == "page":
                p["checks"][check_id] = fn(p, ctx)
        p["scores"] = score_page(p, settings)

    for check_id, _, scope, _, _, fn in CHECKS:
        if scope == "site":
            site["site_checks"][check_id] = fn(site, ctx)

    site["scores"] = score_site(site, settings)
    site["pass_rates"] = pass_rates(site)
    site["issues"] = build_issues(site, brand, settings)
    site.pop("robots_obj", None)

    # Trim heavy fields the dashboard does not need.
    for p in site["pages"]:
        for k in ("main_text", "paragraphs", "links", "main_links", "images", "jsonld"):
            if k in p:
                p[f"{k}_count"] = len(p[k]) if isinstance(p[k], list) else None
                if k in ("paragraphs",):
                    p["opening"] = p[k][0][:600] if p[k] else None
                p.pop(k)
    site.pop("linked_from", None)
    site.pop("statuses", None)
    return site


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Audit a site and its competitors.")
    ap.add_argument("--site", required=True)
    ap.add_argument("--brand", required=True)
    ap.add_argument("--competitor", action="append", default=[])
    ap.add_argument("--out", default="results/audit.json")
    ap.add_argument("--settings")
    ap.add_argument("--max-pages", type=int)
    ap.add_argument("--quiet", action="store_true", help="Do not print page addresses (for public logs).")
    args = ap.parse_args(argv)

    settings = load_settings(args.settings)
    now = datetime.now(timezone.utc)
    competitors = args.competitor[:5]
    competitor_hosts = {bare(c) for c in competitors}
    log = (lambda *_: None) if args.quiet else print

    own_max = args.max_pages or settings["crawl"]["max_pages_own_site"]
    comp_max = min(args.max_pages or settings["crawl"]["max_pages_competitor"], settings["crawl"]["max_pages_competitor"])

    result = {
        "audit_date": now.date().isoformat(),
        "generated_at": now.isoformat(timespec="seconds"),
        "brand": args.brand,
        "site": audit_site(args.site, args.brand, settings, own_max, competitor_hosts, now, log),
        "competitors": [
            audit_site(c, bare(c), settings, comp_max, competitor_hosts | {bare(args.site)}, now, log)
            for c in competitors
        ],
        "checks": [
            {"id": c[0], "area": c[1], "scope": c[2], "weight": settings["scoring"]["weights"][c[3]], "label": c[4]}
            for c in CHECKS
        ],
        "settings": settings,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str))
    s = result["site"].get("scores", {})
    print(f"Done. {len(result['site']['pages'])} pages. Overall {s.get('overall')}, SEO {s.get('seo')}, AEO {s.get('aeo')}, GEO {s.get('geo')}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
