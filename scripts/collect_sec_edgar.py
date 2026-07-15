#!/usr/bin/env python3
"""Collect recent SEC EDGAR filings for companies in the BioHealth Radar watchlist.

This collector treats EDGAR metadata as proof that a filing exists. It does not
infer clinical, regulatory, commercial, or investment conclusions from a form.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Iterable

try:
    from .company_registry import load_companies
except ImportError:
    from company_registry import load_companies


TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
DEFAULT_FORMS = {"8-K", "6-K", "10-Q", "10-K", "20-F", "S-1", "F-1", "424B1", "424B2", "424B3", "424B4", "424B5"}

SEC_SOURCE = {
    "name": "SEC EDGAR",
    "type": "Filing",
    "cadence": "6h",
    "reliability": "High",
    "url": "https://www.sec.gov/edgar/search/",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect recent SEC filings for watched biotech companies.")
    parser.add_argument("--days", type=int, default=14, help="Filing-date lookback window.")
    parser.add_argument("--max-total", type=int, default=80, help="Maximum recent filings to emit.")
    parser.add_argument("--max-stored", type=int, default=120, help="Maximum SEC signals retained in data.js.")
    parser.add_argument("--form", action="append", help="Override watched form types; may be repeated.")
    parser.add_argument("--company", action="append", help="Only collect these company IDs; may be repeated.")
    parser.add_argument("--tier", action="append", help="Watch tiers to collect; defaults to A and B.")
    parser.add_argument("--registry", default="data/companies.json", help="Company registry JSON file.")
    parser.add_argument("--data-file", default="data.js", help="Frontend data.js file to merge into.")
    parser.add_argument("--raw-output", default="data/raw/sec_latest.json", help="Raw filing metadata JSON.")
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("SEC_USER_AGENT", ""),
        help="Declared SEC User-Agent. Prefer 'Project Name contact@example.com'.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and classify without writing files.")
    return parser.parse_args()


def request_json(url: str, user_agent: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            encoding = response.headers.get("Content-Encoding", "").lower()
            if encoding == "gzip":
                body = gzip.decompress(body)
            elif encoding == "deflate":
                body = zlib.decompress(body)
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise RuntimeError(
                "SEC EDGAR returned HTTP 403. Verify SEC_USER_AGENT includes a real contact email; "
                "the current network IP may also be restricted by SEC fair-access controls."
            ) from exc
        raise


def build_ticker_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for entry in payload.values():
        ticker = str(entry.get("ticker", "")).upper().strip()
        if ticker:
            mapping[ticker] = entry
    return mapping


def candidate_sec_ticker(company: dict[str, Any]) -> str:
    explicit = str(company.get("secTicker") or "").strip()
    if explicit:
        return explicit.upper()
    ticker = str(company.get("ticker") or "").split("/")[0].strip()
    exchange = str(company.get("exchange") or "")
    if not ticker or not any(name in exchange.upper() for name in ("NASDAQ", "NYSE")):
        return ""
    return ticker.upper()


def resolve_sec_companies(
    companies: list[dict[str, Any]],
    ticker_map: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    resolved: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for company in companies:
        ticker = candidate_sec_ticker(company)
        if not ticker:
            continue
        sec_entry = ticker_map.get(ticker)
        if not sec_entry:
            unresolved.append(company["id"])
            continue
        resolved.append(
            {
                "company": company,
                "secTicker": ticker,
                "cik": str(sec_entry["cik_str"]).zfill(10),
                "secName": sec_entry.get("title", company["name"]),
            }
        )
    return resolved, unresolved


def parse_recent_filings(
    submission: dict[str, Any],
    resolved_company: dict[str, Any],
) -> list[dict[str, Any]]:
    recent = submission.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", [])
    records: list[dict[str, Any]] = []
    fields = [
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "act",
        "form",
        "fileNumber",
        "filmNumber",
        "items",
        "size",
        "isXBRL",
        "isInlineXBRL",
        "primaryDocument",
        "primaryDocDescription",
    ]
    for index, accession in enumerate(accessions):
        record = {
            field: _column_value(recent, field, index)
            for field in fields
        }
        record.update(
            {
                "accessionNumber": accession,
                "companyId": resolved_company["company"]["id"],
                "companyName": resolved_company["company"]["name"],
                "companyDirections": resolved_company["company"].get("directions", []),
                "secTicker": resolved_company["secTicker"],
                "cik": resolved_company["cik"],
                "secName": submission.get("name") or resolved_company["secName"],
            }
        )
        record["sourceUrl"] = filing_url(record)
        records.append(record)
    return records


def _column_value(recent: dict[str, Any], field: str, index: int) -> Any:
    values = recent.get(field, [])
    return values[index] if index < len(values) else ""


def filing_url(record: dict[str, Any]) -> str:
    accession = str(record.get("accessionNumber", "")).replace("-", "")
    cik = str(record.get("cik", "")).lstrip("0") or "0"
    document = record.get("primaryDocument", "")
    if accession and document:
        return ARCHIVES_URL.format(cik=cik, accession=accession, document=document)
    return "https://www.sec.gov/edgar/search/"


def form_is_watched(form: str, watched_forms: set[str]) -> bool:
    normalized = str(form or "").upper()
    base_form = normalized[:-2] if normalized.endswith("/A") else normalized
    return normalized in watched_forms or base_form in watched_forms


def filter_filings(
    records: Iterable[dict[str, Any]],
    start_date: dt.date,
    watched_forms: set[str],
) -> list[dict[str, Any]]:
    output = []
    for record in records:
        try:
            filing_date = dt.date.fromisoformat(str(record.get("filingDate", "")))
        except ValueError:
            continue
        if filing_date >= start_date and form_is_watched(str(record.get("form", "")), watched_forms):
            output.append(record)
    return output


def classify_form(form: str) -> tuple[str, str]:
    base_form = form.upper().removesuffix("/A")
    if base_form in {"8-K", "6-K"}:
        return "Corporate Update", "Current Report"
    if base_form in {"10-Q", "10-K", "20-F"}:
        return "Periodic Report", "Periodic Filing"
    if base_form in {"S-1", "F-1"}:
        return "Financing / Registration", "Securities Registration"
    if base_form.startswith("424B"):
        return "Offering", "Prospectus"
    return "Company Filing", "Corporate Filing"


def make_signal(record: dict[str, Any]) -> dict[str, Any]:
    form = str(record.get("form") or "Unknown")
    event_type, sub_category = classify_form(form)
    accession = str(record.get("accessionNumber") or "unknown")
    company_name = str(record.get("companyName") or record.get("secName") or "Unknown company")
    description = str(record.get("primaryDocDescription") or "").strip()
    report = (
        f"SEC metadata describes the primary document as: {description}."
        if description
        else "SEC metadata does not provide a primary document description; filing content has not been interpreted."
    )
    return {
        "id": f"sec-{record.get('cik', 'unknown')}-{accession.replace('-', '')}",
        "date": record.get("filingDate", ""),
        "title": f"{company_name} filed Form {form}",
        "entity": company_name,
        "primaryCategory": "Company & Market",
        "subCategory": sub_category,
        "eventType": event_type,
        "sourceType": "Company",
        "sourceName": "SEC EDGAR",
        "sourceUrl": record.get("sourceUrl", "https://www.sec.gov/edgar/search/"),
        "reliability": "High",
        "evidenceLevel": "Medium",
        "needsReview": True,
        "themes": unique(["Corporate Filings", *record.get("companyDirections", [])]),
        "tags": unique(["SEC", form, record.get("secTicker", "")]),
        "companyIds": [record["companyId"]],
        "fact": (
            f"SEC EDGAR lists accession {accession} for {company_name}, Form {form}, "
            f"filed on {record.get('filingDate') or 'an unknown date'}."
        ),
        "report": report,
        "inference": (
            f"The event was automatically routed as {event_type} from the SEC form type only. "
            "No conclusion was drawn from the filing content."
        ),
        "unknown": (
            "The collector has not yet extracted filing sections, exhibits, transaction terms, "
            "pipeline changes, clinical claims, or financial impact."
        ),
    }


def unique(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def read_data_js(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").strip()
    prefix = "window.BHR_DATA ="
    if not text.startswith(prefix):
        raise ValueError(f"{path} does not look like a BioHealth Radar data.js file")
    return json.loads(text[len(prefix) :].strip().rstrip(";"))


def write_data_js(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(f"window.BHR_DATA = {serialized};\n", encoding="utf-8")


def merge_signals(
    payload: dict[str, Any],
    sec_signals: list[dict[str, Any]],
    max_stored: int,
) -> dict[str, Any]:
    non_sec = [signal for signal in payload.get("signals", []) if not str(signal.get("id", "")).startswith("sec-")]
    prior_sec = [signal for signal in payload.get("signals", []) if str(signal.get("id", "")).startswith("sec-")]
    by_id = {signal["id"]: signal for signal in prior_sec if signal.get("id")}
    for signal in sec_signals:
        by_id[signal["id"]] = signal
    retained_sec = sorted(by_id.values(), key=lambda item: item.get("date", ""), reverse=True)[:max_stored]
    signals = [*non_sec, *retained_sec]
    signals.sort(key=lambda item: item.get("date", ""), reverse=True)

    sources = [source for source in payload.get("sources", []) if source.get("name") != SEC_SOURCE["name"]]
    sources.append(SEC_SOURCE)
    return {
        **payload,
        "updatedAt": dt.date.today().isoformat(),
        "sources": sources,
        "signals": signals,
    }


def main() -> int:
    args = parse_args()
    if not args.user_agent.strip():
        raise ValueError(
            "SEC User-Agent is required. Set SEC_USER_AGENT='BioHealth Radar contact@example.com' "
            "or pass --user-agent."
        )

    companies = load_companies(args.registry)
    wanted_tiers = set(args.tier or ["A", "B"])
    wanted_ids = set(args.company or [])
    selected_companies = [
        company
        for company in companies
        if company.get("watchTier") in wanted_tiers and (not wanted_ids or company["id"] in wanted_ids)
    ]

    ticker_payload = request_json(TICKERS_URL, args.user_agent)
    resolved, unresolved = resolve_sec_companies(selected_companies, build_ticker_map(ticker_payload))
    watched_forms = {form.upper() for form in (args.form or DEFAULT_FORMS)}
    start_date = dt.date.today() - dt.timedelta(days=args.days)
    records: list[dict[str, Any]] = []

    for company in resolved:
        submission = request_json(SUBMISSIONS_URL.format(cik=company["cik"]), args.user_agent)
        records.extend(filter_filings(parse_recent_filings(submission, company), start_date, watched_forms))
        time.sleep(0.15)

    records.sort(key=lambda item: (item.get("filingDate", ""), item.get("acceptanceDateTime", "")), reverse=True)
    records = records[: args.max_total]
    signals = [make_signal(record) for record in records]
    raw_payload = {
        "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "SEC EDGAR",
        "dateWindow": {"start": start_date.isoformat(), "end": dt.date.today().isoformat()},
        "forms": sorted(watched_forms),
        "resolvedCompanies": [
            {
                "companyId": item["company"]["id"],
                "secTicker": item["secTicker"],
                "cik": item["cik"],
                "secName": item["secName"],
            }
            for item in resolved
        ],
        "unresolvedCompanyIds": unresolved,
        "records": records,
        "signals": signals,
    }

    print(
        f"Resolved {len(resolved)} SEC companies; fetched {len(records)} recent filings; "
        f"{len(unresolved)} ticker(s) unresolved."
    )
    for signal in signals[:12]:
        print(f"- {signal['date']} | {signal['eventType']} | {signal['title']}")

    if args.dry_run:
        return 0

    raw_output = Path(args.raw_output)
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    data_path = Path(args.data_file)
    payload = merge_signals(read_data_js(data_path), signals, args.max_stored)
    write_data_js(data_path, payload)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"collect_sec_edgar.py failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
