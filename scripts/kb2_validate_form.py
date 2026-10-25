#!/usr/bin/env python3
"""Validate the four bounded KB v2 domain batches against the v2 unit schema."""
# Retained for history; scripts/kb2_validate_all.py is the consolidated acceptance validator.


from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ("MOR", "LUP", "REG", "HOU")
SCHOOLS = ("TU Delft", "Harvard GSD", "MIT", "UCL Bartlett")
REVIEW_LEVELS = {"ABSTRACT_REVIEW", "BIBLIOGRAPHIC_SCOPE_ONLY"}
CANONICAL_PENDING = "CANONICAL_CROSS_CHECK_PENDING"
CLAIM_VERIFICATION_LEVELS = {CANONICAL_PENDING, "ABSTRACT_REVIEW", "BIBLIOGRAPHIC_SCOPE_ONLY"}
EXPECTED_SUBTOPICS = {
    "MOR": [
        "地塊、街廓與建築類型",
        "Conzen 城鎮平面分析",
        "Muratori／Caniggia 類型過程",
        "Spacematrix：FSI、GSI、OSR、L",
        "密度與形態的關係",
        "周邊式、合院、板樓、點式、連棟與基座塔樓",
        "細粒度與大尺度開發",
        "形態指標與類型比較方法",
    ],
    "LUP": [
        "土地使用分類",
        "相容與衝突：工業與住宅介面",
        "混合使用尺度：建築、街廓、街區",
        "生產性城市與 maker 經濟",
        "用途配比與日夜活動",
        "15 分鐘城市與可及性",
        "商業與零售區位",
    ],
    "REG": [
        "容積率、建蔽率、高度與斜線",
        "歐氏分區與形式準則",
        "德國 BauNVO 制度輪廓",
        "荷蘭 Omgevingswet 與 omgevingsplan",
        "英國裁量式規劃",
        "日本用途地域與地方條例",
        "新加坡用途與容積治理",
        "開發獎勵與容積移轉",
        "制度比較與數值適用性",
    ],
    "HOU": [
        "住宅類型",
        "荷蘭 woningcorporaties 社會住宅模式",
        "混合產權",
        "可負擔性",
        "鄰里單元與批評",
        "居住密度與生活品質",
        "老化與多世代居住",
    ],
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _author_key(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z]+", folded.lower())
    return words[-1] if words else name.lower()


def _sentences(text: str) -> int:
    return len([part for part in re.split(r"(?<=[。！？])\s*", text.strip()) if part.strip()])


def _normalized_sentence(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text)
    folded = re.sub(r"\s+", "", folded)
    return folded.strip("。.!！？?；;：:")


def _unit_sentences(unit: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    summary = unit.get("summary_zh")
    if isinstance(summary, str):
        fields.append(summary)
    implications = unit.get("design_implications_zh") or []
    if isinstance(implications, list):
        fields.extend(text for text in implications if isinstance(text, str))
    debates = unit.get("debates_zh")
    if isinstance(debates, str):
        fields.append(debates)
    sentences: list[str] = []
    for field in fields:
        for part in re.split(r"(?<=[。！？])\s*", field.strip()):
            normalized = _normalized_sentence(part)
            if len(normalized) >= 12:
                sentences.append(normalized)
    return sentences


def _utc_now_from_system() -> str:
    return subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip()


def validate(output: Path, screening_path: Path | None = None, baseline_path: Path | None = None) -> tuple[dict[str, Any], int]:
    schema = _read_json(ROOT / "knowledge/v2/unit.schema.json")
    schema_validator = Draft202012Validator(schema)
    library_dir = ROOT / "knowledge/v2/library"
    v2_library: dict[str, dict[str, Any]] = {
        p.stem: _read_json(p) for p in sorted(library_dir.glob("*.json"))
    }
    legacy_library: dict[str, dict[str, Any]] = {
        p.stem: _read_json(p) for p in sorted((ROOT / "knowledge/library").glob("*.json"))
    }
    library = dict(legacy_library)
    library.update(v2_library)
    v2_library_ids = set(v2_library)
    legacy_library_ids = set(legacy_library)
    errors: list[str] = []
    domain_stats: dict[str, Any] = {}
    used_library: set[str] = set()
    total_units = 0

    for domain in DOMAINS:
        domain_dir = ROOT / "knowledge/v2/domains" / domain
        unit_paths = sorted((domain_dir / "units").glob(f"KU-{domain}-*.json"))
        units = [_read_json(p) for p in unit_paths]
        total_units += len(units)
        if len(units) < 60:
            errors.append(f"{domain}: unit count {len(units)} below minimum 60")

        type_counts: Counter[str] = Counter()
        topic_units: dict[str, list[str]] = defaultdict(list)
        author_occurrences: Counter[str] = Counter()
        source_occurrences: Counter[str] = Counter()
        source_refs = 0
        sentence_occurrences: Counter[str] = Counter()
        claim_verification_counts: Counter[str] = Counter()
        value_range_verification_counts: Counter[str] = Counter()
        school_counts: Counter[str] = Counter()
        region_counts: Counter[str] = Counter()
        tradition_counts: Counter[str] = Counter()
        used_here: set[str] = set()

        for path, unit in zip(unit_paths, units):
            label = f"{domain}/{path.name}"
            for issue in schema_validator.iter_errors(unit):
                errors.append(f"{label}: schema {'.'.join(str(x) for x in issue.absolute_path)}: {issue.message}")

            if unit.get("domain") != domain:
                errors.append(f"{label}: domain field does not match folder")
            if unit.get("subtopic") not in EXPECTED_SUBTOPICS[domain]:
                errors.append(f"{label}: unexpected subtopic {unit.get('subtopic')!r}")
            else:
                topic_units[unit["subtopic"]].append(unit.get("id", path.stem))

            summary = unit.get("summary_zh", "")
            sentence_count = _sentences(summary)
            if sentence_count < 3 or sentence_count > 8:
                errors.append(f"{label}: summary_zh has {sentence_count} sentences; expected 3..8")
            if len(summary) < 80:
                errors.append(f"{label}: summary_zh is shorter than 80 characters")
            summary_templates = (
                "研究設計：", "研究設計:", "地區：", "地區:", "適用於", "適用情境是",
                "分析邊界是", "用於與", "另一項來源提供補充視角", "本單元記錄",
                "對設計的用途是", "以同一範圍、模式和參數重算",
                "比較時仍須記錄資料範圍、時間與使用條件",
            )
            for marker in summary_templates:
                if marker in summary:
                    errors.append(f"{label}: summary_zh contains template marker {marker!r}")
            for implication in unit.get("design_implications_zh", []) or []:
                if "的設計比較中，先把" in implication or "再檢查：" in implication:
                    errors.append(f"{label}: design_implications_zh contains a title-wrapper template")
            if "的主要爭點在於：" in (unit.get("debates_zh") or ""):
                errors.append(f"{label}: debates_zh contains a title-wrapper template")
            claim_verification = unit.get("claim_verification")
            if claim_verification not in (None, *CLAIM_VERIFICATION_LEVELS):
                errors.append(f"{label}: unsupported claim_verification value {claim_verification!r}")
            claim_verification_counts[claim_verification or "NOT_SET"] += 1
            sentence_occurrences.update(_unit_sentences(unit))

            if unit.get("type") == "empirical_finding":
                finding = (unit.get("evidence", {}).get("findings") or [{}])[0]
                for field in ("study_design", "context_region", "effect_or_value"):
                    if finding.get(field) in (None, ""):
                        errors.append(f"{label}: empirical finding lacks {field}")
                if not unit.get("not_applicable_when_zh"):
                    errors.append(f"{label}: empirical finding lacks a stated limitation")

            if unit.get("type") == "value_range":
                values = unit.get("values") or []
                if not values:
                    errors.append(f"{label}: value_range has no values")
                if unit.get("claim_verification") not in CLAIM_VERIFICATION_LEVELS:
                    errors.append(f"{label}: value_range must state its claim verification basis")
                value_range_verification_counts[unit.get("claim_verification") or "NOT_SET"] += 1
                for value in values:
                    context = value.get("context", "")
                    if "本基地法規" not in context:
                        errors.append(f"{label}: value_range context must say it is not this site's law")
                    if "用途：" not in context or "書目" not in context and "來源：" not in context and "書目：" not in context:
                        errors.append(f"{label}: value_range context must state use and source")
                    cited_ids = {ref.get("library_id") for ref in (unit.get("sources") or [])}
                    if value.get("library_id") not in cited_ids:
                        errors.append(f"{label}: value_range citation {value.get('library_id')!r} is not in sources")

            refs = unit.get("sources") or []
            source_ids = [ref.get("library_id") for ref in refs]
            source_occurrences.update(source_ids)
            if len(set(source_ids)) < 2 and unit.get("source_count_flag") != "SINGLE_SOURCE":
                errors.append(f"{label}: multi-source unit has fewer than two distinct source IDs")
            if len(set(source_ids)) >= 2 and unit.get("source_count_flag") != "MULTI_SOURCE":
                errors.append(f"{label}: source_count_flag does not match cited source count")
            source_refs += len(source_ids)
            resolved_authors: list[set[str]] = []
            academic_sources = 0
            for source_id in source_ids:
                record = library.get(source_id or "")
                if record is None:
                    errors.append(f"{label}: unresolved library ID {source_id!r}")
                    continue
                used_library.add(source_id)
                used_here.add(source_id)
                verification = record.get("verification", {})
                if verification.get("status") != "VERIFIED":
                    errors.append(f"{label}: source {source_id} is not VERIFIED")
                if not verification.get("matched_record_id") or not verification.get("query") or not verification.get("checked_at_utc"):
                    errors.append(f"{label}: source {source_id} lacks matched API ID, query, or check time")
                assessment_bases = {claim.get("assessment_basis") for claim in record.get("claims", [])}
                if not (assessment_bases & REVIEW_LEVELS):
                    errors.append(f"{label}: source {source_id} lacks a valid claim review level in its library record")
                names = {_author_key(a) for a in record.get("authors", []) if a}
                if not names:
                    errors.append(f"{label}: source {source_id} has no author metadata")
                resolved_authors.append(names)
                for name in names:
                    author_occurrences[name] += 1
                kind = str(record.get("kind", "")).upper()
                if any(token in kind for token in ("ACADEMIC", "JOURNAL", "PAPER", "THESIS", "ARTICLE")):
                    academic_sources += 1
            if academic_sources < 1:
                errors.append(f"{label}: at least one cited source must be identified as academic")
            if len(resolved_authors) >= 2 and resolved_authors[0] & resolved_authors[1]:
                errors.append(f"{label}: cited sources share author surname(s): {sorted(resolved_authors[0] & resolved_authors[1])}")
            if unit.get("type") == "empirical_finding":
                primary_id = (unit.get("evidence", {}).get("findings") or [{}])[0].get("library_id")
                primary_record = library.get(primary_id or "", {})
                primary_bases = {claim.get("assessment_basis") for claim in primary_record.get("claims", [])}
                if "ABSTRACT_REVIEW" not in primary_bases:
                    errors.append(f"{label}: empirical finding primary source is not marked ABSTRACT_REVIEW in its library record")

            type_counts[unit.get("type", "UNKNOWN")] += 1
            schools = {ref.get("school") for ref in unit.get("curriculum_refs", [])}
            for school in schools:
                school_counts[str(school)] += 1
            if schools != set(SCHOOLS):
                errors.append(f"{label}: curriculum_refs must map all four approved schools")
            for region in filter(None, (unit.get("region") or "").split("；")):
                region_counts[region] += 1
            for tradition in filter(None, (unit.get("tradition") or "").split("；")):
                tradition_counts[tradition] += 1

        empirical_share = (type_counts["empirical_finding"] + type_counts["value_range"]) / max(len(units), 1)
        if empirical_share < 0.30:
            errors.append(f"{domain}: empirical_finding + value_range share {empirical_share:.3f} below 0.30")
        if type_counts["critique"] < 5:
            errors.append(f"{domain}: only {type_counts['critique']} critique units")
        if type_counts["value_range"] < 15:
            errors.append(f"{domain}: only {type_counts['value_range']} value_range units; expected at least 15")
        if len(used_here) < 35:
            errors.append(f"{domain}: only {len(used_here)} distinct verified sources; expected at least 35")
        repeated_groups = {sentence: count for sentence, count in sentence_occurrences.items() if count > 1}
        over_three = {sentence: count for sentence, count in sentence_occurrences.items() if count > 3}
        if over_three:
            for sentence, count in sorted(over_three.items(), key=lambda item: (-item[1], item[0])):
                errors.append(f"{domain}: sentence repeated {count} times (>3): {sentence}")
        for required_type in ("typology", "design_principle", "method"):
            if not type_counts[required_type]:
                errors.append(f"{domain}: required type {required_type} missing")

        missing_topics = sorted(set(EXPECTED_SUBTOPICS[domain]) - set(topic_units))
        if missing_topics:
            errors.append(f"{domain}: curriculum topics without units: {missing_topics}")

        author_share = {
            author: count / max(source_refs, 1)
            for author, count in author_occurrences.items()
        }
        overrepresented = {a: round(s, 4) for a, s in author_share.items() if s > 0.10 + 1e-9}
        if overrepresented:
            errors.append(f"{domain}: author share over 10% of source citations: {overrepresented}")
        source_share = {
            source_id: count / max(source_refs, 1)
            for source_id, count in source_occurrences.items()
        }
        overused_sources = {
            source_id: round(share, 4)
            for source_id, share in source_share.items()
            if share > 0.10 + 1e-9
        }
        if overused_sources:
            errors.append(f"{domain}: source exceeds 10% of domain source citations: {overused_sources}")

        coverage_path = domain_dir / "coverage.json"
        if not coverage_path.exists():
            errors.append(f"{domain}: missing coverage.json")
        else:
            coverage = _read_json(coverage_path)
            coverage_rows = {row.get("subtopic"): row for row in coverage.get("topics", [])}
            if set(coverage_rows) != set(EXPECTED_SUBTOPICS[domain]):
                errors.append(f"{domain}: coverage topics differ from curriculum")
            for topic, expected_ids in topic_units.items():
                row = coverage_rows.get(topic, {})
                if row.get("unit_count") != len(expected_ids) or sorted(row.get("unit_ids", [])) != sorted(expected_ids):
                    errors.append(f"{domain}: coverage mismatch for {topic}")

        domain_stats[domain] = {
            "unit_count": len(units),
            "type_distribution": dict(sorted(type_counts.items())),
            "empirical_and_value_range_share": round(empirical_share, 4),
            "library_documents_used": len(used_here),
            "v2_library_documents_used": len(used_here & v2_library_ids),
            "reused_v0_2_documents": len(used_here & (legacy_library_ids - v2_library_ids)),
            "reverified_v0_2_records_in_v2": len(used_here & legacy_library_ids & v2_library_ids),
            "new_v2_library_documents": len(used_here & (v2_library_ids - legacy_library_ids)),
            "source_citation_entries": source_refs,
            "value_range_unit_count": type_counts["value_range"],
            "claim_verification_distribution": dict(sorted(claim_verification_counts.items())),
            "value_range_claim_verification_distribution": dict(sorted(value_range_verification_counts.items())) ,
            "distinct_verified_sources": len(used_here),
            "sentence_repetition": {
                "duplicate_sentence_groups": len(repeated_groups),
                "over_3_sentence_groups": len(over_three),
                "duplicate_sentence_excess_occurrences": sum(count - 1 for count in repeated_groups.values()),
                "most_repeated_sentences": [
                    {"sentence": sentence, "count": count}
                    for sentence, count in sentence_occurrences.most_common(10)
                    if count > 1
                ],
            },
            "verification_distribution": dict(sorted(Counter(library[s].get("verification", {}).get("status", "MISSING") for s in used_here).items())),
            "region_distribution": dict(sorted(region_counts.items())),
            "tradition_distribution": dict(sorted(tradition_counts.items())),
            "curriculum_school_unit_counts": {school: school_counts.get(school, 0) for school in SCHOOLS},
            "top_5_authors": [
                {"author_surname": author, "citations": count, "share_of_source_citations": round(author_share[author], 4)}
                for author, count in author_occurrences.most_common(5)
            ],
            "top_5_sources": [
                {"library_id": source_id, "citations": count, "share_of_source_citations": round(source_share[source_id], 4)}
                for source_id, count in source_occurrences.most_common(5)
            ],
            "sources_over_10_percent_of_source_citations": overused_sources,
        }

    used_records = [library[s] for s in sorted(used_library) if s in library]
    verification_distribution = dict(sorted(Counter(r.get("verification", {}).get("status", "MISSING") for r in used_records).items()))
    screening = _read_json(screening_path) if screening_path and screening_path.exists() else None
    bibliography_status_distribution = Counter(verification_distribution)
    if screening:
        bibliography_status_distribution.update(
            row.get("status", "MISSING") for row in screening.get("screened_out_or_unresolved", [])
        )
    before_after = None
    if baseline_path and baseline_path.exists():
        baseline = _read_json(baseline_path)
        before_after = {}
        for domain, current in domain_stats.items():
            before = baseline.get("domains", {}).get(domain, {})
            before_after[domain] = {
                "before": {
                    key: before.get(key)
                    for key in (
                        "unit_count", "type_distribution", "value_range_count",
                        "distinct_library_ids", "duplicate_sentence_groups",
                        "over_3_sentence_groups", "duplicate_sentence_excess_occurrences",
                    )
                },
                "after": {
                    "unit_count": current.get("unit_count"),
                    "type_distribution": current.get("type_distribution"),
                    "value_range_count": current.get("value_range_unit_count"),
                    "distinct_library_ids": current.get("distinct_verified_sources"),
                    "duplicate_sentence_groups": current["sentence_repetition"]["duplicate_sentence_groups"],
                    "over_3_sentence_groups": current["sentence_repetition"]["over_3_sentence_groups"],
                    "duplicate_sentence_excess_occurrences": current["sentence_repetition"]["duplicate_sentence_excess_occurrences"],
                },
            }
    report = {
        "validator": "scripts/kb2_validate.py",
        "result": "PASS" if not errors else "FAIL",
        "validated_at_utc": _utc_now_from_system(),
        "schema": "knowledge/v2/unit.schema.json (JSON Schema Draft 2020-12)",
        "scope": list(DOMAINS),
        "total_units": total_units,
        "library_documents_used": len(used_records),
        "v2_library_documents_used": len(used_library & v2_library_ids),
        "reused_v0_2_documents": len(used_library & (legacy_library_ids - v2_library_ids)),
        "reverified_v0_2_records_in_v2": len(used_library & legacy_library_ids & v2_library_ids),
        "new_v2_library_documents": len(used_library & (v2_library_ids - legacy_library_ids)),
        "verification_distribution": verification_distribution,
        "bibliography_status_distribution": dict(sorted(bibliography_status_distribution.items())),
        "domain_statistics": domain_stats,
        "before_after_comparison": before_after,
        "bibliography_screening": screening,
        "errors": errors,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report, len(errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/kb2-kb2-form/validation.json")
    parser.add_argument("--screening", type=Path, default=ROOT / "artifacts/kb2-kb2-form/bibliography-screening.json")
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    report, error_count = validate(args.output, args.screening, args.baseline)
    print(json.dumps({"result": report["result"], "total_units": report["total_units"], "library_documents_used": report["library_documents_used"], "errors": error_count, "output": str(args.output)}, ensure_ascii=False))
    if error_count:
        for error in report["errors"][:100]:
            print(error, file=sys.stderr)
    return 1 if error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
