import unittest

from scripts.collect_china_hk_filings import parse_report_links, portal_for


class ChinaHkFilingsTests(unittest.TestCase):
    def test_portal_selection(self):
        self.assertEqual(portal_for({"identity": {"exchange": "HKEX"}})[0], "HKEXnews")
        self.assertEqual(portal_for({"identity": {"exchange": "SSE", "ticker": "688336"}})[0], "CNINFO")

    def test_report_links_are_classified_and_deduplicated(self):
        body = '<a href="/reports/a.pdf">2025 年年度报告</a>' + (' ' * 500) + '<a href="/reports/a.pdf">年报</a>' + (' ' * 500) + '<a href="/reports/q.pdf">2026 Q1 quarterly report</a>'
        rows = parse_report_links(body, "https://example.test/index", "CNINFO", "c1", "Test")
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["reportType"] for row in rows}, {"年报", "季报"})


if __name__ == "__main__":
    unittest.main()
