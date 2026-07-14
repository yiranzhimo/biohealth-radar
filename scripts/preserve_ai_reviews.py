#!/usr/bin/env python3
"""Preserve prior AI review metadata after regenerating BioHealth Radar data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy aiReview fields from an old data.js into a new data.js.")
    parser.add_argument("--previous", required=True, help="Previous data.js file.")
    parser.add_argument("--current", default="data.js", help="Current generated data.js file to update.")
    parser.add_argument(
        "--preserve-reviewed-status",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If a previous signal was marked reviewed, keep needsReview=false for the same signal ID.",
    )
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


def main() -> int:
    args = parse_args()
    previous_path = Path(args.previous)
    current_path = Path(args.current)
    if not previous_path.exists():
        print(f"Previous data file does not exist: {previous_path}. Nothing to preserve.")
        return 0

    previous = read_data_js(previous_path)
    current = read_data_js(current_path)
    previous_by_id = {
        signal.get("id"): signal
        for signal in previous.get("signals", [])
        if signal.get("id")
    }

    preserved_reviews = 0
    preserved_reviewed_status = 0
    for signal in current.get("signals", []):
        prior = previous_by_id.get(signal.get("id"))
        if not prior:
            continue
        if prior.get("aiReview") and not signal.get("aiReview"):
            signal["aiReview"] = prior["aiReview"]
            preserved_reviews += 1
        if args.preserve_reviewed_status and prior.get("needsReview") is False:
            signal["needsReview"] = False
            preserved_reviewed_status += 1

    write_data_js(current_path, current)
    print(
        f"Preserved {preserved_reviews} aiReview field(s) and "
        f"{preserved_reviewed_status} reviewed status flag(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
