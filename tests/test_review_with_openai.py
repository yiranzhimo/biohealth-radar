import unittest

from scripts import review_with_openai as review


class ReviewPolicyTests(unittest.TestCase):
    def test_old_policy_reviews_are_selected_again(self):
        signals = [
            {"id": "old", "needsReview": True, "aiReview": {"status": "needs_human"}},
            {
                "id": "current",
                "needsReview": True,
                "aiReview": {"policyVersion": review.REVIEW_POLICY_VERSION},
            },
            {"id": "new", "needsReview": True},
        ]

        selected = review.select_candidates(signals, limit=10, force=False)

        self.assertEqual([signal["id"] for signal in selected], ["old", "new"])

    def test_all_pending_has_no_numeric_limit(self):
        signals = [{"id": str(index), "needsReview": True} for index in range(60)]

        selected = review.select_candidates(signals, limit=None, force=False)

        self.assertEqual(len(selected), 60)

    def test_pass_at_threshold_can_clear_review(self):
        result = {
            "status": "pass",
            "confidence": 0.85,
            "humanReviewRequired": False,
        }

        self.assertTrue(review.should_clear_review(result, threshold=0.85))

    def test_human_review_requirement_prevents_auto_clear(self):
        result = {
            "status": "pass",
            "confidence": 0.95,
            "humanReviewRequired": True,
        }

        self.assertFalse(review.should_clear_review(result, threshold=0.85))

    def test_new_human_requirement_reopens_ai_cleared_signal(self):
        signal = {"needsReview": False}
        result = {
            "status": "needs_human",
            "confidence": 0.9,
            "humanReviewRequired": True,
        }

        review.apply_review(
            signal,
            result,
            response_id="response-test",
            model="test-model",
            reviewed_at="2026-07-14T00:00:00+00:00",
            apply_needs_review=True,
            clear_threshold=0.85,
        )

        self.assertTrue(signal["needsReview"])

    def test_new_human_requirement_does_not_override_manual_review(self):
        signal = {"needsReview": False, "manualReview": {"status": "reviewed"}}
        result = {
            "status": "needs_human",
            "confidence": 0.9,
            "humanReviewRequired": True,
        }

        review.apply_review(
            signal,
            result,
            response_id="response-test",
            model="test-model",
            reviewed_at="2026-07-14T00:00:00+00:00",
            apply_needs_review=True,
            clear_threshold=0.85,
        )

        self.assertFalse(signal["needsReview"])

    def test_apply_review_records_policy_version(self):
        signal = {"needsReview": True}
        result = {
            "status": "pass",
            "confidence": 0.9,
            "humanReviewRequired": False,
        }

        review.apply_review(
            signal,
            result,
            response_id="response-test",
            model="test-model",
            reviewed_at="2026-07-14T00:00:00+00:00",
            apply_needs_review=True,
            clear_threshold=0.85,
        )

        self.assertFalse(signal["needsReview"])
        self.assertEqual(signal["aiReview"]["policyVersion"], review.REVIEW_POLICY_VERSION)


if __name__ == "__main__":
    unittest.main()
