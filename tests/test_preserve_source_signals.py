import unittest

from scripts.preserve_source_signals import preserve_signals


class PreserveSourceSignalsTests(unittest.TestCase):
    def test_preserves_missing_source_signals_without_overwriting_current(self):
        previous = {
            "signals": [
                {"id": "sec-old", "date": "2026-07-13", "value": "previous"},
                {"id": "pubmed-old", "date": "2026-07-13"},
            ]
        }
        current = {
            "signals": [
                {"id": "sec-current", "date": "2026-07-15"},
                {"id": "pubmed-new", "date": "2026-07-15"},
            ]
        }

        added = preserve_signals(previous, current, "sec-", max_signals=10)

        self.assertEqual(added, 1)
        ids = [signal["id"] for signal in current["signals"]]
        self.assertIn("sec-old", ids)
        self.assertNotIn("pubmed-old", ids)

    def test_caps_preserved_history(self):
        previous = {
            "signals": [
                {"id": "sec-1", "date": "2026-07-01"},
                {"id": "sec-2", "date": "2026-07-02"},
            ]
        }
        current = {"signals": [{"id": "sec-3", "date": "2026-07-03"}]}

        preserve_signals(previous, current, "sec-", max_signals=2)

        self.assertEqual([signal["id"] for signal in current["signals"]], ["sec-3", "sec-2"])


if __name__ == "__main__":
    unittest.main()
