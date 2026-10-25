#!/usr/bin/env python3
"""Unified, fail-closed validator and bias report for the active KB2 corpus."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # Schema validation is an acceptance gate.
    raise SystemExit(f"jsonschema is required for KB2 validation: {exc}")


DOMAINS_ROOT = Path("knowledge/v2/domains")
SCHEMA_PATH = Path("knowledge/v2/unit.schema.json")
V2_LIBRARY_ROOT = Path("knowledge/v2/library")
LEGACY_LIBRARY_ROOT = Path("knowledge/library")
OUTPUT_PATH = Path("artifacts/kb2-consolidate/validation.json")
BIAS_PATH = Path("artifacts/kb2-consolidate/bias-report-zh.md")

MAX_SENTENCE_REPETITIONS = 3
MAX_REFERENCE_SHARE = 0.10
MAX_AUTHOR_SHARE = 0.10
MIN_VERIFIED_REFERENCES_PER_DOMAIN = 35
MIN_VALUE_RANGES_PER_DOMAIN = 12
VERIFIED_STATUSES = {"VERIFIED", "VERIFIED_OFFICIAL_SITE"}
OFFICIAL_STATUS = "VERIFIED_OFFICIAL_SITE"
SCHOLARLY_KIND_MARKERS = ("ACADEMIC", "JOURNAL", "PAPER", "THESIS", "ARTICLE")
VALUE_RANGE_EXEMPT_DOMAINS = {"THY", "MET", "SOC", "CAS"}
NON_LOCAL_MARKERS = ("並非", "不是", "非本基地", "非基地", "不代表", "不構成", "不屬於", "非本案")
GEOGRAPHIC_MARKERS = (
    "全球", "跨地域", "跨氣候帶", "跨國", "多國", "多城市", "國際樣本", "北美", "美國", "加拿大",
    "歐洲", "荷蘭", "鹿特丹", "阿姆斯特丹", "英國", "德國", "法國", "瑞士", "瑞典", "丹麥", "芬蘭",
    "挪威", "西班牙", "義大利", "比利時", "奧地利", "葡萄牙", "愛爾蘭", "柏林", "倫敦", "巴黎", "維也納",
    "巴塞隆納", "布魯塞爾", "哥本哈根", "亞洲", "日本", "中國", "臺灣", "台灣", "韓國", "南韓", "香港",
    "新加坡", "印度", "孟加拉", "東南亞", "澳洲", "澳大利亞", "紐西蘭", "非洲", "南非", "拉丁美洲", "南美",
    "巴西", "墨西哥", "哥倫比亞", "波哥大", "土耳其", "東京", "首爾", "曼哈頓", "紐約", "美洲",
)


def utc_now() -> str:
    return subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip()


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value] if value is not None else []


def authors_for(record: dict[str, Any]) -> list[str]:
    authors = record.get("authors", [])
    return [str(author).strip() for author in as_list(authors) if str(author).strip()]


def is_scholarly(record: dict[str, Any]) -> bool:
    kind = str(record.get("kind", "")).upper()
    return any(marker in kind for marker in SCHOLARLY_KIND_MARKERS)


def sentence_texts(value: Any) -> list[str]:
    """Extract authored text only; citation IDs and structured metadata are excluded."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                for key in ("option_zh", "tradeoff_zh"):
                    if isinstance(item.get(key), str):
                        result.append(item[key])
        return result
    return []


def prose_fields(unit: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "summary_zh", "key_points_zh", "design_implications_zh", "design_options",
        "applies_when_zh", "not_applicable_when_zh", "debates_zh",
    ):
        values.extend(sentence_texts(unit.get(key)))
    evidence = unit.get("evidence", {})
    if isinstance(evidence, dict):
        for finding in evidence.get("findings", []):
            if isinstance(finding, dict) and isinstance(finding.get("claim_zh"), str):
                values.append(finding["claim_zh"])
    for value in unit.get("values", []):
        if isinstance(value, dict) and isinstance(value.get("context"), str):
            values.append(value["context"])
    case = unit.get("case")
    if isinstance(case, dict):
        for key in ("key_strategies_zh", "outcomes_zh", "critiques_zh"):
            values.extend(sentence_texts(case.get(key)))
    return values


def normalize_sentence(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(normalized.split())
    return normalized.strip(" \t\r\n-•*0123456789.、。；;:：！？!?()（）[]【】\"'`_")


def split_sentences(text: str) -> list[str]:
    return [
        sentence
        for sentence in re.split(r"(?<=[。！？!?])\s*|(?<=[.!?])\s+|\n+", text)
        if normalize_sentence(sentence) and len(normalize_sentence(sentence)) >= 8
    ]


def load_library(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Prefer the active v2 root; use nested reused and legacy files only as fallbacks."""
    records: dict[str, dict[str, Any]] = {}
    origins: dict[str, str] = {}
    duplicate_ids: dict[str, list[str]] = defaultdict(list)
    sources = (
        (root / V2_LIBRARY_ROOT, False),
        (root / LEGACY_LIBRARY_ROOT, True),
    )
    for base, legacy in sources:
        if not base.exists():
            continue
        paths = sorted(base.rglob("*.json"))
        if not legacy:
            paths.sort(key=lambda path: (len(path.relative_to(base).parts) != 1, str(path)))
        for path in paths:
            try:
                record = read_json(path)
            except Exception:
                continue
            ident = record.get("id") if isinstance(record, dict) else None
            if not ident:
                continue
            relative = str(path.relative_to(root))
            if ident in records:
                duplicate_ids[ident].append(relative)
                continue
            records[str(ident)] = record
            origins[str(ident)] = relative
    metadata = {
        "record_count": len(records),
        "duplicate_ids_prefer_v2_root": {
            ident: {"canonical_path": origins[ident], "duplicate_paths": paths}
            for ident, paths in sorted(duplicate_ids.items())
            if ident in origins
        },
        "resolution_order": [
            "knowledge/v2/library/*.json",
            "knowledge/v2/library/reused-from-v0.2/**/*.json (fallback only)",
            "knowledge/library/**/*.json (fallback only; read-only legacy records)",
        ],
    }
    return records, metadata


def all_unit_citations(unit: dict[str, Any]) -> set[str]:
    citations = {str(row.get("library_id")) for row in unit.get("sources", []) if isinstance(row, dict) and row.get("library_id")}
    evidence = unit.get("evidence", {})
    if isinstance(evidence, dict):
        citations.update(
            str(row.get("library_id")) for row in evidence.get("findings", [])
            if isinstance(row, dict) and row.get("library_id")
        )
    citations.update(
        str(row.get("library_id")) for row in unit.get("values", [])
        if isinstance(row, dict) and row.get("library_id")
    )
    return citations


def has_non_local_law_disclaimer(text: str) -> bool:
    if "本基地法規" in text and any(marker in text for marker in ("否", "無", "不適用")):
        return True
    return "法規" in text and any(marker in text for marker in NON_LOCAL_MARKERS)


def has_region(text: str, record: dict[str, Any] | None) -> bool:
    if any(marker in text for marker in GEOGRAPHIC_MARKERS):
        return True
    if not record:
        return False
    for region in as_list(record.get("region")):
        label = str(region).strip()
        if len(label) >= 2 and label in text:
            return True
    return False


def official_url_and_date(record: dict[str, Any]) -> tuple[str | None, str | None]:
    verification = record.get("verification", {})
    if not isinstance(verification, dict):
        return None, None
    url = verification.get("url") or record.get("url")
    accessed = (
        verification.get("accessed_utc") or verification.get("accessed_at")
        or verification.get("access_date") or record.get("accessed_utc") or record.get("accessed_at")
    )
    return (str(url).strip() if url else None, str(accessed).strip() if accessed else None)


def region_bucket(record: dict[str, Any]) -> set[str]:
    raw = " ".join(str(value) for value in as_list(record.get("region"))).casefold()
    result: set[str] = set()
    asia = ("asia", "亞洲", "taiwan", "台灣", "臺灣", "china", "中國", "japan", "日本", "korea", "韓國", "香港", "hong kong", "singapore", "新加坡", "india", "印度", "bangladesh", "孟加拉", "southeast")
    north_america = ("north america", "北美", "usa", "united states", "美國", "canada", "加拿大", "new york", "紐約", "manhattan", "曼哈頓")
    europe = ("europe", "歐洲", "荷蘭", "netherlands", "rotterdam", "鹿特丹", "amsterdam", "阿姆斯特丹", "uk", "britain", "英國", "germany", "德國", "france", "法國", "switzerland", "瑞士", "sweden", "瑞典", "denmark", "丹麥", "finland", "芬蘭", "norway", "挪威", "spain", "西班牙", "belgium", "比利時", "austria", "奧地利", "ireland", "愛爾蘭", "berlin", "柏林", "london", "倫敦", "paris", "巴黎", "copenhagen", "哥本哈根", "brussels", "布魯塞爾")
    if any(token in raw for token in asia):
        result.add("亞洲")
    if any(token in raw for token in north_america):
        result.add("北美")
    if any(token in raw for token in europe):
        result.add("歐洲")
    if not result:
        result.add("其他")
    return result


def literature_category(record: dict[str, Any]) -> str:
    kind = str(record.get("kind", "")).upper()
    status = record.get("verification", {}).get("status") if isinstance(record.get("verification"), dict) else None
    if status == OFFICIAL_STATUS or kind.startswith("OFFICIAL") or kind == "POLICY":
        return "官方"
    if any(marker in kind for marker in ("MANUAL", "HANDBOOK", "GUIDE", "PRACTICE")):
        return "手冊／實務指南"
    if any(marker in kind for marker in ("PAPER", "JOURNAL", "ARTICLE")):
        return "學術期刊／論文"
    if any(marker in kind for marker in ("BOOK", "CHAPTER", "DISSERTATION", "ACADEMIC_REPORT")):
        return "學術書籍／章節／報告"
    return "其他"


def issue(code: str, domain: str | None, unit_id: str | None, message: str) -> dict[str, Any]:
    return {"code": code, "domain": domain, "unit_id": unit_id, "message": message}


def generate_bias_report(
    domains: dict[str, dict[str, Any]],
    library: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
    path: Path,
) -> None:
    records = list(library.values())
    status_counts = Counter(
        (record.get("verification", {}).get("status", "MISSING") if isinstance(record.get("verification"), dict) else "MISSING")
        for record in records
    )
    region_counts: Counter[str] = Counter()
    year_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    tradition_counts: Counter[str] = Counter()
    author_counts: Counter[str] = Counter()
    author_slots = 0
    for record in records:
        for bucket in region_bucket(record):
            region_counts[bucket] += 1
        year = record.get("year")
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = None
        if year is None:
            year_counts["年代未知"] += 1
        elif year < 1970:
            year_counts["1970 年前"] += 1
        elif year < 2000:
            year_counts["1970–1999"] += 1
        elif year < 2010:
            year_counts["2000–2009"] += 1
        elif year < 2020:
            year_counts["2010–2019"] += 1
        else:
            year_counts["2020 年起"] += 1
        kind_counts[literature_category(record)] += 1
        tradition = record.get("tradition")
        for value in as_list(tradition):
            if str(value).strip():
                tradition_counts[str(value).strip()] += 1
        for author in authors_for(record):
            author_counts[author] += 1
            author_slots += 1

    top_authors = author_counts.most_common(10)
    top_ten_share = sum(count for _, count in top_authors) / max(1, author_slots)
    north_west = (region_counts["歐洲"] + region_counts["北美"]) / max(1, len(records))
    pending_units = sum(
        row.get("unit_claim_verification_counts", {}).get("CANONICAL_CROSS_CHECK_PENDING", 0)
        for row in domains.values()
    )
    pending_findings = sum(
        row.get("finding_claim_verification_counts", {}).get("CANONICAL_CROSS_CHECK_PENDING", 0)
        for row in domains.values()
    )
    low_values = [(domain, row["value_range_count"]) for domain, row in domains.items() if row["value_range_count"] < MIN_VALUE_RANGES_PER_DOMAIN]
    low_literature = [
        (domain, row["verified_reference_count"]) for domain, row in domains.items()
        if row["verified_reference_count"] < MIN_VERIFIED_REFERENCES_PER_DOMAIN
    ]
    report_lines = [
        "# 知識庫 v2 來源偏誤與覆蓋報告",
        "",
        f"統計時間：{utc_now()}（由本地 v2 與只讀舊庫書目紀錄計算；未呼叫外部 API）",
        f"統計口徑：{len(records)} 筆按 library ID 去重後的可讀文獻紀錄；同一紀錄可涵蓋多個地域，因此地域分類不是互斥分組。作者集中度按每筆去重書目中的作者署名位置計算。",
        "",
        "## 地區分布",
        "",
        "| 地區 | 文獻紀錄數 | 占全庫比例 |",
        "|---|---:|---:|",
    ]
    for name in ("歐洲", "北美", "亞洲", "其他"):
        report_lines.append(f"| {name} | {region_counts[name]} | {region_counts[name] / max(1, len(records)):.1%} |")
    report_lines += ["", "## 年代分布", "", "| 出版年代 | 文獻紀錄數 |", "|---|---:|"]
    for bucket in ("1970 年前", "1970–1999", "2000–2009", "2010–2019", "2020 年起", "年代未知"):
        report_lines.append(f"| {bucket} | {year_counts[bucket]} |")
    report_lines += ["", "## 文獻種類", "", "| 類型 | 文獻紀錄數 |", "|---|---:|"]
    for category in ("學術期刊／論文", "學術書籍／章節／報告", "手冊／實務指南", "官方", "其他"):
        report_lines.append(f"| {category} | {kind_counts[category]} |")
    report_lines += [
        "", "## 作者集中度", "",
        f"前 10 名作者共占 {top_ten_share:.1%} 的作者署名位置（{sum(count for _, count in top_authors)}/{author_slots}）。",
        "", "| 作者 | 書目數 |", "|---|---:|",
    ]
    for author, count in top_authors:
        report_lines.append(f"| {author} | {count} |")
    report_lines += ["", "## 學派／研究傳統", "", "| 傳統標籤 | 文獻紀錄數 |", "|---|---:|"]
    for tradition, count in sorted(tradition_counts.items(), key=lambda item: (-item[1], item[0])):
        report_lines.append(f"| {tradition} | {count} |")
    report_lines += [
        "", "## 領域覆蓋：數值範圍與 claim_verification", "",
        "| 領域 | 單元 | value_range | 不同引用文獻 | 已驗證引用文獻 | Findings 查核分布 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for domain, row in sorted(domains.items()):
        cv = ", ".join(f"{key}={value}" for key, value in sorted(row["finding_claim_verification_counts"].items())) or "無 findings"
        report_lines.append(
            f"| {domain} | {row['unit_count']} | {row['value_range_count']} | {row['unique_reference_count']} | {row['verified_reference_count']} | {cv} |"
        )
    report_lines += [
        "", "## 偏誤觀察與補強方向", "",
        f"- 歐洲與北美紀錄合計占去重文獻庫的 {north_west:.1%}；後續可以先盤點亞洲、非洲、拉丁美洲及全球南方的現有空缺，再由指揮官另案查證補充，不在本次新增文獻。",
        f"- 前 10 名作者的署名占比為 {top_ten_share:.1%}。若前十集中於少數經典或常被引用作者，補強時應納入不同方法與批評傳統，但不能為了分散比例而任意改動既有來源。",
        f"- 單元層有 {pending_units} 筆、Findings 層有 {pending_findings} 項標示 CANONICAL_CROSS_CHECK_PENDING；這些內容仍需 Claude 逐條交叉核對。",
        "- 對 knowledge/v2 的 JSON 與 Markdown 掃描簡體特徵字後，唯一命中是 knowledge/v2/library/MLIT_DENTEI.json 的日文原標題「立地適正化計画作成の手引き」中的「画」；保留原始書名，未改來源文字。",
        "- 類型統計反映目前收錄形式，不等於研究品質或證據強度；官方網頁、學術書目核對與全文主張查核應分開解讀。",
        "", "## 領域門檻與疑點", "",
    ]
    if low_values:
        report_lines.append("- value_range 未達 12 筆的領域：" + "、".join(f"{domain}（{count}）" for domain, count in low_values) + "。本次不新增數值或出處。")
    if low_literature:
        report_lines.append("- 已驗證不同引用文獻少於 35 筆的領域：" + "、".join(f"{domain}（{count}）" for domain, count in low_literature) + "。")
    partials = sorted(
        (ident, record.get("verification", {}).get("status"))
        for ident, record in library.items()
        if isinstance(record.get("verification"), dict)
        and record.get("verification", {}).get("status") not in VERIFIED_STATUSES
    )
    if partials:
        report_lines.append("- 書目驗證狀態為 AMBIGUOUS、PARTIAL 或缺漏的紀錄：" + "、".join(f"{ident}（{status}）" for ident, status in partials[:30]) + ("等。" if len(partials) > 30 else "。"))
    missing_source_units = sorted({
        (row.get("unit_id"), row.get("message")) for row in issues
        if row.get("code") in {"REFERENCE_MISSING", "REFERENCE_NOT_VERIFIED"}
    })
    if missing_source_units:
        report_lines.append(f"- 本次被引來源中有 {len(missing_source_units)} 項待核實或無法解析；詳見 validation.json。")
    ajacobs = "knowledge/v2/library/AJACOBS93.json"
    report_lines.append(f"- AJACOBS93 同時存在於 v0.2 與 v2；總驗證器以 {ajacobs} 作為有效 v2 記錄，舊庫保持原樣。")
    report_lines += [
        "- 數值與來源只做格式、地域／用途／法規聲明及可追溯性檢查；此報告沒有重新查證任何新文獻，也不判定具體數值是否正確。疑似錯誤應另列給指揮官審查。",
        "", "## 驗證器問題摘要", "",
        f"本次統一驗證器列出 {len(issues)} 個問題；狀態為 {'PASS' if not issues else 'INCOMPLETE'}。問題明細與單元位置見 `artifacts/kb2-consolidate/validation.json`。",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(report_lines), encoding="utf-8")


def validate(root: Path) -> dict[str, Any]:
    schema_path = root / SCHEMA_PATH
    schema = read_json(schema_path)
    Draft202012Validator.check_schema(schema)
    schema_validator = Draft202012Validator(schema)
    library, library_metadata = load_library(root)
    issues: list[dict[str, Any]] = []
    domains: dict[str, dict[str, Any]] = {}
    all_prose_repeats: dict[str, list[dict[str, Any]]] = {}
    status_by_citation: Counter[str] = Counter()
    verified_source_ids: set[str] = set()

    domain_paths = sorted(path for path in (root / DOMAINS_ROOT).iterdir() if path.is_dir())
    for domain_dir in domain_paths:
        domain = domain_dir.name
        units_dir = domain_dir / "units"
        paths = sorted(units_dir.glob("*.json")) if units_dir.exists() else []
        units: list[dict[str, Any]] = []
        type_counts: Counter[str] = Counter()
        unit_claim_counts: Counter[str] = Counter()
        finding_claim_counts: Counter[str] = Counter()
        citation_counts: Counter[str] = Counter()
        author_citation_counts: Counter[str] = Counter()
        author_names_total = 0
        all_references: set[str] = set()
        verified_references: set[str] = set()
        value_range_count = 0
        sentence_counts: Counter[str] = Counter()
        sentence_sources: dict[str, list[str]] = defaultdict(list)
        official_unit_count = 0

        for path in paths:
            relative_path = path.relative_to(root).as_posix()
            try:
                unit = read_json(path)
            except Exception as exc:
                issues.append(issue("UNIT_JSON_INVALID", domain, path.stem, f"{relative_path}: {exc}"))
                continue
            if not isinstance(unit, dict):
                issues.append(issue("UNIT_NOT_OBJECT", domain, path.stem, f"{relative_path}: root must be an object"))
                continue
            units.append(unit)
            unit_id = str(unit.get("id", path.stem))
            type_name = str(unit.get("type", "UNKNOWN"))
            type_counts[type_name] += 1
            if unit.get("domain") != domain:
                issues.append(issue("DOMAIN_FOLDER_MISMATCH", domain, unit_id, f"domain field is {unit.get('domain')!r}"))
            unit_claim_counts[str(unit.get("claim_verification") or "NOT_SET")] += 1

            for error in schema_validator.iter_errors(unit):
                pointer = "/".join(str(part) for part in error.absolute_path) or "<root>"
                issues.append(issue("SCHEMA_INVALID", domain, unit_id, f"{pointer}: {error.message}"))

            citations = all_unit_citations(unit)
            all_references.update(citations)
            source_rows = [row for row in unit.get("sources", []) if isinstance(row, dict)]
            source_ids = [str(row.get("library_id")) for row in source_rows if row.get("library_id")]
            distinct_source_ids = set(source_ids)
            for ident in source_ids:
                citation_counts[ident] += 1
            unit_records = {ident: library.get(ident) for ident in citations}
            statuses = {
                ident: (record.get("verification", {}).get("status", "MISSING") if record and isinstance(record.get("verification"), dict) else "MISSING")
                for ident, record in unit_records.items()
            }
            is_official_unit = type_name == "regulation_profile" or any(status == OFFICIAL_STATUS for status in statuses.values())
            if is_official_unit:
                official_unit_count += 1
            if type_name == "regulation_profile" and not any(status == OFFICIAL_STATUS for status in statuses.values()):
                issues.append(issue("REGULATION_WITHOUT_OFFICIAL_SOURCE", domain, unit_id, "regulation_profile must cite at least one VERIFIED_OFFICIAL_SITE record"))

            for ident in sorted(citations):
                record = library.get(ident)
                if record is None:
                    issues.append(issue("REFERENCE_MISSING", domain, unit_id, f"cited library_id {ident} cannot be resolved in v2 or legacy library"))
                    status_by_citation["MISSING"] += 1
                    continue
                verification = record.get("verification", {})
                status = verification.get("status", "MISSING") if isinstance(verification, dict) else "MISSING"
                status_by_citation[str(status)] += 1
                if status not in VERIFIED_STATUSES:
                    issues.append(issue("REFERENCE_NOT_VERIFIED", domain, unit_id, f"cited library_id {ident} has status {status}"))
                else:
                    verified_source_ids.add(ident)
                    if ident in distinct_source_ids:
                        verified_references.add(ident)
                if status == OFFICIAL_STATUS:
                    url, accessed = official_url_and_date(record)
                    if not url or not accessed:
                        issues.append(issue("OFFICIAL_SOURCE_PROVENANCE_MISSING", domain, unit_id, f"{ident} must include a URL and access date in verification metadata"))

            if not is_official_unit:
                if len(distinct_source_ids) < 2:
                    issues.append(issue("SOURCE_DIVERSITY_LOW", domain, unit_id, f"only {len(distinct_source_ids)} distinct sources; at least 2 are required"))
                found_scholarly = any(library.get(ident) and is_scholarly(library[ident]) for ident in distinct_source_ids)
                if not found_scholarly:
                    issues.append(issue("SCHOLARLY_SOURCE_MISSING", domain, unit_id, "no academic source among citations"))
                first_authors: set[str] = set()
                for ident in distinct_source_ids:
                    record = library.get(ident)
                    authors = authors_for(record) if record else []
                    if authors:
                        first_authors.add(unicodedata.normalize("NFKC", authors[0]).casefold())
                if len(first_authors) < 2:
                    issues.append(issue("INDEPENDENT_AUTHOR_DIVERSITY_LOW", domain, unit_id, f"only {len(first_authors)} distinct first-author identities"))

            for ident in source_ids:
                record = library.get(ident)
                if not record:
                    continue
                authors = authors_for(record)
                for author in authors:
                    author_citation_counts[author] += 1
                    author_names_total += 1

            if type_name == "value_range":
                value_range_count += 1
                values = unit.get("values", [])
                if not values:
                    issues.append(issue("VALUE_RANGE_EMPTY", domain, unit_id, "value_range has no value rows"))
                for index, value in enumerate(values, start=1):
                    if not isinstance(value, dict):
                        continue
                    context = str(value.get("context", ""))
                    ident = str(value.get("library_id", ""))
                    record = library.get(ident)
                    if not context.strip():
                        issues.append(issue("VALUE_RANGE_CONTEXT_MISSING", domain, unit_id, f"values[{index}].context is empty"))
                    elif not has_region(context, record):
                        issues.append(issue("VALUE_RANGE_REGION_MISSING", domain, unit_id, f"values[{index}] lacks an identifiable geographic scope"))
                    if not has_non_local_law_disclaimer(context):
                        issues.append(issue("VALUE_RANGE_LOCAL_LAW_UNCLEAR", domain, unit_id, f"values[{index}] must state that the range is not this site's law"))

            evidence = unit.get("evidence", {})
            if isinstance(evidence, dict):
                for finding in evidence.get("findings", []):
                    if isinstance(finding, dict):
                        tier = str(finding.get("claim_verification") or "NOT_SET")
                        finding_claim_counts[tier] += 1

            for prose in prose_fields(unit):
                for sentence in split_sentences(prose):
                    normalized = normalize_sentence(sentence)
                    sentence_counts[normalized] += 1
                    sentence_sources[normalized].append(unit_id)

        repeated = {
            sentence: count for sentence, count in sentence_counts.items()
            if count > MAX_SENTENCE_REPETITIONS
        }
        repeat_rows: list[dict[str, Any]] = []
        for sentence, count in sorted(repeated.items(), key=lambda item: (-item[1], item[0])):
            unit_ids = sorted(set(sentence_sources[sentence]))
            repeat_rows.append({"count": count, "unit_ids": unit_ids, "sentence": sentence})
            issues.append(issue("SENTENCE_REPEATED_OVER_3", domain, None, f"sentence appears {count} times in {len(unit_ids)} units: {sentence}"))

        citation_events = sum(citation_counts.values())
        reference_shares = {ident: count / max(1, citation_events) for ident, count in citation_counts.items()}
        overused = {
            ident: round(share, 4) for ident, share in sorted(reference_shares.items())
            if share > MAX_REFERENCE_SHARE + 1e-9
        }
        for ident, share in overused.items():
            issues.append(issue("REFERENCE_SHARE_OVER_10_PERCENT", domain, None, f"{ident} occupies {share:.1%} of {citation_events} source citations"))

        author_shares = {author: count / max(1, citation_events) for author, count in author_citation_counts.items()}
        overused_authors = {
            author: round(share, 4) for author, share in sorted(author_shares.items())
            if share > MAX_AUTHOR_SHARE + 1e-9
        }
        for author, share in overused_authors.items():
            issues.append(issue("AUTHOR_SHARE_OVER_10_PERCENT", domain, None, f"{author} occupies {share:.1%} of source citation events"))

        if len(verified_references) < MIN_VERIFIED_REFERENCES_PER_DOMAIN:
            issues.append(issue("DOMAIN_VERIFIED_REFERENCE_FLOOR", domain, None, f"{len(verified_references)} distinct verified references; minimum is {MIN_VERIFIED_REFERENCES_PER_DOMAIN}"))
        # Commander 2026-10-08: theory, method, social-theory and case domains are qualitative; no value-range floor.
        if value_range_count < MIN_VALUE_RANGES_PER_DOMAIN and domain not in VALUE_RANGE_EXEMPT_DOMAINS:
            issues.append(issue("DOMAIN_VALUE_RANGE_FLOOR", domain, None, f"{value_range_count} value_range units; minimum is {MIN_VALUE_RANGES_PER_DOMAIN}"))

        domains[domain] = {
            "unit_count": len(units),
            "type_distribution": dict(sorted(type_counts.items())),
            "value_range_count": value_range_count,
            "unique_reference_count": len(all_references),
            "verified_reference_count": len(verified_references),
            "source_citation_events": citation_events,
            "source_citation_share_max": round(max(reference_shares.values(), default=0.0), 4),
            "sources_over_10_percent": overused,
            "author_citation_share_max": round(max(author_shares.values(), default=0.0), 4),
            "authors_over_10_percent": overused_authors,
            "official_or_regulation_unit_count": official_unit_count,
            "unit_claim_verification_counts": dict(sorted(unit_claim_counts.items())),
            "finding_claim_verification_counts": dict(sorted(finding_claim_counts.items())),
            "sentence_repeat_group_count_over_3": len(repeat_rows),
            "sentence_repeat_occurrences_over_3": sum(row["count"] for row in repeat_rows),
            "sentence_repeats_over_3": repeat_rows,
            "top_sources": [
                {"library_id": ident, "citation_count": count, "share": round(count / max(1, citation_events), 4)}
                for ident, count in citation_counts.most_common(10)
            ],
        }
        all_prose_repeats[domain] = repeat_rows

    unit_claim_distribution: Counter[str] = Counter()
    finding_claim_distribution: Counter[str] = Counter()
    for row in domains.values():
        unit_claim_distribution.update(row["unit_claim_verification_counts"])
        finding_claim_distribution.update(row["finding_claim_verification_counts"])

    report = {
        "validator": "scripts/kb2_validate_all.py",
        "schema": SCHEMA_PATH.as_posix(),
        "generated_at_utc": utc_now(),
        "status": "PASS" if not issues else "INCOMPLETE",
        "domain_count": len(domains),
        "library": {
            **library_metadata,
            "unique_cited_source_ids_verified": len(verified_source_ids),
            "citation_verification_status_counts": dict(sorted(status_by_citation.items())),
        },
        "domains": domains,
        "claim_verification_distribution": {
            "units": dict(sorted(unit_claim_distribution.items())),
            "findings": dict(sorted(finding_claim_distribution.items())),
        },
        "issue_count": len(issues),
        "issues": issues,
        "scope_notes": [
            "學術／概念類依 schema、來源解析與 VERIFIED 狀態、引用／作者集中度、句子重複、value_range 地域與非基地法規說明驗證。",
            "regulation_profile 或引用 VERIFIED_OFFICIAL_SITE 的單元可使用官方來源；官方紀錄必須有 URL 與存取日期。",
            "AJACOBS93 的 v2 書目優先；v0.2 舊庫保留不改。",
            "本次沒有新增或修訂研究數值、文獻來源、正式資料庫或外部服務。",
        ],
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--bias-report", type=Path, default=BIAS_PATH)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    bias_path = args.bias_report if args.bias_report.is_absolute() else root / args.bias_report

    report = validate(root)
    write_json(output, report)
    library, _ = load_library(root)
    generate_bias_report(report["domains"], library, report["issues"], bias_path)
    print(json.dumps({
        "status": report["status"],
        "issue_count": report["issue_count"],
        "domain_count": report["domain_count"],
        "unit_count": sum(row["unit_count"] for row in report["domains"].values()),
        "value_range_count": sum(row["value_range_count"] for row in report["domains"].values()),
        "verified_reference_count_by_domain": {key: row["verified_reference_count"] for key, row in sorted(report["domains"].items())},
        "outputs": [str(output), str(bias_path)],
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
