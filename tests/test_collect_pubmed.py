import datetime as dt
import unittest
import xml.etree.ElementTree as ET

from scripts import collect_pubmed as pubmed


class PubMedDateTests(unittest.TestCase):
    def test_parses_complete_publication_date(self):
        node = ET.fromstring("<PubDate><Year>2026</Year><Month>Aug</Month><Day>9</Day></PubDate>")

        self.assertEqual(pubmed.parse_date_node(node), "2026-08-09")

    def test_zero_day_falls_back_to_first_of_month(self):
        node = ET.fromstring("<PubDate><Year>2026</Year><Month>08</Month><Day>00</Day></PubDate>")

        self.assertEqual(pubmed.parse_date_node(node), "2026-08-01")

    def test_invalid_calendar_day_falls_back_to_first_of_month(self):
        node = ET.fromstring("<PubDate><Year>2026</Year><Month>Feb</Month><Day>31</Day></PubDate>")

        self.assertEqual(pubmed.parse_date_node(node), "2026-02-01")

    def test_invalid_month_falls_back_to_first_of_year(self):
        node = ET.fromstring("<PubDate><Year>2026</Year><Month>00</Month><Day>12</Day></PubDate>")

        self.assertEqual(pubmed.parse_date_node(node), "2026-01-01")

    def test_every_emitted_date_is_iso_parseable(self):
        samples = [
            "<PubDate><Year>2026</Year><Month>6</Month></PubDate>",
            "<PubDate><Year>2026</Year></PubDate>",
            "<PubDate><MedlineDate>2025 Winter</MedlineDate></PubDate>",
        ]

        for sample in samples:
            with self.subTest(sample=sample):
                dt.date.fromisoformat(pubmed.parse_date_node(ET.fromstring(sample)))
