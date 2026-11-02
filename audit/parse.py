"""Turn raw HTML into the facts the checks need."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .fetch import normalize_url, same_site

WORD_RE = re.compile(r"[A-Za-z0-9À-ɏ][\w'’-]*")
NOISE_TAGS = ("script", "style", "noscript", "template", "svg", "iframe")
CHROME_TAGS = ("nav", "header", "footer", "aside", "form")
ARTICLE_TYPES = {"article", "blogposting", "newsarticle", "techarticle", "report", "scholarlyarticle"}


def words(text: str) -> list[str]:
    return WORD_RE.findall(text or "")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _types(obj) -> list[str]:
    t = obj.get("@type", []) if isinstance(obj, dict) else []
    if isinstance(t, str):
        t = [t]
    return [str(x).lower() for x in t if x]


def flatten_jsonld(data) -> list[dict]:
    """Return every typed object in a JSON-LD block, including nested @graph items."""
    out = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if "@type" in node:
                out.append(node)
            for key, value in node.items():
                if key == "@graph" or isinstance(value, (dict, list)):
                    walk(value)

    walk(data)
    return out


def parse_page(url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    head = soup.head or soup

    def meta(name=None, prop=None):
        tag = None
        if name:
            tag = head.find("meta", attrs={"name": re.compile(f"^{re.escape(name)}$", re.I)})
        if tag is None and prop:
            tag = head.find("meta", attrs={"property": re.compile(f"^{re.escape(prop)}$", re.I)})
        return clean(tag.get("content", "")) if tag else None

    title_tag = soup.find("title")
    canonical_tag = soup.find("link", rel=lambda v: v and "canonical" in [r.lower() for r in (v if isinstance(v, list) else [v])])
    html_tag = soup.find("html")

    # Structured data (JSON-LD).
    jsonld_blocks, jsonld_errors = [], 0
    for tag in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        try:
            jsonld_blocks.append(json.loads(raw))
        except (ValueError, TypeError):
            jsonld_errors += 1
    jsonld = [obj for block in jsonld_blocks for obj in flatten_jsonld(block)]
    has_microdata = bool(soup.find(attrs={"itemtype": True}))

    # Raw text before any cleanup, to judge how much is in the HTML itself.
    raw_soup = BeautifulSoup(html, "lxml")
    for t in raw_soup(NOISE_TAGS):
        t.decompose()
    raw_word_count = len(words(raw_soup.get_text(" ")))

    # Images.
    images = []
    for img in soup.find_all("img"):
        images.append(
            {
                "src": urljoin(url, img.get("src") or img.get("data-src") or ""),
                "has_alt": img.has_attr("alt"),
                "alt": clean(img.get("alt", "")),
            }
        )

    # Links (whole page, so nav links count toward orphan checks).
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue
        absolute = normalize_url(urljoin(url, href))
        if urlparse(absolute).scheme not in ("http", "https"):
            continue
        text = clean(a.get_text(" ")) or clean(a.get("aria-label", "")) or clean(
            (a.find("img") or {}).get("alt", "") if a.find("img") else ""
        )
        links.append(
            {
                "href": absolute,
                "text": text,
                "internal": same_site(absolute, url),
                "rel": [r.lower() for r in (a.get("rel") or [])],
            }
        )

    # Main content. Prefer <main>, then <article>, then the body without site chrome.
    work = BeautifulSoup(html, "lxml")
    for t in work(NOISE_TAGS):
        t.decompose()
    main = work.find("main") or work.find(attrs={"role": "main"}) or work.find("article")
    if main is None:
        main = work.body or work
        for t in main(CHROME_TAGS):
            t.decompose()
    main_text = clean(main.get_text(" "))

    headings = [
        {"level": int(h.name[1]), "text": clean(h.get_text(" "))}
        for h in work.find_all(re.compile("^h[1-6]$"))
    ]
    main_headings = [
        {"level": int(h.name[1]), "text": clean(h.get_text(" "))}
        for h in main.find_all(re.compile("^h[1-6]$"))
    ]

    meta_class = re.compile(r"(byline|author|meta|date|breadcrumb|caption|eyebrow|kicker)", re.I)

    def is_meta_line(tag) -> bool:
        for node in [tag, *tag.parents]:
            if node is main:
                break
            if meta_class.search(" ".join(node.get("class", []) or [])):
                return True
        return bool(re.match(r"^(by|posted|published|updated|written by)\b", clean(tag.get_text(" ")), re.I))

    paragraphs = [clean(p.get_text(" ")) for p in main.find_all("p") if not is_meta_line(p)]
    paragraphs = [p for p in paragraphs if p]

    # Sections, meaning the words between one H2 or H3 and the next.
    sections, current = [], {"heading": None, "words": 0}
    for node in main.descendants:
        name = getattr(node, "name", None)
        if name in ("h2", "h3"):
            if current["heading"] is not None or current["words"]:
                sections.append(current)
            current = {"heading": clean(node.get_text(" ")), "words": 0}
        elif name is None and node.parent is not None and node.parent.name not in ("h2", "h3"):
            parent_names = {p.name for p in node.parents}
            if not parent_names & {"h2", "h3"}:
                current["words"] += len(words(str(node)))
    sections.append(current)
    sections = [s for s in sections if s["heading"] is not None]

    # Main-content links, for the outside-source check.
    main_links = []
    for a in main.find_all("a", href=True):
        absolute = normalize_url(urljoin(url, a["href"].strip()))
        if urlparse(absolute).scheme in ("http", "https"):
            main_links.append({"href": absolute, "internal": same_site(absolute, url)})

    # Author and date signals that a reader can see.
    visible_author = None
    for sel in (
        {"rel": "author"},
        {"itemprop": "author"},
        {"class": re.compile(r"(^|[-_ ])(author|byline)([-_ ]|$)", re.I)},
    ):
        tag = soup.find(attrs=sel)
        if tag and clean(tag.get_text(" ")):
            visible_author = re.split(r",|\||\u00b7| on ", re.sub(r"^\s*(by|written by)\s+", "", clean(tag.get_text(" ")), flags=re.I))[0].strip()[:80]
            break
    if not visible_author:
        m = re.search(r"\bBy\s+([A-Z][a-z]+(?:\s+[A-Z][a-z.'-]+){0,3})", main_text[:800])
        if m:
            visible_author = m.group(1)

    time_tags = [t.get("datetime") or clean(t.get_text(" ")) for t in soup.find_all("time")]
    date_text = re.findall(
        r"\b(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b",
        main_text[:3000],
    )

    path = urlparse(url).path.lower()
    article_schema = any(set(_types(o)) & ARTICLE_TYPES for o in jsonld)

    return {
        "title": clean(title_tag.get_text()) if title_tag else None,
        "meta_description": meta(name="description"),
        "robots_meta": (meta(name="robots") or "").lower(),
        "canonical": normalize_url(urljoin(url, canonical_tag["href"])) if canonical_tag and canonical_tag.get("href") else None,
        "lang": (html_tag.get("lang") if html_tag else None) or None,
        "viewport": meta(name="viewport"),
        "og": {k: meta(prop=f"og:{k}") for k in ("title", "description", "image")},
        "headings": headings,
        "main_headings": main_headings,
        "images": images,
        "links": links,
        "main_links": main_links,
        "main_text": main_text,
        "word_count": len(words(main_text)),
        "raw_word_count": raw_word_count,
        "paragraphs": paragraphs,
        "sections": sections,
        "has_list_or_table": bool(main.find(["ul", "ol", "table", "dl"])),
        "jsonld": jsonld,
        "jsonld_errors": jsonld_errors,
        "has_microdata": has_microdata,
        "visible_author": visible_author,
        "visible_dates": [d for d in time_tags if d] + date_text,
        "has_article_tag": bool(soup.find("article")),
        "is_article": article_schema,
        "path": path,
        "script_count": len(soup.find_all("script", src=True)),
        "app_shell": bool(
            soup.find(id=re.compile(r"^(root|app|__next|__nuxt|svelte)$"))
            and raw_word_count < 100
        ),
    }


def jsonld_types(page: dict) -> set[str]:
    return {t for o in page["jsonld"] for t in _types(o)}


def jsonld_of(page: dict, *types: str) -> list[dict]:
    wanted = {t.lower() for t in types}
    return [o for o in page["jsonld"] if set(_types(o)) & wanted]
