#!/usr/bin/env python3
"""Validate the authored knowledge-v2 units for the assigned public/green/ecology slice."""
# Retained for history; scripts/kb2_validate_all.py is the consolidated acceptance validator.


from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOPICS: dict[str, list[str]] = {
    "PUB": [
        "廣場尺度與圍合",
        "邊緣效應",
        "座位與停留",
        "活躍立面",
        "安全：CPTED 與批評",
        "公共空間私有化與管理",
        "包容、性別與可用性",
        "夜間經濟",
    ],
    "GRN": [
        "公園類型與階層",
        "綠地可及性",
        "開放空間系統與綠色網絡",
        "遊戲與兒童",
        "公園使用與維護",
        "健康效益實證",
        "綠地仕紳化",
    ],
    "ECO": [
        "地景生態學：嵌塊、廊道、基質",
        "生態網絡與連結度",
        "都市森林與樹冠",
        "物種友善設計",
        "自然為本的解決方案",
        "生態服務",
    ],
}
SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?])")
NUMBER = re.compile(r"(?:\d+(?:\.\d+)?|[一二三四五六七八九十百千萬]+)")


def utc_now() -> str:
    return subprocess.check_output(
        ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True
    ).strip()


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_library() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    entries: dict[str, dict[str, Any]] = {}
    locations: dict[str, str] = {}
    for folder in (ROOT / "knowledge/v2/library", ROOT / "knowledge/library"):
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                item = read_json(path)
                ident = item.get("id")
                if not ident:
                    continue
                if ident in entries:
                    old = entries[ident]
                    same = (
                        old.get("title") == item.get("title")
                        and old.get("year") == item.get("year")
                        and old.get("doi") == item.get("doi")
                    )
                    if not same:
                        entries[ident] = {"_duplicate_conflict": True, "id": ident}
                        locations[ident] += f"; {path.relative_to(ROOT)}"
                    continue
                entries[ident] = item
                locations[ident] = str(path.relative_to(ROOT))
            except Exception:
                continue
    return entries, locations


def source_status(item: dict[str, Any]) -> str:
    return str((item.get("verification") or {}).get("status", "UNKNOWN"))


def primary_author(item: dict[str, Any]) -> str:
    authors = item.get("authors") or []
    if not authors:
        return "UNKNOWN"
    name = str(authors[0]).strip()
    return re.sub(r"\s+", " ", name)


def split_sentences(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return [re.sub(r"\s+", " ", part).strip() for part in SENTENCE_SPLIT.split(value) if part.strip()]


def collect_unit_sentences(unit: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in (
        "summary_zh",
        "design_implications_zh",
        "applies_when_zh",
        "not_applicable_when_zh",
        "debates_zh",
        "key_points_zh",
    ):
        raw = unit.get(field)
        if isinstance(raw, str):
            values.extend(split_sentences(raw))
        elif isinstance(raw, list):
            for part in raw:
                values.extend(split_sentences(part))
    for option in unit.get("design_options", []) or []:
        if isinstance(option, dict):
            values.extend(split_sentences(option.get("option_zh")))
            values.extend(split_sentences(option.get("tradeoff_zh")))
    return [re.sub(r"[\s，,。；;：:]+$", "", value) for value in values if value.strip()]


def validate_domain(
    code: str,
    schema_validator: Draft202012Validator,
    library: dict[str, dict[str, Any]],
    library_locations: dict[str, str],
) -> dict[str, Any]:
    domain_dir = ROOT / "knowledge/v2/domains" / code
    unit_dir = domain_dir / "units"
    failures: list[str] = []
    warnings: list[str] = []
    units: list[dict[str, Any]] = []
    for path in sorted(unit_dir.glob(f"KU-{code}-*.json")) if unit_dir.exists() else []:
        try:
            item = read_json(path)
            item["_path"] = path
            units.append(item)
        except Exception as exc:
            failures.append(f"JSON parse failed: {path.relative_to(ROOT)}: {exc}")

    if not 60 <= len(units) <= 100:
        failures.append(f"unit count {len(units)} is outside required 60..100")

    schema_errors: list[dict[str, str]] = []
    for unit in units:
        path = unit.pop("_path")
        for error in schema_validator.iter_errors(unit):
            schema_errors.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "json_path": "/".join(str(x) for x in error.absolute_path),
                    "message": error.message,
                }
            )
        unit["_path"] = path
    if schema_errors:
        failures.append(f"{len(schema_errors)} JSON Schema error(s)")

    ids = [unit.get("id") for unit in units]
    duplicate_ids = sorted(ident for ident, count in Counter(ids).items() if ident and count > 1)
    if duplicate_ids:
        failures.append(f"duplicate unit ids: {duplicate_ids}")

    type_counts = Counter(str(unit.get("type", "UNKNOWN")) for unit in units)
    min_type_floor = max(1, (len(units) * 30 + 99) // 100)
    if type_counts["empirical_finding"] + type_counts["value_range"] < min_type_floor:
        failures.append("empirical_finding + value_range is below 30%")
    if type_counts["value_range"] < 12:
        failures.append(f"value_range count {type_counts['value_range']} is below 12")
    if type_counts["critique"] < 5:
        failures.append(f"critique count {type_counts['critique']} is below 5")
    for required_type in ("typology", "design_principle", "method"):
        if type_counts[required_type] < 1:
            failures.append(f"required type missing: {required_type}")

    topic_counts = Counter(str(unit.get("subtopic", "")) for unit in units)
    expected_topics = EXPECTED_TOPICS[code]
    missing_topics = [topic for topic in expected_topics if topic_counts[topic] == 0]
    unexpected_topics = [topic for topic in topic_counts if topic not in expected_topics]
    if missing_topics:
        failures.append(f"missing curriculum topics: {missing_topics}")
    if unexpected_topics:
        failures.append(f"unit subtopics absent from curriculum map: {unexpected_topics}")

    coverage_path = domain_dir / "coverage.json"
    coverage_error = None
    coverage_ids: dict[str, list[str]] = {}
    if not coverage_path.exists():
        failures.append("coverage.json missing")
    else:
        try:
            coverage = read_json(coverage_path)
            coverage_ids = coverage.get("topic_to_units", {})
            coverage_counts = coverage.get("topic_counts", {})
            by_topic: dict[str, list[str]] = defaultdict(list)
            for unit in units:
                by_topic[str(unit.get("subtopic", ""))].append(str(unit.get("id", "")))
            for topic in expected_topics:
                actual = sorted(by_topic.get(topic, []))
                declared = sorted(coverage_ids.get(topic, []))
                if actual != declared:
                    coverage_error = f"coverage id mismatch for {topic}"
                    break
                if coverage_counts.get(topic) != len(actual):
                    coverage_error = f"coverage count mismatch for {topic}"
                    break
            if set(coverage_ids) != set(expected_topics):
                coverage_error = "coverage topics differ from curriculum topics"
            if coverage_error:
                failures.append(coverage_error)
        except Exception as exc:
            failures.append(f"coverage.json parse error: {exc}")

    used_ids: set[str] = set()
    citation_authors: Counter[str] = Counter()
    all_author_citations: Counter[str] = Counter()
    unit_reference_errors: list[str] = []
    empirical_errors: list[str] = []
    value_errors: list[str] = []
    status_counts: Counter[str] = Counter()
    claim_verification_counts: Counter[str] = Counter()
    region_counts: Counter[str] = Counter()
    tradition_counts: Counter[str] = Counter()
    sentence_counts: Counter[str] = Counter()
    for unit in units:
        uid = str(unit.get("id", "UNKNOWN"))
        summary = unit.get("summary_zh", "")
        sentence_count = len(split_sentences(summary))
        if not 3 <= sentence_count <= 8:
            failures.append(f"{uid}: summary sentence count {sentence_count} is outside 3..8")

        refs = unit.get("sources") or []
        ref_ids = list(dict.fromkeys(str(ref.get("library_id", "")) for ref in refs if ref.get("library_id")))
        if len(ref_ids) < 2:
            unit_reference_errors.append(f"{uid}: fewer than 2 distinct sources")
        authors_for_unit: set[str] = set()
        academic_found = False
        for ident in ref_ids:
            used_ids.add(ident)
            item = library.get(ident)
            if item is None:
                unit_reference_errors.append(f"{uid}: missing library id {ident}")
                continue
            status = source_status(item)
            status_counts[status] += 1
            if status != "VERIFIED":
                unit_reference_errors.append(f"{uid}: source {ident} status is {status}")
            if item.get("_duplicate_conflict"):
                unit_reference_errors.append(f"{uid}: conflicting duplicate library id {ident}")
            authors = [re.sub(r"\s+", " ", str(value).strip()) for value in (item.get("authors") or []) if str(value).strip()]
            author = authors[0] if authors else "UNKNOWN"
            authors_for_unit.update(authors or [author])
            citation_authors[author] += 1
            for cited_author in set(authors or [author]):
                all_author_citations[cited_author] += 1
            kinds = str(item.get("kind", ""))
            academic_found |= kinds.startswith("ACADEMIC_")
            region = item.get("region") or []
            if isinstance(region, str):
                region = [region]
            for label in region:
                region_counts[str(label)] += 1
            tradition = item.get("tradition")
            if tradition:
                tradition_counts[str(tradition)] += 1
        if len(authors_for_unit) < 2:
            unit_reference_errors.append(f"{uid}: references do not have 2 distinct lead authors")
        if not academic_found:
            unit_reference_errors.append(f"{uid}: no academic source")
        if unit.get("source_count_flag") != ("MULTI_SOURCE" if len(ref_ids) >= 2 else "SINGLE_SOURCE"):
            unit_reference_errors.append(f"{uid}: source_count_flag does not match citations")

        for finding in (unit.get("evidence") or {}).get("findings", []) or []:
            ident = str(finding.get("library_id", ""))
            used_ids.add(ident)
            if ident not in library:
                unit_reference_errors.append(f"{uid}: evidence refers to missing library id {ident}")
            verification = finding.get("claim_verification")
            if verification in ("ABSTRACT_REVIEW", "BIBLIOGRAPHIC_SCOPE_ONLY", "CANONICAL_CROSS_CHECK_PENDING"):
                claim_verification_counts[verification] += 1
            if verification not in ("ABSTRACT_REVIEW", "BIBLIOGRAPHIC_SCOPE_ONLY", "CANONICAL_CROSS_CHECK_PENDING", "CANONICAL_CROSS_CHECKED_CLAUDE_20261008"):
                unit_reference_errors.append(f"{uid}: invalid claim_verification for {ident}")
            if unit.get("type") == "empirical_finding":
                needed = ("study_design", "context_region", "effect_or_value", "limitations_zh")
                missing = [key for key in needed if not nonempty(finding.get(key))]
                if missing:
                    empirical_errors.append(f"{uid}/{ident}: missing empirical fields {missing}")

        if unit.get("type") == "empirical_finding" and not (unit.get("evidence") or {}).get("findings"):
            empirical_errors.append(f"{uid}: no evidence findings")

        if unit.get("type") == "value_range":
            values = unit.get("values") or []
            if not values:
                value_errors.append(f"{uid}: value_range has no values")
            for value in values:
                if not NUMBER.search(str(value.get("range", ""))):
                    value_errors.append(f"{uid}: range has no numeric value")
                context = str(value.get("context", ""))
                if "非本基地法規" not in context:
                    value_errors.append(f"{uid}: value context omits 非本基地法規")
                if not nonempty(context) or not nonempty(value.get("unit")) or not nonempty(value.get("name")):
                    value_errors.append(f"{uid}: value context/name/unit incomplete")
                ident = str(value.get("library_id", ""))
                used_ids.add(ident)
                if ident not in library:
                    value_errors.append(f"{uid}: value uses missing library id {ident}")

        for sentence in collect_unit_sentences(unit):
            sentence_counts[sentence] += 1

    if unit_reference_errors:
        failures.extend(unit_reference_errors[:40])
        if len(unit_reference_errors) > 40:
            failures.append(f"and {len(unit_reference_errors) - 40} more reference error(s)")
    if empirical_errors:
        failures.extend(empirical_errors[:40])
        if len(empirical_errors) > 40:
            failures.append(f"and {len(empirical_errors) - 40} more empirical error(s)")
    if value_errors:
        failures.extend(value_errors[:40])
        if len(value_errors) > 40:
            failures.append(f"and {len(value_errors) - 40} more value-range error(s)")

    repeats = [{"sentence": text, "count": count} for text, count in sentence_counts.items() if count > 3]
    if repeats:
        failures.append(f"{len(repeats)} sentence(s) occur more than 3 times")

    unverified_ids = []
    bibliography_counts: Counter[str] = Counter({"VERIFIED": 0, "AMBIGUOUS": 0, "NOT_FOUND": 0})
    for ident in sorted(used_ids):
        item = library.get(ident)
        if item is None:
            continue
        state = source_status(item)
        bibliography_counts[state] += 1
        if state != "VERIFIED":
            unverified_ids.append({"id": ident, "status": state, "path": library_locations.get(ident)})
    if len(used_ids) < 35:
        failures.append(f"distinct cited bibliographies {len(used_ids)} is below 35")
    if unverified_ids:
        failures.append(f"{len(unverified_ids)} cited bibliography record(s) are not VERIFIED")

    total_citations = sum(citation_authors.values())
    top_authors = [
        {
            "author": author,
            "citation_uses": count,
            "share": round(count / total_citations, 4) if total_citations else 0,
        }
        for author, count in citation_authors.most_common(5)
    ]
    if total_citations and top_authors and top_authors[0]["share"] > 0.10:
        failures.append(f"lead author share {top_authors[0]['share']:.1%} exceeds 10%")
    all_author_top_5 = [
        {
            "author": author,
            "reference_uses": count,
            "share_of_source_citations": round(count / total_citations, 4) if total_citations else 0,
        }
        for author, count in all_author_citations.most_common(5)
    ]
    if total_citations and all_author_top_5 and all_author_top_5[0]["share_of_source_citations"] > 0.10:
        failures.append(f"author reference-use share {all_author_top_5[0]['share_of_source_citations']:.1%} exceeds 10%")

    regions = sorted(region_counts)
    has_nonwestern = any(
        term in " ".join(regions).lower()
        for term in ("asia", "japan", "singapore", "china", "africa", "nigeria", "latin", "brazil", "global south", "colombia", "australia", "澳洲", "日本", "東亞", "哥倫比亞", "非洲", "全球南方", "巴西", "中國", "新加坡")
    )
    if not has_nonwestern:
        failures.append("cited bibliography has no region outside North America and Western Europe")
    if len(tradition_counts) < 3:
        failures.append(f"only {len(tradition_counts)} traditions recorded; need at least 3 for diversity review")

    return {
        "status": "PASS" if not failures else "INCOMPLETE",
        "unit_count": len(units),
        "type_distribution": dict(sorted(type_counts.items())),
        "topic_counts": dict(sorted(topic_counts.items())),
        "missing_topics": missing_topics,
        "unexpected_topics": unexpected_topics,
        "distinct_library_records_used": len(used_ids),
        "bibliography_verification_counts": dict(sorted(bibliography_counts.items())),
        "claim_verification_counts": dict(sorted(claim_verification_counts.items())),
        "reference_status_uses": dict(sorted(status_counts.items())),
        "lead_author_citation_uses": total_citations,
        "top_5_authors": top_authors,
        "all_author_reference_uses": sum(all_author_citations.values()),
        "all_author_top_5": all_author_top_5,
        "region_distribution": dict(sorted(region_counts.items())),
        "tradition_distribution": dict(sorted(tradition_counts.items())),
        "schema_error_count": len(schema_errors),
        "schema_errors": schema_errors[:50],
        "repeated_sentence_count_over_3": len(repeats),
        "repeated_sentences": repeats[:30],
        "unverified_cited_records": unverified_ids,
        "failures": failures,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domains", default="PUB,GRN,ECO")
    parser.add_argument("--output", default="artifacts/kb2-kb2-public/validation.json")
    args = parser.parse_args()
    domains = [value.strip().upper() for value in args.domains.split(",") if value.strip()]
    unknown = [code for code in domains if code not in EXPECTED_TOPICS]
    if unknown:
        raise SystemExit(f"unsupported domain code(s): {unknown}")

    schema_path = ROOT / "knowledge/v2/unit.schema.json"
    schema = read_json(schema_path)
    Draft202012Validator.check_schema(schema)
    schema_validator = Draft202012Validator(schema)
    library, library_locations = load_library()
    results = {
        code: validate_domain(code, schema_validator, library, library_locations)
        for code in domains
    }
    failures = [
        f"{code}: {message}"
        for code, domain in results.items()
        for message in domain["failures"]
    ]
    report = {
        "generated_at_utc": utc_now(),
        "validator": "scripts/kb2_validate.py",
        "schema": "knowledge/v2/unit.schema.json",
        "domains": results,
        "status": "PASS" if not failures else "INCOMPLETE",
        "failure_count": len(failures),
        "failures": failures,
    }
    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
