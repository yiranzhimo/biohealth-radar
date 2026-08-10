#!/usr/bin/env python3
"""Build a stable fingerprint for the fields supplied to signal review."""

from __future__ import annotations

import hashlib
import json
from typing import Any


REVIEW_INPUT_FIELDS = (
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
    "themes",
    "tags",
    "fact",
    "report",
    "inference",
    "unknown",
)


def review_input_payload(signal: dict[str, Any]) -> dict[str, Any]:
    payload = {field: signal.get(field) for field in REVIEW_INPUT_FIELDS}
    payload["themes"] = signal.get("themes", [])
    payload["tags"] = signal.get("tags", [])
    return payload


def review_input_hash(signal: dict[str, Any]) -> str:
    serialized = json.dumps(
        review_input_payload(signal),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
