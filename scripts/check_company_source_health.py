#!/usr/bin/env python3
"""Report official-source coverage and fail only on anomalous collection health."""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check official company source collection health.")
    parser.add_argument("--sources", default="data/raw/company_sources_latest.json")
    parser.add_argument("--max-failure-rate", type=float, default=0.9)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    sources = [item for item in payload.get("sources", []) if isinstance(item, dict)]
    status = collections.Counter(item.get("lastCheckStatus", "success") for item in sources)
    failures = [item for item in sources if item.get("lastCheckStatus") == "failed"]
    errors = collections.Counter(str(item.get("lastCheckError") or "unknown") for item in failures)
    companies = {item.get("companyId") for item in sources if item.get("companyId")}
    return {
        "sourceCount": len(sources),
        "companyCount": len(companies),
        "successCount": status.get("success", 0),
        "failureCount": status.get("failed", 0),
        "failureRate": round(status.get("failed", 0) / len(sources), 4) if sources else 1.0,
        "failureReasons": dict(sorted(errors.items())),
    }


def main() -> int:
    args = parse_args()
    payload = json.loads(Path(args.sources).read_text(encoding="utf-8"))
    summary = summarize(payload)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"Official source health: {summary['successCount']}/{summary['sourceCount']} success, "
            f"{summary['failureCount']} failed ({summary['failureRate']:.1%})."
        )
        if summary["failureReasons"]:
            print("Failure reasons:", ", ".join(f"{key}={value}" for key, value in summary["failureReasons"].items()))
    if not summary["sourceCount"] or summary["failureRate"] > args.max_failure_rate:
        print("Official source failure rate exceeds configured threshold.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
