import unittest

from scripts.collect_nih_reporter import parse_project, topic_hints


class NihReporterCollectorTests(unittest.TestCase):
    def test_parses_compact_for_profit_project_record(self):
        raw = {
            "appl_id": 123,
            "project_num": "1R41TEST",
            "project_title": "CRISPR gene therapy platform",
            "fiscal_year": 2025,
            "award_amount": 250000,
            "award_notice_date": "2025-09-23T00:00:00",
            "organization": {
                "org_name": "Example Therapeutics, Inc.",
                "org_city": "Boston",
                "org_state": "MA",
                "org_country": "UNITED STATES",
                "primary_uei": "UEI123",
                "org_ipf_code": "IPF123",
            },
            "organization_type": {"name": "Domestic For-Profits"},
            "abstract_text": "A " * 400,
            "terms": "gene editing CRISPR",
        }

        record = parse_project(raw, "gene therapy")

        self.assertEqual(record["organization"]["uei"], "UEI123")
        self.assertIn("Gene Editing / Gene Therapy", record["topicHints"])
        self.assertLessEqual(len(record["projectSummaryExcerpt"]), 280)
        self.assertNotIn("abstract_text", record)

    def test_topic_hints_are_evidence_based(self):
        self.assertEqual(topic_hints({"project_title": "Administrative supplement"}), [])


if __name__ == "__main__":
    unittest.main()
