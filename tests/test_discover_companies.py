import unittest

from scripts.discover_companies import build_discovery, normalized_company_name


class CompanyDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.companies = [
            {
                "id": "known-bio",
                "name": "Known Bio",
                "aliases": ["Known Bio, Inc."],
                "directions": ["Gene Editing"],
                "watchTier": "A",
                "officialUrl": "https://known.example",
            }
        ]

    def test_normalizes_legal_suffix_without_removing_business_term(self):
        self.assertEqual(normalized_company_name("Example Therapeutics, Inc."), "example therapeutics")

    def test_cross_source_candidate_is_corroborated_but_not_auto_promoted_without_threshold_rules(self):
        clinical = {
            "capturedAt": "2026-08-10T00:00:00+00:00",
            "records": [
                {
                    "nctId": "NCT1",
                    "leadSponsor": "Example Therapeutics, Inc.",
                    "interventions": ["EX-1"],
                    "phases": ["PHASE1"],
                    "overallStatus": "RECRUITING",
                    "lastUpdatePostDate": "2026-08-09",
                    "briefTitle": "Study of EX-1",
                    "sourceUrl": "https://clinicaltrials.gov/study/NCT1",
                }
            ],
            "signals": [{"id": "clinicaltrials-NCT1", "themes": ["Cell Therapy"], "tags": []}],
        }
        nih = {
            "capturedAt": "2026-08-10T00:00:00+00:00",
            "records": [
                {
                    "applId": 123,
                    "projectTitle": "Cell therapy development",
                    "awardNoticeDate": "2026-08-08",
                    "organization": {"name": "EXAMPLE THERAPEUTICS INC", "uei": "UEI1", "ipf": "IPF1"},
                    "matchedTerms": ["cell therapy"],
                    "topicHints": ["Cell Therapy"],
                    "sourceUrl": "https://reporter.nih.gov/project-details/123",
                }
            ],
        }

        payload = build_discovery(self.companies, clinical, {}, nih, {})

        self.assertEqual(len(payload["candidates"]), 1)
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["status"], "corroborated")
        self.assertEqual(candidate["sourceCount"], 2)
        self.assertTrue(candidate["autoPromotionEligible"])

    def test_known_company_mentions_are_retained_but_not_candidates(self):
        clinical = {
            "records": [
                {
                    "nctId": "NCT2",
                    "leadSponsor": "Known Bio, Inc.",
                    "sourceUrl": "https://clinicaltrials.gov/study/NCT2",
                }
            ]
        }

        payload = build_discovery(self.companies, clinical, {}, {}, {})

        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["mentions"][0]["knownCompanyIds"], ["known-bio"])

    def test_china_and_hong_kong_official_records_become_identified_candidates(self):
        asia = {
            "capturedAt": "2026-08-10T00:00:00+00:00",
            "sources": [
                {
                    "id": "csi-star-biology-medicine-constituents",
                    "observedOn": "2026-08-10",
                    "url": "https://www.csindex.com.cn/",
                    "records": [
                        {
                            "securityCode": "688331",
                            "companyNameCn": "荣昌生物",
                            "companyNameEn": "RemeGen Co., Ltd.",
                            "indexCode": "000683",
                            "indexName": "上证科创板生物医药指数",
                            "industryLevel1Cn": "医药卫生",
                            "observedOn": "2026-08-10",
                            "sourceUrl": "https://www.csindex.com.cn/",
                        }
                    ],
                },
                {
                    "id": "hkex-active-biotech-marker",
                    "observedOn": "2026-08-10",
                    "url": "https://www.hkex.com.hk/Products/Securities/Equities?sc_lang=en",
                    "records": [
                        {
                            "stockCode": "01167",
                            "issuerShortNameEn": "JACOBIO",
                            "securityName": "JACOBIO-B",
                            "isin": "KYG4987A1094",
                            "observedOn": "2026-08-10",
                            "sourceUrl": "https://www.hkex.com.hk/Products/Securities/Equities?sc_lang=en",
                        }
                    ],
                },
                {
                    "id": "hsi-biotech-constituents",
                    "observedOn": "2026-07-31",
                    "url": "https://www.hsi.com.hk/eng/indexes/all-indexes/hsbio",
                    "records": [
                        {
                            "stockCode": "09688",
                            "issuerShortNameEn": "ZAI LAB",
                            "securityName": "ZAI LAB",
                            "isin": "KYG9887T1168",
                            "observedOn": "2026-07-31",
                            "sourceUrl": "https://www.hsi.com.hk/static/example.pdf",
                        }
                    ],
                },
            ],
        }

        payload = build_discovery(self.companies, {}, {}, {}, {}, china_hk_payload=asia)

        self.assertEqual(
            payload["summary"]["mentionsBySource"],
            {"CSI": 2, "HKEX": 1, "HSI": 1},
        )
        self.assertEqual(len(payload["candidates"]), 3)
        identifiers = [candidate["identifiers"] for candidate in payload["candidates"]]
        self.assertTrue(any(item.get("cnSecurityCode") == ["688331"] for item in identifiers))
        self.assertTrue(any(item.get("hkexStockCode") == ["01167"] for item in identifiers))
        self.assertTrue(any(item.get("hkexStockCode") == ["09688"] for item in identifiers))


if __name__ == "__main__":
    unittest.main()
