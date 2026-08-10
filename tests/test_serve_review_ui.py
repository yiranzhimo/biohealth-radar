import unittest

from scripts.serve_review_ui import build_override, upsert_override


class ReviewUiServerTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {
            "id": "candidate-example",
            "normalizedName": "example",
            "identifiers": {},
            "sourceTypes": ["ClinicalTrials"],
            "mentionIds": ["mention-1"],
            "classificationHints": {},
            "discoveryScore": 0.8,
        }

    def test_builds_auditable_manual_override(self):
        override = build_override(
            self.candidate,
            decision="accepted",
            reviewer="tester",
            reason="Official website checked.",
            evidence_urls=["https://example.test/about"],
            reviewed_at="2026-08-10",
        )

        self.assertEqual(override["candidateId"], "candidate-example")
        self.assertEqual(len(override["candidateInputHash"]), 64)
        self.assertEqual(override["evidenceUrls"], ["https://example.test/about"])

    def test_merge_requires_known_target_value(self):
        with self.assertRaisesRegex(ValueError, "targetCompanyId"):
            build_override(
                self.candidate,
                decision="merged",
                reviewer="tester",
                reason="Duplicate.",
            )

    def test_rejects_non_https_evidence(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            build_override(
                self.candidate,
                decision="rejected",
                reviewer="tester",
                reason="Not a company.",
                evidence_urls=["http://example.test"],
            )

    def test_upsert_replaces_same_candidate_only(self):
        payload = {
            "overrides": [
                {"candidateId": "candidate-example", "decision": "needs_human"},
                {"candidateId": "candidate-other", "decision": "accepted"},
            ]
        }
        replacement = {"candidateId": "candidate-example", "decision": "rejected"}

        result = upsert_override(payload, replacement)

        self.assertEqual(len(result["overrides"]), 2)
        self.assertEqual(
            next(item for item in result["overrides"] if item["candidateId"] == "candidate-example")["decision"],
            "rejected",
        )


if __name__ == "__main__":
    unittest.main()
