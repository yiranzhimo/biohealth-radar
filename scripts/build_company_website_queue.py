#!/usr/bin/env python3
"""Build an auditable queue for resolving market links to true company domains."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build unresolved official website queue.")
    parser.add_argument("--profiles", default="data/company_profiles.json")
    parser.add_argument("--overrides", default="data/company_web_overrides.json")
    parser.add_argument("--output", default="data/raw/company_website_resolution_queue.json")
    return parser.parse_args()


def build_queue(profiles: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    override_map = overrides.get("overrides", {})
    items = []
    for profile in profiles.get("profiles", []):
        identity = profile.get("identity") or {}
        company_id = str(profile.get("companyId") or "")
        if not company_id or identity.get("websiteStatus") != "market_page_pending_official_domain":
            continue
        if company_id in override_map:
            continue
        items.append(
            {
                "companyId": company_id,
                "name": profile.get("name"),
                "marketPageUrl": identity.get("officialUrl"),
                "identifiers": identity.get("identifiers", {}),
                "sourceTypes": profile.get("classification", {}).get("directions", []),
                "status": "needs_official_domain",
            }
        )
    return {
        "schemaVersion": "1.0",
        "kind": "company_website_resolution_queue",
        "capturedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "count": len(items),
        "items": sorted(items, key=lambda item: str(item.get("name") or "").lower()),
    }


def main() -> int:
    args = parse_args()
    profiles = json.loads(Path(args.profiles).read_text(encoding="utf-8"))
    overrides = json.loads(Path(args.overrides).read_text(encoding="utf-8")) if Path(args.overrides).exists() else {}
    Path(args.output).write_text(json.dumps(build_queue(profiles, overrides), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Queued unresolved official domains: {build_queue(profiles, overrides)['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
