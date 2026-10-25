#!/usr/bin/env python3
"""Validate the KB2 THY/MET/SOC deliverable and write its evidence report."""
# Retained for history; scripts/kb2_validate_all.py is the consolidated acceptance validator.


from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # Fail closed: schema validation is a required gate.
    raise SystemExit(f"jsonschema is required for KB2 validation: {exc}")


DOMAINS = ("THY", "MET", "SOC")
MIN_UNITS = 60
MAX_UNITS = 100
MIN_CRITIQUES = 5
MIN_EVIDENCE_SHARE = 0.30
MAX_AUTHOR_SHARE = 0.10
MIN_VALUE_RANGES = 12
MIN_VERIFIED_REFERENCES = 40
MAX_SENTENCE_REPETITIONS = 3
FIRST_ROUND_BASELINE_COMMIT = "713b62efafb28562a48439f657878f890d456642"
REQUIRED_TYPES = {"typology", "design_principle", "method"}
SCHOOLS = {"TU Delft", "Harvard GSD", "MIT", "UCL Bartlett"}
CURRICULUM_TOPICS = {
    "THY": [
        "規範性城市理論（Lynch 的城市好形式、性能向度）",
        "城市作為神聖秩序、機器、有機體",
        "Sitte 與城市藝術",
        "現代主義（CIAM、機能城市）與批判（Jacobs、Team 10、Collage City、Rossi、Krier）",
        "新都市主義",
        "地景都市主義／生態都市主義",
        "日常都市主義",
        "城市轉型史（倫敦、巴黎 Haussmann、維也納 Ringstrasse、巴塞隆納 Cerdà、芝加哥）",
        "荷蘭都市主義傳統",
    ],
    "MET": [
        "製圖與疊圖（layers approach，荷蘭）",
        "類型形態分析",
        "研究式設計（research by design）",
        "情境與策略規劃",
        "評估準則",
        "繪圖作為思考工具",
        "參與式方法",
    ],
    "SOC": [
        "正義城市",
        "參與階梯與合作式規劃",
        "治理與公私合作",
        "開發經濟與可行性（土地價值、殘值法）",
        "分期與風險",
        "都市更新的社會影響",
    ],
}
SCHOLARLY_KINDS = {
    "ACADEMIC_PAPER",
    "ACADEMIC_BOOK",
    "ACADEMIC_DISSERTATION",
    "ACADEMIC_REPORT",
    "ACADEMIC_CHAPTER",
}
ALLOWED_BIBLIOGRAPHY_APIS = {"OpenAlex", "Crossref", "Open Library"}


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def citation_basis(claim: str) -> str | None:
    for basis in ("ABSTRACT_REVIEW", "BIBLIOGRAPHIC_SCOPE_ONLY"):
        if claim.startswith(f"【{basis}】"):
            return basis
    return None


def author_family(author: str) -> str:
    normalized = unicodedata.normalize("NFKD", author)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    tokens = re.findall(r"[a-z0-9]+", normalized.casefold())
    tokens = [token for token in tokens if len(token) > 1]
    return tokens[-1] if tokens else ""


def prose_sentences(unit: dict[str, Any]) -> list[str]:
    """Return normalized authored prose for the repetition gate."""
    fields = (
        "summary_zh",
        "key_points_zh",
        "design_implications_zh",
        "design_options",
        "applies_when_zh",
        "not_applicable_when_zh",
        "debates_zh",
    )
    values: list[str] = []
    for field in fields:
        value = unit.get(field)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    values.append(item)
                elif isinstance(item, dict):
                    values.extend(v for v in item.values() if isinstance(v, str))
    evidence = unit.get("evidence", {})
    for finding in evidence.get("findings", []) if isinstance(evidence, dict) else []:
        claim = finding.get("claim_zh") if isinstance(finding, dict) else None
        if isinstance(claim, str):
            values.append(claim)
    for value in unit.get("values", []):
        if isinstance(value, dict):
            context = value.get("context")
            if isinstance(context, str):
                values.append(context)

    sentences: list[str] = []
    for value in values:
        for sentence in re.split(r"(?<=[。！？!?])\s*|(?<=[.!?])\s+|\n+", value):
            normalized = unicodedata.normalize("NFKC", sentence)
            normalized = " ".join(normalized.split()).strip(" \t\r\n-•*0123456789.、。；;:：！？!?()（）[]【】\"'`_")
            if len(normalized) >= 8:
                sentences.append(normalized)
    return sentences


def first_round_repetition_metrics(root: Path, domain: str) -> dict[str, Any]:
    """Measure the first-round snapshot with the same prose extractor."""
    counts: Counter[str] = Counter()
    for number in range(1, 61):
        relative = f"knowledge/v2/domains/{domain}/units/KU-{domain}-{number:03}.json"
        result = subprocess.run(
            ["git", "show", f"{FIRST_ROUND_BASELINE_COMMIT}:{relative}"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return {
                "status": "UNAVAILABLE",
                "source_commit": FIRST_ROUND_BASELINE_COMMIT,
                "error": result.stderr.strip() or f"git show failed for {relative}",
            }
        try:
            counts.update(prose_sentences(json.loads(result.stdout)))
        except Exception as exc:
            return {
                "status": "UNAVAILABLE",
                "source_commit": FIRST_ROUND_BASELINE_COMMIT,
                "error": f"invalid baseline unit {relative}: {exc}",
            }
    repeated = [count for count in counts.values() if count > MAX_SENTENCE_REPETITIONS]
    return {
        "status": "AVAILABLE",
        "source_commit": FIRST_ROUND_BASELINE_COMMIT,
        "repeated_sentence_count": len(repeated),
        "duplicate_sentence_occurrences": sum(repeated),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/kb2-kb2-theory/validation.json"),
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path("artifacts/kb2-kb2-theory/bibliography-audit.json"),
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    audit_path = args.audit if args.audit.is_absolute() else root / args.audit
    schema_path = root / "knowledge/v2/unit.schema.json"
    schema = read_json(schema_path)
    Draft202012Validator.check_schema(schema)
    schema_validator = Draft202012Validator(schema)

    library: dict[str, dict[str, Any]] = {}
    for base in (root / "knowledge/library", root / "knowledge/v2/library"):
        if not base.exists():
            continue
        for path in sorted(base.glob("*.json")):
            item = read_json(path)
            if item.get("id") in library:
                raise SystemExit(f"duplicate library id across v0.2 and v2: {item.get('id')}")
            library[item.get("id", path.stem)] = item

    audit = read_json(audit_path) if audit_path.exists() else {}
    audit_claims = audit.get("claim_level_overrides", {})
    audit_verifications = audit.get("verification_overrides", {})
    report: dict[str, Any] = {
        "validator": "scripts/kb2_validate.py",
        "schema": "knowledge/v2/unit.schema.json",
        "domains": {},
        "first_round_repetition_comparison": {},
        "bibliography_audit": {
            "claim_level_override_count": len(audit_claims),
            "verification_override_count": len(audit_verifications),
            "lookup_attempts": audit.get("lookup_attempts", []),
            "api_policy": audit.get("api_policy", ""),
        },
        "errors": [],
    }

    for domain in DOMAINS:
        base = root / "knowledge/v2/domains" / domain
        units_dir = base / "units"
        paths = sorted(units_dir.glob(f"KU-{domain}-*.json")) if units_dir.exists() else []
        units: list[dict[str, Any]] = []
        unit_by_id: dict[str, dict[str, Any]] = {}
        domain_errors: list[str] = []
        for path in paths:
            try:
                unit = read_json(path)
            except Exception as exc:
                domain_errors.append(f"{path.relative_to(root)}: invalid JSON: {exc}")
                continue
            units.append(unit)
            unit_by_id[unit.get("id", path.stem)] = unit
            for error in schema_validator.iter_errors(unit):
                pointer = "/".join(str(part) for part in error.absolute_path)
                domain_errors.append(
                    f"{path.relative_to(root)}: schema {pointer or '<root>'}: {error.message}"
                )

        coverage_path = base / "coverage.json"
        coverage = read_json(coverage_path) if coverage_path.exists() else {}
        curriculum_line = next(
            (
                line
                for line in (root / "knowledge/v2/CURRICULUM.md").read_text(encoding="utf-8").splitlines()
                if line.startswith(f"| {domain} |")
            ),
            "",
        )
        expected_topics = CURRICULUM_TOPICS[domain]
        covered_topics = coverage.get("topics", [])
        coverage_by_name = {entry.get("topic"): entry for entry in covered_topics}
        expected_set = set(expected_topics)
        actual_set = set(coverage_by_name)
        for topic in sorted(expected_set - actual_set):
            domain_errors.append(f"coverage missing curriculum topic: {topic}")
        for topic in sorted(actual_set - expected_set):
            domain_errors.append(f"coverage has non-curriculum topic: {topic}")
        for topic in expected_topics:
            if topic not in curriculum_line:
                domain_errors.append(f"validator topic does not match curriculum row: {topic}")
            entry = coverage_by_name.get(topic)
            if not entry:
                continue
            listed = entry.get("unit_ids", [])
            matches = [u.get("id") for u in units if u.get("subtopic") == topic]
            if sorted(listed) != sorted(matches):
                domain_errors.append(f"coverage IDs disagree with units for topic: {topic}")
            if entry.get("unit_count") != len(matches):
                domain_errors.append(f"coverage count disagrees with units for topic: {topic}")
            if not matches:
                domain_errors.append(f"curriculum topic has no unit: {topic}")

        type_counts = Counter(u.get("type", "<missing>") for u in units)
        used_ids: set[str] = set()
        author_counts: Counter[str] = Counter()
        author_denominator = 0
        author_unit_counts: Counter[str] = Counter()
        source_unit_counts: Counter[str] = Counter()
        verification_counts: Counter[str] = Counter()
        verification_query_ids: set[str] = set()
        region_counts: Counter[str] = Counter()
        unit_region_counts: Counter[str] = Counter()
        tradition_counts: Counter[str] = Counter()
        basis_counts: Counter[str] = Counter()
        for unit in units:
            unit_id = unit.get("id", "<missing>")
            citations = unit.get("sources", [])
            cited_refs: list[dict[str, Any]] = []
            cited_authors: set[str] = set()
            for citation in citations:
                library_id = citation.get("library_id")
                source = library.get(library_id)
                if source is None:
                    domain_errors.append(f"{unit_id}: missing library id {library_id}")
                    continue
                cited_refs.append(source)
                used_ids.add(library_id)
                verification = audit_verifications.get(library_id, source.get("verification", {}))
                status = verification.get("status", source.get("verification", {}).get("status", "UNVERIFIED"))
                verification_counts[status] += 1
                if library_id not in verification_query_ids:
                    verification_query_ids.add(library_id)
                    query = verification.get("query", {})
                    missing_fields = [
                        field for field, value in (
                            ("api", verification.get("api")),
                            ("query.title", query.get("title")),
                            ("query.author", query.get("author")),
                            ("query.year", query.get("year")),
                            ("matched_record_id", verification.get("matched_record_id")),
                            ("checked_at_utc", verification.get("checked_at_utc")),
                        ) if value in (None, "")
                    ]
                    if missing_fields:
                        domain_errors.append(f"{library_id}: bibliography verification lacks {', '.join(missing_fields)}")
                    if verification.get("api") not in ALLOWED_BIBLIOGRAPHY_APIS:
                        domain_errors.append(f"{library_id}: bibliography verification uses an unapproved API")
                    if query.get("year") != source.get("year"):
                        domain_errors.append(f"{library_id}: verified query year differs from library year")
                    query_family = author_family(query.get("author", ""))
                    source_families = {author_family(author) for author in source.get("authors", [])}
                    corporate_aliases = {"regelgeving": "crow"}
                    query_family = corporate_aliases.get(query_family, query_family)
                    if query_family and query_family not in source_families:
                        domain_errors.append(f"{library_id}: verified query author does not match a library author")
                for author in source.get("authors", []):
                    author_counts[author] += 1
                    author_denominator += 1
                    cited_authors.add(author)
                for region in source.get("region", []):
                    region_counts[region] += 1
                basis = audit_claims.get(library_id, {}).get("assessment_basis")
                if basis is None:
                    claim_id = citation.get("claim_id")
                    claim = next(
                        (c for c in source.get("claims", []) if c.get("claim_id") == claim_id),
                        None,
                    )
                    basis = (claim or {}).get("assessment_basis", "UNMARKED")
                basis_counts[basis] += 1
                claim_id = citation.get("claim_id")
                if claim_id is not None and not any(
                    c.get("claim_id") == claim_id for c in source.get("claims", [])
                ):
                    domain_errors.append(f"{unit_id}: missing claim id {library_id}/{claim_id}")
                source_unit_counts[library_id] += 1
            for author in cited_authors:
                author_unit_counts[author] += 1
            if len(citations) < 2:
                domain_errors.append(f"{unit_id}: fewer than two independent source records")
            if len(cited_refs) >= 2:
                author_sets = [set(source.get("authors", [])) for source in cited_refs]
                if any(author_sets[i] & author_sets[j] for i in range(len(author_sets)) for j in range(i + 1, len(author_sets))):
                    domain_errors.append(f"{unit_id}: cited sources share an author")
                if not any(source.get("kind") in SCHOLARLY_KINDS for source in cited_refs):
                    domain_errors.append(f"{unit_id}: lacks an academic source")
            if unit.get("region"):
                for region in unit["region"].split("；"):
                    unit_region_counts[region] += 1
            if unit.get("tradition"):
                tradition_counts[unit["tradition"]] += 1
            summary = unit.get("summary_zh", "")
            sentence_count = sum(summary.count(mark) for mark in ("。", "！", "？"))
            if not 3 <= sentence_count <= 8:
                domain_errors.append(f"{unit_id}: summary_zh has {sentence_count} sentences, expected 3-8")
            if "。。" in summary or "。，" in summary or "！！" in summary:
                domain_errors.append(f"{unit_id}: summary_zh has duplicated punctuation")
            if re.search(r"[\u3400-\u9fff]", unit.get("title_en", "")):
                domain_errors.append(f"{unit_id}: title_en contains non-English CJK text")
            if unit.get("type") == "empirical_finding":
                findings = unit.get("evidence", {}).get("findings", [])
                primary = next(
                    (f for f in findings if f.get("study_design") and f.get("context_region") and f.get("effect_or_value")),
                    None,
                )
                if primary is None:
                    domain_errors.append(f"{unit_id}: empirical finding lacks study design, region, or effect/direction")
                if "限制" not in summary and "限制" not in unit.get("debates_zh", ""):
                    domain_errors.append(f"{unit_id}: empirical finding does not state limitations")
                if primary:
                    basis = citation_basis(primary.get("claim_zh", ""))
                    if basis is None:
                        domain_errors.append(f"{unit_id}: empirical claim lacks an explicit verification level")
                    else:
                        basis_counts[f"unit_claim:{basis}"] += 1
            if unit.get("type") == "value_range":
                values = unit.get("values", [])
                if not values or any("不是本基地法規" not in v.get("context", "") for v in values):
                    domain_errors.append(f"{unit_id}: value_range lacks context or the non-local-regulation statement")
                if any(v.get("claim_verification") != "CANONICAL_CROSS_CHECK_PENDING" for v in values):
                    domain_errors.append(f"{unit_id}: value_range lacks CANONICAL_CROSS_CHECK_PENDING on every value")
                cited_library_ids = {citation.get("library_id") for citation in citations}
                if any(v.get("library_id") not in cited_library_ids for v in values):
                    domain_errors.append(f"{unit_id}: value_range cites a source absent from the unit source list")
            if unit.get("type") == "case" and not isinstance(unit.get("case"), dict):
                domain_errors.append(f"{unit_id}: case type lacks a case record")
            if unit.get("source_count_flag") != "MULTI_SOURCE":
                domain_errors.append(f"{unit_id}: expected MULTI_SOURCE flag")

        unique_statuses: Counter[str] = Counter({"VERIFIED": 0, "AMBIGUOUS": 0, "NOT_FOUND": 0})
        for library_id in sorted(used_ids):
            verification = audit_verifications.get(library_id, library[library_id].get("verification", {}))
            status = verification.get("status", library[library_id].get("verification", {}).get("status", "UNVERIFIED"))
            unique_statuses[status] += 1
        max_author_share = max(
            (count / author_denominator for count in author_counts.values()),
            default=0.0,
        )
        evidence_count = type_counts.get("empirical_finding", 0) + type_counts.get("value_range", 0)
        evidence_share = evidence_count / len(units) if units else 0.0
        prose_counts: Counter[str] = Counter()
        prose_units: dict[str, set[str]] = {}
        for unit in units:
            for sentence in prose_sentences(unit):
                prose_counts[sentence] += 1
                prose_units.setdefault(sentence, set()).add(unit.get("id", "<missing>"))
        repeated_sentences = [
            {"sentence": sentence, "count": count, "unit_ids": sorted(prose_units[sentence])}
            for sentence, count in prose_counts.items()
            if count > MAX_SENTENCE_REPETITIONS
        ]
        repeated_sentences.sort(key=lambda entry: (-entry["count"], entry["sentence"]))
        first_round_metrics = first_round_repetition_metrics(root, domain)
        current_duplicate_occurrences = sum(entry["count"] for entry in repeated_sentences)
        if first_round_metrics.get("status") != "AVAILABLE":
            domain_errors.append(
                f"first-round repetition baseline unavailable: {first_round_metrics.get('error', 'unknown error')}"
            )
            report["first_round_repetition_comparison"][domain] = {
                "status": "UNAVAILABLE",
                "before": first_round_metrics,
                "after": {
                    "repeated_sentence_count": len(repeated_sentences),
                    "duplicate_sentence_occurrences": current_duplicate_occurrences,
                },
            }
        else:
            report["first_round_repetition_comparison"][domain] = {
                "status": "AVAILABLE",
                "rule": f"same normalized sentence occurs more than {MAX_SENTENCE_REPETITIONS} times",
                "before": first_round_metrics,
                "after": {
                    "repeated_sentence_count": len(repeated_sentences),
                    "duplicate_sentence_occurrences": current_duplicate_occurrences,
                },
                "delta_after_minus_before": {
                    "repeated_sentence_count": len(repeated_sentences)
                    - first_round_metrics["repeated_sentence_count"],
                    "duplicate_sentence_occurrences": current_duplicate_occurrences
                    - first_round_metrics["duplicate_sentence_occurrences"],
                },
            }
        max_source_use = max(source_unit_counts.values(), default=0)
        max_author_unit_share = max(
            (count / len(units) for count in author_unit_counts.values()),
            default=0.0,
        )
        schools_found = {
            ref.get("school")
            for unit in units
            for ref in unit.get("curriculum_refs", [])
        }
        missing_schools = sorted(SCHOOLS - schools_found)
        if not MIN_UNITS <= len(units) <= MAX_UNITS:
            domain_errors.append(f"unit count {len(units)} outside {MIN_UNITS}-{MAX_UNITS}")
        if evidence_share < MIN_EVIDENCE_SHARE:
            domain_errors.append(f"empirical_finding + value_range share {evidence_share:.3f} below {MIN_EVIDENCE_SHARE:.2f}")
        if type_counts.get("critique", 0) < MIN_CRITIQUES:
            domain_errors.append(f"critique count {type_counts.get('critique', 0)} below {MIN_CRITIQUES}")
        if REQUIRED_TYPES - set(type_counts):
            domain_errors.append(f"missing required types: {sorted(REQUIRED_TYPES - set(type_counts))}")
        if max_author_share > MAX_AUTHOR_SHARE:
            domain_errors.append(f"single-author citation share {max_author_share:.3f} above {MAX_AUTHOR_SHARE:.2f}")
        if max_author_unit_share > MAX_AUTHOR_SHARE:
            domain_errors.append(f"single-author unit share {max_author_unit_share:.3f} above {MAX_AUTHOR_SHARE:.2f}")
        if units and max_source_use / len(units) > MAX_AUTHOR_SHARE:
            domain_errors.append(f"single-reference unit share {max_source_use / len(units):.3f} above {MAX_AUTHOR_SHARE:.2f}")
        if len(used_ids) < MIN_VERIFIED_REFERENCES:
            domain_errors.append(f"unique verified bibliography count {len(used_ids)} below {MIN_VERIFIED_REFERENCES}")
        if type_counts.get("value_range", 0) < MIN_VALUE_RANGES:
            domain_errors.append(f"value_range count {type_counts.get('value_range', 0)} below {MIN_VALUE_RANGES}")
        if repeated_sentences:
            domain_errors.append(
                f"repeated sentence gate failed: {len(repeated_sentences)} sentences occur more than {MAX_SENTENCE_REPETITIONS} times"
            )
        if missing_schools:
            domain_errors.append(f"missing curriculum refs for schools: {missing_schools}")
        if unique_statuses.get("AMBIGUOUS", 0) or unique_statuses.get("NOT_FOUND", 0):
            domain_errors.append("a cited bibliography entry is ambiguous or not found")
        if unique_statuses.get("UNVERIFIED", 0):
            domain_errors.append("a cited bibliography entry has no verification status")

        report["domains"][domain] = {
            "status": "PASS" if not domain_errors else "INCOMPLETE",
            "unit_count": len(units),
            "type_distribution": dict(sorted(type_counts.items())),
            "empirical_plus_value_range_count": evidence_count,
            "empirical_plus_value_range_share": round(evidence_share, 4),
            "critique_count": type_counts.get("critique", 0),
            "unique_library_ids_used": len(used_ids),
            "verification_unique_source_counts": dict(sorted(unique_statuses.items())),
            "verification_citation_counts": {
                status: verification_counts.get(status, 0)
                for status in ("VERIFIED", "AMBIGUOUS", "NOT_FOUND")
            },
            "bibliography_query_validated_source_count": len(verification_query_ids),
            "fresh_verification_override_count": len(used_ids & set(audit_verifications)),
            "claim_assessment_basis_citation_counts": dict(sorted(basis_counts.items())),
            "region_distribution": dict(sorted(region_counts.items())),
            "unit_region_context_counts": dict(sorted(unit_region_counts.items())),
            "tradition_distribution": dict(sorted(tradition_counts.items())),
            "top_5_authors": [
                {"author": author, "citation_count": count, "share": round(count / author_denominator, 4)}
                for author, count in author_counts.most_common(5)
            ],
            "max_single_author_share": round(max_author_share, 4),
            "max_author_unit_share": round(max_author_unit_share, 4),
            "max_single_reference_unit_share": round(max_source_use / len(units), 4) if units else 0.0,
            "value_range_count": type_counts.get("value_range", 0),
            "unique_verified_reference_minimum": MIN_VERIFIED_REFERENCES,
            "repetition_check": {
                "maximum_allowed_occurrences": MAX_SENTENCE_REPETITIONS,
                "repeated_sentence_count": len(repeated_sentences),
                "duplicate_sentence_occurrences": current_duplicate_occurrences,
                "top_repeated_sentences": repeated_sentences[:50],
            },
            "curriculum_topics": {
                topic: {
                    "unit_count": len(coverage_by_name.get(topic, {}).get("unit_ids", [])),
                    "unit_ids": coverage_by_name.get(topic, {}).get("unit_ids", []),
                }
                for topic in expected_topics
            },
            "curriculum_schools_found": sorted(schools_found),
            "errors": domain_errors,
        }
        report["errors"].extend(f"{domain}: {error}" for error in domain_errors)

    report["status"] = "PASS" if not report["errors"] else "INCOMPLETE"
    inventory_statuses: Counter[str] = Counter()
    for source in library.values():
        status = audit_verifications.get(source.get("id"), source.get("verification", {})).get(
            "status", source.get("verification", {}).get("status", "UNVERIFIED")
        )
        inventory_statuses[status] += 1
    report["source_inventory_status_counts"] = {
        status: inventory_statuses.get(status, 0)
        for status in ("VERIFIED", "AMBIGUOUS", "NOT_FOUND", "UNVERIFIED")
    }
    report["summary"] = {
        "domain_count": len(DOMAINS),
        "unit_count": sum(v["unit_count"] for v in report["domains"].values()),
        "library_ids_used": sorted(
            {
                citation.get("library_id")
                for domain in DOMAINS
                for path in sorted((root / "knowledge/v2/domains" / domain / "units").glob("*.json"))
                for citation in read_json(path).get("sources", [])
            }
        ),
        "error_count": len(report["errors"]),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "unit_count": report["summary"]["unit_count"], "error_count": len(report["errors"]), "output": str(output)}, ensure_ascii=False))
    if report["errors"]:
        for error in report["errors"][:40]:
            print(error, file=sys.stderr)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
