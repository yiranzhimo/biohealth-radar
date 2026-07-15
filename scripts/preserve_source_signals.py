#!/usr/bin/env python3
"""Preserve source-specific signals when an optional collector is unavailable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preserve source signals from a previous data.js snapshot.")
    parser.add_argument("--previous", required=True, help="Previous data.js snapshot.")
    parser.add_argument("--current", default="data.js", help="Current generated data.js.")
    parser.add_argument("--id-prefix", required=True, help="Signal ID prefix to preserve, such as sec-.")
    parser.add_argument("--max-signals", type=int, default=120, help="Maximum matching signals to retain.")
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


def preserve_signals(
    previous: dict[str, Any],
    current: dict[str, Any],
    id_prefix: str,
    max_signals: int,
) -> int:
    current_signals = current.get("signals", [])
    current_by_id = {signal.get("id"): signal for signal in current_signals if signal.get("id")}
    candidates = [
        signal
        for signal in previous.get("signals", [])
        if str(signal.get("id", "")).startswith(id_prefix)
    ]
    added = 0
    for signal in candidates:
        if signal.get("id") not in current_by_id:
            current_by_id[signal["id"]] = signal
            added += 1

    matching = sorted(
        [signal for signal in current_by_id.values() if str(signal.get("id", "")).startswith(id_prefix)],
        key=lambda item: item.get("date", ""),
        reverse=True,
    )[:max_signals]
    non_matching = [
        signal
        for signal in current_by_id.values()
        if not str(signal.get("id", "")).startswith(id_prefix)
    ]
    current["signals"] = sorted(
        [*non_matching, *matching],
        key=lambda item: item.get("date", ""),
        reverse=True,
    )
    return added


def main() -> int:
    args = parse_args()
    previous_path = Path(args.previous)
    current_path = Path(args.current)
    if not previous_path.exists():
        print(f"Previous data file does not exist: {previous_path}. Nothing to preserve.")
        return 0

    previous = read_data_js(previous_path)
    current = read_data_js(current_path)
    added = preserve_signals(previous, current, args.id_prefix, args.max_signals)
    write_data_js(current_path, current)
    print(f"Preserved {added} missing signal(s) with prefix {args.id_prefix}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
