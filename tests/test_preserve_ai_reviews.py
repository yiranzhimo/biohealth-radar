import unittest

from scripts.preserve_ai_reviews import preserve_reviews
from scripts.review_fingerprint import review_input_hash


class PreserveAiReviewsTests(unittest.TestCase):
    def test_preserves_reviews_when_review_input_is_unchanged(self):
        prior_signal = {
            "id": "clinicaltrials-NCT1",
            "title": "Stable title",
            "needsReview": False,
            "aiReview": {"policyVersion": "publication-quality-v2"},
            "manualReview": {"status": "reviewed"},
        }
        current_signal = {
            "id": "clinicaltrials-NCT1",
            "title": "Stable title",
            "needsReview": True,
        }

        counts = preserve_reviews(
            {"signals": [prior_signal]},
            {"signals": [current_signal]},
        )

        self.assertEqual(counts, (1, 1, 1, 0))
        self.assertFalse(current_signal["needsReview"])
        self.assertEqual(current_signal["aiReview"]["inputHash"], review_input_hash(current_signal))
        self.assertEqual(current_signal["manualReview"]["inputHash"], review_input_hash(current_signal))

    def test_changed_content_does_not_inherit_review(self):
        prior_signal = {
            "id": "clinicaltrials-NCT1",
            "title": "Old title",
            "needsReview": False,
            "aiReview": {"policyVersion": "publication-quality-v2"},
            "manualReview": {"status": "reviewed"},
        }
        current_signal = {
            "id": "clinicaltrials-NCT1",
            "title": "Updated title",
            "needsReview": False,
            "aiReview": {"status": "stale"},
            "manualReview": {"status": "reviewed"},
        }

        counts = preserve_reviews(
            {"signals": [prior_signal]},
            {"signals": [current_signal]},
        )

        self.assertEqual(counts, (0, 0, 0, 1))
        self.assertTrue(current_signal["needsReview"])
        self.assertNotIn("aiReview", current_signal)
        self.assertNotIn("manualReview", current_signal)


if __name__ == "__main__":
    unittest.main()
