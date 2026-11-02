"""Every check in the audit.

Each check is listed once in CHECKS with its area, its scope (page or site),
its weight and a short label. Its function returns a status of pass, fail or
na (does not apply), plus evidence that shows where the problem is.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from .fetch import normalize_url
from .parse import jsonld_of, jsonld_types, words

QUESTION_START = re.compile(
    r"^(what|why|how|when|where|who|which|can|do|does|is|are|should|will|could|would)\b", re.I
)
DATA_POINT = re.compile(
    r"(\$\s?\d[\d,.]*|\d[\d,.]*\s?(%|percent|x\b|times|million|billion|thousand|k\b|hours?|minutes?|days?|weeks?|months?|years?|seconds?|ms\b|users|customers|people|companies)|\b\d{1,3}(,\d{3})+\b)",
    re.I,
)
FAQ_HINT = re.compile(r"\b(faq|faqs|frequently asked|common questions)\b", re.I)


def n_of(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def P(status, **evidence):
    return {"status": status, **evidence}


def bare_host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def is_home(page, ctx) -> bool:
    return normalize_url(page["url"]) in {ctx["home_url"], ctx["start_url"]} or page["path"] in ("", "/")


def is_article(page, ctx) -> bool:
    """Blog posts, guides and other pages where author and dates matter."""
    if page.get("is_article"):
        return True
    hints = ctx["settings"]["article_path_hints"]
    segments = [s for s in page["path"].split("/") if s]
    if len(segments) >= 2 and segments[0] in hints:
        return True
    return page.get("has_article_tag") and bool(page.get("visible_dates"))


def parse_date(value):
    if not value:
        return None
    value = str(value).strip()
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        pass
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y", "%b. %d, %Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def schema_dates(page):
    pub = mod = None
    for o in page["jsonld"]:
        pub = pub or o.get("datePublished")
        mod = mod or o.get("dateModified")
    return pub, mod


def schema_author(page):
    for o in page["jsonld"]:
        a = o.get("author")
        if isinstance(a, list):
            a = a[0] if a else None
        if isinstance(a, dict):
            a = a.get("name")
        if a:
            return str(a)
    return None


# ---------------------------------------------------------------- SEO, page


def seo_indexable(page, ctx):
    if page["status"] != 200:
        return P("fail", current=f"Status {page['status']}")
    if "noindex" in page.get("robots_meta", "") or "noindex" in page.get("x_robots", ""):
        return P("fail", current="The page carries a noindex tag", spot="Page settings (search engine visibility)")
    return P("pass")


def seo_canonical(page, ctx):
    can = page.get("canonical")
    if not can:
        return P("fail", current="No canonical tag", spot="Page SEO settings (canonical URL)")
    if can.rstrip("/") != normalize_url(page["final_url"]).rstrip("/"):
        return P("fail", current=f"Points to {can}", spot="Page SEO settings (canonical URL)")
    return P("pass")


def seo_title_length(page, ctx):
    t = ctx["settings"]["thresholds"]
    title = page.get("title") or ""
    if not title:
        return P("fail", current="(no title)", spot="Page title", length=0)
    if not t["title_min"] <= len(title) <= t["title_max"]:
        return P("fail", current=title, spot="Page title", length=len(title))
    return P("pass")


def seo_title_unique(page, ctx):
    title = page.get("title")
    if not title:
        return P("na")
    others = [u for u in ctx["titles"].get(title.lower(), []) if u != page["url"]]
    if others:
        return P("fail", current=title, spot="Page title", also_on=others[:5])
    return P("pass")


def seo_meta_length(page, ctx):
    t = ctx["settings"]["thresholds"]
    desc = page.get("meta_description") or ""
    if not desc:
        return P("fail", current="(no meta description)", spot="Meta description", length=0)
    if not t["meta_min"] <= len(desc) <= t["meta_max"]:
        return P("fail", current=desc, spot="Meta description", length=len(desc))
    return P("pass")


def seo_meta_unique(page, ctx):
    desc = page.get("meta_description")
    if not desc:
        return P("na")
    others = [u for u in ctx["metas"].get(desc.lower(), []) if u != page["url"]]
    if others:
        return P("fail", current=desc, spot="Meta description", also_on=others[:5])
    return P("pass")


def seo_h1(page, ctx):
    h1s = [h["text"] for h in page["headings"] if h["level"] == 1]
    if len(h1s) != 1:
        return P("fail", current=" | ".join(h1s) if h1s else "(no H1)", count=len(h1s), spot="Main heading (H1)")
    return P("pass")


def seo_heading_order(page, ctx):
    prev = None
    for h in page["headings"]:
        if prev is not None and h["level"] > prev + 1:
            return P("fail", current=f"H{prev} is followed by H{h['level']} “{h['text'][:80]}”", spot="Headings")
        prev = h["level"]
    return P("pass") if page["headings"] else P("na")


def seo_img_alt(page, ctx):
    missing = [i["src"] for i in page["images"] if not i["has_alt"]]
    if not page["images"]:
        return P("na")
    if missing:
        return P("fail", current=f"{len(missing)} of {n_of(len(page['images']), 'image')} {'has' if len(missing) == 1 else 'have'} no alt text", items=missing[:10], spot="Images")
    return P("pass")


def seo_og(page, ctx):
    missing = [k for k, v in page["og"].items() if not v]
    if missing:
        return P("fail", current="Missing og:" + ", og:".join(missing), spot="Social sharing settings")
    return P("pass")


def seo_viewport(page, ctx):
    return P("pass") if page.get("viewport") else P("fail", current="No viewport tag", spot="Site template header")


def seo_lang(page, ctx):
    return P("pass") if page.get("lang") else P("fail", current="No language set", spot="Site template (html tag)")


def seo_words(page, ctx):
    n = page["word_count"]
    if n < ctx["settings"]["thresholds"]["min_words"]:
        return P("fail", current=f"{n} words", count=n, spot="Main content")
    return P("pass")


def seo_internal_links(page, ctx):
    targets = {l["href"] for l in page["links"] if l["internal"] and l["href"] != page["url"]}
    if len(targets) < ctx["settings"]["thresholds"]["min_internal_links"]:
        return P("fail", current=n_of(len(targets), "link") + " to other pages on the site", count=len(targets), spot="Main content")
    return P("pass")


def seo_link_text(page, ctx):
    generic = set(ctx["settings"]["generic_link_text"])
    bad = sorted({l["text"] for l in page["links"] if l["text"].lower().strip(" .!>→") in generic})
    if bad:
        return P("fail", current=", ".join(f"“{b}”" for b in bad[:6]), spot="Link text")
    return P("pass")


def seo_clean_url(page, ctx):
    p = urlparse(page["url"])
    problems = []
    if p.query:
        problems.append("has a ? query")
    if p.path != p.path.lower():
        problems.append("has capital letters")
    if "_" in p.path:
        problems.append("uses underscores")
    if len(page["url"]) > ctx["settings"]["thresholds"]["max_url_length"]:
        problems.append("is long")
    if re.search(r"\.(php|aspx?|html?)$", p.path):
        problems.append("ends in a file extension")
    if problems:
        return P("fail", current=page["url"], problems=problems, spot="Page URL (address)")
    return P("pass")


def seo_no_redirect(page, ctx):
    if page["redirects"]:
        return P("fail", current=f"Redirects to {page['final_url']}", spot="Links that point to this address")
    return P("pass")


def seo_broken_links(page, ctx):
    broken = sorted(
        {
            l["href"]
            for l in page["links"]
            if l["internal"] and (ctx["statuses"].get(l["href"]) or 0) >= 400
        }
    )
    if broken:
        return P("fail", current=n_of(len(broken), "broken link"), items=broken[:10], spot="Links on this page")
    return P("pass")


def seo_not_orphan(page, ctx):
    if is_home(page, ctx):
        return P("na")
    sources = set(ctx["linked_from"].get(page["url"], [])) | set(ctx["linked_from"].get(page["final_url"], []))
    sources.discard(page["url"])
    if not sources:
        return P("fail", current="No other page links here", spot="Site navigation and related pages")
    return P("pass")


def seo_speed(page, ctx):
    e = page.get("elapsed")
    if e is None:
        return P("na")
    if e > ctx["settings"]["thresholds"]["max_response_seconds"]:
        return P("fail", current=f"{e:.2f} seconds", seconds=round(e, 2), spot="Hosting or server")
    return P("pass")


# ---------------------------------------------------------------- SEO, site


def site_robots(site, ctx):
    if site["robots"]["exists"]:
        return P("pass")
    return P("fail", current="No robots.txt found", spot="yoursite/robots.txt")


def site_sitemap(site, ctx):
    if site.get("sitemap", {}).get("url"):
        return P("pass", current=site["sitemap"]["url"])
    return P("fail", current="No XML sitemap found", spot="yoursite/sitemap.xml")


def site_sitemap_lastmod(site, ctx):
    entries = site.get("sitemap", {}).get("entries", {})
    if not entries:
        return P("na")
    missing = [u for u, lm in entries.items() if not lm]
    if len(missing) > 0.1 * len(entries):
        return P("fail", current=f"{len(missing)} of {len(entries)} entries have no lastmod date", items=missing[:5], spot="XML sitemap")
    return P("pass")


def site_sitemap_live(site, ctx):
    sample = site.get("sitemap", {}).get("sample", {})
    if not sample:
        return P("na")
    bad = [u for u, s in sample.items() if s["status"] != 200 or s["redirected"]]
    if bad:
        return P("fail", current=f"{len(bad)} of {len(sample)} checked entries are broken or redirect", items=bad[:10], spot="XML sitemap")
    return P("pass")


# ---------------------------------------------------------------- AEO, page


def aeo_direct_answer(page, ctx):
    t = ctx["settings"]["thresholds"]
    first = next((p for p in page["paragraphs"] if len(words(p)) >= 5), None)
    if not first:
        return P("fail", current="(no opening paragraph)", spot="Opening paragraph")
    n = len(words(first))
    if not t["answer_min_words"] <= n <= t["answer_max_words"]:
        return P("fail", current=first[:600], count=n, spot="Opening paragraph")
    return P("pass")


def aeo_question_headings(page, ctx):
    hs = [h["text"] for h in page["main_headings"] if h["level"] in (2, 3)]
    if not hs:
        return P("fail", current="No H2 or H3 headings", spot="Headings")
    if any(h.endswith("?") or QUESTION_START.match(h) for h in hs):
        return P("pass")
    return P("fail", current=" | ".join(hs[:5]), spot="Headings")


def has_faq_content(page):
    q_heads = [h for h in page["main_headings"] if h["text"].endswith("?")]
    return any(FAQ_HINT.search(h["text"]) for h in page["headings"]) or len(q_heads) >= 3


def aeo_faq_schema(page, ctx):
    if not has_faq_content(page):
        return P("na")
    if "faqpage" in jsonld_types(page):
        return P("pass")
    return P("fail", current="FAQ content with no FAQPage markup", spot="FAQ section")


def aeo_lists(page, ctx):
    if page["word_count"] < 150:
        return P("na")
    return P("pass") if page["has_list_or_table"] else P("fail", current="Text only, no lists or tables", spot="Main content")


def aeo_paragraphs(page, ctx):
    limit = ctx["settings"]["thresholds"]["max_paragraph_words"]
    long_ones = [p for p in page["paragraphs"] if len(words(p)) > limit]
    if long_ones:
        return P("fail", current=long_ones[0][:300] + ("..." if len(long_ones[0]) > 300 else ""), count=len(long_ones), spot="Long paragraphs")
    return P("pass")


def aeo_schema_present(page, ctx):
    if page["jsonld"] or page["has_microdata"]:
        return P("pass")
    return P("fail", current="No structured data", spot="Page code (structured data)")


REQUIRED_PROPS = {
    "organization": ["name"],
    "article": ["headline", "author", "datePublished"],
    "blogposting": ["headline", "author", "datePublished"],
    "newsarticle": ["headline", "author", "datePublished"],
    "faqpage": ["mainEntity"],
    "breadcrumblist": ["itemListElement"],
    "product": ["name"],
    "localbusiness": ["name", "address"],
}


def aeo_schema_valid(page, ctx):
    if not page["jsonld"] and not page["jsonld_errors"]:
        return P("na")
    if page["jsonld_errors"]:
        return P("fail", current=f"{page['jsonld_errors']} structured data block(s) cannot be read", spot="Page code (structured data)")
    for obj in page["jsonld"]:
        types = obj.get("@type")
        types = [types] if isinstance(types, str) else (types or [])
        for t in types:
            missing = [p for p in REQUIRED_PROPS.get(str(t).lower(), []) if not obj.get(p)]
            if missing:
                return P("fail", current=f"{t} is missing {', '.join(missing)}", spot="Page code (structured data)")
    return P("pass")


def aeo_schema_type(page, ctx):
    types = jsonld_types(page)
    if not types:
        return P("na")
    if is_home(page, ctx):
        expected = {"organization", "website", "corporation", "localbusiness"}
        label = "Organization or WebSite"
    elif is_article(page, ctx):
        expected = {"article", "blogposting", "newsarticle", "techarticle"}
        label = "Article or BlogPosting"
    elif has_faq_content(page):
        expected = {"faqpage"}
        label = "FAQPage"
    else:
        return P("pass")
    if types & expected:
        return P("pass")
    return P("fail", current="Has " + ", ".join(sorted(types)), expected=label, spot="Page code (structured data)")


def aeo_breadcrumbs(page, ctx):
    if is_home(page, ctx):
        return P("na")
    if "breadcrumblist" in jsonld_types(page):
        return P("pass")
    return P("fail", current="No breadcrumb markup", spot="Page code (structured data)")


def aeo_raw_html(page, ctx):
    thin = page["raw_word_count"] < ctx["settings"]["thresholds"]["raw_html_min_words"]
    if page["app_shell"] or (thin and page["script_count"] >= 3):
        return P("fail", current=f"{page['raw_word_count']} words in the HTML before scripts run", spot="How the site is built")
    return P("pass")


# ---------------------------------------------------------------- GEO, page


def geo_author_visible(page, ctx):
    if not is_article(page, ctx):
        return P("na")
    if page.get("visible_author"):
        return P("pass", current=page["visible_author"])
    return P("fail", current="No author name on the page", spot="Top of the article")


def geo_author_schema(page, ctx):
    if not is_article(page, ctx):
        return P("na")
    if schema_author(page):
        return P("pass")
    return P("fail", current="No author in structured data", spot="Page code (structured data)")


def geo_dates_visible(page, ctx):
    if not is_article(page, ctx):
        return P("na")
    if page["visible_dates"]:
        return P("pass", current=page["visible_dates"][0])
    return P("fail", current="No date shown on the page", spot="Top of the article")


def geo_dates_schema(page, ctx):
    if not is_article(page, ctx):
        return P("na")
    pub, mod = schema_dates(page)
    if pub and mod:
        return P("pass")
    missing = [n for n, v in (("datePublished", pub), ("dateModified", mod)) if not v]
    return P("fail", current="Missing " + " and ".join(missing), spot="Page code (structured data)")


def page_date(page):
    pub, mod = schema_dates(page)
    for v in (mod, page.get("sitemap_lastmod"), pub, *(page.get("visible_dates") or [])):
        d = parse_date(v)
        if d:
            return d
    return parse_date(page.get("last_modified"))


def geo_fresh(page, ctx):
    d = page_date(page)
    if d is None:
        return P("fail", current="No date found", spot="Article date") if is_article(page, ctx) else P("na")
    months = ctx["settings"]["thresholds"]["freshness_months"]
    age_days = (ctx["now"] - d).days
    if age_days > months * 30.5:
        return P("fail", current=f"Last updated {d.date().isoformat()}", days=age_days, spot="Article content")
    return P("pass")


def geo_sources(page, ctx):
    if page["word_count"] < 300:
        return P("na")
    skip = set(ctx["settings"]["not_outside_sources"]) | ctx["competitor_hosts"]
    hosts = {
        bare_host(l["href"])
        for l in page["main_links"]
        if not l["internal"] and bare_host(l["href"]) not in skip
    }
    if len(hosts) < ctx["settings"]["thresholds"]["min_outside_sources"]:
        return P("fail", current=n_of(len(hosts), "outside source") + " cited", count=len(hosts), spot="Main content")
    return P("pass")


def geo_numbers(page, ctx):
    if page["word_count"] < 150:
        return P("na")
    found = DATA_POINT.findall(page["main_text"])
    if len(found) < ctx["settings"]["thresholds"]["min_data_points"]:
        return P("fail", current=n_of(len(found), "specific number") + " found", spot="Main content")
    return P("pass")


def geo_sections(page, ctx):
    t = ctx["settings"]["thresholds"]
    secs = page["sections"]
    if len(secs) < 2:
        return P("na")
    good = [s for s in secs if t["section_min_words"] <= s["words"] <= t["section_max_words"]]
    if len(good) / len(secs) < t["section_share_in_range"]:
        bad = [s for s in secs if s not in good]
        sample = "; ".join(f"“{s['heading'][:50]}” has {s['words']} words" for s in bad[:3])
        return P("fail", current=sample, spot="Sections under each heading")
    return P("pass")


def geo_summary(page, ctx):
    if page["word_count"] < ctx["settings"]["thresholds"]["summary_block_min_words"]:
        return P("na")
    markers = ctx["settings"]["summary_markers"]
    text = " ".join(h["text"].lower() for h in page["headings"]) + " " + page["main_text"][:400].lower()
    if any(m in text for m in markers):
        return P("pass")
    return P("fail", current="No summary or key takeaways block", spot="Top of the main content")


def geo_no_competitor_links(page, ctx):
    hits = sorted({l["href"] for l in page["links"] if bare_host(l["href"]) in ctx["competitor_hosts"]})
    if hits:
        return P("fail", current=n_of(len(hits), "link") + " to competitor sites", items=hits[:5], spot="Links on this page")
    return P("pass")


# ---------------------------------------------------------------- GEO, site


def site_ai_search(site, ctx):
    robots = site.get("robots_obj")
    if robots is None:
        return P("na")
    home = site["home_url"]
    blocked = [b for b in ctx["settings"]["ai_search_bots"] if not robots.allows(home, b)]
    if blocked:
        return P("fail", current="Blocked " + ", ".join(blocked), spot="robots.txt")
    return P("pass")


def site_ai_training(site, ctx):
    robots = site.get("robots_obj")
    if robots is None:
        return P("na")
    unnamed = [b for b in ctx["settings"]["ai_training_bots"] if not robots.names_agent(b)]
    if unnamed:
        return P("fail", current="No rule for " + ", ".join(unnamed), spot="robots.txt")
    return P("pass")


def site_org_schema(site, ctx):
    home = next((p for p in site["pages"] if is_home(p, ctx) and "jsonld" in p), None)
    if not home:
        return P("na")
    orgs = jsonld_of(home, "Organization", "Corporation", "LocalBusiness")
    if not orgs:
        return P("fail", current="No Organization markup on the homepage", spot="Homepage code (structured data)")
    o = orgs[0]
    missing = [k for k in ("name", "logo", "sameAs") if not o.get(k)]
    if missing:
        return P("fail", current="Organization markup is missing " + ", ".join(missing), spot="Homepage code (structured data)")
    return P("pass")


def site_llms(site, ctx):
    return P("pass") if site.get("llms_txt") else P("fail", current="No llms.txt file", spot="yoursite/llms.txt")


# ---------------------------------------------------------------- the list

H, M, L = "high", "medium", "low"

CHECKS = [
    # id, area, scope, weight, short label, function
    ("seo.indexable", "seo", "page", H, "Loads and can be indexed", seo_indexable),
    ("seo.canonical", "seo", "page", M, "Canonical tag points to itself", seo_canonical),
    ("seo.title_length", "seo", "page", H, "Title is 30 to 60 characters", seo_title_length),
    ("seo.title_unique", "seo", "page", M, "Title is unique", seo_title_unique),
    ("seo.meta_length", "seo", "page", M, "Meta description is 70 to 160 characters", seo_meta_length),
    ("seo.meta_unique", "seo", "page", L, "Meta description is unique", seo_meta_unique),
    ("seo.h1", "seo", "page", M, "One H1", seo_h1),
    ("seo.heading_order", "seo", "page", L, "Headings nest in order", seo_heading_order),
    ("seo.img_alt", "seo", "page", M, "Images have alt text", seo_img_alt),
    ("seo.og", "seo", "page", L, "Open Graph tags are set", seo_og),
    ("seo.viewport", "seo", "page", M, "Viewport is set", seo_viewport),
    ("seo.lang", "seo", "page", L, "Language is set", seo_lang),
    ("seo.words", "seo", "page", M, "At least 300 words", seo_words),
    ("seo.internal_links", "seo", "page", M, "At least 3 internal links", seo_internal_links),
    ("seo.link_text", "seo", "page", L, "Link text is descriptive", seo_link_text),
    ("seo.clean_url", "seo", "page", L, "Clean URL", seo_clean_url),
    ("seo.no_redirect", "seo", "page", M, "No redirect", seo_no_redirect),
    ("seo.broken_links", "seo", "page", H, "No broken internal links", seo_broken_links),
    ("seo.not_orphan", "seo", "page", M, "Other pages link here", seo_not_orphan),
    ("seo.speed", "seo", "page", M, "Server responds in under 1.5 seconds", seo_speed),
    ("seo.robots_txt", "seo", "site", M, "robots.txt exists", site_robots),
    ("seo.sitemap", "seo", "site", H, "XML sitemap exists", site_sitemap),
    ("seo.sitemap_lastmod", "seo", "site", L, "Sitemap has lastmod dates", site_sitemap_lastmod),
    ("seo.sitemap_live", "seo", "site", M, "Sitemap lists only live pages", site_sitemap_live),
    ("aeo.direct_answer", "aeo", "page", H, "Opens with a direct answer", aeo_direct_answer),
    ("aeo.question_headings", "aeo", "page", M, "Some headings are questions", aeo_question_headings),
    ("aeo.faq_schema", "aeo", "page", M, "FAQ content has FAQPage markup", aeo_faq_schema),
    ("aeo.lists", "aeo", "page", L, "Uses lists or tables", aeo_lists),
    ("aeo.paragraphs", "aeo", "page", L, "Paragraphs under 120 words", aeo_paragraphs),
    ("aeo.schema_present", "aeo", "page", H, "Structured data is present", aeo_schema_present),
    ("aeo.schema_valid", "aeo", "page", M, "Structured data is valid", aeo_schema_valid),
    ("aeo.schema_type", "aeo", "page", M, "Structured data is the right type", aeo_schema_type),
    ("aeo.breadcrumbs", "aeo", "page", L, "Breadcrumb markup", aeo_breadcrumbs),
    ("aeo.raw_html", "aeo", "page", H, "Content is in the raw HTML", aeo_raw_html),
    ("geo.author_visible", "geo", "page", M, "Author is visible", geo_author_visible),
    ("geo.author_schema", "geo", "page", L, "Author is in structured data", geo_author_schema),
    ("geo.dates_visible", "geo", "page", M, "Dates are on the page", geo_dates_visible),
    ("geo.dates_schema", "geo", "page", L, "Dates are in structured data", geo_dates_schema),
    ("geo.fresh", "geo", "page", M, "Updated within 12 months", geo_fresh),
    ("geo.sources", "geo", "page", M, "Cites at least 2 outside sources", geo_sources),
    ("geo.numbers", "geo", "page", M, "Includes specific numbers", geo_numbers),
    ("geo.sections", "geo", "page", L, "Sections of 60 to 350 words", geo_sections),
    ("geo.summary", "geo", "page", L, "Summary or key takeaways block", geo_summary),
    ("geo.no_competitor_links", "geo", "page", M, "No links to competitors", geo_no_competitor_links),
    ("geo.ai_search_bots", "geo", "site", H, "AI search crawlers are allowed", site_ai_search),
    ("geo.ai_training_bots", "geo", "site", L, "AI training crawlers have a deliberate rule", site_ai_training),
    ("geo.org_schema", "geo", "site", M, "Organization markup is complete", site_org_schema),
    ("geo.llms_txt", "geo", "site", L, "llms.txt exists", site_llms),
]

CHECK_INDEX = {c[0]: c for c in CHECKS}
