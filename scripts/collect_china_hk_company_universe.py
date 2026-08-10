#!/usr/bin/env python3
"""Collect a bounded China/Hong Kong biotech company seed universe from official sources."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    from .http_utils import urlopen_with_retry
except ImportError:
    from http_utils import urlopen_with_retry


CSI_INDEX_CODE = "000683"
CSI_BASE_URL = "https://www.csindex.com.cn/csindex-home"
CSI_INDEX_URL = f"https://www.csindex.com.cn/#/indices/family/detail?indexCode={CSI_INDEX_CODE}"
CSI_DETAILS_URL = (
    f"{CSI_BASE_URL}/indexInfo/index-details-data?fileLang=2&indexCode={CSI_INDEX_CODE}"
)
HKEX_SECURITIES_URL = (
    "https://www.hkex.com.hk/eng/services/trading/securities/"
    "securitieslists/ListOfSecurities.xlsx"
)
HKEX_EQUITIES_URL = "https://www.hkex.com.hk/Products/Securities/Equities?sc_lang=en"
HSI_BIOTECH_FACTSHEET_URL = (
    "https://www.hsi.com.hk/static/uploads/contents/en/dl_centre/factsheets/hsbioe.pdf"
)
HSI_BIOTECH_INDEX_URL = "https://www.hsi.com.hk/eng/indexes/all-indexes/hsbio"
USER_AGENT = "BioHealthRadar/0.1 (official company discovery)"
XML_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
BIOTECH_MARKER_RE = re.compile(r"\s*-\s*(?:S)?B$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover China and Hong Kong biotech issuers from official market sources."
    )
    parser.add_argument("--output", default="data/raw/china_hk_company_universe_latest.json")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def request_bytes(url: str, timeout: float, accept: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"Accept": accept, "User-Agent": USER_AGENT},
    )
    with urlopen_with_retry(request, timeout=timeout) as response:
        return response.read()


def request_json(url: str, timeout: float) -> dict[str, Any]:
    return json.loads(request_bytes(url, timeout, "application/json").decode("utf-8"))


def csi_constituent_file_url(payload: dict[str, Any]) -> str:
    if str(payload.get("code")) != "200" or not payload.get("success"):
        raise ValueError(f"CSI response was unsuccessful: {payload.get('msg') or payload.get('code')}")
    files = (payload.get("data") or {}).get("样本列表") or []
    url = next((str(item.get("filePath") or "").strip() for item in files if item.get("filePath")), "")
    if not url:
        raise ValueError("CSI response did not include a constituent-list file URL")
    return url


def parse_csi_date(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 8:
        return ""
    try:
        return dt.datetime.strptime(digits, "%Y%m%d").date().isoformat()
    except ValueError:
        return ""


def parse_csi_rows(rows: list[list[Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Parse rows from CSI's official constituent list.

    Kept separate from the binary XLS reader so the field mapping stays unit-testable.
    """
    if not rows:
        raise ValueError("CSI constituent list was empty")
    observed_on = next((parse_csi_date(row[0]) for row in rows[1:] if row), "")
    records = []
    for row in rows[1:]:
        padded = [*row, *([""] * max(0, 9 - len(row)))]
        row_date, index_code, index_name_cn, index_name_en, code, name_cn, name_en, exchange_cn, exchange_en = (
            str(value or "").strip() for value in padded[:9]
        )
        if not code or not name_cn:
            continue
        records.append(
            {
                "market": "CN",
                "exchange": "SSE",
                "securityCode": code,
                "companyNameCn": name_cn,
                "companyNameEn": name_en or None,
                "nameQuality": "official_constituent_name",
                "indexCode": index_code or CSI_INDEX_CODE,
                "indexName": index_name_cn or "科创生物",
                "indexNameEn": index_name_en or "STAR Biology and Medicine",
                "exchangeNameCn": exchange_cn or None,
                "exchangeNameEn": exchange_en or None,
                "observedOn": parse_csi_date(row_date) or observed_on or None,
                "sourceUrl": CSI_DETAILS_URL,
            }
        )
    return observed_on, records


def parse_csi_records(content: bytes) -> tuple[str, list[dict[str, Any]]]:
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError(
            "xlrd is required to parse the CSI .xls file; install requirements-company-discovery.txt"
        ) from exc
    workbook = xlrd.open_workbook(file_contents=content)
    sheet = workbook.sheet_by_index(0)
    return parse_csi_rows([sheet.row_values(index) for index in range(sheet.nrows)])


def column_name(cell_reference: str) -> str:
    match = re.match(r"[A-Z]+", cell_reference)
    return match.group(0) if match else ""


def shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(node.itertext()) for node in root.findall("x:si", XML_NS)]


def cell_value(cell: ET.Element, strings: list[str]) -> str:
    value_node = cell.find("x:v", XML_NS)
    if cell.get("t") == "inlineStr":
        return "".join(cell.itertext()).strip()
    if value_node is None or value_node.text is None:
        return ""
    value = value_node.text.strip()
    if cell.get("t") == "s":
        try:
            return strings[int(value)]
        except (IndexError, ValueError):
            return ""
    return value


def parse_xlsx_rows(content: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        strings = shared_strings(archive)
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows: list[dict[str, str]] = []
    for row in root.findall(".//x:sheetData/x:row", XML_NS):
        values = {
            column_name(str(cell.get("r") or "")): cell_value(cell, strings)
            for cell in row.findall("x:c", XML_NS)
        }
        rows.append(values)
    return rows


def parse_hkex_date(value: str) -> str:
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if not match:
        return ""
    day, month, year = (int(part) for part in match.groups())
    return dt.date(year, month, day).isoformat()


def issuer_short_name(stock_name: str) -> str:
    return BIOTECH_MARKER_RE.sub("", stock_name).strip()


def parse_hkex_records(content: bytes) -> tuple[str, list[dict[str, Any]]]:
    rows = parse_xlsx_rows(content)
    observed_on = next((parse_hkex_date(row.get("A", "")) for row in rows if parse_hkex_date(row.get("A", ""))), "")
    records = []
    for row in rows:
        stock_code = row.get("A", "").strip()
        stock_name = row.get("B", "").strip()
        category = row.get("C", "").strip()
        sub_category = row.get("D", "").strip()
        if category != "Equity" or not BIOTECH_MARKER_RE.search(stock_name):
            continue
        records.append(
            {
                "market": "HK",
                "exchange": "HKEX",
                "stockCode": stock_code,
                "issuerShortNameEn": issuer_short_name(stock_name),
                "securityName": stock_name,
                "nameQuality": "official_trading_short_name",
                "legalNameStatus": "unresolved",
                "biotechMarker": stock_name[len(issuer_short_name(stock_name)) :],
                "isin": row.get("F", "").strip() or None,
                "category": category,
                "subCategory": sub_category,
                "observedOn": observed_on or None,
                "sourceUrl": (
                    "https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/"
                    f"Equities-Quote?sym={int(stock_code)}&sc_lang=en"
                    if stock_code.isdigit()
                    else HKEX_EQUITIES_URL
                ),
            }
        )
    records.sort(key=lambda item: item["stockCode"])
    return observed_on, records


def parse_hsi_date(text: str) -> str:
    match = re.search(r"All data as at\s+(\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})", text)
    if not match:
        return ""
    try:
        return dt.datetime.strptime(match.group(1), "%d %b %Y").date().isoformat()
    except ValueError:
        return ""


def parse_hsi_text(pages: list[str]) -> tuple[str, list[dict[str, Any]]]:
    text = "\n".join(pages)
    observed_on = parse_hsi_date(text)
    row_re = re.compile(
        r"^(\d{1,5})\s+([A-Z0-9]{12})\s+(.+?)\s+Healthcare\s+(\d+(?:\.\d+)?)$"
    )
    records = []
    for line in text.splitlines():
        match = row_re.match(line.strip())
        if not match:
            continue
        stock_code, isin, company_name, weight = match.groups()
        records.append(
            {
                "market": "HK",
                "exchange": "HKEX",
                "stockCode": stock_code.zfill(5),
                "issuerShortNameEn": issuer_short_name(company_name),
                "securityName": company_name,
                "nameQuality": "official_index_name",
                "legalNameStatus": "unresolved",
                "isin": isin,
                "weight": float(weight),
                "industryClassification": "Healthcare",
                "observedOn": observed_on or None,
                "sourceUrl": HSI_BIOTECH_FACTSHEET_URL,
            }
        )
    records.sort(key=lambda item: item["stockCode"])
    if not records:
        raise ValueError("Hang Seng Biotech Index factsheet contained no constituent rows")
    return observed_on, records


def parse_hsi_records(content: bytes) -> tuple[str, list[dict[str, Any]]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "pypdf is required to parse the HSI factsheet; install requirements-company-discovery.txt"
        ) from exc
    reader = PdfReader(BytesIO(content))
    return parse_hsi_text([page.extract_text() or "" for page in reader.pages])


def collect(timeout: float = 30.0) -> dict[str, Any]:
    csi_details = request_json(CSI_DETAILS_URL, timeout)
    csi_file_url = csi_constituent_file_url(csi_details)
    csi_content = request_bytes(csi_file_url, timeout, "application/vnd.ms-excel")
    hkex_content = request_bytes(
        HKEX_SECURITIES_URL,
        timeout,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    hsi_content = request_bytes(HSI_BIOTECH_FACTSHEET_URL, timeout, "application/pdf")
    csi_observed_on, csi_records = parse_csi_records(csi_content)
    hkex_observed_on, hkex_records = parse_hkex_records(hkex_content)
    hsi_observed_on, hsi_records = parse_hsi_records(hsi_content)
    hong_kong_security_codes = {
        str(record.get("stockCode") or "") for record in [*hkex_records, *hsi_records]
    }
    captured_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    return {
        "schemaVersion": "1.0",
        "kind": "china_hk_biotech_company_universe",
        "capturedAt": captured_at,
        "summary": {
            "recordCount": len(csi_records) + len(hkex_records) + len(hsi_records),
            "chinaRecordCount": len(csi_records),
            "hongKongRecordCount": len(hkex_records),
            "hongKongIndexRecordCount": len(hsi_records),
            "hongKongUniqueSecurityCount": len(hong_kong_security_codes),
            "uniqueSecurityCount": len(csi_records) + len(hong_kong_security_codes),
        },
        "sources": [
            {
                "id": "csi-star-biology-medicine-constituents",
                "name": "中证指数有限公司",
                "type": "Official Biotech Index",
                "reliability": "High",
                "url": CSI_INDEX_URL,
                "observedOn": csi_observed_on or None,
                "coverage": "上证科创板生物医药指数当日全部成分股，不是全部中国 biotech 公司。",
                "records": csi_records,
            },
            {
                "id": "hkex-active-biotech-marker",
                "name": "Hong Kong Exchanges and Clearing Limited",
                "type": "Official Securities List",
                "reliability": "High",
                "url": HKEX_SECURITIES_URL,
                "observedOn": hkex_observed_on or None,
                "coverage": (
                    "当前证券简称仍带 B/SB 标记的港交所股票；名称为官方交易简称，"
                    "不是法定全称；不包含已转为一般上市的历史 18A 公司。"
                ),
                "records": hkex_records,
            },
            {
                "id": "hsi-biotech-constituents",
                "name": "Hang Seng Indexes Company Limited",
                "type": "Official Biotech Index",
                "reliability": "High",
                "url": HSI_BIOTECH_INDEX_URL,
                "observedOn": hsi_observed_on or None,
                "coverage": (
                    "恒生生物科技指数当前 30 家成分公司，覆盖部分已移除 B 标记的成熟公司；"
                    "仅覆盖符合港股通资格且按该指数方法筛选的最大公司。"
                ),
                "records": hsi_records,
            },
        ],
    }


def main() -> int:
    args = parse_args()
    payload = collect(args.timeout)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.dry_run:
        print(serialized, end="")
    else:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    summary = payload["summary"]
    print(
        f"Collected {summary['chinaRecordCount']} China and "
        f"{summary['hongKongRecordCount']} HKEX marker plus "
        f"{summary['hongKongIndexRecordCount']} HSI biotech issuer record(s)."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, zipfile.BadZipFile, ET.ParseError) as exc:
        print(f"collect_china_hk_company_universe.py failed: {exc}")
        raise SystemExit(1)
