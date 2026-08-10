#!/usr/bin/env python3
"""Discover public biotech registrants through SEC SIC company feeds."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Any

try:
    from .http_utils import urlopen_with_retry
    from .local_config import local_setting
except ImportError:
    from http_utils import urlopen_with_retry
    from local_config import local_setting


SEC_BROWSE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SIC_CODES = {
    "2833": "Medicinal Chemicals and Botanical Products",
    "2834": "Pharmaceutical Preparations",
    "2835": "In Vitro and In Vivo Diagnostic Substances",
    "2836": "Biological Products, Except Diagnostic Substances",
}
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
CIK_TITLE_RE = re.compile(r"^(?P<form>.+?)\s+-\s+(?P<name>.+)\s+\((?P<cik>\d{6,10})\)\s*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover public biotech companies from SEC SIC registrants.")
    parser.add_argument("--sic", action="append", help="SEC SIC code; repeatable.")
    parser.add_argument("--count", type=int, default=100, help="Feed entries requested per SIC (max 100).")
    parser.add_argument(
        "--max-per-sic",
        type=int,
        default=500,
        help="Maximum registrant entries inspected per SIC across paginated feed requests.",
    )
    parser.add_argument("--output", default="data/raw/sec_company_universe_latest.json")
    parser.add_argument(
        "--user-agent",
        default=local_setting("SEC_USER_AGENT"),
        help="Declared SEC User-Agent including a contact email.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def request_bytes(url: str, user_agent: str, accept: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": accept,
            "Accept-Encoding": "gzip, deflate",
        },
    )
    with urlopen_with_retry(request, timeout=30) as response:
        body = response.read()
        encoding = response.headers.get("Content-Encoding", "").lower()
        if encoding == "gzip":
            return gzip.decompress(body)
        if encoding == "deflate":
            return zlib.decompress(body)
        return body


def ticker_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields = payload.get("fields", [])
    output: dict[str, dict[str, Any]] = {}
    for row in payload.get("data", []):
        item = dict(zip(fields, row))
        raw_cik = str(item.get("cik") or "").strip()
        if not raw_cik:
            continue
        cik = raw_cik.zfill(10)
        current = output.setdefault(cik, {"tickers": [], "exchanges": [], "secName": item.get("name")})
        ticker = str(item.get("ticker") or "").strip()
        exchange = str(item.get("exchange") or "").strip()
        if ticker and ticker not in current["tickers"]:
            current["tickers"].append(ticker)
        if exchange and exchange not in current["exchanges"]:
            current["exchanges"].append(exchange)
    return output


def parse_atom_feed(document: bytes, sic: str) -> list[dict[str, Any]]:
    root = ET.fromstring(document)
    records: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title = entry.findtext("atom:title", default="", namespaces=ATOM_NS).strip()
        match = CIK_TITLE_RE.match(title)
        company_info = entry.find(".//atom:company-info", ATOM_NS)
        cik = match.group("cik").zfill(10) if match else ""
        company_name = match.group("name").strip() if match else ""
        form = match.group("form").strip() if match else None
        if company_info is not None:
            raw_cik = company_info.findtext("atom:cik", default="", namespaces=ATOM_NS) or cik
            cik = raw_cik.zfill(10) if raw_cik else ""
            feed_name = str(company_info.get("name") or "").strip()
            if feed_name and not feed_name.startswith("ARRAY("):
                company_name = feed_name
        if not cik:
            continue
        link = entry.find("atom:link[@rel='alternate']", ATOM_NS)
        if link is None:
            link = entry.find("atom:link", ATOM_NS)
        updated = entry.findtext("atom:updated", default="", namespaces=ATOM_NS)
        records.append(
            {
                "cik": cik,
                "companyName": company_name,
                "form": form,
                "sicCodes": [sic],
                "sicLabels": [SIC_CODES.get(sic, "Unknown SEC industry")],
                "observedAt": updated[:10] or None,
                "sourceUrl": link.get("href") if link is not None else "https://www.sec.gov/edgar/search/",
            }
        )
    return records


def merge_records(records: list[dict[str, Any]], tickers: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_cik: dict[str, dict[str, Any]] = {}
    for record in records:
        cik = record["cik"]
        sec_identity = tickers.get(cik, {})
        company_name = str(sec_identity.get("secName") or record.get("companyName") or "").strip()
        if not company_name or company_name.startswith("ARRAY("):
            continue
        record = {**record, "companyName": company_name}
        current = by_cik.get(cik)
        if current is None:
            current = dict(record)
            current.update(sec_identity or {"tickers": [], "exchanges": [], "secName": record["companyName"]})
            by_cik[cik] = current
            continue
        current["sicCodes"] = sorted(set(current["sicCodes"]) | set(record["sicCodes"]))
        current["sicLabels"] = sorted(set(current["sicLabels"]) | set(record["sicLabels"]))
        if (record.get("observedAt") or "") > (current.get("observedAt") or ""):
            current.update(
                {
                    "companyName": record["companyName"],
                    "form": record["form"],
                    "observedAt": record["observedAt"],
                    "sourceUrl": record["sourceUrl"],
                }
            )
    return sorted(by_cik.values(), key=lambda item: (item.get("observedAt") or "", item["cik"]), reverse=True)


def collect(sic_codes: list[str], count: int, max_per_sic: int, user_agent: str) -> dict[str, Any]:
    ticker_payload = json.loads(request_bytes(TICKERS_URL, user_agent, "application/json").decode("utf-8"))
    tickers = ticker_map(ticker_payload)
    raw_records: list[dict[str, Any]] = []
    page_size = min(max(count, 1), 100)
    per_sic_limit = max(max_per_sic, 1)
    for sic in sic_codes:
        start = 0
        while start < per_sic_limit:
            requested_count = min(page_size, per_sic_limit - start)
            query = urllib.parse.urlencode(
                {
                    "action": "getcompany",
                    "SIC": sic,
                    "owner": "exclude",
                    "output": "atom",
                    "count": requested_count,
                    "start": start,
                }
            )
            # SEC fair-access guidance allows at most 10 requests/second.
            time.sleep(0.15)
            feed = request_bytes(f"{SEC_BROWSE_URL}?{query}", user_agent, "application/atom+xml")
            page_records = parse_atom_feed(feed, sic)
            raw_records.extend(page_records)
            if len(page_records) < requested_count:
                break
            start += requested_count
    records = merge_records(raw_records, tickers)
    return {
        "schemaVersion": "1.0",
        "capturedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "source": {
            "name": "SEC EDGAR",
            "type": "Corporate Registrant",
            "reliability": "High",
            "url": "https://www.sec.gov/edgar/search/",
        },
        "observedOn": dt.date.today().isoformat(),
        "sicCodes": {sic: SIC_CODES.get(sic, "Unknown SEC industry") for sic in sic_codes},
        "pageSize": page_size,
        "maxPerSic": per_sic_limit,
        "records": records,
    }


def main() -> int:
    args = parse_args()
    if not args.user_agent.strip():
        raise SystemExit("SEC_USER_AGENT is required and should include a real contact email.")
    sic_codes = args.sic or list(SIC_CODES)
    payload = collect(sic_codes, args.count, args.max_per_sic, args.user_agent)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.dry_run:
        print(serialized, end="")
    else:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(f"Collected {len(payload['records'])} public SEC biotech registrant candidate(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
