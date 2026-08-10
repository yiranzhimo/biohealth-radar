#!/usr/bin/env python3
"""Build company-centric intelligence views from source-tagged radar data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from .company_registry import load_companies, match_company_ids
except ImportError:
    from company_registry import load_companies, match_company_ids


SCHEMA_VERSION = "1.0"
COMPANY_TERMS = re.compile(
    r"\b(therapeutics?|biotech(?:nology)?|biosciences?|biopharma|pharmaceuticals?|"
    r"life sciences?|genomics?|diagnostics?|medicine)\b",
    re.IGNORECASE,
)
NON_COMPANY_TERMS = re.compile(
    r"\b(university|hospital|institute|college|academy|foundation|government|ministry|"
    r"medical center|cancer center|clinic|health system)\b",
    re.IGNORECASE,
)
REPORTED_PLAN_TERMS = re.compile(
    r"\b(plans? to|intends? to|expects? to|"
    r"will (?:advance|build|commercialize|continue|deliver|develop|drive|expand|file|focus|"
    r"initiate|invest|launch|pursue|submit))\b",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build company intelligence data products.")
    parser.add_argument("--data-file", default="data.js", help="Source signal payload.")
    parser.add_argument("--registry", default="data/companies.json", help="Canonical company registry.")
    parser.add_argument(
        "--clinicaltrials-raw",
        default="data/raw/clinicaltrials_latest.json",
        help="ClinicalTrials.gov raw snapshot used for sponsor discovery and program candidates.",
    )
    parser.add_argument(
        "--company-sources-raw",
        default="data/raw/company_sources_latest.json",
        help="Compact snapshots of official company pages.",
    )
    parser.add_argument(
        "--company-discovery-raw",
        default="data/raw/company_discovery_latest.json",
        help="Auditable organization mentions and scored company candidates.",
    )
    parser.add_argument(
        "--company-translations-raw",
        default="data/raw/company_translations_latest.json",
        help="Cached Simplified Chinese translations of official company source text.",
    )
    parser.add_argument(
        "--company-candidate-reviews-raw",
        default="data/raw/company_candidate_reviews_latest.json",
        help="Deterministic and manual intake decisions for discovered company candidates.",
    )
    parser.add_argument("--china-hk-filings-raw", default="data/raw/china_hk_filings_latest.json")
    parser.add_argument("--output-dir", default="data", help="Directory for generated JSON products.")
    parser.add_argument(
        "--frontend-output",
        default="company-intelligence.js",
        help="Generated browser-ready company intelligence bundle.",
    )
    parser.add_argument("--check", action="store_true", help="Fail if generated products are stale.")
    return parser.parse_args()


def read_data_js(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").strip()
    prefix = "window.BHR_DATA ="
    if not text.startswith(prefix):
        raise ValueError(f"{path} does not look like a BioHealth Radar data.js file")
    return json.loads(text[len(prefix) :].strip().rstrip(";"))


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unknown"


def evidence_kind(source_type: str) -> str:
    return {
        "Filing": "Corporate Filing",
        "Registry": "Clinical Registry Record",
        "Paper": "Scientific Publication",
        "Regulator": "Regulatory Record",
        "Company": "Company Report",
        "Media": "Media Report",
    }.get(source_type, "Other Record")


def translation_lookup(translation_payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("sourceTextHash")): item
        for item in (translation_payload or {}).get("translations", [])
        if item.get("sourceTextHash") and item.get("translationCn")
    }


def translated_text(text: str, translations: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any] | None]:
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    item = translations.get(digest)
    if not item or item.get("sourceText") != text.strip():
        return text, None
    return str(item["translationCn"]).strip(), item


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def build_official_source_evidence(
    source_payload: dict[str, Any], translation_payload: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    translations = translation_lookup(translation_payload)
    role_labels = {
        "official": "Official Website",
        "pipeline": "Pipeline Page",
        "investor_relations": "Investor Relations Page",
    }
    for source in source_payload.get("sources", []):
        company_id = str(source.get("companyId", "")).strip()
        content_hash = str(source.get("contentHash", "")).strip()
        source_url = source.get("resolvedUrl") or source.get("requestedUrl")
        if not company_id or not content_hash or not source_url:
            continue
        role = str(source.get("sourceRole", "official"))
        company_name = str(source.get("companyName") or company_id)
        claim = str(source.get("description") or "").strip()
        if not claim and source.get("excerpts"):
            claim = str(source["excerpts"][0]).strip()
        if not claim:
            claim = str(source.get("title") or "Official page captured; no concise descriptive claim was extracted.")
        claim_cn, translation = translated_text(claim, translations)
        observed_at = str(source.get("lastChangedAt") or source.get("capturedAt") or "")
        published_at = observed_at[:10] or None
        evidence.append(
            {
                "id": f"evidence-company-{company_id}-{role}-{content_hash[:12]}",
                "signalId": None,
                "companyIds": [company_id],
                "publishedAt": published_at,
                "snapshotDate": str(source.get("capturedAt") or "")[:10] or published_at,
                "title": source.get("title") or f"{company_name} {role_labels.get(role, 'Official Page')}",
                "eventType": "Official Source Update" if source.get("changeType") == "updated" else "Official Source Snapshot",
                "evidenceKind": "Official Company Source",
                "sourceType": "Company",
                "sourceName": f"{company_name} — {role_labels.get(role, 'Official Page')}",
                "sourceRole": role,
                "sourceUrl": source_url,
                "reliability": "High",
                "evidenceLevel": "Medium",
                "needsReview": True,
                "themes": ["Company Intelligence"],
                "tags": ["Official Source", role_labels.get(role, "Official Page")],
                "fact": f"The official page was captured with normalized-content hash {content_hash}.",
                "report": f"公司官方页面表述：{claim_cn}",
                "reportOriginal": claim,
                "reportCn": claim_cn if translation or contains_chinese(claim) else None,
                "translation": (
                    {
                        "status": "translated",
                        "provider": translation.get("provider"),
                        "model": translation.get("model"),
                        "translatedAt": translation.get("translatedAt"),
                        "sourceTextHash": translation.get("sourceTextHash"),
                    }
                    if translation
                    else {"status": "not_needed" if contains_chinese(claim) else "missing"}
                ),
                "inference": "",
                "unknown": "该表述尚未经过独立来源核验，也不等同于未来结果或管理层指引。",
                "contentHash": content_hash,
                "changeType": source.get("changeType"),
                "lastCheckStatus": source.get("lastCheckStatus", "success"),
                "excerpts": source.get("excerpts", []),
                "businessExcerpts": source.get("businessExcerpts", []),
                "productExcerpts": source.get("productExcerpts", []),
                "planExcerpts": source.get("planExcerpts", []),
            }
        )
    return evidence


def build_evidence(
    payload: dict[str, Any],
    official_source_payload: dict[str, Any] | None = None,
    translation_payload: dict[str, Any] | None = None,
    china_hk_filings_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for signal in payload.get("signals", []):
        evidence.append(
            {
                "id": f"evidence-{signal['id']}",
                "signalId": signal["id"],
                "companyIds": signal.get("companyIds", []),
                "publishedAt": signal.get("date"),
                "snapshotDate": payload.get("updatedAt"),
                "title": signal.get("title"),
                "eventType": signal.get("eventType"),
                "evidenceKind": evidence_kind(str(signal.get("sourceType", ""))),
                "sourceType": signal.get("sourceType"),
                "sourceName": signal.get("sourceName"),
                "sourceUrl": signal.get("sourceUrl"),
                "reliability": signal.get("reliability"),
                "evidenceLevel": signal.get("evidenceLevel"),
                "needsReview": signal.get("needsReview", True),
                "themes": signal.get("themes", []),
                "tags": signal.get("tags", []),
                "fact": signal.get("fact", ""),
                "report": signal.get("report", ""),
                "inference": signal.get("inference", ""),
                "unknown": signal.get("unknown", ""),
            }
        )
    evidence.extend(build_official_source_evidence(official_source_payload or {}, translation_payload))
    for record in (china_hk_filings_payload or {}).get("records", []):
        if record.get("status") != "discovered" or not record.get("url"):
            continue
        evidence.append({
            "id": f"evidence-{record['companyId']}-periodic-{hashlib.sha1(record['url'].encode()).hexdigest()[:12]}",
            "signalId": None,
            "companyIds": [record["companyId"]],
            "publishedAt": record.get("date"),
            "snapshotDate": (china_hk_filings_payload or {}).get("capturedAt"),
            "title": record.get("title") or f"{record.get('companyName')} {record.get('reportType')}",
            "eventType": "Periodic Report",
            "evidenceKind": "Periodic Filing",
            "sourceType": "Filing",
            "sourceName": record.get("source"),
            "sourceUrl": record["url"],
            "reliability": "High",
            "evidenceLevel": "Medium",
            "needsReview": True,
            "themes": ["Corporate Filings"],
            "tags": [record.get("reportType"), record.get("form")],
            "fact": f"{record.get('source')} 记录了 {record.get('reportType')} 披露链接。",
            "report": f"{record.get('companyName')} 最新{record.get('reportType')}原始链接。",
            "inference": "仅确认官方披露链接，不从标题推断主营业务或未来计划。",
            "unknown": "尚未提取报告正文中的主营业务、管线和战略信息。",
        })
    return evidence


def looks_like_company(name: str) -> bool:
    return bool(COMPANY_TERMS.search(name)) and not bool(NON_COMPANY_TERMS.search(name))


def discover_company_candidates(
    clinical_payload: dict[str, Any],
    companies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    signals_by_nct = {
        str(signal.get("id", "")).removeprefix("clinicaltrials-"): signal
        for signal in clinical_payload.get("signals", [])
    }
    captured_date = str(clinical_payload.get("capturedAt", ""))[:10]
    candidates: dict[str, dict[str, Any]] = {}
    for record in clinical_payload.get("records", []):
        sponsor = str(record.get("leadSponsor") or record.get("organization") or "").strip()
        if not sponsor or not looks_like_company(sponsor):
            continue
        if match_company_ids([sponsor], companies):
            continue
        candidate_id = f"candidate-{slugify(sponsor)}"
        signal = signals_by_nct.get(str(record.get("nctId", "")), {})
        score = 0.72
        if record.get("interventions"):
            score += 0.08
        if [phase for phase in record.get("phases", []) if phase and phase != "NA"]:
            score += 0.08
        source_date = record.get("lastUpdatePostDate") or record.get("firstPostDate") or captured_date
        item = candidates.setdefault(
            candidate_id,
            {
                "id": candidate_id,
                "name": sponsor,
                "status": "needs_review",
                "candidateType": "Biotech Company",
                "discoveryScore": round(min(score, 0.95), 2),
                "firstSeenAt": captured_date,
                "lastSeenAt": captured_date,
                "classificationHints": {
                    "themes": [],
                    "tags": [],
                },
                "discoveryReasons": [
                    "ClinicalTrials.gov lead sponsor name contains biotech or life-science company terminology."
                ],
                "sources": [],
            },
        )
        item["classificationHints"]["themes"] = sorted(
            set(item["classificationHints"]["themes"]) | set(signal.get("themes", []))
        )
        item["classificationHints"]["tags"] = sorted(
            set(item["classificationHints"]["tags"]) | set(signal.get("tags", []))
        )
        item["sources"].append(
            {
                "sourceType": "Registry",
                "sourceName": "ClinicalTrials.gov",
                "sourceDate": source_date,
                "sourceUrl": record.get("sourceUrl"),
                "externalId": record.get("nctId"),
                "observedInterventions": record.get("interventions", []),
            }
        )

    for candidate in candidates.values():
        candidate["sources"].sort(key=lambda item: (item.get("sourceDate", ""), item.get("externalId", "")), reverse=True)
    return sorted(candidates.values(), key=lambda item: (-item["discoveryScore"], item["name"]))


def build_program_candidates(
    clinical_payload: dict[str, Any],
    companies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    signals_by_nct = {
        str(signal.get("id", "")).removeprefix("clinicaltrials-"): signal
        for signal in clinical_payload.get("signals", [])
    }
    known_company_ids = {company["id"] for company in companies}
    programs: dict[tuple[str, str], dict[str, Any]] = {}
    for record in clinical_payload.get("records", []):
        nct_id = str(record.get("nctId", ""))
        signal = signals_by_nct.get(nct_id, {})
        company_ids = [company_id for company_id in signal.get("companyIds", []) if company_id in known_company_ids]
        for company_id in company_ids:
            for intervention in record.get("interventions", []):
                name = str(intervention or "").strip()
                if not name:
                    continue
                key = (company_id, name.lower())
                program = programs.setdefault(
                    key,
                    {
                        "id": f"program-candidate-{company_id}-{slugify(name)}",
                        "companyId": company_id,
                        "name": name,
                        "verificationStatus": "candidate",
                        "relationship": "trial_intervention",
                        "ownershipVerified": False,
                        "trialIds": [],
                        "indications": [],
                        "phases": [],
                        "trialStatuses": [],
                        "evidenceUrls": [],
                    },
                )
                program["trialIds"] = sorted(set(program["trialIds"]) | {nct_id})
                program["indications"] = sorted(set(program["indications"]) | set(record.get("conditions", [])))
                program["phases"] = sorted(set(program["phases"]) | set(record.get("phases", [])))
                program["trialStatuses"] = sorted(
                    set(program["trialStatuses"]) | {str(record.get("overallStatus") or "Unknown")}
                )
                if record.get("sourceUrl"):
                    program["evidenceUrls"] = sorted(set(program["evidenceUrls"]) | {record["sourceUrl"]})
    return sorted(programs.values(), key=lambda item: (item["companyId"], item["name"].lower()))


def classify_company(company: dict[str, Any]) -> str:
    directions = set(company.get("directions", []))
    if directions & {"Precision Diagnostics", "Diagnostics", "Sequencing & Research Tools"}:
        return "Diagnostics / Research Tools"
    if directions & {"AI Drug Discovery", "Organoids & Disease Models"}:
        return "Platform / Therapeutics"
    return "Therapeutics"


def extract_reported_plans(
    official_evidence: list[dict[str, Any]], translation_payload: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    seen: set[str] = set()
    translations = translation_lookup(translation_payload)
    for item in official_evidence:
        for excerpt in [*item.get("planExcerpts", []), *item.get("excerpts", [])]:
            text = str(excerpt).strip()
            key = text.casefold()
            if not text or key in seen or not REPORTED_PLAN_TERMS.search(text):
                continue
            seen.add(key)
            text_cn, translation = translated_text(text, translations)
            plans.append(
                {
                    "text": text_cn,
                    "textOriginal": text,
                    "translationStatus": "translated" if translation else "missing",
                    "translation": (
                        {
                            "provider": translation.get("provider"),
                            "model": translation.get("model"),
                            "translatedAt": translation.get("translatedAt"),
                            "sourceTextHash": translation.get("sourceTextHash"),
                        }
                        if translation
                        else None
                    ),
                    "claimType": "Report",
                    "attribution": item.get("sourceName"),
                    "evidenceId": item["id"],
                    "sourceUrl": item.get("sourceUrl"),
                    "needsReview": True,
                }
            )
            if len(plans) == 5:
                return plans
    return plans


def build_periodic_report_links(company_evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose latest SEC periodic-report URLs as navigation links, not business evidence."""
    allowed = {"10-K": "年报", "10-Q": "季报", "20-F": "年报", "6-K": "半年报/临时报告"}
    links = {}
    for item in company_evidence:
        if item.get("sourceType") != "Filing" or not item.get("sourceUrl"):
            continue
        forms = set(item.get("tags", [])) & set(allowed)
        if not forms:
            match = re.search(r"Form\s+(10-K|10-Q|20-F|6-K)", str(item.get("title", "")))
            if match:
                forms = {match.group(1)}
        for form in forms:
            links[(form, item["sourceUrl"])] = {
                "form": form,
                "label": allowed[form],
                "date": item.get("publishedAt"),
                "title": item.get("title"),
                "url": item["sourceUrl"],
                "source": "SEC EDGAR",
            }
    return sorted(links.values(), key=lambda row: (row.get("date") or "", row["form"]), reverse=True)[:8]


def build_report_portals(company: dict[str, Any]) -> list[dict[str, str]]:
    """Official disclosure search portals for China/Hong Kong listings."""
    exchange = company.get("exchange")
    identifiers = company.get("identifiers") or {}
    code = str((identifiers.get("hkexStockCode") or identifiers.get("cnSecurityCode") or [company.get("ticker") or ""])[0]).zfill(5)
    if exchange == "HKEX":
        return [{"label": "港交所披露易", "source": "HKEXnews", "url": "https://www1.hkexnews.hk/index.htm"}]
    if exchange in {"SSE", "SZSE"} and code:
        return [
            {"label": "巨潮资讯（定期报告）", "source": "CNINFO", "url": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}"},
            {"label": "交易所公司资料", "source": exchange, "url": f"https://www.sse.com.cn/assortment/stock/list/info/company/index.shtml?COMPANY_CODE={code}" if exchange == "SSE" else "https://www.szse.cn/disclosure/listed/notice/index.html"},
        ]
    return []


def build_company_profiles(
    payload: dict[str, Any],
    companies: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    programs: list[dict[str, Any]],
    translation_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    evidence_by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in evidence:
        for company_id in item.get("companyIds", []):
            evidence_by_company[company_id].append(item)
    programs_by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for program in programs:
        programs_by_company[program["companyId"]].append(program)

    profiles: list[dict[str, Any]] = []
    for company in companies:
        company_evidence = sorted(
            evidence_by_company.get(company["id"], []),
            key=lambda item: (item.get("publishedAt", ""), item.get("id", "")),
            reverse=True,
        )
        company_programs = programs_by_company.get(company["id"], [])
        periodic_reports = build_periodic_report_links(company_evidence)
        report_portals = build_report_portals(company)
        source_counts = Counter(item.get("sourceType", "Unknown") for item in company_evidence)
        directions = company.get("directions", [])
        modalities = company.get("modalities", [])
        official_evidence = [item for item in company_evidence if item.get("sourceType") == "Company"]
        if official_evidence:
            official_claims = [item.get("report", "") for item in official_evidence[:2] if item.get("report")]
            summary = "；".join(official_claims)
            original_claims = [
                str(item.get("reportOriginal") or "") for item in official_evidence[:2] if item.get("reportOriginal")
            ]
            summary_original = " ".join(original_claims)
            translation_states = {
                item.get("translation", {}).get("status", "missing") for item in official_evidence[:2]
            }
            translation_status = (
                "translated" if translation_states <= {"translated", "not_needed"} else "partial"
            )
            business_status = "company_reported"
            summary_type = "Report"
        else:
            source_basis = company.get("_discoverySourceBasis")
            summary_prefix = (
                f"{source_basis}，" if source_basis else f"Registry 将 {company['name']} 归入 "
            )
            summary = (
                summary_prefix +
                f"{', '.join(directions) or 'Unclassified'}；"
                f"当前记录的技术或产品模态包括 {', '.join(modalities) or 'Unknown'}。"
                "这只能说明进入雷达的来源依据，不能替代主营业务核验。"
            )
            summary_original = None
            translation_status = "not_applicable"
            business_status = "provisional"
            summary_type = "Unknown"
        reported_plans = extract_reported_plans(official_evidence, translation_payload)
        product_claims = []
        for item in official_evidence:
            for excerpt in [*item.get("productExcerpts", []), *item.get("excerpts", [])]:
                if excerpt and excerpt not in {claim["textOriginal"] for claim in product_claims}:
                    product_claims.append(
                        {
                            "textOriginal": excerpt,
                            "text": translated_text(excerpt, translation_lookup(translation_payload))[0],
                            "evidenceId": item["id"],
                            "sourceUrl": item.get("sourceUrl"),
                            "needsReview": True,
                            "claimType": "Report",
                        }
                    )
                if len(product_claims) >= 6:
                    break
            if len(product_claims) >= 6:
                break
        gaps = []
        if not company_evidence:
            if company.get("_discoverySourceBasis"):
                gaps.append(f"已记录{company['_discoverySourceBasis']}链接，但尚未抓取官网、年报或公司披露正文。")
            else:
                gaps.append("当前快照没有关联到该公司的来源证据。")
        if company_evidence and set(source_counts) <= {"Filing"}:
            gaps.append("目前只有 SEC filing metadata，尚未提取 filing 正文中的业务和战略信息。")
        if not company_programs:
            gaps.append("尚未建立经过验证的结构化产品或管线记录。")
        if not official_evidence:
            gaps.append("尚未从官网形成有出处的公司自述型主营业务摘要。")
        failed_official_checks = [item for item in official_evidence if item.get("lastCheckStatus") == "failed"]
        if failed_official_checks:
            gaps.append(f"{len(failed_official_checks)} 个官方页面最近一次采集失败，当前快照可能已陈旧。")
        if reported_plans:
            gaps.append("官网中的未来计划属于公司自述，尚未用年报、管理层指引或后续执行结果交叉核验。")
        else:
            gaps.append("尚未从年报和管理层指引形成经过核验的未来计划摘要。")

        recent_events = [
            {
                "id": f"event-{item.get('signalId') or item['id']}",
                "date": item.get("publishedAt"),
                "title": item.get("title"),
                "eventType": item.get("eventType"),
                "sourceType": item.get("sourceType"),
                "evidenceLevel": item.get("evidenceLevel"),
                "needsReview": item.get("needsReview"),
                "evidenceId": item["id"],
                "sourceUrl": item.get("sourceUrl"),
            }
            for item in company_evidence[:8]
        ]
        profiles.append(
            {
                "companyId": company["id"],
                "name": company["name"],
                "asOfDate": payload.get("updatedAt"),
                "profileStatus": "partial" if company_evidence else "seed_only",
                "identity": {
                    "ownership": company.get("ownership"),
                    "ticker": company.get("ticker"),
                    "exchange": company.get("exchange"),
                    "headquarters": company.get("headquarters"),
                    "officialUrl": company.get("officialUrl"),
                    "irUrl": company.get("irUrl"),
                    "pipelineUrl": company.get("pipelineUrl"),
                    "identifiers": company.get("identifiers", {}),
                    "websiteStatus": company.get("_websiteResolutionStatus", "curated"),
                    "legalNameStatus": "unresolved" if company.get("_discoverySourceBasis") else "curated",
                    "periodicReports": periodic_reports,
                    "reportPortals": report_portals,
                },
                "classification": {
                    "companyType": classify_company(company),
                    "directions": directions,
                    "modalities": modalities,
                    "watchTier": company.get("watchTier"),
                },
                "currentBusiness": {
                    "status": business_status,
                    "summaryType": summary_type,
                    "summary": summary,
                    "summaryOriginal": summary_original,
                    "translationStatus": translation_status,
                    "businessModel": [],
                    "commercialProducts": product_claims,
                    "programCandidateIds": [program["id"] for program in company_programs],
                    "evidenceIds": [item["id"] for item in company_evidence],
                },
                "futureDirection": {
                    "reportedPlans": reported_plans,
                    "observedMoves": recent_events[:5],
                    "inferences": [],
                    "unknowns": gaps,
                },
                "coverage": {
                    "evidenceCount": len(company_evidence),
                    "evidenceBySourceType": dict(sorted(source_counts.items())),
                    "lastEvidenceDate": company_evidence[0]["publishedAt"] if company_evidence else None,
                    "programCandidateCount": len(company_programs),
                    "gaps": gaps,
                },
                "recentEvents": recent_events,
            }
        )
    return sorted(profiles, key=lambda item: item["name"].lower())


def discovered_profile_company(candidate: dict[str, Any]) -> dict[str, Any]:
    """Turn an accepted discovery candidate into a safe, linkable profile seed.

    These fields are deliberately source-qualified: a market index or SEC SIC
    classification confirms why the entity entered the radar, not its complete
    business description.
    """
    identifiers = candidate.get("identifiers") or {}
    source_types = set(candidate.get("sourceTypes") or [])
    directions = (candidate.get("classificationHints") or {}).get("directions", [])
    ticker_values = identifiers.get("ticker") or []
    hk_codes = identifiers.get("hkexStockCode") or []
    cn_codes = identifiers.get("cnSecurityCode") or []
    ciks = identifiers.get("cik") or []
    ticker = str(ticker_values[0]) if ticker_values else None
    official_url = None
    exchange = None
    if ciks:
        official_url = f"https://www.sec.gov/edgar/browse/?CIK={str(ciks[0]).zfill(10)}"
        exchange = "SEC"
    elif hk_codes:
        code = str(hk_codes[0]).zfill(5)
        ticker = ticker or code
        official_url = (
            "https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/"
            f"Equities-Quote?sym={int(code)}&sc_lang=en"
        )
        exchange = "HKEX"
    elif cn_codes:
        code = str(cn_codes[0]).zfill(6)
        ticker = ticker or code
        official_url = (
            "https://www.sse.com.cn/assortment/stock/list/info/company/index.shtml?COMPANY_CODE="
            f"{code}"
        )
        exchange = "SSE"
    else:
        first_source = (candidate.get("sources") or [{}])[0]
        official_url = first_source.get("sourceUrl")
    if "SEC" in source_types:
        source_basis = "SEC EDGAR 的 biotech 相关 SIC 注册主体"
    elif "CSI" in source_types:
        source_basis = "中证科创生物指数成分股"
    elif "HSI" in source_types:
        source_basis = "恒生生物科技指数成分股"
    elif "HKEX" in source_types:
        source_basis = "港交所当前 B/SB biotech 标记证券"
    elif "NIH" in source_types:
        source_basis = "NIH RePORTER biotech 相关营利机构记录"
    else:
        source_basis = "官方来源发现记录"
    return {
        "id": candidate["id"],
        "name": candidate.get("name") or candidate["id"],
        "ownership": "Public" if exchange in {"SEC", "HKEX", "SSE"} else None,
        "ticker": ticker,
        "exchange": exchange,
        "headquarters": None,
        "officialUrl": official_url,
        "irUrl": None,
        "pipelineUrl": None,
        "directions": directions,
        "modalities": [],
        "watchTier": "Discovery",
        "_discoverySourceBasis": source_basis,
        "_websiteResolutionStatus": "market_page_pending_official_domain",
        "identifiers": identifiers,
    }


def json_document(kind: str, as_of_date: str, key: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": kind,
        "asOfDate": as_of_date,
        key: items,
    }


def serialize_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def attach_candidate_reviews(
    candidates: list[dict[str, Any]], review_payload: dict[str, Any] | None
) -> list[dict[str, Any]]:
    reviews = {
        item.get("candidateId"): item
        for item in (review_payload or {}).get("reviews", [])
        if item.get("candidateId")
    }
    output = []
    for candidate in candidates:
        review = reviews.get(candidate.get("id"))
        if review is None:
            review = {
                "candidateId": candidate.get("id"),
                "decision": "needs_human",
                "decisionMode": "fallback",
                "humanReviewRequired": True,
                "universeEligible": False,
                "identityStatus": "unreviewed",
                "biotechStatus": "unreviewed",
                "profileStatus": "not_started",
                "reviewScore": 0,
                "reviewReasons": ["尚未生成候选公司准入审核记录。"],
                "flags": ["missing_intake_review"],
            }
        output.append({**candidate, "intakeReview": review})
    return sorted(
        output,
        key=lambda item: (
            not item["intakeReview"].get("humanReviewRequired", True),
            -float(item["intakeReview"].get("reviewScore", 0)),
            item["name"],
        ),
    )


def build_company_universe(
    companies: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    entities = [
        {
            "id": company["id"],
            "name": company["name"],
            "entityType": "profiled_company",
            "universeStatus": "profiled",
            "identifiers": {
                "ticker": [company["ticker"]] if company.get("ticker") else [],
            },
            "classificationHints": {
                "directions": company.get("directions", []),
                "modalities": company.get("modalities", []),
            },
            "sourceTypes": [],
        }
        for company in companies
    ]
    entities.extend(
        {
            "id": candidate["id"],
            "name": candidate["name"],
            "aliases": candidate.get("aliases", []),
            "entityType": "discovered_company",
            "universeStatus": "accepted_pending_profile",
            "identifiers": candidate.get("identifiers", {}),
            "classificationHints": candidate.get("classificationHints", {}),
            "sourceTypes": candidate.get("sourceTypes", []),
            "intakeReview": candidate["intakeReview"],
        }
        for candidate in candidates
        if candidate["intakeReview"].get("universeEligible")
    )
    return sorted(entities, key=lambda item: item["name"].lower())


def build_company_identity_links(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create auditable cross-listing/identifier links without merging entities."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for entity in entities:
        for kind, values in (entity.get("identifiers") or {}).items():
            if isinstance(values, str):
                values = [values]
            for value in values or []:
                normalized = re.sub(r"[^A-Z0-9]", "", str(value).upper())
                if normalized:
                    buckets[(str(kind), normalized)].append(entity)
    links = []
    for (kind, value), matched in sorted(buckets.items()):
        unique = {item["id"]: item for item in matched}
        if len(unique) < 2:
            continue
        links.append({
            "linkId": hashlib.sha1(f"{kind}:{value}".encode()).hexdigest()[:12],
            "linkType": "shared_identifier",
            "identifierKind": kind,
            "identifierValue": value,
            "entityIds": sorted(unique),
            "entityNames": [unique[key]["name"] for key in sorted(unique)],
            "needsReview": True,
            "reviewReason": "同一标识出现在多个实体，可能是 A/H/ADR/集团关系，未自动合并。",
        })
    return links


def build_products(
    payload: dict[str, Any],
    companies: list[dict[str, Any]],
    clinical_payload: dict[str, Any],
    official_source_payload: dict[str, Any] | None = None,
    discovery_payload: dict[str, Any] | None = None,
    translation_payload: dict[str, Any] | None = None,
    candidate_review_payload: dict[str, Any] | None = None,
    china_hk_filings_payload: dict[str, Any] | None = None,
) -> dict[str, str]:
    evidence = build_evidence(payload, official_source_payload, translation_payload, china_hk_filings_payload)
    programs = build_program_candidates(clinical_payload, companies)
    discovery_payload = discovery_payload or {}
    discovered_candidates = (
        discovery_payload.get("candidates", [])
        if "candidates" in discovery_payload
        else discover_company_candidates(clinical_payload, companies)
    )
    candidates = attach_candidate_reviews(discovered_candidates, candidate_review_payload)
    mentions = discovery_payload.get("mentions", [])
    accepted_profile_seeds = [
        discovered_profile_company(candidate)
        for candidate in candidates
        if candidate.get("intakeReview", {}).get("universeEligible")
    ]
    profiles = build_company_profiles(
        payload,
        [*companies, *accepted_profile_seeds],
        evidence,
        programs,
        translation_payload,
    )
    as_of_date = str(payload.get("updatedAt", ""))
    evidence_doc = json_document("company_evidence", as_of_date, "evidence", evidence)
    programs_doc = json_document("program_candidates", as_of_date, "programs", programs)
    candidates_doc = json_document("company_candidates", as_of_date, "candidates", candidates)
    mentions_doc = json_document("company_mentions", as_of_date, "mentions", mentions)
    profiles_doc = json_document("company_profiles", as_of_date, "profiles", profiles)
    reviews_doc = candidate_review_payload or json_document(
        "company_candidate_reviews", as_of_date, "reviews", []
    )
    company_universe = build_company_universe(companies, candidates)
    universe_doc = json_document("company_universe", as_of_date, "entities", company_universe)
    identity_links = build_company_identity_links(company_universe)
    identity_links_doc = json_document("company_identity_links", as_of_date, "links", identity_links)
    review_summary = (candidate_review_payload or {}).get("summary", {})
    failed_source_count = sum(
        1 for item in (official_source_payload or {}).get("sources", []) if item.get("lastCheckStatus") == "failed"
    )
    profile_coverage = {
        "profileCount": len(profiles),
        "companyReportedCount": sum(item["currentBusiness"]["summaryType"] == "Report" for item in profiles),
        "withEvidenceCount": sum(item["coverage"]["evidenceCount"] > 0 for item in profiles),
        "withProductClaimsCount": sum(bool(item["currentBusiness"].get("commercialProducts")) for item in profiles),
        "withFuturePlansCount": sum(bool(item["futureDirection"].get("reportedPlans")) for item in profiles),
        "failedSourceCount": failed_source_count,
        "identityLinkCount": len(identity_links),
    }
    frontend = {
        "schemaVersion": SCHEMA_VERSION,
        "asOfDate": as_of_date,
        "summary": {
            "profileCount": len(profiles),
            "evidenceCount": len(evidence),
            "programCandidateCount": len(programs),
            "companyCandidateCount": len(candidates),
            "companyMentionCount": len(mentions),
            "companyUniverseCount": len(company_universe),
            "autoAcceptedCandidateCount": review_summary.get("acceptedCount", 0),
            "humanReviewCandidateCount": review_summary.get("needsHumanCount", len(candidates)),
        },
        "discoverySummary": discovery_payload.get("summary", {}),
        "candidateReviewSummary": review_summary,
        "profileCoverage": profile_coverage,
        "profiles": profiles,
        "programs": programs,
        "candidates": candidates,
    }
    return {
        "evidence.json": serialize_json(evidence_doc),
        "programs.json": serialize_json(programs_doc),
        "company_candidates.json": serialize_json(candidates_doc),
        "company_mentions.json": serialize_json(mentions_doc),
        "company_profiles.json": serialize_json(profiles_doc),
        "company_candidate_reviews.json": serialize_json(reviews_doc),
        "company_universe.json": serialize_json(universe_doc),
        "company_identity_links.json": serialize_json(identity_links_doc),
        "company-intelligence.js": f"window.BHR_COMPANY_INTELLIGENCE = {json.dumps(frontend, ensure_ascii=False, indent=2)};\n",
    }


def main() -> int:
    args = parse_args()
    payload = read_data_js(Path(args.data_file))
    companies = load_companies(args.registry)
    clinical_path = Path(args.clinicaltrials_raw)
    clinical_payload = json.loads(clinical_path.read_text(encoding="utf-8")) if clinical_path.exists() else {}
    company_sources_path = Path(args.company_sources_raw)
    company_sources_payload = (
        json.loads(company_sources_path.read_text(encoding="utf-8")) if company_sources_path.exists() else {}
    )
    discovery_path = Path(args.company_discovery_raw)
    discovery_payload = json.loads(discovery_path.read_text(encoding="utf-8")) if discovery_path.exists() else {}
    translation_path = Path(args.company_translations_raw)
    translation_payload = json.loads(translation_path.read_text(encoding="utf-8")) if translation_path.exists() else {}
    candidate_review_path = Path(args.company_candidate_reviews_raw)
    candidate_review_payload = (
        json.loads(candidate_review_path.read_text(encoding="utf-8")) if candidate_review_path.exists() else {}
    )
    china_hk_filings_path = Path(args.china_hk_filings_raw)
    china_hk_filings_payload = json.loads(china_hk_filings_path.read_text(encoding="utf-8")) if china_hk_filings_path.exists() else {}
    products = build_products(
        payload,
        companies,
        clinical_payload,
        company_sources_payload,
        discovery_payload,
        translation_payload,
        candidate_review_payload,
        china_hk_filings_payload,
    )
    output_dir = Path(args.output_dir)
    targets = {
        output_dir / "evidence.json": products["evidence.json"],
        output_dir / "programs.json": products["programs.json"],
        output_dir / "company_candidates.json": products["company_candidates.json"],
        output_dir / "company_mentions.json": products["company_mentions.json"],
        output_dir / "company_profiles.json": products["company_profiles.json"],
        output_dir / "company_candidate_reviews.json": products["company_candidate_reviews.json"],
        output_dir / "company_universe.json": products["company_universe.json"],
        output_dir / "company_identity_links.json": products["company_identity_links.json"],
        Path(args.frontend_output): products["company-intelligence.js"],
    }

    if args.check:
        stale = [str(path) for path, expected in targets.items() if not path.exists() or path.read_text(encoding="utf-8") != expected]
        if stale:
            print(f"Company intelligence products are stale: {', '.join(stale)}", file=sys.stderr)
            return 1
        print(f"Company intelligence products are current ({len(targets)} files).")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    for path, content in targets.items():
        path.write_text(content, encoding="utf-8")
    print(
        f"Built {len(json.loads(products['company_profiles.json'])['profiles'])} profiles, "
        f"{len(json.loads(products['evidence.json'])['evidence'])} evidence records, "
        f"{len(json.loads(products['programs.json'])['programs'])} program candidates, and "
        f"{len(json.loads(products['company_candidates.json'])['candidates'])} company candidates."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
