import unittest

from scripts.collect_clinicaltrials import parse_study


class ClinicalTrialsParsingTests(unittest.TestCase):
    def test_extracts_sponsor_and_collaborators_for_company_discovery(self):
        study = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT1", "briefTitle": "Test"},
                "statusModule": {},
                "sponsorCollaboratorsModule": {
                    "leadSponsor": {"name": "Example Therapeutics"},
                    "collaborators": [
                        {"name": "Partner Bio"},
                        {"name": "Partner Bio"},
                    ],
                },
            }
        }

        record = parse_study(study, "gene therapy")

        self.assertEqual(record["leadSponsor"], "Example Therapeutics")
        self.assertEqual(record["collaborators"], ["Partner Bio"])


if __name__ == "__main__":
    unittest.main()
