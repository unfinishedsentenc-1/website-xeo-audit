"""Plain-English fixes for every check.

Writing rules for all text in this file, because it appears on screen.
Plain, active, declarative sentences. No em dashes. No colons inside
sentences. No superlatives. No hedging.
"""

from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlparse

from .checks import CHECK_INDEX
from .parse import words

YOU, EDITOR, DEV = "You", "A web editor", "A developer"

EDIT_PAGE = "Open the page in your website editor."
SAVE = "Save and publish the page."
RECHECK = "Run the audit again next month to confirm the fix."

FIXES = {
    "seo.indexable": dict(
        what="Google cannot add this page to its results.",
        why="A page that Google leaves out gets no search visitors at all.",
        steps=[EDIT_PAGE, "Open the page settings and find the search engine visibility option.", "Turn off any setting named noindex, hide from search engines, or discourage search engines.", SAVE, "If the page shows an error instead of loading, ask a developer to fix the error first."],
        effort="10 minutes", who=YOU),
    "seo.canonical": dict(
        what="The page does not tell Google that it is the main copy of itself.",
        why="Without this tag Google picks a version on its own and splits your credit between copies.",
        steps=[EDIT_PAGE, "Open the SEO settings for the page.", "Find the canonical URL field.", "Paste the page's own address, exactly as shown in the Where box.", SAVE],
        effort="5 minutes per page", who=EDITOR),
    "seo.title_length": dict(
        what="The page title is too short or too long for Google results.",
        why="Google cuts off long titles and shows short ones with little to click on. A clear title brings more clicks.",
        steps=[EDIT_PAGE, "Click the page title field. Some editors call it SEO title.", "Replace the text with the draft below, or write your own between 30 and 60 characters.", SAVE],
        effort="5 minutes per page", who=YOU, draft="title"),
    "seo.title_unique": dict(
        what="Another page on your site uses the same title.",
        why="Google cannot tell matching pages apart and shows one of them less often.",
        steps=[EDIT_PAGE, "Click the page title field.", "Write a title that says what makes this page different. Use the draft below as a start.", SAVE, "Repeat for each page listed under Also on."],
        effort="5 minutes per page", who=YOU, draft="title"),
    "seo.meta_length": dict(
        what="The page summary that Google shows under the title is missing, too short, or too long.",
        why="This summary is your pitch in the search results. A clear one brings more clicks.",
        steps=[EDIT_PAGE, "Click the meta description field. Some editors call it SEO description or search snippet.", "Paste the draft below, or write your own between 70 and 160 characters.", SAVE],
        effort="5 minutes per page", who=YOU, draft="meta"),
    "seo.meta_unique": dict(
        what="Another page on your site uses the same meta description.",
        why="Repeated summaries make your pages look alike in search results.",
        steps=[EDIT_PAGE, "Click the meta description field.", "Write a summary for this page only. Use the draft below as a start.", SAVE],
        effort="5 minutes per page", who=YOU, draft="meta"),
    "seo.h1": dict(
        what="The page needs exactly one main heading, and it has none or several.",
        why="The main heading tells Google and AI tools what the page is about. Zero or several leaves them guessing.",
        steps=[EDIT_PAGE, "Find the large heading at the top of the page.", "Set it to Heading 1. Set every other large heading to Heading 2.", "If there is no heading at the top, add one that names the topic of the page.", SAVE],
        effort="10 minutes", who=EDITOR),
    "seo.heading_order": dict(
        what="The headings skip a level, for example from Heading 2 straight to Heading 4.",
        why="Ordered headings work like a table of contents for Google, AI tools and screen readers.",
        steps=[EDIT_PAGE, "Find the heading named in the Where box.", "Change its level so it sits one step below the heading above it.", SAVE],
        effort="10 minutes", who=EDITOR),
    "seo.img_alt": dict(
        what="Some images have no text description.",
        why="Google and screen readers cannot see images. The description tells them what is in the picture.",
        steps=[EDIT_PAGE, "Click each image listed in the Where box.", "Find the alt text field.", "Describe the image in a short phrase, for example “Team reviewing the quarterly report.”", "For a purely decorative image, leave alt text empty and mark it decorative if your editor offers that.", SAVE],
        effort="2 minutes per image", who=YOU),
    "seo.og": dict(
        what="The page has no social sharing preview.",
        why="When someone shares the link on LinkedIn or Slack, it shows a bare address instead of a title and image.",
        steps=[EDIT_PAGE, "Open the social sharing settings. Some editors call them Open Graph or social preview.", "Add a title, a description and an image.", SAVE],
        effort="10 minutes per page", who=EDITOR),
    "seo.viewport": dict(
        what="The page is not set up for phone screens.",
        why="Google ranks pages by how they work on phones. Without this setting the page shows tiny text on a phone.",
        steps=["Send this issue to your developer.", "Ask them to add the viewport meta tag to the site template.", "Check the page on your phone once they publish the change."],
        effort="15 minutes", who=DEV),
    "seo.lang": dict(
        what="The page does not say what language it is in.",
        why="Google and screen readers use the language setting to show the page to the right people.",
        steps=["Send this issue to your developer.", "Ask them to set the lang attribute on the html tag in the site template, for example lang=“en”.", RECHECK],
        effort="15 minutes", who=DEV),
    "seo.words": dict(
        what="The page has little text.",
        why="Short pages give Google and AI tools little to work with, so they rank and quote longer pages instead.",
        steps=[EDIT_PAGE, "Add sections that answer the questions a buyer asks about this topic.", "Aim for at least 300 words of useful text. Skip filler.", SAVE],
        effort="1 to 2 hours", who=YOU),
    "seo.internal_links": dict(
        what="The page links to few other pages on your site.",
        why="Links between your pages help Google find them and help visitors keep reading.",
        steps=[EDIT_PAGE, "Find two or three related pages on your site.", "Add a link to each one inside the text, using words that describe the page you link to.", SAVE],
        effort="15 minutes", who=YOU),
    "seo.link_text": dict(
        what="Some links use vague text like “click here” or “learn more.”",
        why="Google and AI tools read link text to learn what the linked page is about. Vague text tells them nothing.",
        steps=[EDIT_PAGE, "Find each link listed in the Where box.", "Change the link text to say where it goes, for example “see our pricing plans.”", SAVE],
        effort="10 minutes", who=YOU),
    "seo.clean_url": dict(
        what="The page address is messy.",
        why="Short, readable addresses get more clicks and are easier to share.",
        steps=["Decide on a short address with lowercase words and hyphens, for example /pricing-plans.", "Change the page address in your website editor.", "Ask your web editor to add a redirect from the old address to the new one.", "Update links on your site that use the old address."],
        effort="30 minutes", who=EDITOR),
    "seo.no_redirect": dict(
        what="Links on your site point to an old address that forwards to a new one.",
        why="Each forward slows the visit and wastes Google's time on your site.",
        steps=["Note the new address shown in the Where box.", "Find links on your site that use the old address.", "Change each link to the new address.", SAVE],
        effort="15 minutes", who=YOU),
    "seo.broken_links": dict(
        what="The page links to pages that no longer exist.",
        why="Broken links frustrate visitors and tell Google the site is not looked after.",
        steps=[EDIT_PAGE, "Find each broken link listed in the Where box.", "Point it to a working page, or remove the link.", SAVE],
        effort="10 minutes", who=YOU),
    "seo.not_orphan": dict(
        what="No other page on your site links to this page.",
        why="Google and visitors find pages by following links. A page with no links pointing to it gets few visits.",
        steps=["Pick one or two related pages on your site.", "Open each one in your website editor.", "Add a link to this page inside the text.", SAVE],
        effort="15 minutes", who=YOU),
    "seo.speed": dict(
        what="The server takes too long to start sending the page.",
        why="Slow pages lose visitors before they load, and Google ranks them lower.",
        steps=["Send this issue to your developer or hosting provider.", "Ask them to turn on page caching and check the hosting plan.", RECHECK],
        effort="Half a day", who=DEV),
    "seo.robots_txt": dict(
        what="The site has no robots.txt file.",
        why="This file tells search engines and AI crawlers what they may visit. Without it they guess.",
        steps=["Send this issue to your web editor or developer.", "Ask them to add a robots.txt file at the top of the site that allows crawlers and lists the sitemap address.", RECHECK],
        effort="15 minutes", who=EDITOR),
    "seo.sitemap": dict(
        what="The site has no XML sitemap.",
        why="A sitemap is a list of your pages for Google. Without it Google finds new pages slower.",
        steps=["Open your website platform settings and look for a sitemap option. Most platforms create one for you.", "Turn it on.", "Add the sitemap address to robots.txt.", RECHECK],
        effort="15 minutes", who=EDITOR),
    "seo.sitemap_lastmod": dict(
        what="The sitemap does not say when each page last changed.",
        why="These dates tell Google which pages to visit again first.",
        steps=["Open your sitemap settings in the website platform.", "Turn on last modified dates.", "If there is no such setting, ask your developer to add lastmod to the sitemap."],
        effort="30 minutes", who=DEV),
    "seo.sitemap_live": dict(
        what="The sitemap lists pages that are gone or that forward somewhere else.",
        why="Google trusts a sitemap less when it lists dead pages.",
        steps=["Look at the addresses in the Where box.", "Remove deleted pages from the sitemap, or replace old addresses with the new ones.", "Most platforms do this when you unpublish a page. Ask your developer if yours does not."],
        effort="30 minutes", who=EDITOR),
    "aeo.direct_answer": dict(
        what="The page does not open with a short, direct answer.",
        why="AI assistants quote pages that answer the question in the first few lines.",
        steps=[EDIT_PAGE, "Click the first paragraph under the main heading.", "Replace it with the draft below, or write 15 to 70 words that answer the page's main question.", "Keep the longer explanation below it.", SAVE],
        effort="15 minutes", who=YOU, draft="answer"),
    "aeo.question_headings": dict(
        what="None of the headings is written as a question.",
        why="People ask AI tools questions. Headings that match those questions make your answers easy to pick up.",
        steps=[EDIT_PAGE, "Pick two or three headings.", "Rewrite each one as the question it answers, for example “How much does it cost?”", SAVE],
        effort="15 minutes", who=YOU),
    "aeo.faq_schema": dict(
        what="The page has questions and answers but no FAQ markup.",
        why="FAQ markup labels each question and answer so Google and AI tools can quote them directly.",
        steps=["Send this issue to your web editor.", "Ask them to add FAQPage structured data that lists each question and answer on the page.", "Many website platforms have an FAQ block that adds it for you."],
        effort="30 minutes", who=EDITOR),
    "aeo.lists": dict(
        what="The page is all paragraphs, with no lists or tables.",
        why="AI tools lift lists and tables straight into their answers.",
        steps=[EDIT_PAGE, "Find a paragraph that names several items, steps or options.", "Turn it into a bulleted or numbered list.", SAVE],
        effort="15 minutes", who=YOU),
    "aeo.paragraphs": dict(
        what="Some paragraphs run longer than 120 words.",
        why="Long blocks are hard to scan, and AI tools quote short, self-contained paragraphs.",
        steps=[EDIT_PAGE, "Find the paragraph shown in the Where box.", "Split it into two or three paragraphs, one idea each.", SAVE],
        effort="10 minutes", who=YOU),
    "aeo.schema_present": dict(
        what="The page has no structured data.",
        why="Structured data is a label in the page code that tells Google and AI tools what the page is, such as an article or a product.",
        steps=["Send this issue to your web editor or developer.", "Ask them to add structured data of the right type. Use Article for blog posts, Organization for the homepage, and WebPage for others.", "Test the page at search.google.com/test/rich-results."],
        effort="1 hour", who=DEV),
    "aeo.schema_valid": dict(
        what="The page's structured data has errors.",
        why="Google and AI tools ignore structured data they cannot read.",
        steps=["Open search.google.com/test/rich-results.", "Paste the page address and run the test.", "Send the errors it lists to your developer to fix."],
        effort="30 minutes", who=DEV),
    "aeo.schema_type": dict(
        what="The page's structured data uses the wrong type.",
        why="The type tells Google and AI tools what kind of page this is. The wrong type gets the page shown in the wrong places.",
        steps=["Send this issue to your developer.", "Ask them to change the structured data type to the one named in the Where box.", "Test the page at search.google.com/test/rich-results."],
        effort="30 minutes", who=DEV),
    "aeo.breadcrumbs": dict(
        what="The page has no breadcrumb markup.",
        why="Breadcrumbs show Google where the page sits in your site, and Google shows that path in results.",
        steps=["Send this issue to your developer.", "Ask them to add BreadcrumbList structured data to the page template.", "One template change fixes every page that uses it."],
        effort="1 hour", who=DEV),
    "aeo.raw_html": dict(
        what="Most of the page's text appears only after scripts run in the browser.",
        why="Most AI crawlers do not run scripts, so they see a blank page and skip you.",
        steps=["Send this issue to your developer.", "Ask them to turn on server-side rendering or prerendering for this page.", "Ask them to confirm the main text shows up when JavaScript is off."],
        effort="1 to 3 days", who=DEV),
    "geo.author_visible": dict(
        what="The article does not show who wrote it.",
        why="AI tools and readers trust content more when a real person stands behind it.",
        steps=[EDIT_PAGE, "Add the author's name near the top of the article.", "Link the name to a short author bio page if you have one.", SAVE],
        effort="10 minutes", who=YOU),
    "geo.author_schema": dict(
        what="The author's name is missing from the page code.",
        why="AI tools read the code to confirm who wrote the article.",
        steps=["Send this issue to your developer.", "Ask them to add the author to the Article structured data on the blog template.", "One template change fixes every post."],
        effort="30 minutes", who=DEV),
    "geo.dates_visible": dict(
        what="The article does not show when it was published or updated.",
        why="Readers and AI tools prefer recent content and skip undated pages.",
        steps=[EDIT_PAGE, "Show the publish date near the top of the article.", "Add an updated date whenever you revise it.", SAVE],
        effort="10 minutes", who=EDITOR),
    "geo.dates_schema": dict(
        what="The publish and update dates are missing from the page code.",
        why="AI tools read these dates to judge how current the content is.",
        steps=["Send this issue to your developer.", "Ask them to add datePublished and dateModified to the Article structured data on the blog template.", "One template change fixes every post."],
        effort="30 minutes", who=DEV),
    "geo.fresh": dict(
        what="The page has not been updated in over a year.",
        why="AI tools and Google favor current information. Old pages lose ground to newer ones.",
        steps=[EDIT_PAGE, "Review the facts, numbers and examples.", "Update anything that has changed and add one new section or example.", "Change the updated date.", SAVE],
        effort="1 hour", who=YOU),
    "geo.sources": dict(
        what="The page cites fewer than two outside sources.",
        why="AI tools trust pages that back up their claims with links to research and respected sites.",
        steps=[EDIT_PAGE, "Find two claims that a reader would want proof for.", "Link each one to a trusted outside source, such as a study, a government site or an industry report.", SAVE],
        effort="30 minutes", who=YOU),
    "geo.numbers": dict(
        what="The page has few specific numbers or data points.",
        why="AI tools quote pages with concrete facts, such as percentages, prices and time saved.",
        steps=[EDIT_PAGE, "Add two or three specific numbers that support your points, such as results, prices or survey figures.", "Cite where each number comes from.", SAVE],
        effort="30 minutes", who=YOU),
    "geo.sections": dict(
        what="Some sections are too short or too long.",
        why="AI tools quote whole sections. Sections of 60 to 350 words are long enough to answer and short enough to quote.",
        steps=[EDIT_PAGE, "Find the sections named in the Where box.", "Combine very short sections, or split long ones with a new heading.", SAVE],
        effort="30 minutes", who=YOU),
    "geo.summary": dict(
        what="This long page has no summary or key takeaways.",
        why="A short summary gives readers and AI tools the main points at a glance.",
        steps=[EDIT_PAGE, "Add a heading named Key takeaways near the top.", "Under it, list three to five one-sentence points.", SAVE],
        effort="15 minutes", who=YOU),
    "geo.no_competitor_links": dict(
        what="The page links to a competitor's site.",
        why="These links send your visitors and your credibility to a competitor.",
        steps=[EDIT_PAGE, "Find each link listed in the Where box.", "Remove it, or link to a neutral source or your own page instead.", SAVE],
        effort="10 minutes", who=YOU),
    "geo.ai_search_bots": dict(
        what="Your robots.txt blocks AI search crawlers.",
        why="ChatGPT, Claude and Perplexity cannot read or cite pages their search crawlers are blocked from.",
        steps=["Send this issue to your developer.", "Ask them to allow OAI-SearchBot, ChatGPT-User, Claude-SearchBot and PerplexityBot in robots.txt.", RECHECK],
        effort="15 minutes", who=DEV),
    "geo.ai_training_bots": dict(
        what="Your robots.txt has no deliberate rule for AI training crawlers.",
        why="These crawlers collect content to train AI models. Allowing or blocking them is a business choice, and the rule makes that choice on purpose.",
        steps=["Decide whether you want your content used to train AI models.", "Ask your developer to add a rule for GPTBot, ClaudeBot and Google-Extended in robots.txt, set to allow or disallow.", RECHECK],
        effort="15 minutes", who=DEV),
    "geo.org_schema": dict(
        what="The homepage code does not fully describe your company.",
        why="Organization markup tells Google and AI tools your official name, logo and social profiles, so they describe you correctly.",
        steps=["Send this issue to your developer.", "Ask them to add Organization structured data to the homepage with your name, logo and links to your official profiles.", "Test it at search.google.com/test/rich-results."],
        effort="30 minutes", who=DEV),
    "geo.llms_txt": dict(
        what="The site has no llms.txt file.",
        why="This file gives AI tools a short guide to your site. No study shows a benefit yet, so it sits last on the list.",
        steps=["Write a short list of your key pages with one line about each.", "Ask your developer to publish it at yoursite/llms.txt."],
        effort="30 minutes", who=DEV),
}

# ---------------------------------------------------------------- draft copy


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def _fit(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit + 1].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut


def draft_title(page: dict, brand: str, settings: dict) -> str:
    t = settings["thresholds"]
    h1 = next((h["text"] for h in page.get("headings", []) if h["level"] == 1), None)
    base = h1 or page.get("title") or ""
    base = re.split(r"\s+[|–—-]\s+", base)[0].strip()
    suffix = f" | {brand}" if brand and brand.lower() not in base.lower() else ""
    title = _fit(base, t["title_max"] - len(suffix)) + suffix
    if len(title) < t["title_min"]:
        first = next((s for s in _sentences(" ".join(page.get("paragraphs", [])[:2]))), "")
        extra = _fit(first.rstrip("."), t["title_max"] - len(title) - 3)
        if extra:
            title = _fit(f"{base}, {extra}", t["title_max"] - len(suffix)) + suffix
    return title if t["title_min"] <= len(title) <= t["title_max"] else None


def draft_meta(page: dict, brand: str, settings: dict) -> str:
    t = settings["thresholds"]
    text = ""
    for s in _sentences(" ".join(page.get("paragraphs", [])[:4])):
        if len(text) + len(s) + 1 > t["meta_max"]:
            break
        text = f"{text} {s}".strip()
    if len(text) < t["meta_min"]:
        text = _fit(" ".join(page.get("paragraphs", [])[:3]), t["meta_max"] - 1)
        if text and not text.endswith("."):
            text += "."
    return text if len(text) >= t["meta_min"] else None


def draft_answer(page: dict, brand: str, settings: dict) -> str:
    t = settings["thresholds"]
    out = []
    for s in _sentences(" ".join(page.get("paragraphs", [])[:3])):
        if len(words(" ".join(out + [s]))) > t["answer_max_words"]:
            break
        out.append(s)
        if len(words(" ".join(out))) >= 40:
            break
    answer = " ".join(out)
    return answer if len(words(answer)) >= t["answer_min_words"] else None


DRAFTS = {"title": draft_title, "meta": draft_meta, "answer": draft_answer}

# ---------------------------------------------------------------- priority and grouping


def priority(weight: int, share: float) -> str:
    if weight >= 3 or (weight == 2 and share >= 0.5):
        return "Do first"
    if weight == 2 or share >= 0.5:
        return "Do next"
    return "Do later"


def template_groups(urls: list[str], total_pages: int) -> list[dict]:
    """Group pages that share one template so one change fixes many pages."""
    if len(urls) >= 3 and total_pages and len(urls) / total_pages >= 0.8:
        return [{"template": "Every page (site-wide template)", "urls": urls}]
    by_section = defaultdict(list)
    for u in urls:
        segs = [s for s in urlparse(u).path.split("/") if s]
        key = f"/{segs[0]}/ pages" if len(segs) >= 2 else "Top-level pages"
        by_section[key].append(u)
    groups = []
    for key, members in sorted(by_section.items(), key=lambda kv: -len(kv[1])):
        groups.append({"template": key if len(members) >= 3 and key != "Top-level pages" else None, "urls": members})
    return groups


TEMPLATE_FRIENDLY = {
    "seo.viewport", "seo.lang", "seo.og", "aeo.breadcrumbs", "aeo.schema_present", "aeo.schema_type",
    "geo.author_schema", "geo.dates_schema", "geo.dates_visible", "geo.author_visible", "aeo.raw_html", "seo.speed",
}


def build_issues(site_result: dict, brand: str, settings: dict) -> list[dict]:
    """Turn failed checks into fix cards, grouped by check and template."""
    pages = site_result["pages"]
    weights = settings["scoring"]["weights"]
    total = len(pages)
    issues = []

    for check_id, info in FIXES.items():
        _, area, scope, level, label, _ = CHECK_INDEX[check_id]
        weight = weights[level]
        if scope == "site":
            r = site_result["site_checks"].get(check_id, {})
            if r.get("status") != "fail":
                continue
            locations = [{"url": site_result["home_url"], "spot": r.get("spot"), "current": r.get("current"), "items": r.get("items", [])}]
            share = 1.0
            groups = []
        else:
            failing = [(p, p["checks"][check_id]) for p in pages if p["checks"].get(check_id, {}).get("status") == "fail"]
            if not failing:
                continue
            applicable = sum(1 for p in pages if p["checks"].get(check_id, {}).get("status") in ("pass", "fail"))
            share = len(failing) / applicable if applicable else 0
            locations = []
            for p, r in failing:
                loc = {"url": p["url"], "spot": r.get("spot"), "current": r.get("current")}
                for k in ("items", "also_on", "expected", "length", "count", "problems"):
                    if k in r:
                        loc[k] = r[k]
                if info.get("draft"):
                    loc["draft"] = DRAFTS[info["draft"]](p, brand, settings)
                    if not loc["draft"]:
                        loc["draft_note"] = "This page has too little text to draft from. Write this one by hand using the steps above."
                locations.append(loc)
            groups = template_groups([l["url"] for l in locations], total) if check_id in TEMPLATE_FRIENDLY or len(locations) >= 3 else []
        one_template = any(g.get("template") for g in groups)
        issues.append(
            {
                "check": check_id,
                "area": area,
                "scope": scope,
                "label": label,
                "weight": weight,
                "what": info["what"],
                "why": info["why"],
                "steps": info["steps"],
                "effort": info["effort"],
                "who": info["who"],
                "priority": priority(weight, share),
                "pages_affected": len(locations) if scope == "page" else None,
                "share": round(share, 3),
                "locations": locations,
                "groups": groups,
                "template_note": (
                    "These pages share one template. One change to the template fixes all of them."
                    if one_template
                    else None
                ),
            }
        )
    order = {"Do first": 0, "Do next": 1, "Do later": 2}
    issues.sort(key=lambda i: (order[i["priority"]], -i["weight"], -(i["pages_affected"] or total)))
    return issues
