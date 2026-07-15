import datetime as dt
import unittest

from scripts import collect_sec_edgar as sec


class SecCollectorTests(unittest.TestCase):
    def test_resolves_company_ticker_to_cik(self):
        companies = [
            {
                "id": "example",
                "name": "Example Biotech",
                "ticker": "EXMP",
                "exchange": "NASDAQ",
            }
        ]
        ticker_map = sec.build_ticker_map(
            {"0": {"ticker": "EXMP", "cik_str": 12345, "title": "EXAMPLE BIOTECH INC"}}
        )

        resolved, unresolved = sec.resolve_sec_companies(companies, ticker_map)

        self.assertEqual(unresolved, [])
        self.assertEqual(resolved[0]["cik"], "0000012345")

    def test_parses_columnar_recent_filings(self):
        submission = {
            "name": "EXAMPLE BIOTECH INC",
            "filings": {
                "recent": {
                    "accessionNumber": ["0000012345-26-000001"],
                    "filingDate": ["2026-07-14"],
                    "form": ["8-K"],
                    "primaryDocument": ["example-8k.htm"],
                    "primaryDocDescription": ["Current report"],
                }
            },
        }
        company = {
            "company": {"id": "example", "name": "Example Biotech", "directions": ["Gene Editing"]},
            "secTicker": "EXMP",
            "cik": "0000012345",
            "secName": "EXAMPLE BIOTECH INC",
        }

        records = sec.parse_recent_filings(submission, company)

        self.assertEqual(records[0]["companyId"], "example")
        self.assertEqual(records[0]["form"], "8-K")
        self.assertIn("/12345/000001234526000001/example-8k.htm", records[0]["sourceUrl"])

    def test_filters_dates_forms_and_amendments(self):
        records = [
            {"filingDate": "2026-07-14", "form": "8-K/A"},
            {"filingDate": "2026-07-14", "form": "DEF 14A"},
            {"filingDate": "2026-06-01", "form": "8-K"},
        ]

        filtered = sec.filter_filings(records, dt.date(2026, 7, 1), {"8-K"})

        self.assertEqual(filtered, [records[0]])

    def test_signal_keeps_filing_claims_neutral(self):
        signal = sec.make_signal(
            {
                "cik": "0000012345",
                "accessionNumber": "0000012345-26-000001",
                "filingDate": "2026-07-14",
                "form": "8-K",
                "companyId": "example",
                "companyName": "Example Biotech",
                "companyDirections": ["Gene Editing"],
                "secTicker": "EXMP",
                "primaryDocDescription": "Current report",
                "sourceUrl": "https://example.test/filing",
            }
        )

        self.assertEqual(signal["companyIds"], ["example"])
        self.assertEqual(signal["primaryCategory"], "Company & Market")
        self.assertIn("No conclusion was drawn", signal["inference"])
        self.assertTrue(signal["needsReview"])

    def test_merge_preserves_non_sec_signals_and_caps_sec_history(self):
        payload = {
            "updatedAt": "2026-07-14",
            "sources": [],
            "signals": [
                {"id": "pubmed-1", "date": "2026-07-14"},
                {"id": "sec-old", "date": "2026-07-01"},
            ],
        }
        new_signals = [
            {"id": "sec-new-1", "date": "2026-07-15"},
            {"id": "sec-new-2", "date": "2026-07-14"},
        ]

        merged = sec.merge_signals(payload, new_signals, max_stored=2)

        self.assertIn("pubmed-1", [signal["id"] for signal in merged["signals"]])
        self.assertEqual(
            [signal["id"] for signal in merged["signals"] if signal["id"].startswith("sec-")],
            ["sec-new-1", "sec-new-2"],
        )
        self.assertEqual(merged["sources"][-1]["name"], "SEC EDGAR")


if __name__ == "__main__":
    unittest.main()
