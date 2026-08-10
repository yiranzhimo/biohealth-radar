#!/usr/bin/env python3
"""Build auditable company mentions and scored candidates from official sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    from .company_registry import load_companies, match_company_ids, normalize
except ImportError:
    from company_registry import load_companies, match_company_ids, normalize


SCHEMA_VERSION = "1.0"
LEGAL_SUFFIXES = {
    "ag",
    "as",
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "limited",
    "llc",
    "llp",
    "ltd",
    "nv",
    "oy",
    "plc",
    "sa",
    "se",
}
COMPANY_TERMS_RE = re.compile(
    r"\b(therapeutics?|biotech(?:nology)?|biosciences?|biopharma|pharmaceuticals?|"
    r"life sciences?|genomics?|diagnostics?|medicine|laboratories|labs?|ventures?)\b",
    re.IGNORECASE,
)
CORPORATE_SUFFIX_RE = re.compile(
    r"\b(inc\.?|incorporated|corp\.?|corporation|ltd\.?|limited|llc|plc|ag|s\.?a\.?|a/?s)\s*$",
    re.IGNORECASE,
)
NON_COMPANY_RE = re.compile(
    r"\b(university|hospital|institute|college|academy|foundation|government|ministry|"
    r"medical center|cancer center|clinic|health system|school of medicine|department of)\b",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover and score biotech company candidates.")
    parser.add_argument("--registry", default="data/companies.json")
    parser.add_argument("--clinicaltrials", default="data/raw/clinicaltrials_latest.json")
    parser.add_argument("--sec-universe", default="data/raw/sec_company_universe_latest.json")
    parser.add_argument("--nih-reporter", default="data/raw/nih_reporter_latest.json")
    parser.add_argument(
        "--china-hk-universe",
        default="data/raw/china_hk_company_universe_latest.json",
    )
    parser.add_argument("--known-sec", default="data/raw/sec_latest.json")
    parser.add_argument("--output", default="data/raw/company_discovery_latest.json")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def load_optional(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    return json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}


def normalized_company_name(value: Any) -> str:
    tokens = normalize(value).split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    if tokens[:1] == ["the"]:
        tokens = tokens[1:]
    return " ".join(tokens)


def looks_like_company(name: str) -> bool:
    return not NON_COMPANY_RE.search(name) and bool(COMPANY_TERMS_RE.search(name) or CORPORATE_SUFFIX_RE.search(name))


def stable_mention_id(source_type: str, source_record_id: Any, role: str, name: str) -> str:
    material = "|".join([source_type, str(source_record_id), role, normalized_company_name(name)])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"mention-{source_type.lower()}-{digest}"


def mention(
    *,
    name: str,
    source_type: str,
    source_name: str,
    source_role: str,
    source_record_id: Any,
    source_date: Any,
    source_url: Any,
    known_company_ids: list[str],
    identifiers: dict[str, Any] | None = None,
    biotech_hints: Iterable[str] = (),
    activity_signals: Iterable[str] = (),
    context_title: str = "",
) -> dict[str, Any]:
    clean_name = " ".join(str(name or "").split())
    return {
        "id": stable_mention_id(source_type, source_record_id, source_role, clean_name),
        "observedName": clean_name,
        "normalizedName": normalized_company_name(clean_name),
        "sourceType": source_type,
        "sourceName": source_name,
        "sourceRole": source_role,
        "sourceRecordId": str(source_record_id or ""),
        "sourceDate": str(source_date or "")[:10] or None,
        "sourceUrl": source_url,
        "knownCompanyIds": sorted(set(known_company_ids)),
        "identifiers": {key: str(value) for key, value in (identifiers or {}).items() if value not in (None, "")},
        "biotechHints": sorted(set(str(item) for item in biotech_hints if item)),
        "activitySignals": sorted(set(str(item) for item in activity_signals if item)),
        "contextTitle": " ".join(str(context_title or "").split())[:300],
    }


def clinical_mentions(payload: dict[str, Any], companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signals = {
        str(item.get("id", "")).removeprefix("clinicaltrials-"): item
        for item in payload.get("signals", [])
    }
    captured = str(payload.get("capturedAt", ""))[:10]
    output: list[dict[str, Any]] = []
    for record in payload.get("records", []):
        nct_id = record.get("nctId")
        signal = signals.get(str(nct_id), {})
        organizations = [(record.get("leadSponsor") or record.get("organization"), "lead_sponsor")]
        organizations.extend((name, "collaborator") for name in record.get("collaborators", []))
        for name, role in organizations:
            clean_name = str(name or "").strip()
            if not clean_name:
                continue
            known_ids = match_company_ids([clean_name], companies)
            if not known_ids and not looks_like_company(clean_name):
                continue
            activity = []
            if record.get("interventions"):
                activity.append("trial_intervention")
            if [phase for phase in record.get("phases", []) if phase and phase != "NA"]:
                activity.append("phased_trial")
            if record.get("overallStatus") in {"RECRUITING", "ACTIVE_NOT_RECRUITING", "NOT_YET_RECRUITING"}:
                activity.append("active_trial")
            output.append(
                mention(
                    name=clean_name,
                    source_type="ClinicalTrials",
                    source_name="ClinicalTrials.gov",
                    source_role=role,
                    source_record_id=nct_id,
                    source_date=record.get("lastUpdatePostDate") or record.get("firstPostDate") or captured,
                    source_url=record.get("sourceUrl"),
                    known_company_ids=known_ids,
                    biotech_hints=[*signal.get("themes", []), *signal.get("tags", [])],
                    activity_signals=activity,
                    context_title=record.get("briefTitle") or record.get("officialTitle"),
                )
            )
    return output


def sec_mentions(
    payload: dict[str, Any],
    companies: list[dict[str, Any]],
    known_cik_to_company: dict[str, str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in payload.get("records", []):
        name = str(record.get("companyName") or record.get("secName") or "").strip()
        cik = str(record.get("cik") or "").zfill(10)
        known_ids = match_company_ids([name], companies)
        if cik in known_cik_to_company:
            known_ids.append(known_cik_to_company[cik])
        output.append(
            mention(
                name=name,
                source_type="SEC",
                source_name="SEC EDGAR",
                source_role="biotech_sic_filer",
                source_record_id=cik,
                source_date=record.get("observedAt"),
                source_url=record.get("sourceUrl"),
                known_company_ids=sorted(set(known_ids)),
                identifiers={"cik": cik, "ticker": next(iter(record.get("tickers", [])), "")},
                biotech_hints=record.get("sicLabels", []),
                activity_signals=["sec_biotech_sic_registrant"],
                context_title="; ".join(record.get("sicLabels", [])),
            )
        )
    return output


def nih_mentions(payload: dict[str, Any], companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in payload.get("records", []):
        organization = record.get("organization") or {}
        name = str(organization.get("name") or "").strip()
        if not name or NON_COMPANY_RE.search(name):
            continue
        output.append(
            mention(
                name=name,
                source_type="NIH",
                source_name="NIH RePORTER",
                source_role="for_profit_award_recipient",
                source_record_id=record.get("applId") or record.get("projectNum"),
                source_date=record.get("awardNoticeDate") or record.get("projectStartDate"),
                source_url=record.get("sourceUrl"),
                known_company_ids=match_company_ids([name], companies),
                identifiers={"uei": organization.get("uei"), "nihIpf": organization.get("ipf")},
                biotech_hints=[*record.get("matchedTerms", []), *record.get("topicHints", [])],
                activity_signals=["nih_for_profit_award"],
                context_title=record.get("projectTitle"),
            )
        )
    return output


def china_hk_mentions(payload: dict[str, Any], companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources = {str(item.get("id")): item for item in payload.get("sources", [])}
    output: list[dict[str, Any]] = []
    csi_source = sources.get("csi-star-biology-medicine-constituents", {})
    for record in csi_source.get("records", []):
        code = str(record.get("securityCode") or "").strip()
        names = []
        for value in (record.get("companyNameCn"), record.get("companyNameEn")):
            name = str(value or "").strip()
            if name and name not in names:
                names.append(name)
        known_ids = match_company_ids(names, companies)
        for name in names:
            output.append(
                mention(
                    name=name,
                    source_type="CSI",
                    source_name="中证指数有限公司",
                    source_role="star_biology_medicine_index_constituent",
                    source_record_id=f"{record.get('indexCode') or '000683'}:{code}",
                    source_date=record.get("observedOn") or csi_source.get("observedOn"),
                    source_url=record.get("sourceUrl") or csi_source.get("url"),
                    known_company_ids=known_ids,
                    identifiers={"cnSecurityCode": code},
                    biotech_hints=[
                        record.get("indexName"),
                        record.get("industryLevel1Cn"),
                        record.get("industryLevel2Cn"),
                    ],
                    activity_signals=["official_biotech_index_constituent"],
                    context_title=" / ".join(names),
                )
            )

    hkex_source = sources.get("hkex-active-biotech-marker", {})
    for record in hkex_source.get("records", []):
        name = str(record.get("issuerShortNameEn") or "").strip()
        stock_code = str(record.get("stockCode") or "").strip()
        if not name or not stock_code:
            continue
        output.append(
            mention(
                name=name,
                source_type="HKEX",
                source_name="Hong Kong Exchanges and Clearing Limited",
                source_role="active_biotech_marker_issuer",
                source_record_id=stock_code,
                source_date=record.get("observedOn") or hkex_source.get("observedOn"),
                source_url=record.get("sourceUrl") or hkex_source.get("url"),
                known_company_ids=match_company_ids([name, record.get("securityName")], companies),
                identifiers={
                    "hkexStockCode": stock_code,
                    "isin": record.get("isin"),
                },
                biotech_hints=["HKEX Chapter 18A biotech marker"],
                activity_signals=["active_hkex_biotech_marker"],
                context_title=str(record.get("securityName") or name),
            )
        )

    hsi_source = sources.get("hsi-biotech-constituents", {})
    for record in hsi_source.get("records", []):
        name = str(record.get("issuerShortNameEn") or "").strip()
        stock_code = str(record.get("stockCode") or "").strip()
        if not name or not stock_code:
            continue
        output.append(
            mention(
                name=name,
                source_type="HSI",
                source_name="Hang Seng Indexes Company Limited",
                source_role="hang_seng_biotech_index_constituent",
                source_record_id=stock_code,
                source_date=record.get("observedOn") or hsi_source.get("observedOn"),
                source_url=record.get("sourceUrl") or hsi_source.get("url"),
                known_company_ids=match_company_ids([name, record.get("securityName")], companies),
                identifiers={
                    "hkexStockCode": stock_code,
                    "isin": record.get("isin"),
                },
                biotech_hints=["Hang Seng Biotech Index constituent"],
                activity_signals=["official_hsi_biotech_index_constituent"],
                context_title=str(record.get("securityName") or name),
            )
        )
    return output


def known_cik_map(payload: dict[str, Any]) -> dict[str, str]:
    return {
        str(record.get("cik") or "").zfill(10): str(record["companyId"])
        for record in payload.get("records", [])
        if record.get("cik") and record.get("companyId")
    }


class DisjointSet:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def cluster_mentions(mentions: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups = DisjointSet(len(mentions))
    seen_keys: dict[str, int] = {}
    for index, item in enumerate(mentions):
        keys = [f"name:{item['normalizedName']}"] if item.get("normalizedName") else []
        keys.extend(
            f"identifier:{kind}:{normalize(value)}"
            for kind, value in item.get("identifiers", {}).items()
            if kind != "ticker" and value
        )
        for key in keys:
            if key in seen_keys:
                groups.union(index, seen_keys[key])
            else:
                seen_keys[key] = index
    clustered: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, item in enumerate(mentions):
        clustered[groups.find(index)].append(item)
    return list(clustered.values())


def candidate_score(group: list[dict[str, Any]]) -> float:
    base_scores = []
    for item in group:
        if item["sourceType"] == "SEC":
            base_scores.append(0.72)
        elif item["sourceType"] == "CSI":
            base_scores.append(0.75)
        elif item["sourceType"] == "HKEX":
            base_scores.append(0.82)
        elif item["sourceType"] == "HSI":
            base_scores.append(0.78)
        elif item["sourceType"] == "NIH":
            base_scores.append(0.58)
        elif item["sourceRole"] == "lead_sponsor":
            base_scores.append(0.62)
        else:
            base_scores.append(0.42)
    score = max(base_scores, default=0.0)
    source_types = {item["sourceType"] for item in group}
    identifiers = {key for item in group for key in item.get("identifiers", {}) if key != "ticker"}
    if len(source_types) > 1:
        score += 0.12 + 0.05 * (len(source_types) - 2)
    if identifiers:
        score += 0.10
    if any(looks_like_company(item["observedName"]) for item in group):
        score += 0.08
    if any(item.get("biotechHints") for item in group):
        score += 0.08
    activity = {signal for item in group for signal in item.get("activitySignals", [])}
    if activity & {"trial_intervention", "phased_trial", "active_trial"}:
        score += 0.08
    return round(min(score, 0.98), 2)


def display_name(names: Iterable[str]) -> str:
    counts = Counter(name for name in names if name)
    selected = min(counts, key=lambda name: (-counts[name], name.isupper(), len(name), name))
    if selected.isupper():
        selected = selected.title()
        for conventional, replacement in {"Llc": "LLC", "Plc": "PLC", "Ag": "AG", "Sa": "SA"}.items():
            selected = re.sub(rf"\b{conventional}\b", replacement, selected)
    return selected


def build_candidate(group: list[dict[str, Any]], previous: dict[str, Any] | None = None) -> dict[str, Any] | None:
    known_ids = sorted({company_id for item in group for company_id in item.get("knownCompanyIds", [])})
    if known_ids:
        return None
    score = candidate_score(group)
    if score < 0.65:
        return None
    names = sorted({item["observedName"] for item in group})
    name = display_name(names)
    source_types = sorted({item["sourceType"] for item in group})
    identifiers: dict[str, list[str]] = defaultdict(list)
    for item in group:
        for kind, value in item.get("identifiers", {}).items():
            if value not in identifiers[kind]:
                identifiers[kind].append(value)
    has_stable_identifier = any(kind != "ticker" for kind in identifiers)
    if score >= 0.85 and len(source_types) >= 2:
        status = "corroborated"
    elif score >= 0.80 and has_stable_identifier:
        status = "identified"
    else:
        status = "needs_review"
    if previous and previous.get("status") in {"verified", "rejected", "merged"}:
        status = previous["status"]
    source_dates = sorted(item["sourceDate"] for item in group if item.get("sourceDate"))
    normalized_name = normalized_company_name(name)
    candidate_id = f"candidate-{re.sub(r'[^a-z0-9]+', '-', normalized_name).strip('-') or hashlib.sha256(name.encode()).hexdigest()[:12]}"
    hints = sorted({hint for item in group for hint in item.get("biotechHints", [])})
    reasons = []
    if "SEC" in source_types:
        reasons.append("SEC EDGAR 将该实体列为 biotech 相关 SIC 行业的注册主体。")
    if "ClinicalTrials" in source_types:
        reasons.append("ClinicalTrials.gov 将该实体列为试验申办方或合作方。")
    if "NIH" in source_types:
        reasons.append("NIH RePORTER 将该实体列为 biotech 相关项目的营利性获资助机构。")
    if "CSI" in source_types:
        reasons.append("中证指数将该证券列为上证科创板生物医药指数成分股。")
    if "HKEX" in source_types:
        reasons.append("港交所当前证券列表为该股票保留了 Chapter 18A biotech 的 B/SB 标记。")
    if "HSI" in source_types:
        reasons.append("恒生指数公司将该证券列为恒生生物科技指数成分股。")
    if len(source_types) >= 2:
        reasons.append(f"{len(source_types)} 个独立官方来源出现了可归一化到同一名称的记录。")
    return {
        "id": candidate_id,
        "name": name,
        "aliases": names,
        "normalizedName": normalized_name,
        "status": status,
        "candidateType": "Biotech Company",
        "discoveryScore": score,
        "autoPromotionEligible": bool(score >= 0.90 and has_stable_identifier and len(source_types) >= 2),
        "firstSeenAt": (previous or {}).get("firstSeenAt") or (source_dates[0] if source_dates else None),
        "lastSeenAt": source_dates[-1] if source_dates else None,
        "identifiers": dict(sorted(identifiers.items())),
        "classificationHints": {"directions": hints, "themes": hints, "tags": []},
        "discoveryReasons": reasons,
        "sourceTypes": source_types,
        "sourceCount": len(source_types),
        "mentionCount": len(group),
        "mentionIds": sorted(item["id"] for item in group),
        "sources": [
            {
                "sourceType": item["sourceType"],
                "sourceName": item["sourceName"],
                "sourceRole": item["sourceRole"],
                "sourceDate": item["sourceDate"],
                "sourceUrl": item["sourceUrl"],
                "externalId": item["sourceRecordId"],
                "contextTitle": item["contextTitle"],
            }
            for item in sorted(group, key=lambda value: (value.get("sourceDate") or "", value["id"]), reverse=True)
        ],
    }


def build_discovery(
    companies: list[dict[str, Any]],
    clinical_payload: dict[str, Any],
    sec_payload: dict[str, Any],
    nih_payload: dict[str, Any],
    known_sec_payload: dict[str, Any],
    previous_payload: dict[str, Any] | None = None,
    china_hk_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mentions = [
        *clinical_mentions(clinical_payload, companies),
        *sec_mentions(sec_payload, companies, known_cik_map(known_sec_payload)),
        *nih_mentions(nih_payload, companies),
        *china_hk_mentions(china_hk_payload or {}, companies),
    ]
    mentions = sorted({item["id"]: item for item in mentions}.values(), key=lambda item: item["id"])
    previous_by_normalized = {
        item.get("normalizedName"): item for item in (previous_payload or {}).get("candidates", [])
    }
    candidates = []
    for group in cluster_mentions(mentions):
        normalized_names = [item.get("normalizedName") for item in group if item.get("normalizedName")]
        previous = next((previous_by_normalized.get(name) for name in normalized_names if name in previous_by_normalized), None)
        candidate = build_candidate(group, previous)
        if candidate:
            candidates.append(candidate)
    candidates.sort(key=lambda item: (-item["discoveryScore"], item["name"]))
    captured_values = [
        str(payload.get("capturedAt", ""))
        for payload in (clinical_payload, sec_payload, nih_payload, china_hk_payload or {})
        if payload.get("capturedAt")
    ]
    captured_at = max(captured_values, default="")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "company_discovery",
        "capturedAt": captured_at,
        "summary": {
            "mentionCount": len(mentions),
            "candidateCount": len(candidates),
            "corroboratedCount": sum(item["status"] == "corroborated" for item in candidates),
            "identifiedCount": sum(item["status"] == "identified" for item in candidates),
            "needsReviewCount": sum(item["status"] == "needs_review" for item in candidates),
            "knownCompanyMentionCount": sum(bool(item["knownCompanyIds"]) for item in mentions),
            "mentionsBySource": dict(sorted(Counter(item["sourceType"] for item in mentions).items())),
        },
        "mentions": mentions,
        "candidates": candidates,
    }


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    previous = load_optional(output_path)
    payload = build_discovery(
        load_companies(args.registry),
        load_optional(args.clinicaltrials),
        load_optional(args.sec_universe),
        load_optional(args.nih_reporter),
        load_optional(args.known_sec),
        previous,
        load_optional(args.china_hk_universe),
    )
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not output_path.exists() or output_path.read_text(encoding="utf-8") != serialized:
            print(f"Company discovery output is stale: {output_path}", file=sys.stderr)
            return 1
        print(f"Company discovery output is current ({payload['summary']['candidateCount']} candidates).")
        return 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialized, encoding="utf-8")
    print(
        f"Built {payload['summary']['mentionCount']} company mentions and "
        f"{payload['summary']['candidateCount']} candidates."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
