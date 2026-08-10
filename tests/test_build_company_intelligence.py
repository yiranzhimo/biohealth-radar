import json
import hashlib
import unittest

from scripts.build_company_intelligence import (
    build_company_profiles,
    build_company_universe,
    build_company_identity_links,
    build_evidence,
    build_official_source_evidence,
    build_products,
    build_program_candidates,
    discover_company_candidates,
    attach_candidate_reviews,
)


class CompanyIntelligenceBuilderTests(unittest.TestCase):
    def setUp(self):
        self.companies = [
            {
                "id": "known-bio",
                "name": "Known Bio",
                "aliases": ["Known Bio, Inc."],
                "ownership": "Public",
                "ticker": "KNWN",
                "exchange": "NASDAQ",
                "headquarters": "United States",
                "directions": ["Gene Editing"],
                "modalities": ["CRISPR"],
                "watchTier": "A",
                "officialUrl": "https://example.test",
                "irUrl": None,
                "pipelineUrl": None,
            }
        ]

    def test_builds_company_linked_evidence_and_profile(self):
        payload = {
            "updatedAt": "2026-08-10",
            "signals": [
                {
                    "id": "sec-1",
                    "companyIds": ["known-bio"],
                    "date": "2026-08-09",
                    "title": "Known Bio filed Form 8-K",
                    "eventType": "Corporate Update",
                    "sourceType": "Filing",
                    "sourceName": "SEC EDGAR",
                    "sourceUrl": "https://example.test/filing",
                    "reliability": "High",
                    "evidenceLevel": "Medium",
                    "needsReview": True,
                    "themes": ["Corporate Filings"],
                    "tags": ["SEC"],
                    "fact": "A filing exists.",
                    "report": "Metadata only.",
                    "inference": "No content inference.",
                    "unknown": "Filing content not extracted.",
                }
            ],
        }

        evidence = build_evidence(payload)
        profiles = build_company_profiles(payload, self.companies, evidence, [])

        self.assertEqual(evidence[0]["evidenceKind"], "Corporate Filing")
        self.assertEqual(profiles[0]["coverage"]["evidenceCount"], 1)
        self.assertEqual(profiles[0]["recentEvents"][0]["evidenceId"], "evidence-sec-1")

    def test_discovers_unmatched_company_like_trial_sponsor(self):
        clinical = {
            "capturedAt": "2026-08-10T00:00:00+00:00",
            "records": [
                {
                    "nctId": "NCT1",
                    "leadSponsor": "New Cell Therapeutics",
                    "interventions": ["NC-101"],
                    "phases": ["PHASE1"],
                    "lastUpdatePostDate": "2026-08-09",
                    "sourceUrl": "https://clinicaltrials.gov/study/NCT1",
                },
                {
                    "nctId": "NCT2",
                    "leadSponsor": "Example University Hospital",
                    "sourceUrl": "https://clinicaltrials.gov/study/NCT2",
                },
            ],
            "signals": [{"id": "clinicaltrials-NCT1", "themes": ["Cell Therapy"], "tags": []}],
        }

        candidates = discover_company_candidates(clinical, self.companies)

        self.assertEqual([item["name"] for item in candidates], ["New Cell Therapeutics"])
        self.assertEqual(candidates[0]["status"], "needs_review")

    def test_program_extraction_stays_candidate_and_does_not_claim_ownership(self):
        clinical = {
            "records": [
                {
                    "nctId": "NCT1",
                    "interventions": ["KB-101"],
                    "conditions": ["Rare disease"],
                    "phases": ["PHASE1"],
                    "overallStatus": "RECRUITING",
                    "sourceUrl": "https://clinicaltrials.gov/study/NCT1",
                }
            ],
            "signals": [{"id": "clinicaltrials-NCT1", "companyIds": ["known-bio"]}],
        }

        programs = build_program_candidates(clinical, self.companies)

        self.assertEqual(programs[0]["verificationStatus"], "candidate")
        self.assertFalse(programs[0]["ownershipVerified"])

    def test_official_page_is_attributed_report_not_verified_fact(self):
        source_payload = {
            "sources": [
                {
                    "companyId": "known-bio",
                    "companyName": "Known Bio",
                    "sourceRole": "official",
                    "resolvedUrl": "https://example.test/",
                    "title": "Known Bio",
                    "description": "Known Bio says it develops gene-editing medicines.",
                    "contentHash": "a" * 64,
                    "capturedAt": "2026-08-10T00:00:00+00:00",
                    "lastChangedAt": "2026-08-10T00:00:00+00:00",
                    "changeType": "new",
                    "excerpts": [],
                }
            ]
        }

        evidence = build_official_source_evidence(source_payload)
        profiles = build_company_profiles(
            {"updatedAt": "2026-08-10"}, self.companies, evidence, []
        )

        self.assertEqual(evidence[0]["sourceType"], "Company")
        self.assertTrue(evidence[0]["needsReview"])
        self.assertIn("公司官方页面表述", evidence[0]["report"])
        self.assertIn("尚未经过独立来源核验", evidence[0]["unknown"])
        self.assertEqual(profiles[0]["currentBusiness"]["status"], "company_reported")
        self.assertEqual(profiles[0]["currentBusiness"]["summaryType"], "Report")

    def test_official_business_and_plan_use_cached_chinese_translation(self):
        business = "Example Bio develops gene-editing medicines."
        plan = "The company plans to initiate a Phase 1 trial."
        source_payload = {
            "sources": [
                {
                    "companyId": "known-bio",
                    "companyName": "Known Bio",
                    "sourceRole": "official",
                    "resolvedUrl": "https://example.test/",
                    "title": "Known Bio",
                    "description": business,
                    "contentHash": "b" * 64,
                    "capturedAt": "2026-08-10T00:00:00+00:00",
                    "excerpts": [plan],
                }
            ]
        }
        translations = {
            "translations": [
                {
                    "sourceTextHash": hashlib.sha256(business.encode()).hexdigest(),
                    "sourceText": business,
                    "translationCn": "Example Bio 开发基因编辑药物。",
                    "provider": "openai",
                    "model": "test-model",
                    "translatedAt": "2026-08-10T00:00:00+00:00",
                },
                {
                    "sourceTextHash": hashlib.sha256(plan.encode()).hexdigest(),
                    "sourceText": plan,
                    "translationCn": "该公司计划启动一项 I 期试验。",
                    "provider": "openai",
                    "model": "test-model",
                    "translatedAt": "2026-08-10T00:00:00+00:00",
                },
            ]
        }

        evidence = build_official_source_evidence(source_payload, translations)
        profiles = build_company_profiles(
            {"updatedAt": "2026-08-10"}, self.companies, evidence, [], translations
        )

        current = profiles[0]["currentBusiness"]
        self.assertIn("开发基因编辑药物", current["summary"])
        self.assertEqual(current["summaryOriginal"], business)
        self.assertEqual(current["translationStatus"], "translated")
        self.assertEqual(profiles[0]["futureDirection"]["reportedPlans"][0]["text"], "该公司计划启动一项 I 期试验。")
        self.assertEqual(profiles[0]["futureDirection"]["reportedPlans"][0]["textOriginal"], plan)

    def test_discovery_candidates_and_mentions_flow_into_products(self):
        discovery = {
            "summary": {"mentionCount": 1},
            "mentions": [{"id": "mention-1"}],
            "candidates": [{"id": "candidate-new", "name": "New Bio"}],
        }

        products = build_products(
            {"updatedAt": "2026-08-10", "signals": []},
            self.companies,
            {},
            {},
            discovery,
        )

        candidates = json.loads(products["company_candidates.json"])["candidates"]
        mentions = json.loads(products["company_mentions.json"])["mentions"]
        self.assertEqual(candidates[0]["id"], "candidate-new")
        self.assertEqual(mentions[0]["id"], "mention-1")

    def test_candidate_reviews_control_universe_and_human_queue(self):
        candidates = [
            {"id": "candidate-accepted", "name": "Accepted Bio", "classificationHints": {}},
            {"id": "candidate-human", "name": "Unclear Bio", "classificationHints": {}},
        ]
        review_payload = {
            "reviews": [
                {
                    "candidateId": "candidate-accepted",
                    "decision": "accepted",
                    "humanReviewRequired": False,
                    "universeEligible": True,
                    "reviewScore": 0.95,
                },
                {
                    "candidateId": "candidate-human",
                    "decision": "needs_human",
                    "humanReviewRequired": True,
                    "universeEligible": False,
                    "reviewScore": 0.5,
                },
            ]
        }

        reviewed = attach_candidate_reviews(candidates, review_payload)
        universe = build_company_universe(self.companies, reviewed)

        self.assertEqual(reviewed[0]["id"], "candidate-human")
        self.assertEqual(len(universe), 2)
        self.assertEqual(
            {item["universeStatus"] for item in universe}, {"profiled", "accepted_pending_profile"}
        )

    def test_identity_links_keep_shared_identifiers_auditable(self):
        links = build_company_identity_links([
            {"id": "a", "name": "A", "identifiers": {"isin": ["US123"]}},
            {"id": "b", "name": "B", "identifiers": {"isin": ["US-123"]}},
        ])
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["entityIds"], ["a", "b"])
        self.assertTrue(links[0]["needsReview"])


if __name__ == "__main__":
    unittest.main()
