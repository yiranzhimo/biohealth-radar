#!/usr/bin/env python3
"""Validate the generated BioHealth Radar payload before publication."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from .review_fingerprint import review_input_hash
    from .review_company_candidates import POLICY_VERSION as CANDIDATE_REVIEW_POLICY_VERSION
    from .review_company_candidates import candidate_input_hash
    from .translate_company_sources import TRANSLATION_POLICY_VERSION, collect_source_texts, text_hash
except ImportError:
    from review_fingerprint import review_input_hash
    from review_company_candidates import POLICY_VERSION as CANDIDATE_REVIEW_POLICY_VERSION
    from review_company_candidates import candidate_input_hash
    from translate_company_sources import TRANSLATION_POLICY_VERSION, collect_source_texts, text_hash


REQUIRED_SIGNAL_FIELDS = (
    "id",
    "date",
    "title",
    "entity",
    "primaryCategory",
    "subCategory",
    "eventType",
    "sourceType",
    "sourceName",
    "sourceUrl",
    "reliability",
    "evidenceLevel",
    "needsReview",
    "themes",
    "tags",
    "companyIds",
    "fact",
    "report",
    "inference",
    "unknown",
)
ALLOWED_SOURCE_TYPES = {"Regulator", "Registry", "Paper", "Filing", "Company", "Media"}
ALLOWED_EVIDENCE_LEVELS = {"High", "Medium", "Low"}
ALLOWED_RELIABILITY_LEVELS = {"High", "Medium", "Low"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate generated BioHealth Radar data.")
    parser.add_argument("--data-file", default="data.js", help="Generated frontend data file.")
    parser.add_argument("--registry", default="data/companies.json", help="Canonical company registry.")
    parser.add_argument(
        "--company-sources",
        default="data/raw/company_sources_latest.json",
        help="Compact official company source snapshots, when present.",
    )
    parser.add_argument(
        "--company-discovery",
        default="data/raw/company_discovery_latest.json",
        help="Company mentions and candidates, when present.",
    )
    parser.add_argument(
        "--company-translations",
        default="data/raw/company_translations_latest.json",
        help="Cached Chinese translations of official company source text, when present.",
    )
    parser.add_argument(
        "--company-candidate-reviews",
        default="data/raw/company_candidate_reviews_latest.json",
        help="Automatic and manual candidate intake decisions, when present.",
    )
    parser.add_argument("--company-universe", default="data/company_universe.json")
    return parser.parse_args()


def read_data_js(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").strip()
    prefix = "window.BHR_DATA ="
    if not text.startswith(prefix):
        raise ValueError(f"{path} does not start with {prefix!r}")
    payload = json.loads(text[len(prefix) :].strip().rstrip(";"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def is_https_url(value: Any) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme == "https" and bool(parsed.netloc)


def validate_payload(payload: dict[str, Any], registry: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    try:
        dt.date.fromisoformat(str(payload.get("updatedAt", "")))
    except ValueError:
        errors.append(f"updatedAt is not an ISO date: {payload.get('updatedAt')!r}")

    companies = payload.get("companies")
    if companies != registry:
        errors.append("embedded companies do not exactly match data/companies.json")
    company_ids = [company.get("id") for company in registry if isinstance(company, dict)]
    if len(company_ids) != len(set(company_ids)) or any(not company_id for company_id in company_ids):
        errors.append("company registry IDs must be present and unique")
    known_company_ids = set(company_ids)

    sources = payload.get("sources")
    if not isinstance(sources, list):
        errors.append("sources must be a list")
    else:
        source_names = [source.get("name") for source in sources if isinstance(source, dict)]
        if len(source_names) != len(set(source_names)) or any(not name for name in source_names):
            errors.append("source names must be present and unique")

    signals = payload.get("signals")
    if not isinstance(signals, list):
        return [*errors, "signals must be a list"]

    seen_ids: set[str] = set()
    parsed_dates: list[dt.date] = []
    for index, signal in enumerate(signals):
        if not isinstance(signal, dict):
            errors.append(f"signals[{index}] must be an object")
            continue
        signal_id = str(signal.get("id") or f"signals[{index}]")
        missing = [field for field in REQUIRED_SIGNAL_FIELDS if field not in signal]
        if missing:
            errors.append(f"{signal_id}: missing required fields {', '.join(missing)}")
        if signal_id in seen_ids:
            errors.append(f"{signal_id}: duplicate signal ID")
        seen_ids.add(signal_id)

        try:
            parsed_date = dt.date.fromisoformat(str(signal.get("date", "")))
            parsed_dates.append(parsed_date)
            if parsed_date > dt.date.today():
                errors.append(f"{signal_id}: future signal date {parsed_date.isoformat()}")
        except ValueError:
            errors.append(f"{signal_id}: invalid ISO date {signal.get('date')!r}")

        if signal.get("sourceType") not in ALLOWED_SOURCE_TYPES:
            errors.append(f"{signal_id}: invalid sourceType {signal.get('sourceType')!r}")
        if signal.get("evidenceLevel") not in ALLOWED_EVIDENCE_LEVELS:
            errors.append(f"{signal_id}: invalid evidenceLevel {signal.get('evidenceLevel')!r}")
        if signal.get("reliability") not in ALLOWED_RELIABILITY_LEVELS:
            errors.append(f"{signal_id}: invalid reliability {signal.get('reliability')!r}")
        if not isinstance(signal.get("needsReview"), bool):
            errors.append(f"{signal_id}: needsReview must be boolean")
        for field in ("themes", "tags", "companyIds"):
            if not isinstance(signal.get(field), list):
                errors.append(f"{signal_id}: {field} must be a list")
        signal_company_ids = signal.get("companyIds")
        if isinstance(signal_company_ids, list):
            if any(not isinstance(company_id, str) for company_id in signal_company_ids):
                errors.append(f"{signal_id}: companyIds must contain only strings")
            else:
                unknown_companies = sorted(set(signal_company_ids) - known_company_ids)
                if unknown_companies:
                    errors.append(f"{signal_id}: unknown company IDs {', '.join(unknown_companies)}")
        if not is_https_url(signal.get("sourceUrl")):
            errors.append(f"{signal_id}: sourceUrl must be an absolute HTTPS URL")

        ai_review = signal.get("aiReview")
        if ai_review is not None and not isinstance(ai_review, dict):
            errors.append(f"{signal_id}: aiReview must be an object")
        elif ai_review and ai_review.get("inputHash"):
            if ai_review["inputHash"] != review_input_hash(signal):
                errors.append(f"{signal_id}: aiReview inputHash does not match current content")
        manual_review = signal.get("manualReview")
        if isinstance(manual_review, dict):
            if manual_review.get("inputHash") and manual_review["inputHash"] != review_input_hash(signal):
                errors.append(f"{signal_id}: manualReview inputHash does not match current content")
            if manual_review.get("status") == "reviewed" and signal.get("needsReview"):
                errors.append(f"{signal_id}: manually reviewed signal is still marked needsReview")

    if len(parsed_dates) == len(signals) and parsed_dates != sorted(parsed_dates, reverse=True):
        errors.append("signals must be sorted by date descending")
    return errors


def validate_company_sources(
    payload: dict[str, Any], registry: list[dict[str, Any]], universe: dict[str, Any] | None = None
) -> list[str]:
    errors: list[str] = []
    if payload.get("contentHashAlgorithm") != "sha256-semantic-visible-text-set-v2":
        errors.append("company sources: unsupported or missing contentHashAlgorithm")
    if payload.get("visibleTextHashAlgorithm") != "sha256-normalized-visible-text-v1":
        errors.append("company sources: unsupported or missing visibleTextHashAlgorithm")
    known_company_ids = {company.get("id") for company in registry}
    known_company_ids.update(item.get("id") for item in (universe or {}).get("entities", []))
    sources = payload.get("sources")
    if not isinstance(sources, list):
        return ["company sources: sources must be a list"]
    seen: set[tuple[Any, Any]] = set()
    for index, source in enumerate(sources):
        label = f"company sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{label} must be an object")
            continue
        company_id = source.get("companyId")
        role = source.get("sourceRole")
        key = (company_id, role)
        if key in seen:
            errors.append(f"{label}: duplicate company and source role")
        seen.add(key)
        if company_id not in known_company_ids and not str(company_id).startswith("candidate-"):
            errors.append(f"{label}: unknown company ID {company_id!r}")
        if role not in {"official", "pipeline", "investor_relations"}:
            errors.append(f"{label}: invalid sourceRole {role!r}")
        if source.get("lastCheckStatus", "success") not in {"success", "failed"}:
            errors.append(f"{label}: invalid lastCheckStatus {source.get('lastCheckStatus')!r}")
        for field in ("requestedUrl", "resolvedUrl"):
            if field == "resolvedUrl" and source.get("lastCheckStatus") == "failed" and not source.get(field):
                continue
            if not is_https_url(source.get(field)):
                errors.append(f"{label}: {field} must be an absolute HTTPS URL")
        for field in ("contentHash", "visibleTextHash"):
            if source.get("lastCheckStatus") == "failed" and not source.get(field):
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", str(source.get(field, ""))):
                errors.append(f"{label}: {field} must be a SHA-256 hex digest")
        excerpts = source.get("excerpts")
        if source.get("lastCheckStatus") == "failed" and excerpts is None:
            excerpts = []
        if not isinstance(excerpts, list) or len(excerpts) > 4:
            errors.append(f"{label}: excerpts must be a list with at most 4 items")
        elif any(not isinstance(item, str) or len(item) > 280 for item in excerpts):
            errors.append(f"{label}: excerpts must be strings no longer than 280 characters")
        for field in ("firstObservedAt", "lastChangedAt", "capturedAt"):
            if source.get("lastCheckStatus") == "failed" and not source.get(field):
                continue
            try:
                dt.datetime.fromisoformat(str(source.get(field, "")))
            except ValueError:
                errors.append(f"{label}: {field} must be an ISO timestamp")
        if source.get("lastCheckStatus") == "failed":
            try:
                dt.datetime.fromisoformat(str(source.get("lastFailureAt", "")))
            except ValueError:
                errors.append(f"{label}: failed check must include an ISO lastFailureAt")
    return errors


def validate_company_discovery(payload: dict[str, Any], registry: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    known_company_ids = {company.get("id") for company in registry}
    mentions = payload.get("mentions")
    candidates = payload.get("candidates")
    if not isinstance(mentions, list):
        return ["company discovery: mentions must be a list"]
    if not isinstance(candidates, list):
        return ["company discovery: candidates must be a list"]
    mention_ids: set[str] = set()
    for index, item in enumerate(mentions):
        label = f"company discovery mentions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        mention_id = item.get("id")
        if not mention_id or mention_id in mention_ids:
            errors.append(f"{label}: ID must be present and unique")
        mention_ids.add(str(mention_id))
        if not item.get("observedName") or not item.get("normalizedName"):
            errors.append(f"{label}: observedName and normalizedName are required")
        if item.get("sourceType") not in {"ClinicalTrials", "SEC", "NIH", "CSI", "HKEX", "HSI"}:
            errors.append(f"{label}: invalid sourceType {item.get('sourceType')!r}")
        if not is_https_url(item.get("sourceUrl")):
            errors.append(f"{label}: sourceUrl must be an absolute HTTPS URL")
        unknown_ids = sorted(set(item.get("knownCompanyIds", [])) - known_company_ids)
        if unknown_ids:
            errors.append(f"{label}: unknown company IDs {', '.join(unknown_ids)}")
    candidate_ids: set[str] = set()
    for index, item in enumerate(candidates):
        label = f"company discovery candidates[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        candidate_id = item.get("id")
        if not candidate_id or candidate_id in candidate_ids:
            errors.append(f"{label}: ID must be present and unique")
        candidate_ids.add(str(candidate_id))
        if item.get("status") not in {"needs_review", "identified", "corroborated", "verified", "rejected", "merged"}:
            errors.append(f"{label}: invalid status {item.get('status')!r}")
        score = item.get("discoveryScore")
        if not isinstance(score, (int, float)) or not 0 <= score <= 1:
            errors.append(f"{label}: discoveryScore must be between 0 and 1")
        unknown_mentions = sorted(set(item.get("mentionIds", [])) - mention_ids)
        if unknown_mentions:
            errors.append(f"{label}: unknown mention IDs {', '.join(unknown_mentions)}")
        if not item.get("name") or not item.get("normalizedName"):
            errors.append(f"{label}: name and normalizedName are required")
    return errors


def validate_company_translations(
    payload: dict[str, Any], source_payload: dict[str, Any] | None = None, *, require_all: bool = False
) -> list[str]:
    errors: list[str] = []
    if payload.get("translationPolicyVersion") != TRANSLATION_POLICY_VERSION:
        errors.append("company translations: unsupported or missing translationPolicyVersion")
    translations = payload.get("translations")
    if not isinstance(translations, list):
        return [*errors, "company translations: translations must be a list"]
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    valid_hashes: set[str] = set()
    for index, item in enumerate(translations):
        label = f"company translations[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        item_id = str(item.get("id") or "")
        digest = str(item.get("sourceTextHash") or "")
        source_text = str(item.get("sourceText") or "")
        translation = str(item.get("translationCn") or "")
        if not item_id or item_id in seen_ids:
            errors.append(f"{label}: ID must be present and unique")
        seen_ids.add(item_id)
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest != text_hash(source_text):
            errors.append(f"{label}: sourceTextHash does not match sourceText")
        if digest in seen_hashes:
            errors.append(f"{label}: duplicate sourceTextHash")
        seen_hashes.add(digest)
        if not translation.strip():
            errors.append(f"{label}: translationCn is required")
        if item.get("translationPolicyVersion") != TRANSLATION_POLICY_VERSION:
            errors.append(f"{label}: stale translationPolicyVersion")
        if item.get("provider") not in {"openai", "manual_bootstrap"}:
            errors.append(f"{label}: invalid provider {item.get('provider')!r}")
        if item.get("provider") == "openai" and not item.get("model"):
            errors.append(f"{label}: OpenAI translation must record model")
        try:
            dt.datetime.fromisoformat(str(item.get("translatedAt", "")))
        except ValueError:
            errors.append(f"{label}: translatedAt must be an ISO timestamp")
        if isinstance(item.get("sourceUses"), list):
            valid_hashes.add(digest)
        else:
            errors.append(f"{label}: sourceUses must be a list")
    if source_payload is not None and require_all:
        required_hashes = {
            item["sourceTextHash"]
            for item in collect_source_texts(source_payload)
            if any(not str(use.get("companyId", "")).startswith("candidate-") for use in item.get("sourceUses", []))
        }
        missing = sorted(required_hashes - valid_hashes)
        if missing:
            errors.append(f"company translations: {len(missing)} current source text(s) lack valid translation")
    return errors


def validate_company_candidate_reviews(
    payload: dict[str, Any], discovery_payload: dict[str, Any] | None = None
) -> list[str]:
    errors: list[str] = []
    if payload.get("policyVersion") != CANDIDATE_REVIEW_POLICY_VERSION:
        errors.append("company candidate reviews: unsupported or missing policyVersion")
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        return [*errors, "company candidate reviews: reviews must be a list"]
    candidates = {
        item.get("id"): item
        for item in (discovery_payload or {}).get("candidates", [])
        if item.get("id")
    }
    seen: set[str] = set()
    for index, item in enumerate(reviews):
        label = f"company candidate reviews[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        candidate_id = str(item.get("candidateId") or "")
        if not candidate_id or candidate_id in seen:
            errors.append(f"{label}: candidateId must be present and unique")
        seen.add(candidate_id)
        candidate = candidates.get(candidate_id)
        if discovery_payload is not None and candidate is None:
            errors.append(f"{label}: unknown candidateId {candidate_id!r}")
        elif candidate is not None and item.get("candidateInputHash") != candidate_input_hash(candidate):
            errors.append(f"{label}: candidateInputHash does not match current candidate")
        decision = item.get("decision")
        if decision not in {"accepted", "needs_human", "rejected", "merged"}:
            errors.append(f"{label}: invalid decision {decision!r}")
        if not isinstance(item.get("humanReviewRequired"), bool):
            errors.append(f"{label}: humanReviewRequired must be boolean")
        if not isinstance(item.get("universeEligible"), bool):
            errors.append(f"{label}: universeEligible must be boolean")
        if decision == "accepted" and (item.get("humanReviewRequired") or not item.get("universeEligible")):
            errors.append(f"{label}: accepted decision must be universe-eligible without human review")
        if decision == "needs_human" and not item.get("humanReviewRequired"):
            errors.append(f"{label}: needs_human decision must require human review")
        score = item.get("reviewScore")
        if not isinstance(score, (int, float)) or not 0 <= score <= 1:
            errors.append(f"{label}: reviewScore must be between 0 and 1")
        if not isinstance(item.get("reviewReasons"), list) or not item.get("reviewReasons"):
            errors.append(f"{label}: reviewReasons must be a non-empty list")
    if discovery_payload is not None:
        missing = sorted(set(candidates) - seen)
        if missing:
            errors.append(f"company candidate reviews: {len(missing)} candidate(s) lack review")
    return errors


def main() -> int:
    args = parse_args()
    try:
        payload = read_data_js(Path(args.data_file))
        registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
        if not isinstance(registry, list):
            raise ValueError("company registry must contain a JSON list")
        errors = validate_payload(payload, registry)
        universe_path = Path(args.company_universe)
        universe = json.loads(universe_path.read_text(encoding="utf-8")) if universe_path.exists() else {}
        company_sources_path = Path(args.company_sources)
        company_source_count = 0
        company_sources: dict[str, Any] | None = None
        if company_sources_path.exists():
            company_sources = json.loads(company_sources_path.read_text(encoding="utf-8"))
            errors.extend(validate_company_sources(company_sources, registry, universe))
            company_source_count = len(company_sources.get("sources", []))
        company_discovery_path = Path(args.company_discovery)
        company_mention_count = 0
        company_candidate_count = 0
        if company_discovery_path.exists():
            company_discovery = json.loads(company_discovery_path.read_text(encoding="utf-8"))
            errors.extend(validate_company_discovery(company_discovery, registry))
            company_mention_count = len(company_discovery.get("mentions", []))
            company_candidate_count = len(company_discovery.get("candidates", []))
        else:
            company_discovery = None
        company_candidate_reviews_path = Path(args.company_candidate_reviews)
        company_review_count = 0
        if company_candidate_reviews_path.exists():
            company_candidate_reviews = json.loads(company_candidate_reviews_path.read_text(encoding="utf-8"))
            errors.extend(validate_company_candidate_reviews(company_candidate_reviews, company_discovery))
            company_review_count = len(company_candidate_reviews.get("reviews", []))
        company_translations_path = Path(args.company_translations)
        company_translation_count = 0
        if company_translations_path.exists():
            company_translations = json.loads(company_translations_path.read_text(encoding="utf-8"))
            errors.extend(validate_company_translations(company_translations, company_sources))
            company_translation_count = len(company_translations.get("translations", []))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Data validation failed: {exc}", file=sys.stderr)
        return 1

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Data validation failed with {len(errors)} error(s).", file=sys.stderr)
        return 1
    print(
        f"Validated {len(payload.get('signals', []))} signal(s), {len(registry)} company record(s), "
        f"{company_source_count} official company source snapshot(s), {company_mention_count} company mention(s), "
        f"{company_candidate_count} company candidate(s), {company_review_count} candidate review(s), "
        f"and {company_translation_count} company translation(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
