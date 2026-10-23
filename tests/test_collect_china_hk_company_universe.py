import unittest
import zipfile
from io import BytesIO
from unittest.mock import patch

from scripts.collect_china_hk_company_universe import (
    HSI_BIOTECH_FACTSHEET_URL,
    HSI_FACTSHEET_MANIFEST_URL,
    collect,
    csi_constituent_file_url,
    fetch_hsi,
    hsi_factsheet_url,
    issuer_short_name,
    parse_csi_rows,
    parse_hkex_records,
    parse_hsi_text,
)


def xlsx_fixture(rows):
    cells = []
    for row_number, row in enumerate(rows, start=1):
        row_cells = "".join(
            f'<c r="{column}{row_number}" t="str"><v>{value}</v></c>'
            for column, value in row.items()
        )
        cells.append(f'<row r="{row_number}">{row_cells}</row>')
    sheet = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(cells)}</sheetData></worksheet>'
    )
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


class ChinaHkCompanyUniverseCollectorTests(unittest.TestCase):
    def test_finds_csi_constituent_file(self):
        payload = {
            "code": "200",
            "success": True,
            "data": {
                "样本列表": [
                    {
                        "filePath": "https://example.test/000683cons.xls",
                    }
                ],
            },
        }
        self.assertEqual(
            csi_constituent_file_url(payload),
            "https://example.test/000683cons.xls",
        )

    def test_parses_csi_constituent_rows(self):
        rows = [
            ["日期Date", "指数代码 Index Code", "指数名称 Index Name"],
            [
                "20260810",
                "000683",
                "科创生物",
                "STAR Biology and Medicine",
                "688235",
                "百济神州",
                "BeiGene, Ltd.",
                "上海证券交易所",
                "Shanghai Stock Exchange",
            ],
        ]

        observed_on, records = parse_csi_rows(rows)

        self.assertEqual(observed_on, "2026-08-10")
        self.assertEqual(records[0]["companyNameCn"], "百济神州")
        self.assertEqual(records[0]["securityCode"], "688235")
        self.assertEqual(records[0]["companyNameEn"], "BeiGene, Ltd.")

    def test_hkex_parser_keeps_only_equities_with_biotech_marker(self):
        content = xlsx_fixture(
            [
                {"A": "Updated as at 10/08/2026"},
                {"A": "Stock Code", "B": "Name of Securities", "C": "Category"},
                {
                    "A": "01167",
                    "B": "JACOBIO-B",
                    "C": "Equity",
                    "D": "Equity Securities (Main Board)",
                    "F": "KYG5007D1034",
                },
                {"A": "09688", "B": "ZAI LAB-SB", "C": "Equity", "F": "US98887Q1040"},
                {"A": "10001", "B": "BANK-B", "C": "Derivative Warrant"},
                {"A": "00013", "B": "HUTCHMED", "C": "Equity"},
            ]
        )

        observed_on, records = parse_hkex_records(content)

        self.assertEqual(observed_on, "2026-08-10")
        self.assertEqual([item["stockCode"] for item in records], ["01167", "09688"])
        self.assertEqual(records[1]["issuerShortNameEn"], "ZAI LAB")
        self.assertEqual(records[0]["nameQuality"], "official_trading_short_name")
        self.assertEqual(records[0]["legalNameStatus"], "unresolved")

    def test_removes_only_terminal_biotech_marker(self):
        self.assertEqual(issuer_short_name("JACOBIO-B"), "JACOBIO")
        self.assertEqual(issuer_short_name("ZAI LAB-SB"), "ZAI LAB")
        self.assertEqual(issuer_short_name("DUALITYBIO - B"), "DUALITYBIO")
        self.assertEqual(issuer_short_name("UNI-BIO GROUP"), "UNI-BIO GROUP")

    def test_parses_hsi_biotech_constituents(self):
        pages = [
            "All data as at 31 Jul 2026",
            "\n".join(
                [
                    "CONSTITUENTS",
                    "6160 CH1391448177 BEONE MEDICINES Healthcare 10.81",
                    "9606 KYG2929M1087 DUALITYBIO - B Healthcare 1.38",
                    "Total 100.00",
                ]
            ),
        ]

        observed_on, records = parse_hsi_text(pages)

        self.assertEqual(observed_on, "2026-07-31")
        self.assertEqual([item["stockCode"] for item in records], ["06160", "09606"])
        self.assertEqual(records[1]["issuerShortNameEn"], "DUALITYBIO")
        self.assertEqual(records[0]["isin"], "CH1391448177")

    def test_resolves_hsi_factsheet_from_official_manifest(self):
        manifest = {"data": [{"seriesCode": "hsbio", "fileEng": "/public-website/webapp/factsheets/en-hk/hsbio.pdf"}]}
        self.assertEqual(hsi_factsheet_url(manifest), HSI_BIOTECH_FACTSHEET_URL)
        with (
            patch("scripts.collect_china_hk_company_universe.request_json", return_value=manifest) as request_json,
            patch("scripts.collect_china_hk_company_universe.request_bytes", return_value=b"pdf") as request_bytes,
            patch("scripts.collect_china_hk_company_universe.parse_hsi_records", return_value=("2026-09-30", [{"stockCode": "06160"}])) as parse_records,
        ):
            fetch_hsi(10)
        request_json.assert_called_once_with(HSI_FACTSHEET_MANIFEST_URL, 10)
        request_bytes.assert_called_once_with(HSI_BIOTECH_FACTSHEET_URL, 10, "application/pdf")
        parse_records.assert_called_once_with(b"pdf", HSI_BIOTECH_FACTSHEET_URL)

    def test_rejects_invalid_hsi_factsheet_manifest_path(self):
        with self.assertRaisesRegex(ValueError, "valid HSBIO English PDF"):
            hsi_factsheet_url({"data": [{"seriesCode": "hsbio", "fileEng": "https://elsewhere.test/file.pdf"}]})

    def test_failed_hsi_refresh_keeps_prior_records_while_other_sources_update(self):
        previous_hsi = {
            "id": "hsi-biotech-constituents",
            "observedOn": "2026-08-31",
            "records": [{"stockCode": "06160"}],
        }
        previous = {
            "capturedAt": "2026-10-02T09:48:31+00:00",
            "sources": [previous_hsi],
        }
        with (
            patch("scripts.collect_china_hk_company_universe.fetch_csi", return_value=("2026-10-23", [{"securityCode": "688235"}])),
            patch("scripts.collect_china_hk_company_universe.fetch_hkex", return_value=("2026-10-23", [{"stockCode": "09688"}])),
            patch("scripts.collect_china_hk_company_universe.fetch_hsi", side_effect=OSError("HTTP Error 404")),
        ):
            payload = collect(previous=previous)

        sources = {source["id"]: source for source in payload["sources"]}
        hsi = sources["hsi-biotech-constituents"]
        self.assertEqual(hsi["records"], previous_hsi["records"])
        self.assertEqual(hsi["observedOn"], "2026-08-31")
        self.assertEqual(hsi["refreshStatus"], "carried_forward")
        self.assertEqual(hsi["lastSuccessfulCaptureAt"], previous["capturedAt"])
        self.assertEqual(sources["hkex-active-biotech-marker"]["refreshStatus"], "fresh")
        self.assertEqual(payload["summary"]["recordCount"], 3)

    def test_failed_source_without_prior_records_still_fails(self):
        with patch("scripts.collect_china_hk_company_universe.fetch_csi", side_effect=OSError("HTTP Error 404")):
            with self.assertRaisesRegex(RuntimeError, "no prior records"):
                collect()

    def test_all_sources_failed_still_fails(self):
        previous = {
            "capturedAt": "2026-10-02T09:48:31+00:00",
            "sources": [
                {"id": source_id, "records": [{"stockCode": "1"}]}
                for source_id in (
                    "csi-star-biology-medicine-constituents",
                    "hkex-active-biotech-marker",
                    "hsi-biotech-constituents",
                )
            ],
        }
        with (
            patch("scripts.collect_china_hk_company_universe.fetch_csi", side_effect=OSError("HTTP Error 404")),
            patch("scripts.collect_china_hk_company_universe.fetch_hkex", side_effect=OSError("HTTP Error 404")),
            patch("scripts.collect_china_hk_company_universe.fetch_hsi", side_effect=OSError("HTTP Error 404")),
        ):
            with self.assertRaisesRegex(RuntimeError, "all China/Hong Kong company sources failed"):
                collect(previous=previous)


if __name__ == "__main__":
    unittest.main()
