#!/usr/bin/env python3
"""Load the company watchlist and link source records to stable company IDs."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable


DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "companies.json"


def load_companies(path: Path | str = DEFAULT_REGISTRY_PATH) -> list[dict[str, Any]]:
    companies = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_companies(companies)
    return companies


def validate_companies(companies: Any) -> None:
    if not isinstance(companies, list):
        raise ValueError("Company registry must contain a JSON list")

    required = {"id", "name", "aliases", "directions", "watchTier", "officialUrl"}
    seen_ids: set[str] = set()
    for index, company in enumerate(companies):
        if not isinstance(company, dict):
            raise ValueError(f"Company entry {index} must be an object")
        missing = sorted(required - company.keys())
        if missing:
            raise ValueError(f"Company entry {index} is missing: {', '.join(missing)}")
        company_id = str(company["id"])
        if company_id in seen_ids:
            raise ValueError(f"Duplicate company ID: {company_id}")
        seen_ids.add(company_id)


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("&", " and ")
    return " ".join(re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).split())


def match_company_ids(values: Iterable[Any], companies: list[dict[str, Any]]) -> list[str]:
    haystack = f" {normalize(' '.join(_flatten(values)))} "
    if not haystack.strip():
        return []

    matched: list[str] = []
    for company in companies:
        names = [company.get("name", ""), *company.get("aliases", [])]
        if any(_contains_alias(haystack, alias) for alias in names):
            matched.append(company["id"])
    return matched


def match_signal_company_ids(signal: dict[str, Any], companies: list[dict[str, Any]]) -> list[str]:
    return match_company_ids(
        [
            signal.get("title", ""),
            signal.get("entity", ""),
            signal.get("fact", ""),
            signal.get("report", ""),
            signal.get("sourceName", ""),
            signal.get("tags", []),
        ],
        companies,
    )


def _contains_alias(haystack: str, alias: Any) -> bool:
    normalized_alias = normalize(alias)
    if len(normalized_alias) < 4:
        return False
    return f" {normalized_alias} " in haystack


def _flatten(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            output.extend(_flatten(value))
        elif value is not None:
            output.append(str(value))
    return output
