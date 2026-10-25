#!/usr/bin/env python3
"""Validate the bounded STR/MOB/SYN knowledge-v2 batch and write its report."""
# Retained for history; scripts/kb2_validate_all.py is the consolidated acceptance validator.


from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
DOMAINS = {
    "STR": [
        "街道階層與功能", "完整街道", "街道斷面", "街廓大小與連結度",
        "交叉口密度", "共享空間", "街道作為公共空間", "路網形態（格子、放射、有機）",
    ],
    "MOB": [
        "建成環境與旅運（3D／5D）", "步行性", "荷蘭自行車設計原則（連貫、直接、安全、舒適、吸引）",
        "自行車停車", "TOD 與節點—場所模型", "大眾運輸服務圈",
        "停車政策與最低停車標準的影響", "無車區與物流",
    ],
    "SYN": [
        "軸線／線段分析", "整合度與選擇度", "自然移動", "多中心性（MCA）",
        "角度與度量距離", "批評（Ratti）與回應", "Place Syntax", "網路分析在設計中的使用與限制",
    ],
}
SCHOOLS = {"TU Delft", "Harvard GSD", "MIT", "UCL Bartlett"}
ALLOWED_APIS = {"OpenAlex", "Crossref", "Open Library"}
EVIDENCE_LEVELS = {"ABSTRACT_REVIEW", "BIBLIOGRAPHIC_SCOPE_ONLY", "CANONICAL_CROSS_CHECK_PENDING", "CANONICAL_CROSS_CHECKED_CLAUDE_20261008"}
AUTHOR_SHARE_MAX = 0.10
SOURCE_SHARE_MAX = 0.10
MIN_UNIQUE_SOURCES = 35
MIN_VALUE_RANGE_UNITS = 12
MAX_SENTENCE_REPETITIONS = 3
OUT = ROOT / "artifacts/kb2-kb2-movement/validation.json"


def utc_now() -> str:
    return subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip()


def sentence_count(text: str) -> int:
    return len(re.findall(r"[。！？]", text))


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[。！？])", text or "") if part.strip()]


def normalize_sentence(sentence: str) -> str:
    compact = re.sub(r"\s+", "", sentence)
    compact = re.sub(r"[。！？]+$", "", compact)
    return compact.strip("「」『』\"'，、；：")


def prose_fields(unit: dict) -> list[str]:
    fields = [
        unit.get("summary_zh", ""),
        unit.get("applies_when_zh", ""),
        unit.get("not_applicable_when_zh", ""),
        unit.get("debates_zh", ""),
        *unit.get("key_points_zh", []),
        *unit.get("design_implications_zh", []),
    ]
    fields.extend(finding.get("claim_zh", "") for finding in unit.get("evidence", {}).get("findings", []))
    fields.extend(value.get("context", "") for value in unit.get("values", []))
    fields.extend(option.get("option_zh", "") for option in unit.get("design_options", []))
    fields.extend(option.get("tradeoff_zh", "") for option in unit.get("design_options", []))
    return fields


def find_repeated_sentences(units: list[dict]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for unit in units:
        for prose in prose_fields(unit):
            for sentence in sentences(prose):
                normalized = normalize_sentence(sentence)
                if normalized and re.search(r"[^，、；：。！？\s]", normalized):
                    counts[normalized] += 1
    return counts


def authors_for(source: dict) -> set[str]:
    authors = source.get("authors", [])
    if isinstance(authors, str):
        authors = [authors]
    return {str(author).strip().casefold() for author in authors if str(author).strip()}


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def main() -> int:
    schema = json.loads((ROOT / "knowledge/v2/unit.schema.json").read_text(encoding="utf-8"))
    schema_validator = Draft202012Validator(schema)
    curriculum = (ROOT / "knowledge/v2/CURRICULUM.md").read_text(encoding="utf-8")
    lib_dir = ROOT / "knowledge/v2/library"
    library = {}
    for path in sorted(lib_dir.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        library[record["id"]] = record

    report = {
        "task_id": "kb2-movement-enrich",
        "generated_at_utc": utc_now(),
        "validation": {"status": "PASS", "checks": 0, "failures": []},
        "domains": {},
        "library_records_in_v2": len(library),
    }
    failures: list[str] = []
    checks = 0

    def require(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    for domain, expected_topics in DOMAINS.items():
        unit_dir = ROOT / f"knowledge/v2/domains/{domain}/units"
        unit_paths = sorted(unit_dir.glob(f"KU-{domain}-*.json"))
        units = [json.loads(path.read_text(encoding="utf-8")) for path in unit_paths]
        by_topic: dict[str, list[dict]] = {}
        type_counts = Counter()
        topic_counts = Counter()
        author_counts = Counter()
        source_citation_counts = Counter()
        region_counts = Counter()
        tradition_counts = Counter()
        cited_ids: set[str] = set()
        citation_events = 0
        source_status_counts = Counter()
        source_verification: dict[str, dict] = {}
        claim_verification_counts = Counter()
        repeated_sentence_counts = find_repeated_sentences(units)

        require(60 <= len(units) <= 100, f"{domain}: unit count {len(units)} outside 60-100")
        require(len(expected_topics) == 8, f"{domain}: validator curriculum topic list is not 8")
        for topic in expected_topics:
            require(topic in curriculum, f"{domain}: curriculum source missing topic text: {topic}")

        for unit_path, unit in zip(unit_paths, units):
            for error in schema_validator.iter_errors(unit):
                location = "/".join(str(part) for part in error.absolute_path)
                require(False, f"{unit_path.relative_to(ROOT)} schema {location}: {error.message}")
            require(unit.get("domain") == domain, f"{unit.get('id')}: wrong domain")
            require(unit.get("id", "").startswith(f"KU-{domain}-"), f"{unit.get('id')}: id/domain mismatch")
            require(unit.get("subtopic") in expected_topics, f"{unit.get('id')}: unexpected subtopic {unit.get('subtopic')}")
            by_topic.setdefault(unit.get("subtopic"), []).append(unit)
            topic_counts[unit.get("subtopic")] += 1
            type_counts[unit.get("type")] += 1

            summary = unit.get("summary_zh", "")
            n_sentences = sentence_count(summary)
            require(3 <= n_sentences <= 8, f"{unit.get('id')}: summary sentence count {n_sentences}")
            refs = unit.get("curriculum_refs", [])
            require(bool(refs), f"{unit.get('id')}: missing curriculum_refs")
            require(all(ref.get("school") in SCHOOLS for ref in refs), f"{unit.get('id')}: curriculum ref outside approved schools")
            require(all(unit.get("subtopic", "") in ref.get("topic", "") for ref in refs),
                    f"{unit.get('id')}: curriculum refs do not name its topic")

            source_refs = unit.get("sources", [])
            ids = [ref.get("library_id") for ref in source_refs if ref.get("library_id")]
            source_records = [library.get(ident) for ident in ids]
            cited_ids.update(ids)
            source_citation_counts.update(ids)
            citation_events += len(ids)
            require(len(set(ids)) >= 2, f"{unit.get('id')}: fewer than 2 distinct cited sources")
            require(unit.get("source_count_flag") == "MULTI_SOURCE", f"{unit.get('id')}: source_count_flag is not MULTI_SOURCE")
            require(all(record is not None for record in source_records), f"{unit.get('id')}: cited library id missing from v2")
            if all(record is not None for record in source_records):
                author_sets = [authors_for(record) for record in source_records]
                require(all(author_sets), f"{unit.get('id')}: cited source has no authors")
                if len(author_sets) >= 2:
                    require(not any(author_sets[i] & author_sets[j] for i in range(len(author_sets)) for j in range(i + 1, len(author_sets))),
                            f"{unit.get('id')}: source authors are not independent")
                require(any(str(record.get("kind", "")).startswith("ACADEMIC_") for record in source_records),
                        f"{unit.get('id')}: no academic source among citations")
                for ident, record in zip(ids, source_records):
                    verification = record.get("verification", {})
                    status = verification.get("status", "NOT_FOUND")
                    source_status_counts[status] += 1
                    source_verification[ident] = verification
                    require(status == "VERIFIED", f"{unit.get('id')}: non-VERIFIED source {ident} ({status})")
                    require(verification.get("api") in ALLOWED_APIS,
                            f"{unit.get('id')}: source {ident} verification API is outside the allowlist")
                    require(bool(verification.get("api") and verification.get("query") and verification.get("matched_record_id")),
                            f"{unit.get('id')}: source {ident} lacks API/query/matched id")
                    for author in authors_for(record):
                        author_counts[author] += 1
                    for region in as_list(record.get("region")):
                        if str(region).strip():
                            region_counts[str(region).strip()] += 1
                    tradition = record.get("tradition")
                    if tradition:
                        tradition_counts[str(tradition)] += 1

            findings = unit.get("evidence", {}).get("findings", [])
            require(len(findings) >= 2, f"{unit.get('id')}: fewer than 2 evidence findings")
            for finding in findings:
                tier = finding.get("claim_verification")
                claim_verification_counts[tier] += 1
                require(tier in EVIDENCE_LEVELS, f"{unit.get('id')}: finding lacks a valid claim_verification tier")
                ident = finding.get("library_id")
                require(ident in library, f"{unit.get('id')}: finding cites unknown library id {ident}")

            if unit.get("type") == "empirical_finding":
                first = findings[0] if findings else {}
                require(first.get("claim_verification") == "ABSTRACT_REVIEW",
                        f"{unit.get('id')}: empirical claim is not ABSTRACT_REVIEW")
                require(all(first.get(key) for key in ("study_design", "context_region", "effect_or_value")),
                        f"{unit.get('id')}: empirical item missing design, region, or effect")
                require(any(word in summary for word in ("限制", "不能", "未", "無法")),
                        f"{unit.get('id')}: empirical summary omits a limitation")
            elif unit.get("type") == "value_range":
                values = unit.get("values", [])
                require(bool(values), f"{unit.get('id')}: value_range has no values")
                require(any(term in summary for term in ("不是本基地法規", "並非本基地法規", "不是任何城市的", "不是設計配額")),
                        f"{unit.get('id')}: value_range summary does not disclaim local-law status")
                for value in values:
                    require(bool(value.get("range") and value.get("unit") and value.get("context") and value.get("library_id")),
                            f"{unit.get('id')}: value_range missing region/use/source context")
                    require(any(term in value.get("context", "") for term in ("不是", "非", "不代表")),
                            f"{unit.get('id')}: value_range context lacks non-local-standard statement")

        require(set(topic_counts) == set(expected_topics), f"{domain}: topic coverage set mismatch")
        require(all(topic_counts[topic] >= 1 for topic in expected_topics), f"{domain}: one or more topics uncovered")
        coverage_path = ROOT / f"knowledge/v2/domains/{domain}/coverage.json"
        readme_path = ROOT / f"knowledge/v2/domains/{domain}/README-zh.md"
        require(coverage_path.exists(), f"{domain}: coverage.json missing")
        require(readme_path.exists(), f"{domain}: README-zh.md missing")
        if coverage_path.exists():
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage_topics = {row.get("topic"): row for row in coverage.get("topics", [])}
            require(coverage.get("domain") == domain, f"{domain}: coverage domain mismatch")
            require(coverage.get("unit_count") == len(units), f"{domain}: coverage total count mismatch")
            require(set(coverage_topics) == set(expected_topics), f"{domain}: coverage topic set mismatch")
            for topic in expected_topics:
                row = coverage_topics.get(topic, {})
                ids = {unit.get("id") for unit in by_topic.get(topic, [])}
                require(row.get("unit_count") == len(ids), f"{domain}: coverage count mismatch for {topic}")
                require(set(row.get("unit_ids", [])) == ids, f"{domain}: coverage ids mismatch for {topic}")
        if readme_path.exists():
            readme = readme_path.read_text(encoding="utf-8")
            require(len(re.findall(r"(?m)^\d+\. ", readme)) >= 10, f"{domain}: README has fewer than 10 findings")

        empirical_and_value = type_counts["empirical_finding"] + type_counts["value_range"]
        require(empirical_and_value / max(1, len(units)) >= 0.30,
                f"{domain}: empirical_finding + value_range share below 30%")
        value_range_count = type_counts["value_range"]
        require(value_range_count >= MIN_VALUE_RANGE_UNITS,
                f"{domain}: value_range unit count {value_range_count} below {MIN_VALUE_RANGE_UNITS}")
        for mandatory_type in ("critique", "typology", "design_principle", "method"):
            require(type_counts[mandatory_type] >= (5 if mandatory_type == "critique" else 1),
                    f"{domain}: required type {mandatory_type} count is too low")

        citation_count_for_author = max(author_counts.values(), default=0)
        author_share = citation_count_for_author / max(1, citation_events)
        require(author_share <= AUTHOR_SHARE_MAX,
                f"{domain}: top author share {author_share:.4f} exceeds {AUTHOR_SHARE_MAX:.2f}")
        require(len(cited_ids) >= MIN_UNIQUE_SOURCES,
                f"{domain}: unique cited sources {len(cited_ids)} below {MIN_UNIQUE_SOURCES}")
        source_shares = {
            ident: count / max(1, citation_events)
            for ident, count in source_citation_counts.items()
        }
        source_share_violations = {
            ident: share for ident, share in source_shares.items()
            if share > SOURCE_SHARE_MAX
        }
        require(not source_share_violations,
                f"{domain}: source citation share exceeds {SOURCE_SHARE_MAX:.2f}: {source_share_violations}")
        repeated_over_limit = {
            sentence: count for sentence, count in repeated_sentence_counts.items()
            if count > MAX_SENTENCE_REPETITIONS
        }
        require(not repeated_over_limit,
                f"{domain}: {len(repeated_over_limit)} sentence(s) occur more than {MAX_SENTENCE_REPETITIONS} times")
        top_authors = [
            {"author": name, "citation_count": count, "share_of_cited_works": round(count / max(1, citation_events), 4)}
            for name, count in author_counts.most_common(5)
        ]
        domain_summary = {
            "unit_count": len(units),
            "topic_counts": dict(sorted(topic_counts.items())),
            "type_distribution": dict(sorted(type_counts.items())),
            "empirical_and_value_range_count": empirical_and_value,
            "empirical_and_value_range_share": round(empirical_and_value / max(1, len(units)), 4),
            "value_range_unit_count": value_range_count,
            "unique_cited_library_records": len(cited_ids),
            "source_citation_events": citation_events,
            "source_citation_share_max": round(max(source_shares.values(), default=0), 4),
            "source_citation_share_top_5": [
                {"library_id": ident, "citation_count": count,
                 "share_of_citations": round(count / max(1, citation_events), 4)}
                for ident, count in source_citation_counts.most_common(5)
            ],
            "claim_verification_counts": dict(sorted(claim_verification_counts.items())),
            "repeated_sentence_kinds_over_3": len(repeated_over_limit),
            "repeated_sentence_occurrences_over_3": sum(repeated_over_limit.values()),
            "max_sentence_repeat": max(repeated_sentence_counts.values(), default=0),
            "repeated_sentences_over_3": [
                {"count": count, "sentence": sentence}
                for sentence, count in sorted(repeated_over_limit.items(), key=lambda item: (-item[1], item[0]))
            ],
            "verification_status_counts": dict(sorted(source_status_counts.items())),
            "verification_status_counts_unique_records": dict(sorted(Counter(
                verification.get("status", "NOT_FOUND") for verification in source_verification.values()
            ).items())),
            "unrepresented_verification_statuses": {status: 0 for status in ("VERIFIED", "AMBIGUOUS", "NOT_FOUND") if status not in source_status_counts},
            "regions_by_cited_source": dict(region_counts.most_common()),
            "traditions_by_cited_source": dict(tradition_counts.most_common()),
            "distribution_counting_note": "Region and tradition counts are citation-event counts; one cited source can carry multiple region tags, so regional totals are non-exclusive.",
            "top_5_authors": top_authors,
            "top_author_share": round(author_share, 4),
        }
        report["domains"][domain] = domain_summary

    research_log_path = ROOT / "artifacts/kb2-kb2-movement/research-log.json"
    if research_log_path.exists():
        log = json.loads(research_log_path.read_text(encoding="utf-8"))
        report["research_search_audit"] = {
            "verified_new_sources": len(log.get("verified_new_sources", [])),
            "candidate_searches_abandoned": log.get("candidate_searches_abandoned", []),
            "search_incomplete": log.get("search_incomplete", []),
            "api_failures": log.get("api_failures", []),
        }
    else:
        require(False, "research-log.json missing")

    duplicate_before_path = ROOT / "artifacts/kb2-kb2-movement/duplicate-sentence-before.json"
    require(duplicate_before_path.exists(), "duplicate-sentence-before.json missing")
    if duplicate_before_path.exists():
        before = json.loads(duplicate_before_path.read_text(encoding="utf-8"))
        comparison = {}
        for domain in DOMAINS:
            before_domain = before.get("domains", {}).get(domain, {})
            after_domain = report["domains"].get(domain, {})
            require(bool(before_domain), f"{domain}: duplicate-sentence baseline missing")
            comparison[domain] = {
                "before_unit_count": before_domain.get("unit_count"),
                "before_sentence_kinds_over_3": before_domain.get("unique_sentence_kinds_gt3"),
                "before_occurrences_over_3": before_domain.get("sentence_occurrences_gt3"),
                "before_max_sentence_repeat": before_domain.get("max_sentence_repeat"),
                "after_unit_count": after_domain.get("unit_count"),
                "after_sentence_kinds_over_3": after_domain.get("repeated_sentence_kinds_over_3"),
                "after_occurrences_over_3": after_domain.get("repeated_sentence_occurrences_over_3"),
                "after_max_sentence_repeat": after_domain.get("max_sentence_repeat"),
            }
        report["duplicate_sentence_before_after"] = comparison

    search_incomplete = report.get("research_search_audit", {}).get("search_incomplete", [])
    resolved_statuses = {
        "RESOLVED",
        "RESOLVED_WITH_ALTERNATIVE_SOURCE",
        "PARTIALLY_RESOLVED_WITH_ALTERNATIVE_SOURCE",
    }
    unresolved_searches = [
        item for item in search_incomplete
        if item.get("resolution_status") not in resolved_statuses
    ]
    report.setdefault("research_search_audit", {})["unresolved_search_count"] = len(unresolved_searches)
    incomplete_topics = sorted({item.get("topic", "unspecified") for item in unresolved_searches})
    report["validation"]["checks"] = checks
    report["validation"]["failures"] = failures
    report["validation"]["structural_status"] = "PASS" if not failures else "FAIL"
    report["validation"]["content_status"] = "INCOMPLETE" if incomplete_topics else "PASS"
    report["validation"]["incomplete_content_gaps"] = [
        {"topic": topic,
         "search_attempts": [item for item in search_incomplete if item.get("topic", "unspecified") == topic]}
        for topic in incomplete_topics
    ]
    report["validation"]["status"] = "FAIL" if failures else ("INCOMPLETE" if incomplete_topics else "PASS")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["validation"]["status"],
                      "structural_status": report["validation"]["structural_status"],
                      "content_status": report["validation"]["content_status"],
                      "checks": checks,
                      "failure_count": len(failures), "output": str(OUT),
                      "domain_counts": {d: v["unit_count"] for d, v in report["domains"].items()},
                      "max_author_share": {d: v["top_author_share"] for d, v in report["domains"].items()}},
                     ensure_ascii=False, indent=2))
    if failures:
        for item in failures[:80]:
            print("FAIL:", item, file=sys.stderr)
        return 1
    if incomplete_topics:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
