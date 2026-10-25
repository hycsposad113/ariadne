#!/usr/bin/env python3
"""Fail-closed structural, provenance, coverage, and bias validator for the HAR/CAS lane."""
# Retained for history; scripts/kb2_validate_all.py is the consolidated acceptance validator.

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # no dependency installation during validation
    raise SystemExit(f"jsonschema is unavailable in this runtime: {exc}")

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "knowledge/v2/unit.schema.json"
CURRICULUM_PATH = ROOT / "knowledge/v2/CURRICULUM.md"
DOMAINS = ("HAR", "CAS")
ALL_CODES = ("THY", "MET", "MOR", "LUP", "REG", "STR", "MOB", "SYN", "PUB", "GRN", "ECO", "WAT", "CLI", "HOU", "HAR", "SOC", "CAS")
CURRICULUM_TOPICS = {
    "WAT": ["水敏感都市設計（WSUD）", "海綿城市", "鹿特丹水廣場（如 Benthemplein）", "洪水風險與多層安全", "潮汐與河口地景", "雨水滯留量的設計值", "韌性理論與批評"],
    "CLI": ["街谷高寬比（H/W）", "天空可視因子", "都市熱島", "風舒適度準則（如 Lawson）", "日照與遮陰", "材料與反照率", "樹木降溫", "室外熱舒適指標", "高密度城市的氣候設計"],
    "HAR": ["水岸再生的世代與模式", "港城介面", "工業遺產與 adaptive reuse", "生產性城市", "分期開發", "文化導向再生與仕紳化批評", "港區轉型案例"],
    "CAS": ["30–50 個案例，涵蓋上列所有領域"],
}


def utc_now() -> str:
    return subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def norm_sentence(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower().strip()
    s = re.sub(r"[\s\u3000]+", "", s)
    s = re.sub(r"[。！？!?；;，,：:、]+$", "", s)
    return s


def sentences(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[。！？!?])\s*|\n+", text) if len(x.strip()) >= 8]


def editorial_texts(unit: dict[str, Any]) -> list[str]:
    """Collect prose for repetition checks, excluding labels and metadata fragments."""
    keys = {
        "summary_zh", "key_points_zh", "claim_zh", "design_implications_zh",
        "option_zh", "tradeoff_zh", "applies_when_zh", "not_applicable_when_zh",
        "debates_zh", "program_mix", "key_strategies_zh",
        "outcomes_zh", "critiques_zh",
    }
    found: list[str] = []

    def visit(value: Any, key: str | None = None) -> None:
        if isinstance(value, str):
            if key in keys:
                found.append(value)
        elif isinstance(value, list):
            for item in value:
                visit(item, key)
        elif isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, child_key)

    visit(unit)
    return found


def all_library() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for base in (ROOT / "knowledge/library", ROOT / "knowledge/v2/library"):
        if not base.exists():
            continue
        for path in sorted(base.glob("*.json")):
            try:
                data = read_json(path)
            except Exception as exc:
                result[path.stem] = {"_path": str(path), "_error": str(exc)}
                continue
            data["_path"] = str(path)
            result[data.get("id", path.stem)] = data
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="artifacts/kb2-kb2-environment/validation.json")
    args = ap.parse_args()
    schema = read_json(SCHEMA_PATH)
    validator = Draft202012Validator(schema)
    library = all_library()
    report: dict[str, Any] = {
        "checked_at_utc": utc_now(),
        "task_id": "kb2-cases",
        "domains": {},
        "overall_status": "PASS",
        "issues": [],
    }
    for domain in DOMAINS:
        droot = ROOT / "knowledge/v2/domains" / domain
        unit_dir = droot / "units"
        paths = sorted(unit_dir.glob(f"KU-{domain}-*.json")) if unit_dir.exists() else []
        units: list[dict[str, Any]] = []
        issues: list[str] = []
        schema_errors = 0
        refs: set[str] = set()
        reference_status: collections.Counter[str] = collections.Counter()
        reference_kind: collections.Counter[str] = collections.Counter()
        author_units: collections.Counter[str] = collections.Counter()
        type_counts: collections.Counter[str] = collections.Counter()
        topic_ids: dict[str, set[str]] = collections.defaultdict(set)
        sentence_counts: collections.Counter[str] = collections.Counter()
        unit_ids_seen: set[str] = set()
        case_count = 0
        single_source = 0
        value_range_count = 0
        empirical_count = 0
        region_counts: collections.Counter[str] = collections.Counter()
        tradition_counts: collections.Counter[str] = collections.Counter()
        curriculum_school_counts: collections.Counter[str] = collections.Counter()
        for path in paths:
            try:
                unit = read_json(path)
            except Exception as exc:
                issues.append(f"{path.relative_to(ROOT)}: invalid JSON: {exc}")
                continue
            units.append(unit)
            unit_id = unit.get("id", path.stem)
            if unit_id in unit_ids_seen:
                issues.append(f"duplicate unit id: {unit_id}")
            unit_ids_seen.add(unit_id)
            for err in validator.iter_errors(unit):
                schema_errors += 1
                issues.append(f"{path.relative_to(ROOT)} schema: {err.json_path}: {err.message}")
            if unit.get("domain") != domain:
                issues.append(f"{unit.get('id')}: domain field does not match directory")
            type_counts[unit.get("type", "MISSING")] += 1
            if unit.get("region"):
                region_counts[str(unit["region"])] += 1
            if unit.get("tradition"):
                tradition_counts[str(unit["tradition"])] += 1
            for ref in unit.get("curriculum_refs", []):
                if ref.get("school"):
                    curriculum_school_counts[str(ref["school"])] += 1
            if unit.get("type") == "case":
                case_count += 1
                if not isinstance(unit.get("case"), dict):
                    issues.append(f"{unit.get('id')}: case type requires case object")
                else:
                    for key in ("location", "period", "area_ha", "fsi", "gsi", "program_mix", "key_strategies_zh", "outcomes_zh", "critiques_zh"):
                        if key not in unit["case"] or (unit["case"].get(key) is None and key not in ("area_ha", "fsi", "gsi")):
                            issues.append(f"{unit.get('id')}: case.{key} must be explicitly populated")
                    for key in ("key_strategies_zh", "outcomes_zh", "critiques_zh"):
                        if not unit["case"].get(key):
                            issues.append(f"{unit.get('id')}: case.{key} cannot be empty")
            if unit.get("type") == "value_range":
                value_range_count += 1
                if not unit.get("values"):
                    issues.append(f"{unit.get('id')}: value_range has no values")
                for value in unit.get("values", []):
                    if "不是本基地法規" not in value.get("context", ""):
                        issues.append(f"{unit.get('id')}: value context must say it is not M4H law")
                    if value.get("library_id") not in {x.get("library_id") for x in unit.get("sources", [])}:
                        issues.append(f"{unit.get('id')}: value library_id must also appear in sources")
            if unit.get("type") == "empirical_finding":
                empirical_count += 1
                findings = unit.get("evidence", {}).get("findings", [])
                if not findings:
                    issues.append(f"{unit.get('id')}: empirical_finding has no findings")
                for finding in findings:
                    for key in ("study_design", "context_region", "effect_or_value"):
                        if not finding.get(key):
                            issues.append(f"{unit.get('id')}: empirical finding missing {key}")
            summary = unit.get("summary_zh", "")
            sent = sentences(summary)
            if not 3 <= len(sent) <= 8:
                issues.append(f"{unit.get('id')}: summary has {len(sent)} sentences, expected 3-8")
            for value in editorial_texts(unit):
                for s in sentences(value):
                    normalized = norm_sentence(s)
                    if normalized:
                        sentence_counts[normalized] += 1
            refs_here = [x.get("library_id") for x in unit.get("sources", []) if x.get("library_id")]
            if len(set(refs_here)) < 2:
                single_source += 1
                if unit.get("source_count_flag") != "SINGLE_SOURCE":
                    issues.append(f"{unit.get('id')}: fewer than two sources without SINGLE_SOURCE flag")
            elif unit.get("source_count_flag") != "MULTI_SOURCE":
                issues.append(f"{unit.get('id')}: at least two sources require MULTI_SOURCE flag")
            authors_in_unit: set[str] = set()
            source_identities_in_unit: set[str] = set()
            academic_ref_count = 0
            official_or_professional_ref_count = 0
            for rid in set(refs_here):
                refs.add(rid)
                record = library.get(rid)
                if not record:
                    issues.append(f"{unit.get('id')}: missing library id {rid}")
                    continue
                reference_status[record.get("verification", {}).get("status", "MISSING")] += 1
                reference_kind[record.get("kind", "MISSING")] += 1
                if record.get("verification", {}).get("status") != "VERIFIED":
                    issues.append(f"{unit.get('id')}: {rid} is not VERIFIED")
                if not record.get("verification", {}).get("matched_record_id"):
                    issues.append(f"{unit.get('id')}: {rid} lacks matched_record_id")
                if not record.get("verification", {}).get("query"):
                    issues.append(f"{unit.get('id')}: {rid} lacks verification query")
                claim_id = next((s.get("claim_id") for s in unit.get("sources", []) if s.get("library_id") == rid and s.get("claim_id")), None)
                claims = record.get("claims", [])
                matched_claim = next((c for c in claims if c.get("claim_id") == claim_id), None) if claim_id else None
                if claim_id and not matched_claim:
                    issues.append(f"{unit.get('id')}: {rid} missing cited claim {claim_id}")
                if matched_claim and matched_claim.get("assessment_basis") not in ("ABSTRACT_REVIEW", "BIBLIOGRAPHIC_SCOPE_ONLY", "DIRECT_SOURCE_REVIEW", "CANONICAL_CROSS_CHECK_PENDING"):
                    issues.append(f"{unit.get('id')}: {rid}/{claim_id} has unrecognized assessment_basis")
                authors = record.get("authors", [])
                if authors:
                    source_identities_in_unit.add(norm_sentence(str(authors[0])))
                kind = str(record.get("kind", ""))
                if kind.startswith("ACADEMIC"):
                    academic_ref_count += 1
                    for author in authors:
                        name = norm_sentence(str(author))
                        if name:
                            authors_in_unit.add(name)
                elif kind.startswith(("OFFICIAL", "PROFESSIONAL")):
                    official_or_professional_ref_count += 1
            if len(set(refs_here)) >= 2 and len(source_identities_in_unit) < 2:
                issues.append(f"{unit.get('id')}: cited records do not provide two independent author identities")
            if refs_here and academic_ref_count < 1:
                issues.append(f"{unit.get('id')}: no academic source")
            if unit.get("type") == "case" and official_or_professional_ref_count < 1:
                issues.append(f"{unit.get('id')}: case requires an official or professional source")
            for author in authors_in_unit:
                author_units[author] += 1
            topic_ids[unit.get("subtopic", "")].add(unit.get("id", path.stem))
        if domain == "HAR":
            if not 60 <= len(units) <= 100:
                issues.append(f"unit count {len(units)} outside required 60-100")
            if value_range_count < 12:
                issues.append(f"value_range count {value_range_count} below 12")
            if empirical_count + value_range_count < 0.30 * max(1, len(units)):
                issues.append("empirical_finding + value_range share below 30%")
            if type_counts.get("critique", 0) < 5:
                issues.append(f"critique count {type_counts.get('critique', 0)} below 5")
            for required_type in ("typology", "design_principle", "method"):
                if not type_counts.get(required_type):
                    issues.append(f"required type missing: {required_type}")
        else:
            if len(units) != 40:
                issues.append(f"CAS unit count {len(units)} is not the required 40 cases")
            if case_count != 40 or type_counts.get("case", 0) != len(units):
                issues.append(f"CAS requires 40 units, all type: case; found {case_count} cases and {len(units)} units")
        if len(refs) < 35:
            issues.append(f"distinct cited bibliography count {len(refs)} below 35")
        shares = {author: count / max(1, len(units)) for author, count in author_units.items()}
        top_authors = sorted(shares.items(), key=lambda item: (-item[1], item[0]))[:5]
        if any(share > 0.10 for _, share in shares.items()):
            over = [(author, round(share, 4)) for author, share in shares.items() if share > 0.10]
            issues.append(f"author share exceeds 10%: {over}")
        repeated = [(s, n) for s, n in sentence_counts.items() if n > 3]
        if repeated:
            issues.append(f"identical sentence repeated more than 3 times ({len(repeated)} phrases)")
        distinct_reference_status = collections.Counter(
            library.get(rid, {}).get("verification", {}).get("status", "MISSING") for rid in refs
        )
        claim_basis: collections.Counter[str] = collections.Counter()
        for unit in units:
            for source in unit.get("sources", []):
                rid = source.get("library_id")
                claim_id = source.get("claim_id")
                record = library.get(rid, {})
                claim = next((c for c in record.get("claims", []) if c.get("claim_id") == claim_id), None)
                if claim:
                    claim_basis[claim.get("assessment_basis", "MISSING")] += 1
        coverage_path = droot / "coverage.json"
        coverage_data = None
        if not coverage_path.exists():
            issues.append("coverage.json missing")
        else:
            try:
                coverage_data = read_json(coverage_path)
                topics = coverage_data.get("topics", [])
                mapped = {t.get("topic"): set(t.get("unit_ids", [])) for t in topics if isinstance(t, dict)}
                for topic_entry in topics:
                    if not isinstance(topic_entry, dict):
                        continue
                    actual_count = len(set(topic_entry.get("unit_ids", [])))
                    if topic_entry.get("unit_count") != actual_count:
                        issues.append(f"coverage topic {topic_entry.get('topic')} unit_count mismatch: declared {topic_entry.get('unit_count')} vs {actual_count}")
                    if topic_entry.get("coverage_status") not in ("COVERED", "PARTIAL", "NOT_COVERED"):
                        issues.append(f"coverage topic {topic_entry.get('topic')} lacks explicit coverage_status")
                    elif topic_entry.get("coverage_status") != "COVERED":
                        issues.append(f"curriculum topic {topic_entry.get('topic')} coverage is {topic_entry.get('coverage_status')}")
                for expected in CURRICULUM_TOPICS[domain]:
                    if expected not in mapped or not mapped[expected]:
                        issues.append(f"curriculum topic not covered: {expected}")
                all_ids = {u.get("id") for u in units}
                if coverage_data.get("total_units") != len(all_ids):
                    issues.append(f"coverage total_units mismatch: declared {coverage_data.get('total_units')} vs {len(all_ids)}")
                for topic, ids in mapped.items():
                    if not ids <= all_ids:
                        issues.append(f"coverage topic {topic} references missing ids: {sorted(ids-all_ids)}")
                mapped_ids = set().union(*mapped.values()) if mapped else set()
                if all_ids - mapped_ids:
                    issues.append(f"coverage omits {len(all_ids-mapped_ids)} unit ids")
                if domain == "CAS":
                    dc = set(coverage_data.get("curriculum_domains_covered", []))
                    if dc != set(ALL_CODES):
                        issues.append(f"CAS domain coverage must list all 17 curriculum codes; got {sorted(dc)}")
                    domain_case_units = coverage_data.get("curriculum_domain_case_units", {})
                    case_ids = {u.get("id") for u in units if u.get("type") == "case"}
                    for code in ALL_CODES:
                        ids_for_code = set(domain_case_units.get(code, []))
                        if not ids_for_code or not ids_for_code <= case_ids:
                            issues.append(f"CAS curriculum domain {code} lacks mapped case units")
            except Exception as exc:
                issues.append(f"coverage.json invalid: {exc}")
        report["domains"][domain] = {
            "unit_count": len(units),
            "type_distribution": dict(sorted(type_counts.items())),
            "distinct_cited_library_ids": len(refs),
            "reference_verification": dict(sorted(reference_status.items())),
            "reference_verification_measure": "source citations counted per unit; repeated use of the same ID appears more than once",
            "distinct_reference_verification": dict(sorted(distinct_reference_status.items())),
            "claim_assessment_basis_counts": dict(sorted(claim_basis.items())),
            "reference_kind": dict(sorted(reference_kind.items())),
            "single_source_units": single_source,
            "value_range_count": value_range_count,
            "empirical_finding_count": empirical_count,
            "empirical_plus_range_share": round((empirical_count+value_range_count)/max(1,len(units)), 4),
            "case_count": case_count,
            "region_distribution": dict(sorted(region_counts.items())),
            "tradition_distribution": dict(sorted(tradition_counts.items())),
            "curriculum_school_reference_counts": dict(sorted(curriculum_school_counts.items())),
            "schema_errors": schema_errors,
            "top_5_author_unit_shares": [{"author": a, "share": round(s,4)} for a,s in top_authors],
            "repeated_sentence_count_over_3": len(repeated),
            "curriculum_topic_unit_counts": {t.get("topic"): len(set(t.get("unit_ids", []))) for t in (coverage_data or {}).get("topics", []) if isinstance(t, dict)},
            "curriculum_topic_coverage_status": {t.get("topic"): t.get("coverage_status", "MISSING") for t in (coverage_data or {}).get("topics", []) if isinstance(t, dict)},
            "issues": issues,
        }
        report["issues"].extend([f"{domain}: {x}" for x in issues])
    used_ids = set()
    for d in DOMAINS:
        droot = ROOT / "knowledge/v2/domains" / d / "units"
        if droot.exists():
            for p in droot.glob("KU-*.json"):
                try:
                    used_ids.update(x.get("library_id") for x in read_json(p).get("sources", []) if x.get("library_id"))
                except Exception:
                    pass
    ref_status = collections.Counter(library.get(r, {}).get("verification", {}).get("status", "MISSING") for r in used_ids)
    report["bibliography_verification"] = dict(sorted(ref_status.items()))
    v2_library_status: collections.Counter[str] = collections.Counter()
    v2_library_ids: set[str] = set()
    for path in (ROOT / "knowledge/v2/library").glob("*.json"):
        try:
            record = read_json(path)
            v2_library_ids.add(record.get("id", path.stem))
            v2_library_status[record.get("verification", {}).get("status", "MISSING")] += 1
        except Exception:
            v2_library_status["INVALID"] += 1
    report["v2_library_inventory"] = {
        "file_count": sum(v2_library_status.values()),
        "verification_status": dict(sorted(v2_library_status.items())),
        "cited_record_count_across_domains": len(used_ids & v2_library_ids),
        "verified_but_not_yet_cited_count": max(0, v2_library_status.get("VERIFIED", 0) - len(used_ids & v2_library_ids)),
    }
    v02_status = collections.Counter()
    for path in (ROOT / "knowledge/library").glob("*.json"):
        try:
            v02_status[read_json(path).get("verification", {}).get("status", "MISSING")] += 1
        except Exception:
            v02_status["INVALID"] += 1
    report["existing_v02_library_verification"] = dict(sorted(v02_status.items()))
    log_path = ROOT / "artifacts/kb2-kb2-environment/research-log.json"
    if log_path.exists():
        try:
            log = read_json(log_path)
            report["prior_research_log_candidate_status"] = dict(sorted(collections.Counter(x.get("status", "MISSING") for x in log.get("results", [])).items()))
        except Exception as exc:
            report["prior_research_log_candidate_status"] = {"log_error": str(exc)}
    api_batch_status: collections.Counter[str] = collections.Counter()
    exact_candidate_status: collections.Counter[str] = collections.Counter()
    fallback_search_status: collections.Counter[str] = collections.Counter()
    discovery_record_count = 0
    api_batch_files = sorted((ROOT / "artifacts/kb2-kb2-environment/api-batches").glob("*.json"))
    for path in api_batch_files:
        try:
            batch = read_json(path)
            for result in batch.get("results", []):
                status = result.get("status", result.get("candidate_status", "MISSING"))
                api_batch_status[status] += 1
                if path.name.startswith("batch-"):
                    exact_candidate_status[status] += 1
                elif path.name.startswith("openlibrary-"):
                    fallback_search_status[status] += 1
            if batch.get("records"):
                found = sum(1 for x in batch["records"] if x.get("candidate_status") == "DISCOVERY_CANDIDATE")
                api_batch_status["DISCOVERY_CANDIDATE"] += found
                discovery_record_count += found
        except Exception as exc:
            report.setdefault("api_batch_errors", []).append(f"{path.relative_to(ROOT)}: {exc}")
    report["api_batch_files"] = [str(p.relative_to(ROOT)) for p in api_batch_files]
    report["api_batch_candidate_status"] = dict(sorted(api_batch_status.items()))
    report["candidate_search_status"] = dict(sorted(exact_candidate_status.items()))
    report["candidate_search_result_count"] = sum(exact_candidate_status.values())
    report["fallback_search_status"] = dict(sorted(fallback_search_status.items()))
    report["discovery_candidate_record_count_non_deduplicated"] = discovery_record_count
    report["overall_status"] = "PASS" if not report["issues"] else "INCOMPLETE"
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status":report["overall_status"],"output":str(out.relative_to(ROOT)),"domains":{d:{"units":v["unit_count"],"sources":v["distinct_cited_library_ids"],"issues":len(v["issues"])} for d,v in report["domains"].items()},"bibliography_verification":report["bibliography_verification"],"issue_count":len(report["issues"])},ensure_ascii=False,indent=2))
    return 0 if report["overall_status"] == "PASS" else 2

if __name__ == "__main__":
    sys.exit(main())
