#!/usr/bin/env python3
"""Collect recent biotech-relevant for-profit organizations from NIH RePORTER."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

try:
    from .http_utils import urlopen_with_retry
except ImportError:
    from http_utils import urlopen_with_retry


API_URL = "https://api.reporter.nih.gov/v2/projects/search"
SOURCE_URL = "https://reporter.nih.gov/"
DEFAULT_TERMS = [
    "biotechnology",
    "gene therapy",
    "cell therapy",
    "drug discovery",
    "molecular diagnostics",
]
TOPIC_RULES = [
    (r"\b(crispr|gene edit|gene therap|genetic medicine)\b", "Gene Editing / Gene Therapy"),
    (r"\b(cell therap|car[- ]?t|stem cell|nk cell)\b", "Cell Therapy"),
    (r"\b(mrna|rna therap|sirna|antisense)\b", "RNA Therapeutics"),
    (r"\b(antibod|bispecific|antibody.drug conjugate|\badc\b)\b", "Antibody / ADC"),
    (r"\b(diagnostic|biomarker|liquid biopsy|screening)\b", "Precision Diagnostics"),
    (r"\b(machine learning|artificial intelligence|drug discovery|computational)\b", "AI Drug Discovery"),
    (r"\b(protein degrad|protac|molecular glue)\b", "Targeted Protein Degradation"),
    (r"\b(organoid|disease model)\b", "Organoids & Disease Models"),
]
INCLUDE_FIELDS = [
    "ApplId",
    "ProjectNum",
    "ProjectTitle",
    "Organization",
    "OrganizationType",
    "FiscalYear",
    "AwardAmount",
    "AwardNoticeDate",
    "ProjectStartDate",
    "ProjectEndDate",
    "Terms",
    "AbstractText",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover biotech companies through NIH-funded projects.")
    parser.add_argument("--term", action="append", help="Override discovery terms; repeatable.")
    parser.add_argument("--fiscal-year", type=int, action="append", help="Fiscal year; repeatable.")
    parser.add_argument("--page-size", type=int, default=25, help="Projects requested per term (max 50).")
    parser.add_argument("--max-total", type=int, default=80, help="Maximum deduplicated projects stored.")
    parser.add_argument("--output", default="data/raw/nih_reporter_latest.json")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def request_projects(term: str, fiscal_years: list[int], page_size: int) -> dict[str, Any]:
    payload = {
        "criteria": {
            "fiscal_years": fiscal_years,
            "organization_type": ["Domestic For-Profits"],
            "advanced_text_search": {
                "search_text": term,
                "operator": "and",
                "search_field": "all",
            },
        },
        "include_fields": INCLUDE_FIELDS,
        "offset": 0,
        "limit": min(max(page_size, 1), 50),
        "sort_field": "award_notice_date",
        "sort_order": "desc",
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "BioHealthRadar/0.1 (company discovery)",
        },
        method="POST",
    )
    with urlopen_with_retry(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_excerpt(value: Any, limit: int = 280) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    shortened = text[: limit - 1].rsplit(" ", 1)[0] or text[: limit - 1]
    return f"{shortened.rstrip()}…"


def topic_hints(project: dict[str, Any]) -> list[str]:
    haystack = " ".join(
        str(project.get(field) or "")
        for field in ("project_title", "terms", "abstract_text")
    ).lower()
    return [label for pattern, label in TOPIC_RULES if re.search(pattern, haystack)]


def parse_project(project: dict[str, Any], matched_term: str) -> dict[str, Any]:
    organization = project.get("organization") or {}
    organization_type = project.get("organization_type") or {}
    appl_id = project.get("appl_id")
    return {
        "applId": appl_id,
        "projectNum": project.get("project_num"),
        "projectTitle": project.get("project_title"),
        "fiscalYear": project.get("fiscal_year"),
        "awardAmount": project.get("award_amount"),
        "awardNoticeDate": str(project.get("award_notice_date") or "")[:10] or None,
        "projectStartDate": str(project.get("project_start_date") or "")[:10] or None,
        "projectEndDate": str(project.get("project_end_date") or "")[:10] or None,
        "organization": {
            "name": organization.get("org_name"),
            "city": organization.get("org_city"),
            "state": organization.get("org_state"),
            "country": organization.get("org_country"),
            "uei": organization.get("primary_uei") or next(iter(organization.get("org_ueis") or []), None),
            "ipf": organization.get("org_ipf_code") or organization.get("external_org_id"),
            "type": organization_type.get("name"),
        },
        "matchedTerms": [matched_term],
        "topicHints": topic_hints(project),
        "projectSummaryExcerpt": normalize_excerpt(project.get("abstract_text")),
        "sourceUrl": f"https://reporter.nih.gov/project-details/{appl_id}" if appl_id else SOURCE_URL,
    }


def merge_project(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing["matchedTerms"] = sorted(set(existing.get("matchedTerms", [])) | set(incoming.get("matchedTerms", [])))
    existing["topicHints"] = sorted(set(existing.get("topicHints", [])) | set(incoming.get("topicHints", [])))
    return existing


def collect(terms: list[str], fiscal_years: list[int], page_size: int, max_total: int) -> dict[str, Any]:
    projects: dict[str, dict[str, Any]] = {}
    query_counts: dict[str, int] = {}
    for index, term in enumerate(terms):
        if index:
            time.sleep(1.0)
        response = request_projects(term, fiscal_years, page_size)
        query_counts[term] = int(response.get("meta", {}).get("total", 0))
        for raw in response.get("results", []):
            parsed = parse_project(raw, term)
            key = str(parsed.get("applId") or parsed.get("projectNum") or "")
            if not key:
                continue
            if key in projects:
                merge_project(projects[key], parsed)
            else:
                projects[key] = parsed
    records = sorted(
        projects.values(),
        key=lambda item: (item.get("awardNoticeDate") or "", str(item.get("applId") or "")),
        reverse=True,
    )[:max_total]
    return {
        "schemaVersion": "1.0",
        "capturedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "source": {
            "name": "NIH RePORTER",
            "type": "Government Funding",
            "reliability": "High",
            "url": SOURCE_URL,
        },
        "fiscalYears": fiscal_years,
        "terms": terms,
        "queryMatchCounts": query_counts,
        "records": records,
    }


def main() -> int:
    args = parse_args()
    if args.max_total < 1:
        raise SystemExit("--max-total must be at least 1")
    terms = args.term or DEFAULT_TERMS
    fiscal_years = args.fiscal_year or [dt.date.today().year, dt.date.today().year - 1]
    payload = collect(terms, fiscal_years, args.page_size, args.max_total)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.dry_run:
        print(serialized, end="")
    else:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(
        f"Collected {len(payload['records'])} NIH project records across {len(terms)} discovery terms.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
