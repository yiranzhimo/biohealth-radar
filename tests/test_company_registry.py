import unittest

from scripts.company_registry import load_companies, match_company_ids, validate_companies
from scripts import collect_clinicaltrials, collect_pubmed


class CompanyRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.companies = load_companies()

    def test_registry_has_unique_ids_and_multiple_directions(self):
        validate_companies(self.companies)
        company_ids = [company["id"] for company in self.companies]
        directions = {
            direction
            for company in self.companies
            for direction in company.get("directions", [])
        }

        self.assertEqual(len(company_ids), len(set(company_ids)))
        self.assertGreaterEqual(len(self.companies), 30)
        self.assertGreaterEqual(len(directions), 10)

    def test_matches_formal_sponsor_alias(self):
        matched = match_company_ids(
            ["Lead sponsor: Sumitomo Pharma America, Inc."],
            self.companies,
        )

        self.assertEqual(matched, ["sumitomo-pharma"])

    def test_matches_historical_company_name(self):
        matched = match_company_ids(
            ["The study was sponsored by BeiGene, Ltd."],
            self.companies,
        )

        self.assertEqual(matched, ["beone-medicines"])

    def test_does_not_match_short_ticker_as_normal_word(self):
        matched = match_company_ids(
            ["A focused ion beam was used for sample preparation."],
            self.companies,
        )

        self.assertNotIn("beam-therapeutics", matched)

    def test_pubmed_signal_links_company_from_affiliation(self):
        signal = collect_pubmed.make_signal(
            {
                "pmid": "1",
                "title": "A platform study",
                "abstract": "",
                "journal": "Test Journal",
                "publicationTypes": [],
                "affiliations": ["Research and Development, Alnylam Pharmaceuticals, Inc."],
                "date": "2026-07-15",
                "sourceUrl": "https://example.test/pubmed/1",
            },
            1,
            self.companies,
        )

        self.assertEqual(signal["companyIds"], ["alnylam"])

    def test_trial_signal_links_company_from_lead_sponsor(self):
        signal = collect_clinicaltrials.make_signal(
            {
                "nctId": "NCT00000001",
                "briefTitle": "A cell therapy study",
                "officialTitle": "",
                "briefSummary": "",
                "conditions": [],
                "interventions": [],
                "primaryOutcomes": [],
                "leadSponsor": "Legend Biotech USA Inc.",
                "organization": "Legend Biotech",
                "overallStatus": "RECRUITING",
                "hasResults": False,
                "phases": ["PHASE1"],
                "enrollment": 20,
                "countries": ["United States"],
                "lastUpdatePostDate": "2026-07-15",
                "sourceUrl": "https://example.test/NCT00000001",
            },
            1,
            self.companies,
        )

        self.assertEqual(signal["companyIds"], ["legend-biotech"])


if __name__ == "__main__":
    unittest.main()
