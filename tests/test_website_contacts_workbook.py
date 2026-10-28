import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.modules.setdefault("undetected_chromedriver", types.SimpleNamespace())

import web_app


class WebsiteContactsWorkbookTests(unittest.TestCase):
    def test_enrichment_preserves_input_columns_and_saves_contact_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "source.xlsx"
            pd.DataFrame(
                {
                    "Domain": ["example-business.ca"],
                    "Google Maps Page": [2],
                    "Website URL": ["https://example-business.ca/"],
                }
            ).to_excel(output_path, index=False, engine="openpyxl")
            job_id = "contact-workbook-test"
            cancel_event = threading.Event()
            web_app.jobs[job_id] = {
                "id": job_id,
                "status": "queued",
                "stage": "Dans la file d’attente",
                "progress": 0,
                "logs": [],
                "row_count": 0,
                "error": None,
                "download_url": None,
                "output_path": None,
                "_output_path": str(output_path),
                "_download_name": "source_contacts.xlsx",
                "_upload_analysis": "contacts",
                "_cancel_event": cancel_event,
            }
            contact_result = {
                "Emails": "hello@example-business.ca",
                "Instagram URLs": "https://instagram.com/example-business",
                "LinkedIn URLs": "",
                "Facebook URLs": "",
                "X URLs": "",
                "Email Source URLs": "hello@example-business.ca => https://example-business.ca/",
                "Instagram Source URLs": "https://instagram.com/example-business => https://example-business.ca/",
                "LinkedIn Source URLs": "",
                "Facebook Source URLs": "",
                "X Source URLs": "",
                "Email Status": "unverified",
                "Email Format Status": "valid_format",
                "Social Status": "found",
                "Social Association Status": "unverified",
                "Cookie Notice (public)": "We use cookies.",
                "Cookie Policy URL": "",
                "Cookie Policy Notes (public)": "",
                "Pages Scanned": 1,
                "Pages Visited": "https://example-business.ca/",
                "Pages Skipped": 0,
                "Skipped Page URLs": "",
                "Pages Failed": 0,
                "Failed Page URLs": "",
                "Scrape Status": "OK",
            }
            try:
                with (
                    patch.object(web_app, "scrape_website_contacts", return_value=contact_result),
                    patch.object(web_app.time, "sleep"),
                ):
                    web_app._run_uploaded_workbook(job_id, cancel_event)

                result = pd.read_excel(output_path, engine="openpyxl")
                self.assertEqual(result.loc[0, "Domain"], "example-business.ca")
                self.assertEqual(result.loc[0, "Google Maps Page"], 2)
                self.assertEqual(result.loc[0, "Emails"], "hello@example-business.ca")
                self.assertEqual(result.loc[0, "Email Status"], "unverified")
                self.assertEqual(result.loc[0, "Pages Scanned"], 1)
                self.assertEqual(web_app.jobs[job_id]["status"], "completed")
                self.assertEqual(web_app.jobs[job_id]["row_count"], 1)
            finally:
                web_app.jobs.pop(job_id, None)


if __name__ == "__main__":
    unittest.main()
