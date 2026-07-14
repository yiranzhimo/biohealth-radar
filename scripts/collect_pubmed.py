#!/usr/bin/env python3
"""Collect recent PubMed records and generate BioHealth Radar signals.

The classifier is intentionally transparent and conservative. It is a first-pass
triage layer, not a substitute for human review or medical evidence appraisal.
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
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL_NAME = "BioHealthRadar"

DEFAULT_QUERIES = [
    '("organoid"[Title/Abstract] OR "organoids"[Title/Abstract] OR "assembloid"[Title/Abstract] OR "organ-on-a-chip"[Title/Abstract])',
    '("virtual cell"[Title/Abstract] OR "cell foundation model"[Title/Abstract] OR "single-cell foundation model"[Title/Abstract] OR "perturbation prediction"[Title/Abstract])',
    '("AI drug discovery"[Title/Abstract] OR "artificial intelligence drug discovery"[Title/Abstract] OR "protein design"[Title/Abstract] OR "molecular generation"[Title/Abstract])',
    '("liquid biopsy"[Title/Abstract] OR "companion diagnostic"[Title/Abstract] OR "pathology AI"[Title/Abstract] OR "radiology AI"[Title/Abstract])',
    '("medical large language model"[Title/Abstract] OR "clinical decision support"[Title/Abstract] OR "hospital workflow"[Title/Abstract])',
    '("aging biomarker"[Title/Abstract] OR "longevity"[Title/Abstract] OR "geroscience"[Title/Abstract])',
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

RULES = [
    {
        "patterns": [
            r"\borganoid",
            r"\borganoids",
            r"\bassembloid",
            r"organ-on-a-chip",
            r"\bmicrophysiological",
        ],
        "primary": "Biotech 技术平台",
        "sub": "Organoids & Advanced Disease Models",
        "themes": ["Organoids", "Advanced Disease Models"],
        "tags": ["类器官", "疾病模型"],
        "entity": "Organoid Research",
    },
    {
        "patterns": [
            r"virtual cell",
            r"cell foundation model",
            r"single-cell foundation",
            r"perturbation prediction",
            r"cell state prediction",
        ],
        "primary": "AI Drug Discovery",
        "sub": "Virtual Cell / Cell Foundation Models",
        "themes": ["Virtual Cell", "AI for Biology", "Multi-omics"],
        "tags": ["虚拟细胞", "细胞基础模型", "多组学"],
        "entity": "Virtual Cell Model",
    },
    {
        "patterns": [
            r"protein design",
            r"de novo protein",
            r"molecular generation",
            r"generative model",
            r"drug discovery",
            r"\badmet\b",
        ],
        "primary": "AI Drug Discovery",
        "sub": "AI-enabled Discovery",
        "themes": ["AI for Biology", "Drug Discovery"],
        "tags": ["AI 制药", "蛋白设计", "分子生成"],
        "entity": "AI Drug Discovery Research",
    },
    {
        "patterns": [
            r"liquid biopsy",
            r"companion diagnostic",
            r"pathology ai",
            r"radiology ai",
            r"precision medicine",
        ],
        "primary": "Diagnostics & Precision Medicine",
        "sub": "Diagnostics & Precision Medicine",
        "themes": ["Diagnostics", "Precision Medicine"],
        "tags": ["诊断", "精准医疗"],
        "entity": "Diagnostics Research",
    },
    {
        "patterns": [
            r"clinical trial",
            r"\bphase [123]\b",
            r"regulatory",
            r"approval",
            r"safety",
        ],
        "primary": "Clinical & Regulatory",
        "sub": "Clinical Evidence",
        "themes": ["Clinical Evidence", "Regulatory Watch"],
        "tags": ["临床", "监管"],
        "entity": "Clinical Evidence",
    },
    {
        "patterns": [
            r"large language model",
            r"\bllm\b",
            r"clinical decision support",
            r"hospital workflow",
            r"electronic health record",
        ],
        "primary": "Healthcare AI",
        "sub": "Medical AI",
        "themes": ["Healthcare AI", "Medical LLM"],
        "tags": ["医疗 AI", "临床决策支持"],
        "entity": "Healthcare AI Research",
    },
    {
        "patterns": [
            r"aging biomarker",
            r"longevity",
            r"geroscience",
            r"senescence",
            r"biological age",
        ],
        "primary": "Longevity & Wellness",
        "sub": "Aging Biology",
        "themes": ["Longevity", "Biomarkers"],
        "tags": ["衰老", "biomarker", "longevity"],
        "entity": "Longevity Research",
    },
]

MONTHS = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect PubMed items for BioHealth Radar.")
    parser.add_argument("--days", type=int, default=365, help="Publication date lookback window.")
    parser.add_argument("--retmax", type=int, default=6, help="Records to request per query.")
    parser.add_argument("--max-total", type=int, default=24, help="Maximum deduped records to emit.")
    parser.add_argument("--email", default="", help="Optional contact email sent to NCBI E-utilities.")
    parser.add_argument("--output", default="data.js", help="Generated frontend data file.")
    parser.add_argument("--raw-output", default="data/raw/pubmed_latest.json", help="Raw parsed records JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and classify without writing files.")
    parser.add_argument("--query", action="append", help="Override default query. Can be passed multiple times.")
    return parser.parse_args()


def request_json(endpoint: str, params: dict[str, str | int]) -> dict[str, Any]:
    url = build_url(endpoint, params | {"retmode": "json"})
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def request_xml(endpoint: str, params: dict[str, str | int]) -> ET.Element:
    url = build_url(endpoint, params | {"retmode": "xml"})
    with urllib.request.urlopen(url, timeout=45) as response:
        return ET.fromstring(response.read())


def build_url(endpoint: str, params: dict[str, str | int]) -> str:
    return f"{EUTILS_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"


def search_pubmed(query: str, start: dt.date, end: dt.date, retmax: int, email: str) -> list[str]:
    params: dict[str, str | int] = {
        "db": "pubmed",
        "term": query,
        "sort": "pub+date",
        "retmax": retmax,
        "datetype": "pdat",
        "mindate": start.strftime("%Y/%m/%d"),
        "maxdate": end.strftime("%Y/%m/%d"),
        "tool": TOOL_NAME,
    }
    if email:
        params["email"] = email
    payload = request_json("esearch.fcgi", params)
    return payload.get("esearchresult", {}).get("idlist", [])


def fetch_pubmed(pmids: list[str], email: str) -> list[dict[str, Any]]:
    if not pmids:
        return []
    params: dict[str, str | int] = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "tool": TOOL_NAME,
    }
    if email:
        params["email"] = email
    root = request_xml("efetch.fcgi", params)
    return [parse_article(article) for article in root.findall(".//PubmedArticle")]


def parse_article(article: ET.Element) -> dict[str, Any]:
    pmid = text(article.find(".//PMID"))
    title = flatten(article.find(".//ArticleTitle")) or "(Untitled PubMed record)"
    abstract_parts = [flatten(node) for node in article.findall(".//Abstract/AbstractText")]
    abstract = " ".join(part for part in abstract_parts if part).strip()
    journal = first_text(
        article,
        [
            ".//Journal/Title",
            ".//Journal/ISOAbbreviation",
        ],
    )
    publication_types = [
        flatten(node) for node in article.findall(".//PublicationTypeList/PublicationType")
    ]
    doi = ""
    for article_id in article.findall(".//ArticleIdList/ArticleId"):
        if article_id.attrib.get("IdType") == "doi":
            doi = flatten(article_id)
            break
    pub_date = get_publication_date(article)
    return {
        "pmid": pmid,
        "title": title,
        "abstract": abstract,
        "journal": journal,
        "publicationTypes": publication_types,
        "doi": doi,
        "date": pub_date,
        "sourceUrl": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "https://pubmed.ncbi.nlm.nih.gov/",
    }


def text(node: ET.Element | None) -> str:
    return "" if node is None or node.text is None else node.text.strip()


def flatten(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def first_text(root: ET.Element, paths: list[str]) -> str:
    for path in paths:
        value = flatten(root.find(path))
        if value:
            return value
    return ""


def get_publication_date(article: ET.Element) -> str:
    for path in [
        ".//Article/ArticleDate",
        ".//Journal/JournalIssue/PubDate",
        ".//PubmedData/History/PubMedPubDate[@PubStatus='pubmed']",
        ".//PubmedData/History/PubMedPubDate",
    ]:
        node = article.find(path)
        parsed = parse_date_node(node)
        if parsed:
            return parsed
    return dt.date.today().isoformat()


def parse_date_node(node: ET.Element | None) -> str:
    if node is None:
        return ""
    year = text(node.find("Year"))
    month = normalize_month(text(node.find("Month")))
    day = text(node.find("Day")).zfill(2)
    if year and month and day:
        return f"{year}-{month}-{day}"
    if year and month:
        return f"{year}-{month}-01"
    if year:
        return f"{year}-01-01"
    medline_date = text(node.find("MedlineDate"))
    match = re.search(r"(19|20)\d{2}", medline_date)
    return f"{match.group(0)}-01-01" if match else ""


def normalize_month(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    if value.isdigit():
        return value.zfill(2)
    return MONTHS.get(value[:3].lower(), "")


def classify(record: dict[str, Any]) -> dict[str, Any]:
    haystack = f"{record.get('title', '')} {record.get('abstract', '')}".lower()
    matched_rules = [rule for rule in RULES if any(re.search(pattern, haystack) for pattern in rule["patterns"])]
    primary_rule = matched_rules[0] if matched_rules else fallback_rule()
    themes = unique([theme for rule in matched_rules for theme in rule["themes"]] or primary_rule["themes"])
    tags = unique([tag for rule in matched_rules for tag in rule["tags"]] or primary_rule["tags"])

    if re.search(r"cancer|tumou?r|oncolog|carcinoma|glioma|leukemia|lymphoma", haystack):
        themes.append("Precision Oncology")
        tags.append("肿瘤")
    if re.search(r"screen|screening|drug response|drug sensitivity", haystack):
        themes.append("Drug Screening")
        tags.append("药筛")
    if re.search(r"single-cell|spatial|multi-omics|transcriptom", haystack):
        themes.append("Multi-omics")
        tags.append("多组学")

    publication_types = " ".join(record.get("publicationTypes", [])).lower()
    event_type = "Research"
    if "review" in publication_types:
        event_type = "Review"
    if "clinical trial" in publication_types or re.search(r"\bphase [123]\b|randomi[sz]ed", haystack):
        event_type = "Clinical Study"

    evidence_level = "Medium"
    if event_type == "Clinical Study":
        evidence_level = "High"
    if not record.get("abstract"):
        evidence_level = "Low"

    return {
        "primaryCategory": primary_rule["primary"],
        "subCategory": primary_rule["sub"],
        "themes": unique(themes),
        "tags": unique(tags),
        "entity": primary_rule["entity"],
        "eventType": event_type,
        "evidenceLevel": evidence_level,
        "matchedRules": [rule["sub"] for rule in matched_rules],
    }


def fallback_rule() -> dict[str, Any]:
    return {
        "primary": "Biotech 技术平台",
        "sub": "General Biotech Research",
        "themes": ["Biotech"],
        "tags": ["biotech"],
        "entity": "Biotech Research",
    }


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def summarize_abstract(abstract: str, limit: int = 260) -> str:
    if not abstract:
        return "PubMed 记录未提供摘要。"
    clean = " ".join(abstract.split())
    return clean if len(clean) <= limit else f"{clean[:limit].rstrip()}..."


def make_signal(record: dict[str, Any], index: int) -> dict[str, Any]:
    classification = classify(record)
    pmid = record.get("pmid", "")
    title = record.get("title", "")
    journal = record.get("journal", "") or "PubMed"
    matched = ", ".join(classification.pop("matchedRules")) or "fallback"
    return {
        "id": f"pubmed-{pmid or index:0>8}",
        "date": record.get("date", ""),
        "title": title,
        "entity": classification["entity"],
        "primaryCategory": classification["primaryCategory"],
        "subCategory": classification["subCategory"],
        "eventType": classification["eventType"],
        "sourceType": "Paper",
        "sourceName": "PubMed",
        "sourceUrl": record.get("sourceUrl", "https://pubmed.ncbi.nlm.nih.gov/"),
        "reliability": "High",
        "evidenceLevel": classification["evidenceLevel"],
        "needsReview": True,
        "themes": classification["themes"],
        "tags": classification["tags"],
        "fact": f"PubMed 记录显示该文献收录于 {journal}，PMID 为 {pmid or 'unknown'}。",
        "report": summarize_abstract(record.get("abstract", "")),
        "inference": f"自动分类命中规则：{matched}。该分类仅用于情报分流，不代表研究质量或临床结论。",
        "unknown": "采集脚本未判断研究质量、样本量、利益冲突、临床阶段或商业化状态。",
    }


def write_data_js(output: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    output.write_text(f"window.BHR_DATA = {serialized};\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    today = dt.date.today()
    start = today - dt.timedelta(days=args.days)
    queries = args.query or DEFAULT_QUERIES

    all_pmids: list[str] = []
    for query in queries:
        pmids = search_pubmed(query, start, today, args.retmax, args.email)
        all_pmids.extend(pmids)
        time.sleep(0.35)

    deduped_pmids = unique(all_pmids)[: args.max_total]
    records = fetch_pubmed(deduped_pmids, args.email)
    records_by_pmid = {record.get("pmid", ""): record for record in records}
    ordered_records = [records_by_pmid[pmid] for pmid in deduped_pmids if pmid in records_by_pmid]
    signals = [make_signal(record, index) for index, record in enumerate(ordered_records, start=1)]
    signals.sort(key=lambda item: item.get("date", ""), reverse=True)

    payload = {
        "updatedAt": today.isoformat(),
        "sources": SOURCE_WATCHLIST,
        "signals": signals,
    }
    raw_payload = {
        "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "PubMed",
        "queries": queries,
        "dateWindow": {
            "start": start.isoformat(),
            "end": today.isoformat(),
        },
        "pmids": deduped_pmids,
        "records": ordered_records,
        "signals": signals,
    }

    print(f"Fetched {len(ordered_records)} PubMed records; generated {len(signals)} signals.")
    for signal in signals[:8]:
        print(
            f"- {signal['date']} | {signal['primaryCategory']} | "
            f"{signal['subCategory']} | PMID {signal['id'].replace('pubmed-', '')}"
        )

    if args.dry_run:
        return 0

    output = Path(args.output)
    raw_output = Path(args.raw_output)
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_data_js(output, payload)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"collect_pubmed.py failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
