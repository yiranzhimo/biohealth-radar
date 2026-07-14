#!/usr/bin/env python3
"""Collect ClinicalTrials.gov records and merge them into BioHealth Radar.

ClinicalTrials.gov records are treated as trial registry metadata. A registry
record can establish status, phase, enrollment, dates, and design fields; it does
not by itself establish safety, efficacy, or clinical benefit.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


API_BASE = "https://clinicaltrials.gov/api/v2/studies"

DEFAULT_TERMS = [
    "organoid cancer",
    "cell therapy oncology",
    "gene therapy",
    "liquid biopsy",
    "artificial intelligence clinical decision support",
    "aging biomarker",
    "virtual cell",
]

SOURCE_WATCHLIST = [
    {
        "name": "ClinicalTrials.gov",
        "type": "Registry",
        "cadence": "6h",
        "reliability": "High",
        "url": "https://clinicaltrials.gov/",
    },
    {
        "name": "FDA",
        "type": "Regulator",
        "cadence": "1h",
        "reliability": "High",
        "url": "https://www.fda.gov/",
    },
    {
        "name": "EMA",
        "type": "Regulator",
        "cadence": "1d",
        "reliability": "High",
        "url": "https://www.ema.europa.eu/",
    },
    {
        "name": "PubMed",
        "type": "Paper",
        "cadence": "1d",
        "reliability": "High",
        "url": "https://pubmed.ncbi.nlm.nih.gov/",
    },
    {
        "name": "bioRxiv / medRxiv",
        "type": "Paper",
        "cadence": "1d",
        "reliability": "Medium",
        "url": "https://www.biorxiv.org/",
    },
    {
        "name": "Company IR / Press",
        "type": "Company",
        "cadence": "1h",
        "reliability": "Medium",
        "url": "https://www.sec.gov/edgar/search/",
    },
    {
        "name": "Selected Industry Media",
        "type": "Media",
        "cadence": "1h",
        "reliability": "Low",
        "url": "https://www.fiercebiotech.com/",
    },
]

THEME_RULES = [
    {
        "patterns": [r"\borganoid", r"\borganoids", r"patient-derived organoid"],
        "themes": ["Organoids", "Advanced Disease Models"],
        "tags": ["类器官", "疾病模型"],
        "entity": "Organoid Clinical Study",
    },
    {
        "patterns": [r"virtual cell", r"cell foundation model", r"cell state prediction"],
        "themes": ["Virtual Cell", "AI for Biology"],
        "tags": ["虚拟细胞", "细胞模型"],
        "entity": "Virtual Cell Clinical Study",
    },
    {
        "patterns": [r"cell therapy", r"\bcar-t\b", r"\btcr\b", r"stem cell", r"nk cell"],
        "themes": ["Cell Therapy", "Oncology"],
        "tags": ["细胞治疗", "肿瘤"],
        "entity": "Cell Therapy Trial",
    },
    {
        "patterns": [r"gene therapy", r"\baav\b", r"crispr", r"gene editing"],
        "themes": ["Gene Therapy", "Genetic Medicine"],
        "tags": ["基因治疗", "基因编辑"],
        "entity": "Gene Therapy Trial",
    },
    {
        "patterns": [r"liquid biopsy", r"companion diagnostic", r"early detection", r"screening"],
        "themes": ["Diagnostics", "Precision Medicine"],
        "tags": ["诊断", "精准医疗"],
        "entity": "Diagnostics Trial",
    },
    {
        "patterns": [
            r"artificial intelligence",
            r"\bai\b",
            r"clinical decision support",
            r"machine learning",
            r"large language model",
        ],
        "themes": ["Healthcare AI", "Medical AI"],
        "tags": ["医疗 AI", "临床决策支持"],
        "entity": "Healthcare AI Trial",
    },
    {
        "patterns": [r"aging", r"longevity", r"biomarker", r"senescence", r"biological age"],
        "themes": ["Longevity", "Biomarkers"],
        "tags": ["衰老", "biomarker"],
        "entity": "Longevity Clinical Study",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect ClinicalTrials.gov studies.")
    parser.add_argument("--page-size", type=int, default=4, help="Records to request per term.")
    parser.add_argument("--max-total", type=int, default=24, help="Maximum deduped trial records to emit.")
    parser.add_argument("--term", action="append", help="Override default query term. Can be passed multiple times.")
    parser.add_argument("--data-file", default="data.js", help="Frontend data.js to merge into.")
    parser.add_argument("--raw-output", default="data/raw/clinicaltrials_latest.json", help="Raw parsed records JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and classify without writing files.")
    parser.add_argument(
        "--replace-existing-trials",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Remove prior ClinicalTrials.gov signals before merging new ones.",
    )
    return parser.parse_args()


def request_studies(term: str, page_size: int) -> list[dict[str, Any]]:
    params = {
        "query.term": term,
        "pageSize": page_size,
        "format": "json",
    }
    url = f"{API_BASE}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("studies", [])


def parse_study(study: dict[str, Any], matched_term: str) -> dict[str, Any]:
    protocol = study.get("protocolSection", {})
    derived = study.get("derivedSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    sponsor = protocol.get("sponsorCollaboratorsModule", {})
    description = protocol.get("descriptionModule", {})
    conditions = protocol.get("conditionsModule", {})
    design = protocol.get("designModule", {})
    arms = protocol.get("armsInterventionsModule", {})
    contacts = protocol.get("contactsLocationsModule", {})

    nct_id = identification.get("nctId", "")
    interventions = arms.get("interventions", [])
    locations = contacts.get("locations", [])
    countries = unique([location.get("country", "") for location in locations])
    condition_terms = conditions.get("conditions", [])
    intervention_names = [item.get("name", "") for item in interventions]
    intervention_types = [item.get("type", "") for item in interventions]

    return {
        "nctId": nct_id,
        "matchedTerm": matched_term,
        "briefTitle": identification.get("briefTitle", ""),
        "officialTitle": identification.get("officialTitle", ""),
        "organization": nested_get(identification, ["organization", "fullName"]),
        "leadSponsor": nested_get(sponsor, ["leadSponsor", "name"]),
        "overallStatus": status.get("overallStatus", ""),
        "hasResults": bool(study.get("hasResults", False)),
        "studyType": design.get("studyType", ""),
        "phases": design.get("phases", []),
        "enrollment": nested_get(design, ["enrollmentInfo", "count"]),
        "enrollmentType": nested_get(design, ["enrollmentInfo", "type"]),
        "startDate": nested_get(status, ["startDateStruct", "date"]),
        "primaryCompletionDate": nested_get(status, ["primaryCompletionDateStruct", "date"]),
        "completionDate": nested_get(status, ["completionDateStruct", "date"]),
        "firstPostDate": nested_get(status, ["studyFirstPostDateStruct", "date"]),
        "lastUpdatePostDate": nested_get(status, ["lastUpdatePostDateStruct", "date"]),
        "versionDate": nested_get(derived, ["miscInfoModule", "versionHolder"]),
        "briefSummary": description.get("briefSummary", ""),
        "detailedDescription": description.get("detailedDescription", ""),
        "conditions": condition_terms,
        "interventions": intervention_names,
        "interventionTypes": intervention_types,
        "primaryOutcomes": [item.get("measure", "") for item in nested_get(protocol, ["outcomesModule", "primaryOutcomes"], [])],
        "countries": countries,
        "sourceUrl": f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else "https://clinicaltrials.gov/",
    }


def nested_get(mapping: dict[str, Any], path: list[str], default: Any = "") -> Any:
    current: Any = mapping
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def classify_trial(record: dict[str, Any]) -> dict[str, Any]:
    haystack = " ".join(
        str(value)
        for value in [
            record.get("briefTitle", ""),
            record.get("officialTitle", ""),
            record.get("briefSummary", ""),
            " ".join(record.get("conditions", [])),
            " ".join(record.get("interventions", [])),
            " ".join(record.get("primaryOutcomes", [])),
        ]
    ).lower()

    matched = [rule for rule in THEME_RULES if any(re.search(pattern, haystack) for pattern in rule["patterns"])]
    themes = ["Clinical Trials"]
    tags = ["临床试验"]
    entity = "Clinical Trial"
    if matched:
        entity = matched[0]["entity"]
        for rule in matched:
            themes.extend(rule["themes"])
            tags.extend(rule["tags"])

    if re.search(r"cancer|tumou?r|oncolog|carcinoma|glioma|leukemia|lymphoma|neoplasm", haystack):
        themes.extend(["Oncology", "Precision Oncology"])
        tags.append("肿瘤")
    if re.search(r"breast", haystack):
        tags.append("乳腺癌")
    if re.search(r"recruiting|not yet recruiting", record.get("overallStatus", "").lower()):
        themes.append("Recruiting")
    if "China" in record.get("countries", []):
        tags.append("中国")

    evidence_level = "Medium"
    if record.get("hasResults"):
        evidence_level = "High"
    if record.get("overallStatus") in {"TERMINATED", "WITHDRAWN", "SUSPENDED"} and not record.get("hasResults"):
        evidence_level = "Low"

    return {
        "entity": entity,
        "primaryCategory": "Clinical & Regulatory",
        "subCategory": "Clinical Trials",
        "eventType": "Clinical Trial Results" if record.get("hasResults") else "Clinical Trial",
        "themes": unique(themes),
        "tags": unique(tags),
        "evidenceLevel": evidence_level,
        "matchedThemes": [theme for rule in matched for theme in rule["themes"]],
    }


def make_signal(record: dict[str, Any], index: int) -> dict[str, Any]:
    classification = classify_trial(record)
    nct_id = record.get("nctId", "")
    title = record.get("briefTitle") or record.get("officialTitle") or f"ClinicalTrials.gov study {nct_id}"
    phase = format_list(record.get("phases", []), "N/A")
    countries = format_list(record.get("countries", []), "N/A")
    enrollment = record.get("enrollment") or "N/A"
    status = record.get("overallStatus") or "UNKNOWN"
    lead = record.get("leadSponsor") or record.get("organization") or "N/A"
    signal_date = (
        record.get("lastUpdatePostDate")
        or record.get("versionDate")
        or record.get("firstPostDate")
        or record.get("startDate")
        or dt.date.today().isoformat()
    )
    matched = ", ".join(classification.pop("matchedThemes")) or "clinical registry"

    return {
        "id": f"clinicaltrials-{nct_id or index:0>8}",
        "date": signal_date,
        "title": title,
        "entity": classification["entity"],
        "primaryCategory": classification["primaryCategory"],
        "subCategory": classification["subCategory"],
        "eventType": classification["eventType"],
        "sourceType": "Registry",
        "sourceName": "ClinicalTrials.gov",
        "sourceUrl": record.get("sourceUrl", "https://clinicaltrials.gov/"),
        "reliability": "High",
        "evidenceLevel": classification["evidenceLevel"],
        "needsReview": True,
        "themes": classification["themes"],
        "tags": classification["tags"],
        "fact": (
            f"ClinicalTrials.gov lists {nct_id or 'unknown NCT ID'} with status {status}, "
            f"phase {phase}, enrollment {enrollment}, lead sponsor {lead}, countries {countries}."
        ),
        "report": summarize(record.get("briefSummary", "")),
        "inference": (
            f"自动分流为 Clinical & Regulatory / Clinical Trials，主题命中：{matched}。"
            "登记状态和设计字段不能直接证明疗效或安全性。"
        ),
        "unknown": "当前登记记录未覆盖方案变化核验、结果质量判断、样本量充分性、终点质量或监管影响。",
    }


def summarize(value: str, limit: int = 260) -> str:
    clean = " ".join(str(value or "").split())
    if not clean:
        return "ClinicalTrials.gov 记录未提供 brief summary。"
    return clean if len(clean) <= limit else f"{clean[:limit].rstrip()}..."


def format_list(values: list[Any], fallback: str) -> str:
    clean = [str(value) for value in values if value]
    return ", ".join(clean) if clean else fallback


def unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def read_data_js(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"updatedAt": dt.date.today().isoformat(), "sources": SOURCE_WATCHLIST, "signals": []}
    text = path.read_text(encoding="utf-8").strip()
    prefix = "window.BHR_DATA ="
    if not text.startswith(prefix):
        raise ValueError(f"{path} does not look like a BioHealth Radar data.js file")
    return json.loads(text[len(prefix) :].strip().rstrip(";"))


def write_data_js(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(f"window.BHR_DATA = {serialized};\n", encoding="utf-8")


def merge_signals(existing: dict[str, Any], trial_signals: list[dict[str, Any]], replace_existing_trials: bool) -> dict[str, Any]:
    existing_signals = existing.get("signals", [])
    if replace_existing_trials:
        existing_signals = [
            signal
            for signal in existing_signals
            if not str(signal.get("id", "")).startswith("clinicaltrials-")
        ]

    by_id: dict[str, dict[str, Any]] = {signal["id"]: signal for signal in existing_signals if signal.get("id")}
    for signal in trial_signals:
        by_id[signal["id"]] = signal

    signals = list(by_id.values())
    signals.sort(key=lambda item: item.get("date", ""), reverse=True)
    return {
        "updatedAt": dt.date.today().isoformat(),
        "sources": SOURCE_WATCHLIST,
        "signals": signals,
    }


def main() -> int:
    args = parse_args()
    terms = args.term or DEFAULT_TERMS
    raw_studies: list[dict[str, Any]] = []

    for term in terms:
        studies = request_studies(term, args.page_size)
        for study in studies:
            raw_studies.append({"matchedTerm": term, "study": study})
        time.sleep(0.35)

    parsed_by_nct: dict[str, dict[str, Any]] = {}
    for item in raw_studies:
        parsed = parse_study(item["study"], item["matchedTerm"])
        nct_id = parsed.get("nctId")
        if nct_id and nct_id not in parsed_by_nct:
            parsed_by_nct[nct_id] = parsed

    records = list(parsed_by_nct.values())[: args.max_total]
    signals = [make_signal(record, index) for index, record in enumerate(records, start=1)]
    signals.sort(key=lambda item: item.get("date", ""), reverse=True)

    raw_payload = {
        "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "ClinicalTrials.gov",
        "terms": terms,
        "records": records,
        "signals": signals,
    }

    print(f"Fetched {len(records)} ClinicalTrials.gov records; generated {len(signals)} signals.")
    for signal in signals[:10]:
        print(
            f"- {signal['date']} | {signal['primaryCategory']} | "
            f"{signal['eventType']} | {signal['id'].replace('clinicaltrials-', '')}"
        )

    if args.dry_run:
        return 0

    data_file = Path(args.data_file)
    raw_output = Path(args.raw_output)
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    existing = read_data_js(data_file)
    merged = merge_signals(existing, signals, args.replace_existing_trials)
    write_data_js(data_file, merged)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"collect_clinicaltrials.py failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
