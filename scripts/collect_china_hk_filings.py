#!/usr/bin/env python3
"""Discover China/Hong Kong listed-company periodic-report links from official portals.

The collector stores only report metadata and short text snippets.  Portal layouts
change frequently, so every record retains parser status and the original URL.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    from .http_utils import urlopen_with_retry
except ImportError:
    from http_utils import urlopen_with_retry

REPORT_RE = re.compile(r"(年报|年度报告|半年报|中期报告|季报|季度报告|annual report|interim report|quarterly report|10-K|10-Q|20-F|6-K)", re.I)
LINK_RE = re.compile(r"(?:href|url)\s*[=:]\s*[\"']([^\"']+\.(?:pdf|PDF|html?|HTML)(?:\?[^\"']*)?)[\"']", re.I)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--profiles", default="data/company_profiles.json")
    p.add_argument("--output", default="data/raw/china_hk_filings_latest.json")
    p.add_argument("--timeout", type=float, default=15)
    return p.parse_args()


def portal_for(profile: dict[str, Any]) -> tuple[str, str] | None:
    identity = profile.get("identity", {})
    exchange = identity.get("exchange")
    if exchange == "HKEX":
        return "HKEXnews", "https://www1.hkexnews.hk/index.htm"
    if exchange in {"SSE", "SZSE"}:
        ids = identity.get("identifiers", {})
        code = str((ids.get("cnSecurityCode") or [identity.get("ticker", "")])[0])
        return "CNINFO", f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}"
    return None


def parse_report_links(body: str, base_url: str, source: str, company_id: str, company_name: str) -> list[dict[str, Any]]:
    results = []
    plain = html.unescape(re.sub(r"<[^>]+>", " ", body))
    for match in LINK_RE.finditer(body):
        url = urllib.parse.urljoin(base_url, html.unescape(match.group(1)))
        context = re.sub(r"<[^>]+>", " ", html.unescape(body[max(0, match.start() - 300): match.end() + 300]))
        kind_matches = list(REPORT_RE.finditer(context))
        kind_match = min(kind_matches, key=lambda item: abs(item.start() - len(context) // 2)) if kind_matches else None
        if not kind_match:
            continue
        kind = kind_match.group(1).lower()
        label = "年报" if ("年" in kind or "annual" in kind or kind in {"10-k", "20-f"}) else "半年报" if ("半年" in kind or "中期" in kind or "interim" in kind or kind == "6-k") else "季报"
        date_match = re.search(r"20\d{2}[-/.年]\d{1,2}(?:[-/.月]\d{1,2})?", context)
        results.append({"companyId": company_id, "companyName": company_name, "source": source, "reportType": label, "form": kind.upper(), "date": date_match.group(0) if date_match else None, "url": url, "title": context.strip()[:300], "status": "discovered"})
    unique = {(item["reportType"], item["url"]): item for item in results}
    return sorted(unique.values(), key=lambda item: (item.get("date") or "", item["url"]), reverse=True)


def collect(profiles: dict[str, Any], timeout: float) -> dict[str, Any]:
    records, failures = [], []
    for profile in profiles.get("profiles", []):
        portal = portal_for(profile)
        if not portal:
            continue
        source, url = portal
        # HKEXnews's public landing page is a JavaScript search shell; without
        # a company-specific query it cannot yield reliable links. Keep the
        # official portal as a navigational record until the query endpoint is
        # implemented, instead of making the same request for every issuer.
        if source == "HKEXnews":
            records.append({"companyId": profile["companyId"], "companyName": profile["name"], "source": source, "portalUrl": url, "status": "portal_only"})
            continue
        user_agent = os.environ.get("BHR_USER_AGENT", "BioHealth-Radar/1.0 official-disclosure-monitor")
        request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"})
        try:
            with urlopen_with_retry(request, timeout=timeout, attempts=2) as response:
                body = response.read(5_000_000).decode("utf-8", errors="replace")
            found = parse_report_links(body, url, source, profile["companyId"], profile["name"])
            records.extend(found[:8])
            if not found:
                records.append({"companyId": profile["companyId"], "companyName": profile["name"], "source": source, "portalUrl": url, "status": "portal_reachable_no_report_links"})
        except Exception as exc:
            failures.append({"companyId": profile["companyId"], "companyName": profile["name"], "source": source, "portalUrl": url, "status": "failed", "error": type(exc).__name__})
    return {"schemaVersion": "1.0", "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "source": "HKEXnews/CNINFO", "records": records, "failures": failures}


if __name__ == "__main__":
    args = parse_args()
    payload = collect(json.loads(Path(args.profiles).read_text(encoding="utf-8")), args.timeout)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Collected {len(payload['records'])} China/HK report links; {len(payload['failures'])} failures.")
