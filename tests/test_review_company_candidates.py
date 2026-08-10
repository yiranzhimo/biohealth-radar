import unittest

from scripts.review_company_candidates import (
    POLICY_VERSION,
    apply_override,
    automatic_review,
    build_reviews,
    candidate_input_hash,
)


class CompanyCandidateReviewTests(unittest.TestCase):
    def candidate(self, **changes):
        candidate = {
            "id": "candidate-example",
            "normalizedName": "example therapeutics",
            "identifiers": {},
            "sourceTypes": [],
            "mentionIds": ["mention-1"],
            "classificationHints": {"directions": []},
            "discoveryScore": 0.8,
        }
        candidate.update(changes)
        return candidate

    def test_sec_cik_and_biotech_sic_are_automatically_accepted(self):
        candidate = self.candidate(
            identifiers={"cik": ["0001234567"]},
            sourceTypes=["SEC"],
            classificationHints={"directions": ["Pharmaceutical Preparations"]},
        )

        review = automatic_review(candidate, "2026-08-10T00:00:00+00:00")

        self.assertEqual(review["decision"], "accepted")
        self.assertFalse(review["humanReviewRequired"])
        self.assertEqual(review["identityStatus"], "verified")
        self.assertEqual(review["policyVersion"], POLICY_VERSION)

    def test_nih_for_profit_recipient_with_identifier_is_automatically_accepted(self):
        candidate = self.candidate(
            identifiers={"uei": ["UEI123"], "nihIpf": ["IPF123"]},
            sourceTypes=["NIH"],
            classificationHints={"directions": ["Cell Therapy"]},
        )

        review = automatic_review(candidate, "2026-08-10T00:00:00+00:00")

        self.assertEqual(review["decision"], "accepted")
        self.assertEqual(review["biotechStatus"], "supported")

    def test_candidate_without_stable_identifier_needs_human(self):
        candidate = self.candidate(sourceTypes=["ClinicalTrials"], discoveryScore=0.9)

        review = automatic_review(candidate, "2026-08-10T00:00:00+00:00")

        self.assertEqual(review["decision"], "needs_human")
        self.assertTrue(review["humanReviewRequired"])

    def test_csi_biotech_index_constituent_is_automatically_accepted(self):
        candidate = self.candidate(
            identifiers={"cnSecurityCode": ["688331"]},
            sourceTypes=["CSI"],
            classificationHints={"directions": ["上证科创板生物医药指数"]},
        )

        review = automatic_review(candidate, "2026-08-10T00:00:00+00:00")

        self.assertEqual(review["decision"], "accepted")
        self.assertEqual(review["identityStatus"], "verified")

    def test_hkex_biotech_marker_issuer_is_automatically_accepted(self):
        candidate = self.candidate(
            identifiers={"hkexStockCode": ["01167"], "isin": ["KYG4987A1094"]},
            sourceTypes=["HKEX"],
            classificationHints={"directions": ["HKEX Chapter 18A biotech marker"]},
        )

        review = automatic_review(candidate, "2026-08-10T00:00:00+00:00")

        self.assertEqual(review["decision"], "accepted")
        self.assertEqual(review["biotechStatus"], "supported")

    def test_hsi_biotech_constituent_is_automatically_accepted(self):
        candidate = self.candidate(
            identifiers={"hkexStockCode": ["09688"], "isin": ["KYG9887T1168"]},
            sourceTypes=["HSI"],
            classificationHints={"directions": ["Hang Seng Biotech Index constituent"]},
        )

        review = automatic_review(candidate, "2026-08-10T00:00:00+00:00")

        self.assertEqual(review["decision"], "accepted")
        self.assertEqual(review["identityStatus"], "verified")

    def test_conflicting_ciks_need_human(self):
        candidate = self.candidate(
            identifiers={"cik": ["0001234567", "0007654321"]}, sourceTypes=["SEC"]
        )

        review = automatic_review(candidate, "2026-08-10T00:00:00+00:00")

        self.assertEqual(review["decision"], "needs_human")
        self.assertIn("conflicting_stable_identifiers", review["flags"])

    def test_manual_override_is_applied_and_stale_override_is_reopened(self):
        candidate = self.candidate(sourceTypes=["ClinicalTrials"])
        review = automatic_review(candidate, "2026-08-10T00:00:00+00:00")
        accepted = apply_override(
            review,
            {
                "decision": "accepted",
                "candidateInputHash": candidate_input_hash(candidate),
                "reviewer": "tester",
                "reason": "Official site checked.",
            },
        )
        stale = apply_override(
            review,
            {"decision": "accepted", "candidateInputHash": "old-hash"},
        )

        self.assertEqual(accepted["decisionMode"], "manual")
        self.assertTrue(accepted["universeEligible"])
        self.assertEqual(stale["decision"], "needs_human")
        self.assertIn("stale_manual_override", stale["flags"])

    def test_build_summary_counts_human_exceptions(self):
        discovery = {
            "capturedAt": "2026-08-10T00:00:00+00:00",
            "candidates": [
                self.candidate(
                    id="candidate-sec",
                    identifiers={"cik": ["0001234567"]},
                    sourceTypes=["SEC"],
                ),
                self.candidate(id="candidate-trial", sourceTypes=["ClinicalTrials"]),
            ],
        }

        payload = build_reviews(discovery)

        self.assertEqual(payload["summary"]["acceptedCount"], 1)
        self.assertEqual(payload["summary"]["needsHumanCount"], 1)


if __name__ == "__main__":
    unittest.main()
