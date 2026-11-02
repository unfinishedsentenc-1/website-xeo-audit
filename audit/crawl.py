"""Find and fetch the pages of one site."""

from __future__ import annotations

import gzip
import re
from collections import deque
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .fetch import Fetcher, Robots, normalize_url, same_site
from .parse import parse_page

SKIP_EXTENSIONS = re.compile(
    r"\.(pdf|jpe?g|png|gif|webp|svg|ico|css|js|json|xml|zip|gz|mp4|mp3|mov|avi|docx?|xlsx?|pptx?|woff2?|ttf|eot|rss|atom)$",
    re.I,
)


def read_sitemaps(start: str, robots: Robots, fetcher: Fetcher, limit: int = 2000) -> dict:
    """Read the XML sitemap (and any nested sitemaps). Returns urls with their lastmod dates."""
    listed = [urljoin(start, s) for s in robots.sitemaps()]
    candidates = listed + [u for u in (urljoin(start, "/sitemap.xml"), urljoin(start, "/sitemap_index.xml")) if u not in listed]
    seen, entries, found_any = set(), {}, None
    queue = deque(candidates)
    while queue and len(seen) < 25 and len(entries) < limit:
        sm = queue.popleft()
        if sm in seen:
            continue
        seen.add(sm)
        res = fetcher.get(sm)
        if not res.ok:
            continue
        body = res.text
        if sm.endswith(".gz") and not body.lstrip().startswith("<"):
            try:
                body = gzip.decompress(res.text.encode("latin-1")).decode("utf-8", "replace")
            except OSError:
                continue
        soup = BeautifulSoup(body, "xml")
        if soup.find("sitemapindex"):
            found_any = found_any or sm
            for loc in soup.select("sitemap > loc"):
                queue.append(loc.get_text(strip=True))
        elif soup.find("urlset"):
            found_any = found_any or sm
            for u in soup.find_all("url"):
                loc = u.find("loc")
                if not loc:
                    continue
                lastmod = u.find("lastmod")
                entries[normalize_url(loc.get_text(strip=True))] = (
                    lastmod.get_text(strip=True) if lastmod else None
                )
    return {"url": found_any, "entries": entries}


def crawl_site(start_url: str, settings: dict, max_pages: int, log=print) -> dict:
    fetcher = Fetcher(settings)
    start = normalize_url(start_url if "://" in start_url else f"https://{start_url}")

    home = fetcher.get(start)
    result = {
        "start_url": start,
        "home_url": home.final_url,
        "blocked": None,
        "pages": [],
        "skipped_by_robots": [],
        "statuses": {},
    }
    if home.error or home.status is None:
        result["blocked"] = (
            "The site did not answer. It is down, the address is wrong, or it refuses "
            "connections from cloud computers."
        )
        return result
    if home.blocked:
        result["blocked"] = home.blocked
        return result
    base = home.final_url

    robots = Robots(base, fetcher)
    result["robots"] = {
        "exists": robots.exists,
        "text": robots.text[:20000],
        "status": robots.result.status,
    }
    if not robots.allows(base):
        result["blocked"] = "The site's robots.txt asks crawlers like ours to stay out, so we did not crawl it."
        result["robots_obj"] = robots
        return result

    sitemap = read_sitemaps(base, robots, fetcher)
    result["sitemap"] = {"url": sitemap["url"], "entries": sitemap["entries"]}

    skip_query = settings["crawl"]["skip_urls_with_query_strings"]
    queue = deque([base])
    queued = {base, start}
    linked_from: dict[str, set] = {}

    def enqueue(url: str):
        if url in queued or not same_site(url, base):
            return
        p = urlparse(url)
        if SKIP_EXTENSIONS.search(p.path) or (skip_query and p.query):
            return
        queued.add(url)
        queue.append(url)

    sitemap_urls = list(sitemap["entries"].keys())
    used_sitemap = False
    blocked_in_a_row = 0

    while len(result["pages"]) < max_pages:
        if not queue:
            if used_sitemap:
                break
            used_sitemap = True
            for u in sitemap_urls:
                enqueue(u)
            if not queue:
                break
        url = queue.popleft()
        if not robots.allows(url):
            result["skipped_by_robots"].append(url)
            continue
        res = home if url == base and not result["pages"] else fetcher.get(url)
        result["statuses"][url] = res.status
        if res.final_url != url:
            result["statuses"][res.final_url] = res.status
        if res.blocked:
            blocked_in_a_row += 1
            if blocked_in_a_row >= 5:
                result["blocked_partway"] = res.blocked
                break
            continue
        blocked_in_a_row = 0
        if res.status is None or not res.ok or not res.is_html or not res.text:
            # Missing and broken pages are reported as broken links, not scored as pages.
            continue
        if res.final_url != url and (res.final_url in queued and res.final_url != url):
            # A redirect to a page we already have. Keep the record, skip the duplicate.
            pass
        page = {
            "url": url,
            "final_url": res.final_url,
            "status": res.status,
            "elapsed": res.elapsed,
            "redirects": res.redirects,
            "x_robots": res.headers.get("x-robots-tag", "").lower(),
            "last_modified": res.headers.get("last-modified"),
            "in_sitemap": url in sitemap["entries"],
            "sitemap_lastmod": sitemap["entries"].get(url),
            "robots_allowed": True,
        }
        if res.ok:
            page.update(parse_page(res.final_url, res.text))
            for link in page["links"]:
                if link["internal"]:
                    linked_from.setdefault(link["href"], set()).add(url)
                    enqueue(link["href"])
        result["pages"].append(page)
        log(f"  {len(result['pages']):>3}  {res.status}  {urlparse(url).path or '/'}")

    # Check internal link targets we did not crawl, so broken links are found.
    crawled = {p["url"] for p in result["pages"]} | {p["final_url"] for p in result["pages"]}
    unchecked = [u for u in linked_from if u not in result["statuses"] and u not in crawled]
    for u in unchecked[:150]:
        if not robots.allows(u):
            continue
        res = fetcher.get(u, method="HEAD")
        if res.status in (405, 501) or res.status is None:
            res = fetcher.get(u)
        result["statuses"][u] = res.status

    # Sample sitemap entries to see whether they are live pages.
    sample_size = settings["thresholds"]["sitemap_sample_size"]
    sample = {}
    for u in sitemap_urls[:sample_size]:
        if u in result["statuses"]:
            page = next((p for p in result["pages"] if p["url"] == u), None)
            sample[u] = {"status": result["statuses"][u], "redirected": bool(page and page["redirects"])}
        elif robots.allows(u):
            res = fetcher.get(u, method="HEAD")
            if res.status in (405, 501) or res.status is None:
                res = fetcher.get(u)
            sample[u] = {"status": res.status, "redirected": bool(res.redirects)}
    result["sitemap"]["sample"] = sample

    result["linked_from"] = {k: sorted(v) for k, v in linked_from.items()}

    llms = fetcher.get(urljoin(base, "/llms.txt"))
    result["llms_txt"] = bool(llms.ok and llms.text.strip() and "<html" not in llms.text[:500].lower())
    result["robots_obj"] = robots
    return result
