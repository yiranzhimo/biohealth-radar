import copy
import json
import unittest
from pathlib import Path

from scripts.review_fingerprint import review_input_hash
from scripts.validate_data import (
    read_data_js,
    validate_company_discovery,
    validate_company_candidate_reviews,
    validate_company_sources,
    validate_company_translations,
    validate_payload,
)


class DataValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = read_data_js(Path("data.js"))
        cls.registry = json.loads(Path("data/companies.json").read_text(encoding="utf-8"))

    def test_current_payload_is_valid(self):
        self.assertEqual(validate_payload(self.payload, self.registry), [])

    def test_rejects_invalid_signal_date(self):
        payload = copy.deepcopy(self.payload)
        payload["signals"][0]["date"] = "2026-08-00"

        errors = validate_payload(payload, self.registry)

        self.assertTrue(any("invalid ISO date" in error for error in errors))

    def test_rejects_review_hash_for_different_content(self):
        payload = copy.deepcopy(self.payload)
        signal = payload["signals"][0]
        signal["aiReview"] = {"inputHash": review_input_hash(signal)}
        signal["title"] = "Changed after review"

        errors = validate_payload(payload, self.registry)

        self.assertTrue(any("inputHash does not match" in error for error in errors))

    def test_current_company_source_snapshots_are_valid(self):
        path = Path("data/raw/company_sources_latest.json")
        sources = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(validate_company_sources(sources, self.registry), [])

    def test_current_company_discovery_is_valid(self):
        discovery = json.loads(Path("data/raw/company_discovery_latest.json").read_text(encoding="utf-8"))

        self.assertEqual(validate_company_discovery(discovery, self.registry), [])

    def test_current_company_translations_are_valid(self):
        sources = json.loads(Path("data/raw/company_sources_latest.json").read_text(encoding="utf-8"))
        translations = json.loads(Path("data/raw/company_translations_latest.json").read_text(encoding="utf-8"))

        self.assertEqual(validate_company_translations(translations, sources), [])

    def test_current_company_candidate_reviews_are_valid(self):
        discovery = json.loads(Path("data/raw/company_discovery_latest.json").read_text(encoding="utf-8"))
        reviews = json.loads(
            Path("data/raw/company_candidate_reviews_latest.json").read_text(encoding="utf-8")
        )

        self.assertEqual(validate_company_candidate_reviews(reviews, discovery), [])


if __name__ == "__main__":
    unittest.main()
