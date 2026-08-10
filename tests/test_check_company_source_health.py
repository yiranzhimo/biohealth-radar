import unittest

from scripts.check_company_source_health import summarize


class CompanySourceHealthTests(unittest.TestCase):
    def test_summarizes_successes_and_failures(self):
        summary = summarize(
            {
                "sources": [
                    {"companyId": "a", "lastCheckStatus": "success"},
                    {"companyId": "b", "lastCheckStatus": "failed", "lastCheckError": "HTTPError"},
                ]
            }
        )
        self.assertEqual(summary["companyCount"], 2)
        self.assertEqual(summary["failureCount"], 1)
        self.assertEqual(summary["failureReasons"], {"HTTPError": 1})


if __name__ == "__main__":
    unittest.main()
