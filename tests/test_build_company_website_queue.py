import unittest

from scripts.build_company_website_queue import build_queue


class CompanyWebsiteQueueTests(unittest.TestCase):
    def test_excludes_overridden_domains(self):
        result = build_queue(
            {
                "profiles": [
                    {
                        "companyId": "candidate-a",
                        "name": "A",
                        "identity": {
                            "officialUrl": "https://example.test/market",
                            "websiteStatus": "market_page_pending_official_domain",
                            "identifiers": {"cik": ["0000000001"]},
                        },
                        "classification": {"directions": ["Biotech"]},
                    },
                    {
                        "companyId": "candidate-b",
                        "name": "B",
                        "identity": {"websiteStatus": "curated"},
                        "classification": {},
                    },
                ]
            },
            {"overrides": {"candidate-a": {"officialUrl": "https://a.example/"}}},
        )
        self.assertEqual(result["count"], 0)


if __name__ == "__main__":
    unittest.main()
