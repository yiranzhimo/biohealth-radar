#!/usr/bin/env python3
"""Translate official company-source text into Simplified Chinese with an auditable cache."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

try:
    from .http_utils import urlopen_with_retry
except ImportError:
    from http_utils import urlopen_with_retry


RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = os.environ.get("OPENAI_REVIEW_MODEL", "gpt-4o-mini")
TRANSLATION_POLICY_VERSION = "company-source-zh-cn-v1"
REPORTED_PLAN_TERMS = re.compile(
    r"\b(plans? to|intends? to|expects? to|"
    r"will (?:advance|build|commercialize|continue|deliver|develop|drive|expand|file|focus|"
    r"initiate|invest|launch|pursue|submit))\b",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """Translate the supplied official biotech company source text into faithful,
natural Simplified Chinese.

Rules:
- Translate only the supplied text. Do not summarize, add facts, or strengthen claims.
- Preserve company names, product and drug names, study identifiers, trademarks, tickers,
  scientific abbreviations, and established terms such as CRISPR, CAR-T, ADC, RNA, and mRNA.
- Preserve uncertainty, attribution, approval scope, and forward-looking wording exactly in meaning.
- Do not turn a company statement into an independently verified fact or medical advice.
- Return exactly one translation for every supplied id and no extra ids.
- Return only JSON matching the schema."""

TRANSLATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["translations"],
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "translationCn"],
                "properties": {
                    "id": {"type": "string"},
                    "translationCn": {"type": "string"},
                },
            },
        }
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Translate official company source text to Chinese.")
    parser.add_argument("--sources", default="data/raw/company_sources_latest.json")
    parser.add_argument("--output", default="data/raw/company_translations_latest.json")
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_TRANSLATION_MODEL", DEFAULT_MODEL),
        help="OpenAI model ID used for translation.",
    )
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--limit", type=int, help="Maximum pending text items to translate.")
    parser.add_argument("--force", action="store_true", help="Translate current text even when cached.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true", help="Fail if current source text lacks translation.")
    parser.add_argument(
        "--strict-check",
        action="store_true",
        help="When checking, fail on any pending translation. Useful after the translation job.",
    )
    parser.add_argument("--sleep", type=float, default=0.2)
    return parser.parse_args()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def translation_id(text: str) -> str:
    return f"translation-{text_hash(text)[:16]}"


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def collect_source_texts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    uses_by_text: dict[str, list[dict[str, str]]] = defaultdict(list)
    for source in payload.get("sources", []):
        excerpts = source.get("excerpts", [])
        claim = str(source.get("description") or (excerpts[0] if excerpts else "") or source.get("title") or "").strip()
        if claim:
            uses_by_text[claim].append(
                {
                    "companyId": str(source.get("companyId") or ""),
                    "sourceRole": str(source.get("sourceRole") or "official"),
                    "field": "business_summary",
                }
            )
        for excerpt in excerpts:
            plan = str(excerpt or "").strip()
            if plan and REPORTED_PLAN_TERMS.search(plan):
                uses_by_text[plan].append(
                    {
                        "companyId": str(source.get("companyId") or ""),
                        "sourceRole": str(source.get("sourceRole") or "official"),
                        "field": "future_plan",
                    }
                )
    return [
        {
            "id": translation_id(text),
            "sourceTextHash": text_hash(text),
            "sourceText": text,
            "sourceUses": sorted(uses, key=lambda item: (item["companyId"], item["sourceRole"], item["field"])),
        }
        for text, uses in sorted(uses_by_text.items())
        if not contains_chinese(text)
    ]


def valid_cached(entry: dict[str, Any], required: dict[str, Any]) -> bool:
    return bool(
        entry.get("sourceTextHash") == required["sourceTextHash"]
        and entry.get("sourceText") == required["sourceText"]
        and entry.get("translationCn")
        and entry.get("translationPolicyVersion") == TRANSLATION_POLICY_VERSION
    )


def select_pending(
    required: list[dict[str, Any]], previous_payload: dict[str, Any], force: bool = False
) -> list[dict[str, Any]]:
    previous = {item.get("sourceTextHash"): item for item in previous_payload.get("translations", [])}
    if force:
        return required
    return [item for item in required if not valid_cached(previous.get(item["sourceTextHash"], {}), item)]


def extract_output_text(response_payload: dict[str, Any]) -> str:
    if response_payload.get("output_text"):
        return str(response_payload["output_text"])
    for item in response_payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return str(content["text"])
    return ""


def call_openai(items: list[dict[str, Any]], model: str, api_key: str) -> dict[str, Any]:
    user_payload = {
        "targetLanguage": "Simplified Chinese (zh-CN)",
        "items": [{"id": item["id"], "sourceText": item["sourceText"]} for item in items],
    }
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
            {
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "company_source_translation",
                "strict": True,
                "schema": TRANSLATION_SCHEMA,
            }
        },
    }
    request = urllib.request.Request(
        RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen_with_retry(request, timeout=90) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {detail}") from exc
    output_text = extract_output_text(response_payload)
    if not output_text:
        raise RuntimeError("OpenAI response did not contain output text")
    result = json.loads(output_text)
    expected_ids = {item["id"] for item in items}
    translations = result.get("translations", [])
    actual_ids = {item.get("id") for item in translations}
    if actual_ids != expected_ids or len(translations) != len(items):
        raise RuntimeError(f"Translation response IDs did not match request: expected={expected_ids}, actual={actual_ids}")
    if any(not str(item.get("translationCn") or "").strip() for item in translations):
        raise RuntimeError("Translation response contained an empty translation")
    return {"responseId": response_payload.get("id"), "translations": translations}


def merge_translations(
    required: list[dict[str, Any]],
    previous_payload: dict[str, Any],
    translated: list[dict[str, Any]],
    *,
    model: str,
    translated_at: str,
) -> list[dict[str, Any]]:
    by_hash = {
        str(item.get("sourceTextHash")): dict(item)
        for item in previous_payload.get("translations", [])
        if item.get("sourceTextHash")
    }
    required_by_id = {item["id"]: item for item in required}
    for result in translated:
        item = required_by_id[result["id"]]
        by_hash[item["sourceTextHash"]] = {
            **item,
            "translationCn": str(result["translationCn"]).strip(),
            "provider": "openai",
            "model": model,
            "translatedAt": translated_at,
            "translationPolicyVersion": TRANSLATION_POLICY_VERSION,
            "responseId": result.get("responseId"),
        }
    for item in required:
        cached = by_hash.get(item["sourceTextHash"])
        if cached and valid_cached(cached, item):
            cached["sourceUses"] = item["sourceUses"]
    return sorted(by_hash.values(), key=lambda item: (item.get("sourceTextHash", ""), item.get("id", "")))


def translate_pending(
    pending: list[dict[str, Any]],
    *,
    model: str,
    api_key: str,
    batch_size: int,
    sleep_seconds: float,
    caller: Callable[[list[dict[str, Any]], str, str], dict[str, Any]] = call_openai,
) -> list[dict[str, Any]]:
    completed: list[dict[str, Any]] = []
    size = max(1, batch_size)
    for offset in range(0, len(pending), size):
        batch = pending[offset : offset + size]
        result = caller(batch, model, api_key)
        for item in result["translations"]:
            completed.append({**item, "responseId": result.get("responseId")})
        if offset + size < len(pending):
            time.sleep(max(0, sleep_seconds))
    return completed


def main() -> int:
    args = parse_args()
    source_path = Path(args.sources)
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    output_path = Path(args.output)
    previous_payload = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else {}
    required = collect_source_texts(source_payload)
    pending = select_pending(required, previous_payload, force=args.force)
    if args.limit is not None:
        pending = pending[: max(0, args.limit)]
    print(f"Found {len(required)} translatable source text(s); {len(pending)} pending.")
    for item in pending:
        print(f"- {item['id']} | {item['sourceText'][:100]}")
    if args.check:
        return 1 if args.strict_check and pending else 0
    if args.dry_run:
        return 0
    if not pending:
        return 0
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("OPENAI_API_KEY is required when company-source translations are pending.", file=sys.stderr)
        return 2
    translated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    translated = translate_pending(
        pending,
        model=args.model,
        api_key=api_key,
        batch_size=args.batch_size,
        sleep_seconds=args.sleep,
    )
    translations = merge_translations(
        required,
        previous_payload,
        translated,
        model=args.model,
        translated_at=translated_at,
    )
    payload = {
        "schemaVersion": "1.0",
        "kind": "company_source_translations",
        "capturedAt": translated_at,
        "sourceCapturedAt": source_payload.get("capturedAt")
        or max((str(item.get("capturedAt") or "") for item in source_payload.get("sources", [])), default="")
        or None,
        "translationPolicyVersion": TRANSLATION_POLICY_VERSION,
        "translations": translations,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Stored {len(translations)} cached company-source translation(s).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"translate_company_sources.py failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
