#!/usr/bin/env python3
"""Apply deterministic, evidence-gated intake review to discovered company candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


POLICY_VERSION = "company-intake-v3"
STABLE_IDENTIFIER_KINDS = {
    "cik",
    "cnSecurityCode",
    "hkexStockCode",
    "isin",
    "uei",
    "nihIpf",
}
MANUAL_DECISIONS = {"accepted", "rejected", "merged", "needs_human"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automatically review discovered company candidates.")
    parser.add_argument("--discovery", default="data/raw/company_discovery_latest.json")
    parser.add_argument("--overrides", default="data/company_candidate_overrides.json")
    parser.add_argument("--output", default="data/raw/company_candidate_reviews_latest.json")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def candidate_input_hash(candidate: dict[str, Any]) -> str:
    material = {
        "id": candidate.get("id"),
        "normalizedName": candidate.get("normalizedName"),
        "identifiers": candidate.get("identifiers", {}),
        "sourceTypes": candidate.get("sourceTypes", []),
        "mentionIds": candidate.get("mentionIds", []),
        "classificationHints": candidate.get("classificationHints", {}),
        "discoveryScore": candidate.get("discoveryScore"),
    }
    serialized = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def identifier_values(candidate: dict[str, Any], kind: str) -> list[str]:
    values = candidate.get("identifiers", {}).get(kind, [])
    if isinstance(values, str):
        values = [values]
    return sorted({str(value).strip() for value in values if str(value).strip()})


def stable_identifiers(candidate: dict[str, Any]) -> dict[str, list[str]]:
    return {
        kind: values
        for kind in sorted(STABLE_IDENTIFIER_KINDS)
        if (values := identifier_values(candidate, kind))
    }


def identifier_conflicts(candidate: dict[str, Any]) -> list[str]:
    return [kind for kind, values in stable_identifiers(candidate).items() if len(values) > 1]


def valid_sec_identity(candidate: dict[str, Any]) -> bool:
    ciks = identifier_values(candidate, "cik")
    return "SEC" in candidate.get("sourceTypes", []) and len(ciks) == 1 and bool(re.fullmatch(r"\d{10}", ciks[0]))


def valid_nih_identity(candidate: dict[str, Any]) -> bool:
    identifiers = stable_identifiers(candidate)
    return "NIH" in candidate.get("sourceTypes", []) and bool(identifiers.get("uei") or identifiers.get("nihIpf"))


def valid_csi_identity(candidate: dict[str, Any]) -> bool:
    codes = identifier_values(candidate, "cnSecurityCode")
    return "CSI" in candidate.get("sourceTypes", []) and len(codes) == 1 and bool(re.fullmatch(r"\d{6}", codes[0]))


def valid_hkex_identity(candidate: dict[str, Any]) -> bool:
    codes = identifier_values(candidate, "hkexStockCode")
    return "HKEX" in candidate.get("sourceTypes", []) and len(codes) == 1 and bool(re.fullmatch(r"\d{5}", codes[0]))


def valid_hsi_identity(candidate: dict[str, Any]) -> bool:
    codes = identifier_values(candidate, "hkexStockCode")
    isins = identifier_values(candidate, "isin")
    return (
        "HSI" in candidate.get("sourceTypes", [])
        and len(codes) == 1
        and bool(re.fullmatch(r"\d{5}", codes[0]))
        and len(isins) == 1
        and bool(re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", isins[0]))
    )


def automatic_review(candidate: dict[str, Any], reviewed_at: str) -> dict[str, Any]:
    conflicts = identifier_conflicts(candidate)
    source_types = set(candidate.get("sourceTypes", []))
    hints = candidate.get("classificationHints", {}).get("directions", [])
    stable = stable_identifiers(candidate)
    reasons: list[str] = []
    flags: list[str] = []

    if conflicts:
        reasons.append(f"同一候选聚类包含多个 {', '.join(conflicts)}，可能混合了不同法律实体。")
        flags.append("conflicting_stable_identifiers")
        decision = "needs_human"
        identity_status = "conflicting"
        biotech_status = "unresolved"
        score = 0.35
    elif valid_sec_identity(candidate):
        reasons.append("SEC EDGAR 提供唯一 CIK，可自动确认法律实体身份。")
        reasons.append("SEC 将该实体列入 biotech 相关 SIC 2833–2836，满足公司池领域准入条件。")
        decision = "accepted"
        identity_status = "verified"
        biotech_status = "supported"
        score = 0.97
    elif valid_nih_identity(candidate) and hints:
        reasons.append("NIH RePORTER 提供 UEI 或 NIH IPF，可自动确认营利性获资助机构身份。")
        reasons.append("该机构出现在 biotech 主题项目中，满足公司池领域准入条件。")
        decision = "accepted"
        identity_status = "verified"
        biotech_status = "supported"
        score = 0.91
    elif valid_csi_identity(candidate):
        reasons.append("中证指数提供唯一六位证券代码，可确认科创板上市证券身份。")
        reasons.append("该证券属于上证科创板生物医药指数成分，满足公司池领域准入条件。")
        decision = "accepted"
        identity_status = "verified"
        biotech_status = "supported"
        score = 0.95
    elif valid_hkex_identity(candidate):
        reasons.append("港交所提供唯一五位股票代码，可确认当前上市证券身份。")
        reasons.append("证券简称带港交所 B/SB biotech 标记，满足公司池领域准入条件。")
        decision = "accepted"
        identity_status = "verified"
        biotech_status = "supported"
        score = 0.96
    elif valid_hsi_identity(candidate):
        reasons.append("恒生指数公司提供唯一港股代码和 ISIN，可确认当前上市证券身份。")
        reasons.append("该证券属于恒生生物科技指数成分，满足公司池领域准入条件。")
        decision = "accepted"
        identity_status = "verified"
        biotech_status = "supported"
        score = 0.95
    elif len(source_types) >= 2 and stable and float(candidate.get("discoveryScore", 0)) >= 0.85:
        reasons.append("至少两个独立官方来源指向同一规范化实体，并具有稳定标识符。")
        decision = "accepted"
        identity_status = "verified"
        biotech_status = "supported"
        score = 0.94
    else:
        reasons.append("当前缺少可唯一确认法律实体的稳定标识符或足够的官方来源支持。")
        flags.append("insufficient_identity_evidence")
        decision = "needs_human"
        identity_status = "unverified"
        biotech_status = "provisional"
        score = min(float(candidate.get("discoveryScore", 0)), 0.79)

    if decision == "accepted":
        flags.append("official_business_profile_pending")
    return {
        "candidateId": candidate.get("id"),
        "candidateInputHash": candidate_input_hash(candidate),
        "decision": decision,
        "decisionMode": "automatic",
        "humanReviewRequired": decision == "needs_human",
        "universeEligible": decision == "accepted",
        "identityStatus": identity_status,
        "biotechStatus": biotech_status,
        "profileStatus": "official_sources_pending" if decision == "accepted" else "not_started",
        "reviewScore": round(score, 2),
        "reviewReasons": reasons,
        "flags": flags,
        "reviewedAt": reviewed_at,
        "policyVersion": POLICY_VERSION,
        "sourceTypes": sorted(source_types),
        "stableIdentifiers": stable,
        "evidenceMentionIds": sorted(candidate.get("mentionIds", [])),
    }


def apply_override(review: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    decision = str(override.get("decision") or "")
    if decision not in MANUAL_DECISIONS:
        raise ValueError(f"invalid manual decision {decision!r} for {review['candidateId']}")
    if override.get("candidateInputHash") and override["candidateInputHash"] != review["candidateInputHash"]:
        return {
            **review,
            "decision": "needs_human",
            "humanReviewRequired": True,
            "universeEligible": False,
            "flags": sorted(set(review["flags"]) | {"stale_manual_override"}),
            "reviewReasons": ["候选输入已变化，原人工结论需要重新确认。"],
        }
    return {
        **review,
        "decision": decision,
        "decisionMode": "manual",
        "humanReviewRequired": decision == "needs_human",
        "universeEligible": decision == "accepted",
        "reviewScore": 1.0,
        "reviewReasons": [str(override.get("reason") or "人工审核结论。")],
        "flags": [],
        "reviewedAt": override.get("reviewedAt") or review["reviewedAt"],
        "reviewer": override.get("reviewer"),
        "targetCompanyId": override.get("targetCompanyId"),
        "evidenceUrls": override.get("evidenceUrls", []),
    }


def build_reviews(
    discovery_payload: dict[str, Any], overrides_payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    reviewed_at = str(discovery_payload.get("capturedAt") or "")
    overrides = {
        item.get("candidateId"): item
        for item in (overrides_payload or {}).get("overrides", [])
        if item.get("candidateId")
    }
    reviews = []
    for candidate in discovery_payload.get("candidates", []):
        review = automatic_review(candidate, reviewed_at)
        if candidate.get("id") in overrides:
            review = apply_override(review, overrides[candidate["id"]])
        reviews.append(review)
    reviews.sort(key=lambda item: (item["humanReviewRequired"], -item["reviewScore"], item["candidateId"]))
    return {
        "schemaVersion": "1.0",
        "kind": "company_candidate_reviews",
        "capturedAt": reviewed_at,
        "policyVersion": POLICY_VERSION,
        "summary": {
            "reviewCount": len(reviews),
            "automaticCount": sum(item["decisionMode"] == "automatic" for item in reviews),
            "acceptedCount": sum(item["decision"] == "accepted" for item in reviews),
            "needsHumanCount": sum(item["humanReviewRequired"] for item in reviews),
            "rejectedCount": sum(item["decision"] == "rejected" for item in reviews),
            "mergedCount": sum(item["decision"] == "merged" for item in reviews),
        },
        "reviews": reviews,
    }


def main() -> int:
    args = parse_args()
    discovery_payload = json.loads(Path(args.discovery).read_text(encoding="utf-8"))
    overrides_path = Path(args.overrides)
    overrides_payload = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
    payload = build_reviews(discovery_payload, overrides_payload)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    output = Path(args.output)
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != serialized:
            print("Company candidate reviews are stale.", file=sys.stderr)
            return 1
        print(f"Company candidate reviews are current ({len(payload['reviews'])} reviews).")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized, encoding="utf-8")
    summary = payload["summary"]
    print(
        f"Reviewed {summary['reviewCount']} candidate(s): {summary['acceptedCount']} accepted automatically or manually, "
        f"{summary['needsHumanCount']} need human review."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"review_company_candidates.py failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
