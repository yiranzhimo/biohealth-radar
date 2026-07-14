#!/usr/bin/env python3
"""Run AI-assisted review for BioHealth Radar signals with the OpenAI API.

This script performs structured pre-review. It should not be treated as a final
medical, clinical, regulatory, or investment judgment.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4o-mini"
REVIEW_POLICY_VERSION = "publication-quality-v2"

SYSTEM_PROMPT = """You are reviewing biotech and healthcare intelligence signals.

Your task is publication-quality review, source hygiene, and triage. You are not
reviewing whether a biomedical intervention is clinically valid, and you must not
provide medical advice.

Review only the supplied signal fields. Do not invent external facts. Separate:
- fact: directly supported by the source metadata in the signal
- report: what the source claims or reports
- inference: what the platform inferred from those fields
- unknown: what is missing or cannot be verified from the signal

Judge whether the supplied card can be published as a neutral intelligence record.
The mere fact that a source concerns a disease, clinical trial, treatment, safety,
regulation, or patient population is NOT by itself a reason to require human review.
A registry record may safely report that a study exists, but must not imply that its
intervention works. A PubMed record may safely report the article's title and topic,
but must not turn the title into a verified clinical conclusion.

Return status=pass and humanReviewRequired=false when all of these are true:
- the category and evidence level are reasonable for the supplied metadata
- fact, report, inference, and unknown are clearly separated
- efficacy, safety, regulatory, commercial, and patient-impact statements are
  attributed to the source or explicitly marked as unknown
- there is no treatment recommendation or unsupported clinical conclusion

Return status=needs_human and humanReviewRequired=true only when publication needs
judgment or correction, including unsupported efficacy or safety conclusions,
treatment advice, evidence inflation, materially weak classification, contradictory
fields, or source metadata too sparse to support the card. Use riskFlags to record
clinical or regulatory subject matter even when the card passes; a risk flag does
not automatically require human review.

Do not generalize from a single study, registry record, company claim, or preprint
into treatment advice. Return only JSON that matches the schema."""

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "status",
        "confidence",
        "humanReviewRequired",
        "reviewSummaryCn",
        "classificationAssessment",
        "sourceEvidenceAssessment",
        "riskFlags",
        "suggestedEdits",
    ],
    "properties": {
        "status": {
            "type": "string",
            "enum": ["pass", "needs_human", "fail"],
            "description": "pass means the card is internally consistent and neutrally grounded for publication; needs_human means publication needs judgment or correction; fail means materially incorrect or unsafe.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "humanReviewRequired": {
            "type": "boolean",
            "description": "True only when publication needs human judgment or correction. Clinical subject matter alone is not sufficient.",
        },
        "reviewSummaryCn": {
            "type": "string",
            "description": "Concise Chinese review summary.",
        },
        "classificationAssessment": {
            "type": "object",
            "additionalProperties": False,
            "required": ["isSupported", "notesCn"],
            "properties": {
                "isSupported": {"type": "boolean"},
                "notesCn": {"type": "string"},
            },
        },
        "sourceEvidenceAssessment": {
            "type": "object",
            "additionalProperties": False,
            "required": ["factReportInferenceSeparated", "evidenceLevelReasonable", "notesCn"],
            "properties": {
                "factReportInferenceSeparated": {"type": "boolean"},
                "evidenceLevelReasonable": {"type": "boolean"},
                "notesCn": {"type": "string"},
            },
        },
        "riskFlags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Short risk tags such as clinical_claim, medical_advice_risk, weak_classification, insufficient_source, regulatory_claim, commercial_claim.",
        },
        "suggestedEdits": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "primaryCategory",
                "subCategory",
                "evidenceLevel",
                "themes",
                "tags",
                "fact",
                "report",
                "inference",
                "unknown",
            ],
            "properties": {
                "primaryCategory": {"type": "string"},
                "subCategory": {"type": "string"},
                "evidenceLevel": {"type": "string", "enum": ["High", "Medium", "Low"]},
                "themes": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "fact": {"type": "string"},
                "report": {"type": "string"},
                "inference": {"type": "string"},
                "unknown": {"type": "string"},
            },
        },
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI-assisted review for BioHealth Radar signals.")
    parser.add_argument("--data-file", default="data.js", help="Frontend data.js file to read and update.")
    parser.add_argument("--raw-output", default="data/raw/openai_reviews_latest.json", help="Raw AI review output JSON.")
    parser.add_argument("--model", default=os.environ.get("OPENAI_REVIEW_MODEL", DEFAULT_MODEL), help="OpenAI model ID.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum signals to review.")
    parser.add_argument("--force", action="store_true", help="Review signals even if aiReview already exists.")
    parser.add_argument("--dry-run", action="store_true", help="Show selected candidates without calling the API.")
    parser.add_argument(
        "--apply-needs-review",
        action="store_true",
        help="Allow AI review to clear needsReview for high-confidence low-risk passes.",
    )
    parser.add_argument(
        "--auto-clear-threshold",
        type=float,
        default=0.85,
        help="Minimum confidence for clearing needsReview when --apply-needs-review is set.",
    )
    parser.add_argument("--sleep", type=float, default=0.2, help="Delay between API calls.")
    return parser.parse_args()


def read_data_js(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").strip()
    prefix = "window.BHR_DATA ="
    if not text.startswith(prefix):
        raise ValueError(f"{path} does not look like a BioHealth Radar data.js file")
    return json.loads(text[len(prefix) :].strip().rstrip(";"))


def write_data_js(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(f"window.BHR_DATA = {serialized};\n", encoding="utf-8")


def select_candidates(signals: list[dict[str, Any]], limit: int, force: bool) -> list[dict[str, Any]]:
    candidates = []
    for signal in signals:
        ai_review = signal.get("aiReview") or {}
        if not force and ai_review.get("policyVersion") == REVIEW_POLICY_VERSION:
            continue
        if not signal.get("needsReview") and not force:
            continue
        candidates.append(signal)
        if len(candidates) >= limit:
            break
    return candidates


def build_user_payload(signal: dict[str, Any]) -> str:
    review_input = {
        "id": signal.get("id"),
        "date": signal.get("date"),
        "title": signal.get("title"),
        "entity": signal.get("entity"),
        "primaryCategory": signal.get("primaryCategory"),
        "subCategory": signal.get("subCategory"),
        "eventType": signal.get("eventType"),
        "sourceType": signal.get("sourceType"),
        "sourceName": signal.get("sourceName"),
        "sourceUrl": signal.get("sourceUrl"),
        "reliability": signal.get("reliability"),
        "evidenceLevel": signal.get("evidenceLevel"),
        "themes": signal.get("themes", []),
        "tags": signal.get("tags", []),
        "fact": signal.get("fact"),
        "report": signal.get("report"),
        "inference": signal.get("inference"),
        "unknown": signal.get("unknown"),
    }
    return json.dumps(review_input, ensure_ascii=False, indent=2)


def call_openai(signal: dict[str, Any], model: str, api_key: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": build_user_payload(signal)}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "biohealth_signal_review",
                "strict": True,
                "schema": REVIEW_SCHEMA,
            }
        },
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        RESPONSES_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {detail}") from exc

    output_text = extract_output_text(response_payload)
    if not output_text:
        raise RuntimeError(f"OpenAI response did not contain output text: {response_payload}")
    review = json.loads(output_text)
    return {
        "responseId": response_payload.get("id"),
        "review": review,
    }


def extract_output_text(response_payload: dict[str, Any]) -> str:
    if response_payload.get("output_text"):
        return response_payload["output_text"]
    for item in response_payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    return ""


def should_clear_review(review: dict[str, Any], threshold: float) -> bool:
    return (
        review.get("status") == "pass"
        and not review.get("humanReviewRequired")
        and float(review.get("confidence", 0)) >= threshold
    )


def apply_review(
    signal: dict[str, Any],
    review: dict[str, Any],
    response_id: str,
    model: str,
    reviewed_at: str,
    apply_needs_review: bool,
    clear_threshold: float,
) -> None:
    signal["aiReview"] = {
        "provider": "openai",
        "model": model,
        "policyVersion": REVIEW_POLICY_VERSION,
        "responseId": response_id,
        "reviewedAt": reviewed_at,
        **review,
    }
    if apply_needs_review:
        if should_clear_review(review, clear_threshold):
            signal["needsReview"] = False
        elif not signal.get("manualReview"):
            signal["needsReview"] = True


def main() -> int:
    args = parse_args()
    data_path = Path(args.data_file)
    payload = read_data_js(data_path)
    signals = payload.get("signals", [])
    candidates = select_candidates(signals, args.limit, args.force)

    print(f"Selected {len(candidates)} signal(s) for OpenAI review.")
    for signal in candidates:
        print(f"- {signal.get('id')} | {signal.get('sourceType')} | {signal.get('title', '')[:90]}")

    if args.dry_run:
        return 0

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set. Export it before running this script.", file=sys.stderr)
        return 2

    reviewed_at = dt.datetime.now(dt.timezone.utc).isoformat()
    raw_reviews: list[dict[str, Any]] = []
    for signal in candidates:
        result = call_openai(signal, args.model, api_key)
        review = result["review"]
        apply_review(
            signal,
            review,
            result.get("responseId", ""),
            args.model,
            reviewed_at,
            args.apply_needs_review,
            args.auto_clear_threshold,
        )
        raw_reviews.append(
            {
                "signalId": signal.get("id"),
                "responseId": result.get("responseId"),
                "review": review,
            }
        )
        print(
            f"Reviewed {signal.get('id')}: {review.get('status')} "
            f"confidence={review.get('confidence')} human={review.get('humanReviewRequired')}"
        )
        time.sleep(args.sleep)

    payload["updatedAt"] = dt.date.today().isoformat()
    raw_output = Path(args.raw_output)
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_text(
        json.dumps(
            {
                "capturedAt": reviewed_at,
                "model": args.model,
                "policyVersion": REVIEW_POLICY_VERSION,
                "applyNeedsReview": args.apply_needs_review,
                "autoClearThreshold": args.auto_clear_threshold,
                "reviews": raw_reviews,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_data_js(data_path, payload)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"review_with_openai.py failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
