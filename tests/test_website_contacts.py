import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.robotparser import RobotFileParser

import requests

from src.scrap_from_Google.website_contacts import (
    _PageParser,
    _clean_email,
    _extract_emails,
    _is_social_profile,
    _normalize_url,
    _fetch_public_page,
    scrape_website_contacts,
)


def _robots_parser(*lines):
    parser = RobotFileParser()
    parser.parse(list(lines))
    return parser


class WebsiteContactExtractionTests(unittest.TestCase):
    def test_email_extraction_filters_placeholders_and_urls(self):
        emails = _extract_emails(
            [
                "Contact SALES [at] Example-Business [dot] CA.",
                "owner&#64;example-business.ca",
                "https://user@example-business.ca/account",
                "name@example.com john@example.org you@company.com",
                "test@@example-business.ca path/to/package@types/node",
            ]
        )
        self.assertEqual(
            emails,
            {"sales@example-business.ca", "owner@example-business.ca"},
        )

    def test_email_validation_rejects_malformed_and_preserves_unknown_domains(self):
        self.assertEqual(_clean_email(" Team+Sales@small-business.technology "), "team+sales@small-business.technology")
        self.assertIsNone(_clean_email("first..last@business.com"))
        self.assertIsNone(_clean_email("email@business.com"))

    def test_html_parser_collects_visible_text_attributes_mailto_and_jsonld(self):
        parser = _PageParser()
        parser.feed(
            """
            <div id="cookie-consent">We use cookies to improve the website.</div>
            <p>sales [at] company [dot] ca</p>
            <a href="mailto:hello@company.ca">Email</a>
            <span data-email="owner&#64;company.ca"></span>
            <script type="application/ld+json">
              {"@type":"Organization","email":"structured@company.ca",
               "sameAs":["https://www.instagram.com/company"]}
            </script>
            """
        )
        extracted = _extract_emails([*parser.text_parts, *parser.email_candidates])
        self.assertEqual(
            extracted,
            {"sales@company.ca", "hello@company.ca", "owner@company.ca"},
        )
        self.assertEqual(len(parser.structured_data), 1)
        self.assertIn("cookies", " ".join(parser.cookie_text_parts).lower())

    def test_social_links_normalize_tracking_and_reject_share_and_fake_hosts(self):
        self.assertEqual(
            _normalize_url("https://www.instagram.com/company/?utm_source=site#top"),
            "https://instagram.com/company/",
        )
        self.assertTrue(_is_social_profile("https://linkedin.com/company/acme"))
        self.assertFalse(_is_social_profile("https://x.com/intent/tweet?url=example.com"))
        self.assertFalse(_is_social_profile("https://instagram.com.evil.example/company"))

    def test_internal_pages_emails_sources_social_and_cookie_policy(self):
        pages = {
            "https://company.test/": """
                <div id="cookie-consent">We use cookies for analytics. Contact cookiehelp@company.test.</div>
                <p>hello&#64;company.test</p>
                <a href="/contact">Contact</a>
                <a href="/privacy-policy">Privacy</a>
                <a href="https://www.facebook.com/company?utm_source=footer">Facebook</a>
                <a href="https://twitter.com/company">Twitter</a>
                <a href="https://x.com/intent/tweet?text=share">Share</a>
                <script>
                  window.publicLinks = ["https:\\/\\/www.instagram.com\\/script-profile"];
                  window.contact = "script@company.test";
                </script>
                <script type="application/ld+json">
                  {"sameAs":["https://www.linkedin.com/company/company"]}
                </script>
            """,
            "https://company.test/contact": """
                <p>sales [at] company [dot] test</p>
                <a href="https://instagram.com/company">Instagram</a>
            """,
            "https://company.test/privacy-policy": """
                <p>Cookies are retained for 12 months for analytics. Email privacy@company.test.</p>
            """,
        }
        session_ids = []

        def fake_fetch(session, url, cancel_check=None):
            session_ids.append(id(session))
            if url == "https://company.test/":
                session.cookies.set("consent", "accepted", domain="company.test")
            if url.endswith("/contact"):
                self.assertEqual(session.cookies.get("consent"), "accepted")
            return pages.get(url), url

        with (
            patch(
                "src.scrap_from_Google.website_contacts._validate_public_url",
                side_effect=lambda url: url.split("#", 1)[0],
            ),
            patch(
                "src.scrap_from_Google.website_contacts._sitemap_pages",
                return_value=([], [], _robots_parser()),
            ),
            patch(
                "src.scrap_from_Google.website_contacts._fetch_public_page",
                side_effect=fake_fetch,
            ),
            patch("src.scrap_from_Google.website_contacts.time.sleep"),
        ):
            result = scrape_website_contacts("https://company.test/")

        self.assertEqual(
            set(result["Emails"].split("; ")),
            {
                "hello@company.test",
                "sales@company.test",
                "script@company.test",
                "cookiehelp@company.test",
                "privacy@company.test",
            },
        )
        self.assertIn("https://facebook.com/company", result["Facebook URLs"])
        self.assertIn("https://instagram.com/company", result["Instagram URLs"])
        self.assertIn("https://instagram.com/script-profile", result["Instagram URLs"])
        self.assertIn("https://linkedin.com/company/company", result["LinkedIn URLs"])
        self.assertIn("https://twitter.com/company", result["X URLs"])
        self.assertNotIn("intent/tweet", result["X URLs"])
        self.assertIn("hello@company.test => https://company.test/", result["Email Source URLs"])
        self.assertIn(
            "cookiehelp@company.test => https://company.test/",
            result["Email Source URLs"],
        )
        self.assertIn(
            "privacy@company.test => https://company.test/privacy-policy",
            result["Email Source URLs"],
        )
        self.assertIn("12 months", result["Cookie Policy Notes (public)"])
        self.assertEqual(result["Cookie Policy URL"], "https://company.test/privacy-policy")
        self.assertEqual(result["Email Status"], "unverified")
        self.assertEqual(result["Email Format Status"], "valid_format")
        self.assertEqual(result["Social Status"], "found")
        self.assertGreaterEqual(len(set(session_ids)), 1)
        self.assertEqual(result["Pages Scanned"], 3)

    def test_transient_http_error_is_retried(self):
        def response(status):
            return SimpleNamespace(
                status_code=status,
                is_redirect=False,
                is_permanent_redirect=False,
                headers={"Content-Type": "text/html; charset=utf8mb4"},
                encoding="utf8mb4",
                iter_content=lambda chunk_size: [b"<p>UTF-8 content</p>"],
                close=lambda: None,
            )

        session = SimpleNamespace(get=MagicMock(side_effect=[response(503), response(200)]))
        with (
            patch(
                "src.scrap_from_Google.website_contacts._validate_public_url",
                side_effect=lambda url: url,
            ),
            patch("src.scrap_from_Google.website_contacts.time.sleep"),
        ):
            html, final_url = _fetch_public_page(session, "https://company.test/")
        self.assertIn("UTF-8 content", html)
        self.assertEqual(final_url, "https://company.test/")
        self.assertEqual(session.get.call_count, 2)

    def test_page_failures_are_counted_without_discarding_homepage_results(self):
        def fake_fetch(session, url, cancel_check=None):
            if url.endswith("/contact"):
                raise requests.Timeout("test timeout")
            return '<a href="/contact">Contact</a><p>info@company.test</p>', url

        with (
            patch(
                "src.scrap_from_Google.website_contacts._validate_public_url",
                side_effect=lambda url: url.split("#", 1)[0],
            ),
            patch(
                "src.scrap_from_Google.website_contacts._sitemap_pages",
                return_value=([], [], _robots_parser()),
            ),
            patch(
                "src.scrap_from_Google.website_contacts._fetch_public_page",
                side_effect=fake_fetch,
            ),
            patch("src.scrap_from_Google.website_contacts.time.sleep"),
        ):
            result = scrape_website_contacts("https://company.test/")

        self.assertEqual(result["Emails"], "info@company.test")
        self.assertEqual(result["Pages Failed"], 1)
        self.assertTrue(result["Scrape Status"].startswith("Partiel"))

    def test_robots_disallowed_pages_are_skipped(self):
        fetched_urls = []

        def fake_fetch(session, url, cancel_check=None):
            fetched_urls.append(url)
            return '<a href="/private/contact">Contact</a>', url

        with (
            patch(
                "src.scrap_from_Google.website_contacts._validate_public_url",
                side_effect=lambda url: url.split("#", 1)[0],
            ),
            patch(
                "src.scrap_from_Google.website_contacts._sitemap_pages",
                return_value=(
                    [],
                    [],
                    _robots_parser("User-agent: *", "Disallow: /private"),
                ),
            ),
            patch(
                "src.scrap_from_Google.website_contacts._fetch_public_page",
                side_effect=fake_fetch,
            ),
            patch("src.scrap_from_Google.website_contacts.time.sleep"),
        ):
            result = scrape_website_contacts("https://company.test/")

        self.assertEqual(fetched_urls, ["https://company.test/"])
        self.assertEqual(result["Pages Skipped"], 1)
        self.assertIn("https://company.test/private/contact", result["Skipped Page URLs"])

    def test_scraper_rejects_unrelated_email_domains_and_keeps_personal_providers(self):
        def fake_fetch(session, url, cancel_check=None):
            return (
                "<p>hello@indexsy.com jacky@indexsy.ca junk@123-32.com "
                "invalid@123_32</p><a href='mailto:owner@gmail.com'>Email</a>",
                url,
            )

        with (
            patch(
                "src.scrap_from_Google.website_contacts._validate_public_url",
                side_effect=lambda url: url.split("#", 1)[0],
            ),
            patch(
                "src.scrap_from_Google.website_contacts._sitemap_pages",
                return_value=([], [], _robots_parser()),
            ),
            patch(
                "src.scrap_from_Google.website_contacts._fetch_public_page",
                side_effect=fake_fetch,
            ),
            patch("src.scrap_from_Google.website_contacts.time.sleep"),
        ):
            result = scrape_website_contacts("https://indexsy.ca/")

        self.assertEqual(
            set(result["Emails"].split("; ")),
            {"hello@indexsy.com", "jacky@indexsy.ca", "owner@gmail.com"},
        )
        self.assertNotIn("junk@123-32.com", result["Emails"])
        self.assertNotIn("invalid@123_32", result["Emails"])

    def test_sitemap_contact_pages_are_added_to_crawl(self):
        from src.scrap_from_Google.website_contacts import _sitemap_pages

        sitemap = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://company.test/contact-us</loc></url>
          <url><loc>https://company.test/assets/site.css</loc></url>
        </urlset>"""
        with (
            patch(
                "src.scrap_from_Google.website_contacts._validate_public_url",
                side_effect=lambda url: url,
            ),
            patch(
                "src.scrap_from_Google.website_contacts._fetch_public_page",
                return_value=(sitemap, "https://company.test/sitemap.xml"),
            ),
        ):
            session = requests.Session()
            pages, failures, _ = _sitemap_pages(session, "https://company.test/")
            session.close()
        self.assertEqual(pages, ["https://company.test/contact-us"])
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
