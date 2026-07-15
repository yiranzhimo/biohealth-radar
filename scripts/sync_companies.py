#!/usr/bin/env python3
"""Embed the company registry in data.js and refresh signal-company links."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .company_registry import load_companies, match_signal_company_ids
except ImportError:
    from company_registry import load_companies, match_signal_company_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync the company registry into BioHealth Radar data.js.")
    parser.add_argument("--registry", default="data/companies.json", help="Company registry JSON file.")
    parser.add_argument("--data-file", default="data.js", help="Frontend data.js file.")
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
    companies = load_companies(args.registry)
    data_path = Path(args.data_file)
    payload = read_data_js(data_path)
    payload["companies"] = companies

    linked_signals = 0
    for signal in payload.get("signals", []):
        signal["companyIds"] = match_signal_company_ids(signal, companies)
        if signal["companyIds"]:
            linked_signals += 1

    write_data_js(data_path, payload)
    print(f"Synced {len(companies)} companies; linked {linked_signals} signal(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
