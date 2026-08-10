#!/usr/bin/env python3
"""Capture compact, attributable snapshots of official company web pages.

The collector intentionally stores metadata, selected short excerpts, and a hash
of normalized visible text. It does not archive full HTML or full page text.
"""

from __future__ import annotations

import argparse
import datetime as dt
import concurrent.futures
import hashlib
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from .company_registry import load_companies
    from .http_utils import urlopen_with_retry
except ImportError:
    from company_registry import load_companies
    from http_utils import urlopen_with_retry


SCHEMA_VERSION = "1.0"
MAX_RESPONSE_BYTES = 2_000_000
MAX_EXCERPTS = 4
MAX_EXCERPT_CHARS = 280
PAGE_ROLES = (
    ("official", "officialUrl"),
    ("pipeline", "pipelineUrl"),
    ("investor_relations", "irUrl"),
)
GENERIC_RELEVANCE_TERMS = {
    "about",
    "business",
    "clinical",
    "commercial",
    "company",
    "development",
    "focus",
    "investor",
    "mission",
    "pipeline",
    "platform",
    "product",
    "program",
    "research",
    "strategy",
    "therapeutic",
}
SPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\s*[|•]\s*")
BOILERPLATE_RE = re.compile(
    r"(you are about to leave|privacy policy|cookie policy|not responsible for the content|"
    r"website you are about to visit|all rights reserved)",
    re.IGNORECASE,
)
BUSINESS_EXCERPT_RE = re.compile(r"\b(about|business|mission|focus|we are|company)\b", re.IGNORECASE)
PRODUCT_EXCERPT_RE = re.compile(
    r"\b(product|pipeline|platform|program|therapy|therapeutic|drug|diagnostic)\b", re.IGNORECASE
)
PLAN_EXCERPT_RE = re.compile(
    r"\b(plans? to|intends? to|expects? to|will (?:advance|develop|expand|file|launch|pursue|submit))\b",
    re.IGNORECASE,
)


class VisibleTextParser(HTMLParser):
    """Extract page metadata and visible text blocks without external packages."""

    BLOCK_TAGS = {
        "article",
        "div",
        "figcaption",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "main",
        "p",
        "section",
        "td",
        "th",
    }
    SKIP_TAGS = {"canvas", "noscript", "script", "style", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.description = ""
        self.blocks: list[str] = []
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._heading_level: str | None = None
        self.headings: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        if tag in {"h1", "h2", "h3"}:
            self._flush()
            self._heading_level = tag
        if tag == "meta":
            values = {str(key).lower(): str(value or "") for key, value in attrs}
            marker = (values.get("name") or values.get("property") or "").lower()
            if marker in {"description", "og:description", "twitter:description"} and not self.description:
                self.description = normalize_text(values.get("content", ""))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK_TAGS:
            block = self._flush()
            if self._heading_level and block:
                self.headings.append(block)
            if tag == self._heading_level:
                self._heading_level = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = normalize_text(data)
        if not value:
            return
        if self._in_title:
            self.title_parts.append(value)
        else:
            self._buffer.append(value)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> str:
        block = normalize_text(" ".join(self._buffer))
        self._buffer.clear()
        if block and (not self.blocks or self.blocks[-1] != block):
            self.blocks.append(block)
        return block


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect compact snapshots from official company pages.")
    parser.add_argument("--registry", default="data/companies.json")
    parser.add_argument(
        "--profiles",
        help="Use generated company_profiles.json as the collection universe (includes discovered companies).",
    )
    parser.add_argument("--web-overrides", default="data/company_web_overrides.json")
    parser.add_argument("--output", default="data/raw/company_sources_latest.json")
    parser.add_argument("--company", action="append", default=[], help="Company ID to collect; repeatable.")
    parser.add_argument("--tier", action="append", default=[], help="Watch tier to collect; repeatable.")
    parser.add_argument("--max-companies", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--due-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def normalize_text(value: str) -> str:
    return SPACE_RE.sub(" ", html.unescape(value or "")).strip()


def truncate_text(value: str, limit: int) -> str:
    value = normalize_text(value)
    if len(value) <= limit:
        return value
    shortened = value[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    if not shortened:
        shortened = value[: limit - 1]
    return f"{shortened}…"


def safe_https_url(value: Any) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme == "https" and bool(parsed.netloc)


def decode_response(raw: bytes, content_type: str) -> str:
    charset_match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
    charset = charset_match.group(1) if charset_match else "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def parse_page(document: str, relevance_terms: set[str]) -> dict[str, Any]:
    parser = VisibleTextParser()
    parser.feed(document)
    parser.close()
    visible_text = normalize_text(" ".join(parser.blocks))
    candidates: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for position, block in enumerate([parser.description, *parser.headings, *parser.blocks]):
        for sentence in SENTENCE_SPLIT_RE.split(block):
            excerpt = normalize_text(sentence)
            if len(excerpt) < 40 or BOILERPLATE_RE.search(excerpt):
                continue
            excerpt = truncate_text(excerpt, MAX_EXCERPT_CHARS)
            key = excerpt.casefold()
            if key in seen:
                continue
            seen.add(key)
            lowered = key
            score = sum(1 for term in relevance_terms if term in lowered)
            if score:
                candidates.append((score, -position, excerpt))
    candidates.sort(reverse=True)
    excerpts = [item[2] for item in candidates[:MAX_EXCERPTS]]
    if not excerpts and parser.description:
        excerpts = [truncate_text(parser.description, MAX_EXCERPT_CHARS)]
    semantic_parts = {
        normalize_text(" ".join(parser.title_parts)),
        parser.description,
        *parser.headings,
        *(item[2] for item in candidates),
    }
    semantic_text = "\n".join(sorted(part for part in semantic_parts if part)) or visible_text
    business_excerpts = [item[2] for item in candidates if BUSINESS_EXCERPT_RE.search(item[2])][:MAX_EXCERPTS]
    product_excerpts = [item[2] for item in candidates if PRODUCT_EXCERPT_RE.search(item[2])][:MAX_EXCERPTS]
    plan_excerpts = [item[2] for item in candidates if PLAN_EXCERPT_RE.search(item[2])][:MAX_EXCERPTS]
    return {
        "title": truncate_text(" ".join(parser.title_parts), 300),
        "description": truncate_text(parser.description, 500),
        "headings": list(dict.fromkeys(parser.headings))[:12],
        "excerpts": excerpts,
        "businessExcerpts": list(dict.fromkeys(business_excerpts)),
        "productExcerpts": list(dict.fromkeys(product_excerpts)),
        "planExcerpts": list(dict.fromkeys(plan_excerpts)),
        "contentHash": hashlib.sha256(semantic_text.encode("utf-8")).hexdigest(),
        "visibleTextHash": hashlib.sha256(visible_text.encode("utf-8")).hexdigest(),
        "visibleTextChars": len(visible_text),
    }


def company_terms(company: dict[str, Any]) -> set[str]:
    terms = set(GENERIC_RELEVANCE_TERMS)
    values = [company.get("name", ""), *company.get("directions", []), *company.get("modalities", [])]
    for value in values:
        for token in re.findall(r"[a-z0-9][a-z0-9+-]{2,}", str(value).lower()):
            terms.add(token)
    return terms


def fetch_page(
    url: str,
    *,
    user_agent: str,
    timeout: float,
    attempts: int,
    conditional: dict[str, Any] | None = None,
) -> tuple[str, str, str, dict[str, str]]:
    request_headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.8",
    }
    if conditional and conditional.get("etag"):
        request_headers["If-None-Match"] = str(conditional["etag"])
    if conditional and conditional.get("lastModified"):
        request_headers["If-Modified-Since"] = str(conditional["lastModified"])
    request = urllib.request.Request(
        url,
        headers=request_headers,
    )
    try:
        with urlopen_with_retry(request, timeout=timeout, attempts=attempts) as response:
            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type.lower():
                raise ValueError(f"unsupported content type: {content_type or 'unknown'}")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError(f"response exceeds {MAX_RESPONSE_BYTES} bytes")
            resolved_url = response.geturl()
            headers = {
                "etag": response.headers.get("ETag", ""),
                "lastModified": response.headers.get("Last-Modified", ""),
            }
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return "", url, "text/html", {"notModified": "true"}
        raise
    if not safe_https_url(resolved_url):
        raise ValueError("response redirected to a non-HTTPS URL")
    return decode_response(raw, content_type), resolved_url, content_type, headers


def merge_snapshot(
    previous: dict[str, Any] | None,
    fresh: dict[str, Any],
    *,
    observed_at: str,
) -> dict[str, Any]:
    previous_hash = (previous or {}).get("contentHash")
    if previous_hash == fresh.get("contentHash"):
        merged = dict(previous or {})
        merged.update({"requestedUrl": fresh["requestedUrl"], "resolvedUrl": fresh["resolvedUrl"]})
        merged["changeType"] = "unchanged"
        merged["lastCheckStatus"] = "success"
        merged["lastCheckedAt"] = observed_at
        merged["nextCheckAt"] = fresh.get("nextCheckAt")
        merged.pop("lastCheckError", None)
        merged.pop("lastFailureAt", None)
        return merged
    fresh["changeType"] = "updated" if previous_hash else "new"
    fresh["lastCheckStatus"] = "success"
    fresh["firstObservedAt"] = (previous or {}).get("firstObservedAt") or observed_at
    fresh["lastChangedAt"] = observed_at
    fresh["capturedAt"] = observed_at
    fresh["lastCheckedAt"] = observed_at
    fresh.setdefault("nextCheckAt", None)
    return fresh


def select_companies(
    companies: list[dict[str, Any]],
    company_ids: list[str],
    tiers: list[str],
    max_companies: int | None,
) -> list[dict[str, Any]]:
    requested = set(company_ids)
    selected = [
        company
        for company in companies
        if (not requested or company["id"] in requested)
        and (not tiers or str(company.get("watchTier")) in set(tiers))
    ]
    unknown = requested - {company["id"] for company in companies}
    if unknown:
        raise ValueError(f"Unknown company IDs: {', '.join(sorted(unknown))}")
    if max_companies is not None:
        if max_companies < 1:
            raise ValueError("--max-companies must be at least 1")
        selected = selected[:max_companies]
    return selected


def load_profile_seed_companies(path: str | Path, overrides_path: str | Path | None = None) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    overrides_payload: dict[str, Any] = {}
    if overrides_path and Path(overrides_path).exists():
        overrides_payload = json.loads(Path(overrides_path).read_text(encoding="utf-8"))
    overrides = overrides_payload.get("overrides", {})
    output = []
    for profile in payload.get("profiles", []):
        identity = profile.get("identity") or {}
        classification = profile.get("classification") or {}
        official_url = identity.get("officialUrl")
        if not official_url:
            continue
        item = {
                "id": profile.get("companyId"),
                "name": profile.get("name") or profile.get("companyId"),
                "directions": classification.get("directions", []),
                "modalities": classification.get("modalities", []),
                "watchTier": classification.get("watchTier"),
                "officialUrl": official_url,
                "pipelineUrl": identity.get("pipelineUrl"),
                "irUrl": identity.get("irUrl"),
            }
        override = overrides.get(item["id"], {}) if isinstance(overrides, dict) else {}
        if isinstance(override, dict):
            for field in ("officialUrl", "pipelineUrl", "irUrl", "refreshIntervalDays"):
                if override.get(field):
                    item[field] = override[field]
        output.append(item)
    return [item for item in output if item.get("id")]


def refresh_interval_days(company: dict[str, Any], role: str) -> int:
    explicit = company.get("refreshIntervalDays")
    if explicit:
        return max(1, int(explicit))
    if role in {"pipeline", "investor_relations"}:
        return 7
    return 1 if company.get("watchTier") in {"A", "B"} else 7


def is_due(previous: dict[str, Any] | None, company: dict[str, Any], role: str, now: dt.datetime) -> bool:
    if not previous:
        return True
    next_check = str(previous.get("nextCheckAt") or "")
    if next_check:
        try:
            return now >= dt.datetime.fromisoformat(next_check)
        except ValueError:
            return True
    last_checked = str(previous.get("lastCheckedAt") or previous.get("capturedAt") or "")
    if not last_checked:
        return True
    try:
        checked_at = dt.datetime.fromisoformat(last_checked)
    except ValueError:
        return True
    return now >= checked_at + dt.timedelta(days=refresh_interval_days(company, role))


def collect(
    companies: list[dict[str, Any]],
    previous_payload: dict[str, Any],
    *,
    observed_at: str,
    user_agent: str,
    timeout: float,
    attempts: int,
    workers: int = 6,
    due_only: bool = False,
    force: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    previous_by_key = {
        (item.get("companyId"), item.get("sourceRole")): item
        for item in previous_payload.get("sources", [])
        if isinstance(item, dict)
    }
    observed_dt = dt.datetime.fromisoformat(observed_at)
    jobs: list[tuple[dict[str, Any], str, str, dict[str, Any] | None]] = []
    output: list[dict[str, Any]] = []
    for company in companies:
        for role, url_field in PAGE_ROLES:
            url = company.get(url_field)
            if not url:
                continue
            previous = previous_by_key.get((company["id"], role))
            if due_only and not force and not is_due(previous, company, role, observed_dt):
                if previous:
                    output.append(previous)
                continue
            jobs.append((company, role, str(url), previous))

    def fetch_one(job: tuple[dict[str, Any], str, str, dict[str, Any] | None]) -> tuple[dict[str, Any], str | None]:
        company, role, url, previous = job
        if not safe_https_url(url):
            record = previous or {
                "companyId": company["id"], "companyName": company["name"], "sourceRole": role,
                "sourceType": "Company", "requestedUrl": url, "lastCheckStatus": "failed",
                "lastFailureAt": observed_at, "lastCheckedAt": observed_at,
                "firstObservedAt": observed_at, "capturedAt": observed_at, "lastChangedAt": observed_at,
                "lastCheckError": "invalid_url",
            }
            return record, f"{company['id']} {role}: URL must be HTTPS"
        try:
            document, resolved_url, content_type, response_headers = fetch_page(
                url,
                user_agent=user_agent,
                timeout=timeout,
                attempts=attempts,
                conditional=previous,
            )
            next_check = observed_dt + dt.timedelta(days=refresh_interval_days(company, role))
            if response_headers.get("notModified") and previous:
                fresh = {
                    **previous,
                    "requestedUrl": url,
                    "resolvedUrl": resolved_url,
                    "nextCheckAt": next_check.isoformat(),
                }
                return merge_snapshot(previous, fresh, observed_at=observed_at), None
            fresh = {
                "companyId": company["id"], "companyName": company["name"], "sourceRole": role,
                "sourceType": "Company", "requestedUrl": url, "resolvedUrl": resolved_url,
                "contentType": content_type.split(";", 1)[0].strip().lower(),
                "refreshIntervalDays": refresh_interval_days(company, role),
                "nextCheckAt": next_check.isoformat(), **parse_page(document, company_terms(company)),
                **{key: value for key, value in response_headers.items() if value},
            }
            return merge_snapshot(previous, fresh, observed_at=observed_at), None
        except (OSError, ValueError, urllib.error.URLError) as exc:
            if previous:
                preserved = dict(previous)
                preserved["lastCheckStatus"] = "failed"
                preserved["lastCheckError"] = type(exc).__name__
                preserved["lastFailureAt"] = observed_at
                preserved["lastCheckedAt"] = observed_at
                return preserved, f"{company['id']} {role}: {exc}"
            return {
                "companyId": company["id"], "companyName": company["name"], "sourceRole": role,
                "sourceType": "Company", "requestedUrl": url, "lastCheckStatus": "failed",
                "lastFailureAt": observed_at, "lastCheckedAt": observed_at,
                "firstObservedAt": observed_at, "capturedAt": observed_at, "lastChangedAt": observed_at,
                "lastCheckError": type(exc).__name__,
            }, f"{company['id']} {role}: {exc}"

    errors: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        for record, error in executor.map(fetch_one, jobs):
            output.append(record)
            if error:
                errors.append(error)
    return output, errors


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    previous_payload: dict[str, Any] = {}
    if output_path.exists():
        previous_payload = json.loads(output_path.read_text(encoding="utf-8"))
    companies = (
        load_profile_seed_companies(args.profiles, args.web_overrides)
        if args.profiles
        else load_companies(args.registry)
    )
    try:
        selected = select_companies(companies, args.company, args.tier, args.max_companies)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    selected_ids = {company["id"] for company in selected}
    observed_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    user_agent = os.environ.get("BHR_USER_AGENT", "BioHealthRadar/0.1 (official-source monitor)")
    collected, errors = collect(
        selected,
        previous_payload,
        observed_at=observed_at,
        user_agent=user_agent,
        timeout=args.timeout,
        attempts=args.attempts,
        workers=args.workers,
        due_only=args.due_only,
        force=args.force,
    )
    untouched = [
        item
        for item in previous_payload.get("sources", [])
        if isinstance(item, dict) and item.get("companyId") not in selected_ids
    ]
    sources = sorted([*untouched, *collected], key=lambda item: (item.get("companyId", ""), item.get("sourceRole", "")))
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "official_company_source_snapshots",
        "contentHashAlgorithm": "sha256-semantic-visible-text-set-v2",
        "visibleTextHashAlgorithm": "sha256-normalized-visible-text-v1",
        "sources": sources,
    }
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for error in errors:
        print(f"Warning: {error}", file=sys.stderr)
    changed = sum(
        item.get("lastCheckStatus", "success") == "success"
        and item.get("changeType") in {"new", "updated"}
        for item in collected
    )
    print(f"Collected {len(collected)} official page snapshots for {len(selected)} companies; {changed} changed, {len(errors)} failed.")
    return 0 if collected or not selected else 1


if __name__ == "__main__":
    raise SystemExit(main())
