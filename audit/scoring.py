"""Scores from 0 to 100.

Page score for an area = points earned / points possible on that page.
Each check is worth its weight (high 3, medium 2, low 1). Checks that do not
apply to a page are left out.

Area score for the site = 80 percent the average page score plus 20 percent
the site-level score. An area with no site-level checks uses page scores only.

Overall score = the average of the three area scores.
"""

from __future__ import annotations

from .checks import CHECKS

AREAS = ("seo", "aeo", "geo")


def _score(results: dict, scope: str, area: str, weights: dict) -> float | None:
    earned = possible = 0
    for check_id, a, s, level, _, _ in CHECKS:
        if a != area or s != scope:
            continue
        r = results.get(check_id)
        if not r or r["status"] == "na":
            continue
        w = weights[level]
        possible += w
        if r["status"] == "pass":
            earned += w
    return round(100 * earned / possible, 1) if possible else None


def score_page(page: dict, settings: dict) -> dict:
    weights = settings["scoring"]["weights"]
    scores = {a: _score(page["checks"], "page", a, weights) for a in AREAS}
    vals = [v for v in scores.values() if v is not None]
    scores["overall"] = round(sum(vals) / len(vals), 1) if vals else None
    return scores


def score_site(site: dict, settings: dict) -> dict:
    weights = settings["scoring"]["weights"]
    share = settings["scoring"]["site_level_share"]
    pages = [p for p in site["pages"] if p.get("scores")]
    out = {}
    for a in AREAS:
        page_vals = [p["scores"][a] for p in pages if p["scores"][a] is not None]
        page_avg = sum(page_vals) / len(page_vals) if page_vals else None
        site_val = _score(site["site_checks"], "site", a, weights)
        if page_avg is None:
            out[a] = site_val
        elif site_val is None:
            out[a] = round(page_avg, 1)
        else:
            out[a] = round((1 - share) * page_avg + share * site_val, 1)
        out[f"{a}_pages"] = round(page_avg, 1) if page_avg is not None else None
        out[f"{a}_site"] = site_val
    vals = [out[a] for a in AREAS if out[a] is not None]
    out["overall"] = round(sum(vals) / len(vals), 1) if vals else None
    return out


def pass_rates(site: dict) -> dict:
    """Share of applicable pages that pass each page-level check. Used for competitor comparisons."""
    rates = {}
    for check_id, _, scope, _, _, _ in CHECKS:
        if scope != "page":
            continue
        statuses = [p["checks"][check_id]["status"] for p in site["pages"] if check_id in p.get("checks", {})]
        applicable = [s for s in statuses if s != "na"]
        rates[check_id] = round(sum(s == "pass" for s in applicable) / len(applicable), 3) if applicable else None
    for check_id, r in site.get("site_checks", {}).items():
        rates[check_id] = None if r["status"] == "na" else (1.0 if r["status"] == "pass" else 0.0)
    return rates
