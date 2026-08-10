import unittest
from unittest.mock import patch

from scripts.collect_sec_company_universe import collect, merge_records, parse_atom_feed, ticker_map


class SecCompanyUniverseCollectorTests(unittest.TestCase):
    def test_parses_hyphenated_form_from_atom_title(self):
        document = b"""<?xml version='1.0'?>
        <feed xmlns='http://www.w3.org/2005/Atom'>
          <entry>
            <title>10-K - Example Therapeutics, Inc. (0001234567)</title>
            <updated>2026-08-09T12:00:00-04:00</updated>
            <link rel='alternate' href='https://www.sec.gov/Archives/example'/>
          </entry>
        </feed>"""

        records = parse_atom_feed(document, "2834")

        self.assertEqual(records[0]["form"], "10-K")
        self.assertEqual(records[0]["cik"], "0001234567")
        self.assertEqual(records[0]["observedAt"], "2026-08-09")

    def test_recovers_cik_when_sec_feed_name_is_broken(self):
        document = b"""<feed xmlns='http://www.w3.org/2005/Atom'><entry>
          <title>ARRAY(0x123)</title><updated>2026-08-10T00:00:00-04:00</updated>
          <content type='text/xml'><company-info name='ARRAY(0x456)'>
            <cik>0001234567</cik><sic>2834</sic>
          </company-info></content>
          <link href='https://www.sec.gov/cgi-bin/browse-edgar?CIK=0001234567'/>
        </entry></feed>"""

        records = parse_atom_feed(document, "2834")

        self.assertEqual(records[0]["cik"], "0001234567")
        self.assertEqual(records[0]["companyName"], "")

    def test_attaches_ticker_and_exchange_by_cik(self):
        mapping = ticker_map(
            {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [[1234567, "Example Therapeutics", "EXMP", "Nasdaq"]],
            }
        )
        records = merge_records(
            [
                {
                    "cik": "0001234567",
                    "companyName": "Example Therapeutics",
                    "form": "10-K",
                    "sicCodes": ["2834"],
                    "sicLabels": ["Pharmaceutical Preparations"],
                    "observedAt": "2026-08-09",
                    "sourceUrl": "https://www.sec.gov/example",
                }
            ],
            mapping,
        )

        self.assertEqual(records[0]["tickers"], ["EXMP"])

    @patch("scripts.collect_sec_company_universe.time.sleep")
    @patch("scripts.collect_sec_company_universe.request_bytes")
    def test_collect_paginates_until_short_page(self, request_bytes, sleep):
        ticker_payload = b'{"fields":["cik","name","ticker","exchange"],"data":[]}'

        def feed(start_cik: int, count: int) -> bytes:
            entries = "".join(
                f"<entry><title>10-K - Company {index} ({index:010d})</title>"
                f"<updated>2026-08-10T00:00:00-04:00</updated></entry>"
                for index in range(start_cik, start_cik + count)
            )
            return f"<feed xmlns='http://www.w3.org/2005/Atom'>{entries}</feed>".encode()

        request_bytes.side_effect = [ticker_payload, feed(1, 2), feed(3, 1)]

        payload = collect(["2834"], count=2, max_per_sic=10, user_agent="Radar test@example.com")

        self.assertEqual(len(payload["records"]), 3)
        self.assertEqual(payload["pageSize"], 2)
        self.assertEqual(payload["maxPerSic"], 10)
        feed_urls = [call.args[0] for call in request_bytes.call_args_list[1:]]
        self.assertIn("start=0", feed_urls[0])
        self.assertIn("start=2", feed_urls[1])
        self.assertEqual(sleep.call_count, 2)

    @patch("scripts.collect_sec_company_universe.time.sleep")
    @patch("scripts.collect_sec_company_universe.request_bytes")
    def test_collect_respects_maximum_per_sic(self, request_bytes, _sleep):
        ticker_payload = b'{"fields":["cik","name","ticker","exchange"],"data":[]}'

        def feed(start_cik: int, count: int) -> bytes:
            entries = "".join(
                f"<entry><title>10-K - Company {index} ({index:010d})</title>"
                f"<updated>2026-08-10T00:00:00-04:00</updated></entry>"
                for index in range(start_cik, start_cik + count)
            )
            return f"<feed xmlns='http://www.w3.org/2005/Atom'>{entries}</feed>".encode()

        request_bytes.side_effect = [ticker_payload, feed(1, 2), feed(3, 1)]

        payload = collect(["2834"], count=2, max_per_sic=3, user_agent="Radar test@example.com")

        self.assertEqual(len(payload["records"]), 3)
        feed_urls = [call.args[0] for call in request_bytes.call_args_list[1:]]
        self.assertIn("count=1", feed_urls[1])


if __name__ == "__main__":
    unittest.main()
