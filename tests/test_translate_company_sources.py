import unittest

from scripts.translate_company_sources import (
    TRANSLATION_POLICY_VERSION,
    collect_source_texts,
    merge_translations,
    select_pending,
    translate_pending,
)


class CompanySourceTranslationTests(unittest.TestCase):
    def setUp(self):
        self.source_payload = {
            "sources": [
                {
                    "companyId": "example-bio",
                    "sourceRole": "official",
                    "description": "Example Bio develops gene-editing medicines.",
                    "excerpts": ["The company plans to initiate a Phase 1 trial."],
                }
            ]
        }

    def test_collects_business_and_future_plan_text(self):
        items = collect_source_texts(self.source_payload)

        self.assertEqual(len(items), 2)
        fields = {use["field"] for item in items for use in item["sourceUses"]}
        self.assertEqual(fields, {"business_summary", "future_plan"})

    def test_skips_already_chinese_text(self):
        payload = {
            "sources": [
                {
                    "companyId": "example-bio",
                    "sourceRole": "official",
                    "description": "该公司开发基因编辑药物。",
                    "excerpts": [],
                }
            ]
        }

        self.assertEqual(collect_source_texts(payload), [])

    def test_current_cached_translation_is_not_pending(self):
        required = collect_source_texts(self.source_payload)
        cached = [
            {
                **item,
                "translationCn": "已有翻译",
                "translationPolicyVersion": TRANSLATION_POLICY_VERSION,
            }
            for item in required
        ]

        self.assertEqual(select_pending(required, {"translations": cached}), [])

    def test_changed_policy_is_pending(self):
        required = collect_source_texts(self.source_payload)
        cached = [
            {
                **item,
                "translationCn": "已有翻译",
                "translationPolicyVersion": "old-policy",
            }
            for item in required
        ]

        self.assertEqual(len(select_pending(required, {"translations": cached})), 2)

    def test_batches_and_merges_api_results(self):
        required = collect_source_texts(self.source_payload)
        calls = []

        def fake_caller(items, model, api_key):
            calls.append([item["id"] for item in items])
            return {
                "responseId": f"response-{len(calls)}",
                "translations": [
                    {"id": item["id"], "translationCn": f"中文：{item['sourceText']}"} for item in items
                ],
            }

        translated = translate_pending(
            required,
            model="test-model",
            api_key="test-key",
            batch_size=1,
            sleep_seconds=0,
            caller=fake_caller,
        )
        merged = merge_translations(
            required,
            {},
            translated,
            model="test-model",
            translated_at="2026-08-10T00:00:00+00:00",
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(merged), 2)
        self.assertTrue(all(item["provider"] == "openai" for item in merged))
        self.assertTrue(all(item["responseId"].startswith("response-") for item in merged))


if __name__ == "__main__":
    unittest.main()
