import datetime as dt
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.collect_company_sources import (
    collect,
    is_due,
    load_profile_seed_companies,
    merge_snapshot,
    parse_page,
    select_companies,
)


class CompanySourceCollectorTests(unittest.TestCase):
    def setUp(self):
        self.company = {
            "id": "example-bio",
            "name": "Example Bio",
            "directions": ["Gene Editing"],
            "modalities": ["CRISPR"],
            "watchTier": "A",
            "officialUrl": "https://example.test/",
            "pipelineUrl": "https://example.test/pipeline",
            "irUrl": None,
        }

    def test_parse_page_stores_compact_excerpts_not_full_html(self):
        document = """
        <html><head><title>Example Bio</title>
        <meta name="description" content="Example Bio develops CRISPR gene editing therapies."></head>
        <body><script>secret full document text</script>
        <h1>Our Pipeline</h1><p>Our clinical pipeline includes a gene editing program for rare disease.</p>
        </body></html>
        """

        parsed = parse_page(document, {"pipeline", "gene", "editing", "clinical"})

        self.assertEqual(parsed["title"], "Example Bio")
        self.assertTrue(parsed["contentHash"])
        self.assertLessEqual(len(parsed["excerpts"]), 4)
        self.assertNotIn("secret full document text", " ".join(parsed["excerpts"]))
        self.assertIsInstance(parsed["businessExcerpts"], list)
        self.assertIsInstance(parsed["productExcerpts"], list)
        self.assertIsInstance(parsed["planExcerpts"], list)

    def test_unchanged_snapshot_preserves_capture_timestamp(self):
        previous = {
            "companyId": "example-bio",
            "contentHash": "same",
            "capturedAt": "2026-08-01T00:00:00+00:00",
            "firstObservedAt": "2026-08-01T00:00:00+00:00",
            "lastChangedAt": "2026-08-01T00:00:00+00:00",
        }
        fresh = {
            "companyId": "example-bio",
            "contentHash": "same",
            "requestedUrl": "https://example.test/new-path",
            "resolvedUrl": "https://example.test/new-path",
        }

        merged = merge_snapshot(previous, fresh, observed_at="2026-08-10T00:00:00+00:00")

        self.assertEqual(merged["changeType"], "unchanged")
        self.assertEqual(merged["capturedAt"], "2026-08-01T00:00:00+00:00")

    def test_semantic_hash_ignores_relevant_block_order(self):
        first = parse_page(
            "<title>Example</title><p>Our clinical pipeline develops gene editing medicines.</p>"
            "<p>Our research platform supports therapeutic discovery programs.</p>",
            {"clinical", "pipeline", "gene", "editing", "research", "platform"},
        )
        second = parse_page(
            "<title>Example</title><p>Our research platform supports therapeutic discovery programs.</p>"
            "<p>Our clinical pipeline develops gene editing medicines.</p>",
            {"clinical", "pipeline", "gene", "editing", "research", "platform"},
        )

        self.assertEqual(first["contentHash"], second["contentHash"])
        self.assertNotEqual(first["visibleTextHash"], second["visibleTextHash"])

    @patch("scripts.collect_company_sources.fetch_page", side_effect=OSError("network down"))
    def test_failed_refresh_preserves_previous_success(self, _fetch):
        previous = {
            "sources": [
                {
                    "companyId": "example-bio",
                    "sourceRole": "official",
                    "contentHash": "old",
                    "capturedAt": "2026-08-01T00:00:00+00:00",
                }
            ]
        }

        records, errors = collect(
            [self.company],
            previous,
            observed_at="2026-08-10T00:00:00+00:00",
            user_agent="test",
            timeout=1,
            attempts=1,
        )

        self.assertEqual(records[0]["contentHash"], "old")
        self.assertEqual(records[0]["lastCheckStatus"], "failed")
        self.assertEqual(records[0]["lastFailureAt"], "2026-08-10T00:00:00+00:00")
        self.assertEqual(len(errors), 2)

    def test_rejects_unknown_company_selection(self):
        with self.assertRaisesRegex(ValueError, "Unknown company IDs"):
            select_companies([self.company], ["missing"], [], None)

    def test_loads_generated_profile_seeds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "company_profiles.json"
            path.write_text(
                '{"profiles": [{"companyId": "candidate-bio", "name": "Candidate Bio", '
                '"identity": {"officialUrl": "https://example.test/"}, '
                '"classification": {"directions": ["Biotech"]}}]}',
                encoding="utf-8",
            )
            companies = load_profile_seed_companies(path)

        self.assertEqual(companies[0]["id"], "candidate-bio")
        self.assertEqual(companies[0]["officialUrl"], "https://example.test/")

    def test_due_scheduler_skips_until_next_check(self):
        previous = {"lastCheckedAt": "2026-08-10T00:00:00+00:00", "nextCheckAt": "2026-08-17T00:00:00+00:00"}
        self.assertFalse(is_due(previous, self.company, "official", dt.datetime.fromisoformat("2026-08-12T00:00:00+00:00")))
        self.assertTrue(is_due(previous, self.company, "official", dt.datetime.fromisoformat("2026-08-18T00:00:00+00:00")))


if __name__ == "__main__":
    unittest.main()
