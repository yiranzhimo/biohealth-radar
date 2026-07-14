#!/usr/bin/env python3
"""Mark BioHealth Radar signals as manually reviewed."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mark one or more BioHealth Radar signals as manually reviewed.")
    parser.add_argument("signal_ids", nargs="+", help="Signal IDs to mark reviewed, e.g. pubmed-42443151.")
    parser.add_argument("--data-file", default="data.js", help="Frontend data.js file to update.")
    parser.add_argument("--reviewer", default="manual", help="Reviewer label stored in manualReview.")
    parser.add_argument("--note", default="", help="Short review note.")
    parser.add_argument("--status", choices=["reviewed", "rejected"], default="reviewed", help="Manual review status.")
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
    data_path = Path(args.data_file)
    payload = read_data_js(data_path)
    wanted = set(args.signal_ids)
    found: set[str] = set()
    reviewed_at = dt.datetime.now(dt.timezone.utc).isoformat()

    for signal in payload.get("signals", []):
        signal_id = signal.get("id")
        if signal_id not in wanted:
            continue
        found.add(signal_id)
        signal["needsReview"] = args.status != "reviewed"
        signal["manualReview"] = {
            "status": args.status,
            "reviewer": args.reviewer,
            "reviewedAt": reviewed_at,
            "note": args.note,
        }

    missing = sorted(wanted - found)
    if missing:
        print(f"Signal ID(s) not found: {', '.join(missing)}", file=sys.stderr)
        return 1

    payload["updatedAt"] = dt.date.today().isoformat()
    write_data_js(data_path, payload)
    print(f"Marked {len(found)} signal(s) as {args.status}: {', '.join(sorted(found))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
