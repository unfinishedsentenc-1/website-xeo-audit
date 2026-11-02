"""End-to-end test against the practice site in tests/fixture_site.

Run with   python -m unittest discover -s tests -v
"""

import json
import threading
import unittest
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from audit.run import audit_site, load_settings

FIXTURE = Path(__file__).parent / "fixture_site"


class Handler(SimpleHTTPRequestHandler):
    base = ""

    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        path = self.path.split("?")[0]
        if path == "/old-home":
            self.send_response(301)
            self.send_header("Location", "/")
            self.end_headers()
            return
        target = FIXTURE / path.lstrip("/")
        if target.is_dir():
            target = target / "index.html"
        if not target.exists():
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if not head:
                self.wfile.write(b"<html><body>Not found</body></html>")
            return
        body = target.read_text().replace("BASE", self.base).encode()
        ctype = "text/plain" if target.suffix == ".txt" else "application/xml" if target.suffix == ".xml" else "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head:
            self.wfile.write(body)


class AuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        Handler.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        settings = load_settings()
        settings["crawl"]["delay_seconds"] = 0
        settings["thresholds"]["summary_block_min_words"] = 400
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        cls.site = audit_site(Handler.base + "/", "Practice Co", settings, 50, {"rival.example.net"}, now, log=lambda *_: None)
        cls.pages = {p["url"].replace(Handler.base, ""): p for p in cls.site["pages"]}

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def status(self, path, check):
        return self.pages[path]["checks"][check]["status"]

    def test_crawl_found_pages_and_respected_robots(self):
        self.assertIn("/", self.pages)
        self.assertIn("/blog/good-post", self.pages)
        self.assertIn("/orphan", self.pages)  # found only through the sitemap
        self.assertNotIn("/private/", self.pages)

    def test_good_post_passes_trust_checks(self):
        for check in ("geo.author_visible", "geo.author_schema", "geo.dates_visible", "geo.dates_schema",
                      "geo.fresh", "geo.sources", "geo.numbers", "geo.summary", "aeo.direct_answer",
                      "aeo.question_headings", "aeo.breadcrumbs", "seo.canonical", "seo.title_length"):
            self.assertEqual(self.status("/blog/good-post", check), "pass", check)

    def test_bad_page_fails_what_it_should(self):
        for check in ("seo.indexable", "seo.title_length", "seo.meta_length", "seo.h1", "seo.heading_order",
                      "seo.img_alt", "seo.viewport", "seo.lang", "seo.words", "seo.link_text", "seo.clean_url",
                      "seo.broken_links", "aeo.schema_present", "aeo.raw_html", "geo.no_competitor_links"):
            self.assertEqual(self.status("/products/Bad_Page.html", check), "fail", check)

    def test_missing_pages_are_broken_links_not_pages(self):
        self.assertNotIn("/missing-page", self.pages)
        self.assertEqual(self.status("/", "seo.broken_links"), "fail")

    def test_opening_answer_skips_byline(self):
        self.assertTrue(self.pages["/blog/good-post"]["opening"].startswith("To get invoices paid faster"))
        self.assertEqual(self.pages["/blog/good-post"]["visible_author"], "Dana Reyes")

    def test_orphan_detected(self):
        self.assertEqual(self.status("/orphan", "seo.not_orphan"), "fail")
        self.assertEqual(self.status("/blog/good-post", "seo.not_orphan"), "pass")

    def test_site_checks(self):
        sc = self.site["site_checks"]
        self.assertEqual(sc["seo.robots_txt"]["status"], "pass")
        self.assertEqual(sc["seo.sitemap"]["status"], "pass")
        self.assertEqual(sc["seo.sitemap_lastmod"]["status"], "fail")
        self.assertEqual(sc["seo.sitemap_live"]["status"], "fail")  # /gone is a 404
        self.assertEqual(sc["geo.ai_search_bots"]["status"], "fail")  # PerplexityBot blocked
        self.assertIn("PerplexityBot", sc["geo.ai_search_bots"]["current"])
        self.assertEqual(sc["geo.ai_training_bots"]["status"], "fail")  # ClaudeBot has no rule
        self.assertEqual(sc["geo.org_schema"]["status"], "pass")
        self.assertEqual(sc["geo.llms_txt"]["status"], "fail")

    def test_scores_are_in_range_and_ordered(self):
        s = self.site["scores"]
        for k in ("seo", "aeo", "geo", "overall"):
            self.assertTrue(0 <= s[k] <= 100, k)
        good = self.pages["/blog/good-post"]["scores"]["overall"]
        bad = self.pages["/products/Bad_Page.html"]["scores"]["overall"]
        self.assertGreater(good, bad + 30)

    def test_issues_have_everything_a_fix_needs(self):
        issues = self.site["issues"]
        self.assertTrue(issues)
        for i in issues:
            for key in ("what", "why", "steps", "effort", "who", "priority", "locations"):
                self.assertTrue(i[key], f"{i['check']} missing {key}")
            self.assertIn(i["priority"], ("Do first", "Do next", "Do later"))
        title = next(i for i in issues if i["check"] == "seo.title_length")
        draft = title["locations"][0]["draft"]
        self.assertTrue(30 <= len(draft) <= 60, draft)

    def test_screen_text_follows_style_rules(self):
        from audit.fixes import FIXES
        for check_id, f in FIXES.items():
            for text in [f["what"], f["why"], *f["steps"]]:
                self.assertNotIn("—", text, check_id)  # no em dashes
                self.assertNotRegex(text, r"[a-z]: [a-z]", check_id)  # no colons inside sentences

    def test_output_is_json_serializable(self):
        json.dumps(self.site, default=str)


if __name__ == "__main__":
    unittest.main()
