#!/usr/bin/env python3
"""Run fixed judgement cases with a deterministic fake or explicit live profile.

The default fake path is offline and only tests snapshot integrity plus validator
plumbing. Live execution requires explicit project/profile/database arguments,
authorization gates, and durable ModelRun accounting.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "knowledge/judgement/eval"
sys.path.insert(0, str(ROOT / "src"))

# Keep imports explicit: the assembler is deterministic and read-only, while
# the production service is intentionally not imported by this eval runner.
from urban_design.judgement.core import Registry, canonical, narrative, validate
from urban_design.judgement.inputs import assemble


class EvalError(RuntimeError):
    pass


class EvalBlocked(EvalError):
    """Live execution stopped before dispatch because a required gate is absent."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_file(root: Path, relative: str, expected_sha: str) -> None:
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        raise EvalError(f"path escapes repository: {relative}")
    if not path.is_file():
        raise EvalError(f"missing source snapshot: {relative}")
    actual = file_sha(path)
    if actual != expected_sha:
        raise EvalError(f"source hash mismatch: {relative}")


def validate_case(case: dict[str, Any], schema: dict[str, Any]) -> None:
    errors = sorted(Draft202012Validator(schema).iter_errors(case), key=lambda e: list(e.path))
    if errors:
        message = "; ".join(f"{list(e.path)}: {e.message}" for e in errors)
        raise EvalError(f"invalid eval case {case.get('case_id', '<unknown>')}: {message}")


def fixture_card(bundle: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Return a fixed, non-interpretive card independent of case expectations."""
    candidates = [
        (ident, metric)
        for ident, metric in sorted(bundle["metrics"].items())
        if isinstance(metric.get("value"), (int, float))
        and not isinstance(metric.get("value"), bool)
    ]
    if not candidates:
        raise EvalError("fixture bundle has no scalar numeric metric to reference")
    ident, metric = candidates[0]
    ref = {"kind": "metric", "id": ident, "value": metric["value"], "unit": metric.get("unit")}
    observation = {
        "text": "合成測試只檢查來源指標可被引用，不表示設計判斷。",
        "refs": [ref],
    }
    lens = spec["lenses"][0]
    return {
        "skill_id": spec["skill_id"],
        "skill_version": spec["version"],
        "stage": spec["stage"],
        "subject": bundle["subject"],
        "observations": [copy.deepcopy(observation) for _ in range(3)],
        "judgement": {
            "stance": "INSUFFICIENT_EVIDENCE",
            "headline": "這是合成測試輸出，只確認資料與驗證器可以串接。",
        },
        "reasoning": [
            {"lens": lens, "text": "合成測試不對任何設計方案作解讀、比較或排序。", "knowledge_refs": []},
            {"lens": lens, "text": "此合成回應不代表模型在固定案例上的判斷一致性。", "knowledge_refs": []},
        ],
        "confidence": {"level": "low", "why": "合成測試不提供語義判斷。"},
        "revision_directions": [{
            "action": "保留目前資料供來源引用串接測試。",
            "target": "fixture input",
            "parameter_family": "analysis_needed",
            "expected_effect": "驗證結構與來源引用可讀。",
            "trade_off": "沒有設計效果判斷。",
        }],
        "counterpoints": ["合成輸出沒有判斷方案品質或設計取捨。"],
        "limitations": ["FAKE_PROVIDER：僅驗證欄位、來源引用與資料缺口接線。"] + (
            ["DATA_GAP:e5.*：缺少風場輸入，不能作風場判讀。"]
            if spec['skill_id'] == 'J-CLIMATE' and any(g.startswith('DATA_GAP:e5') for g in bundle['data_gaps']) else []
        ),
        "questions_for_designer": ["正式模型評測時，設計者要補充哪些真實偏好？"],
    }


def apply_transform(bundle: dict[str, Any], transform: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(bundle)
    remove_metric_prefixes = tuple(transform.get("remove_metric_prefixes", []))
    remove_source_prefixes = tuple(transform.get("remove_source_prefixes", []))
    result["metrics"] = {
        ident: metric for ident, metric in result["metrics"].items()
        if not ident.startswith(remove_metric_prefixes)
        and not any(str(metric.get("source_path", "")).startswith(prefix) for prefix in remove_source_prefixes)
    }
    result["sources"] = {
        path: digest for path, digest in result["sources"].items()
        if not path.startswith(remove_source_prefixes)
    }
    result["data_gaps"] = sorted(set(result.get("data_gaps", [])) | set(transform.get("append_data_gaps", [])))
    result["inputs"] = [{"metric_id": ident, **metric} for ident, metric in sorted(result["metrics"].items())]
    return result


def check_required_metrics(bundle: dict[str, Any], required: list[str]) -> dict[str, Any]:
    metrics = bundle["metrics"]
    gaps = bundle.get("data_gaps", [])
    available, missing = [], []
    for pattern in required:
        if pattern.endswith(".*"):
            prefix = pattern[:-1]
            found = any(ident.startswith(prefix) for ident in metrics)
            gap_found = any(gap.removeprefix("DATA_GAP:").startswith(prefix) for gap in gaps)
        else:
            found = pattern in metrics
            gap_found = any(gap == "DATA_GAP:" + pattern for gap in gaps)
        (available if found else missing).append(pattern)
        if gap_found and pattern not in missing:
            missing.append(pattern)
            if pattern in available:
                available.remove(pattern)
    return {"available": sorted(set(available)), "missing_or_gapped": sorted(set(missing))}


def load_suite() -> tuple[dict[str, Any], Registry, list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]]:
    manifest_path = EVAL_DIR / "manifest.json"
    manifest = read_json(manifest_path)
    schema_entry = manifest["case_schema"]
    verify_file(ROOT, schema_entry["path"], schema_entry["sha256"])
    schema = read_json(ROOT / schema_entry["path"])
    source_manifest = manifest["source_manifest"]
    verify_file(ROOT, source_manifest["path"], source_manifest["sha256"])
    source_entries = read_json(ROOT / source_manifest["path"])["sources"]
    profile_manifest = manifest["provider_profiles"]
    verify_file(ROOT, profile_manifest["path"], profile_manifest["sha256"])
    for source in source_entries:
        verify_file(ROOT, source["path"], source["sha256"])

    registry = Registry(ROOT)
    loaded = []
    for entry in manifest["cases"]:
        verify_file(ROOT, entry["path"], entry["sha256"])
        case = read_json(ROOT / entry["path"])
        validate_case(case, schema)
        snapshot_ref = case["snapshot"]
        verify_file(ROOT, snapshot_ref["path"], snapshot_ref["sha256"])
        snapshot = read_json(ROOT / snapshot_ref["path"])
        bundle = snapshot["bundle"]
        if sha256(canonical(bundle).encode()) != snapshot_ref["bundle_sha256"]:
            raise EvalError(f"bundle hash mismatch: {case['case_id']}")
        skill = case["skill_id"]
        spec = registry.specs[skill]
        if snapshot["registry_sha256"] != registry.version or snapshot["skill_version"] != spec["version"]:
            raise EvalError(f"skill registry drift: {case['case_id']}")
        if snapshot["skill_id"] != skill or bundle["subject"].get("kind") not in {"site", "scheme", "scheme_set"}:
            raise EvalError(f"snapshot identity mismatch: {case['case_id']}")
        current = assemble(None, snapshot["project_id"], skill, snapshot["subject_ids"], registry, source_catalog=None)
        if sha256(canonical(current).encode()) != snapshot["bundle_sha256"]:
            raise EvalError(f"deterministic assembler drift: {case['case_id']}")
        transformed = apply_transform(bundle, case["transform"])
        loaded.append((case, transformed, registry.specs[skill]))
    return manifest, registry, loaded


def run_fake() -> dict[str, Any]:
    manifest, registry, loaded = load_suite()
    source_count = len(read_json(ROOT / manifest["source_manifest"]["path"])["sources"])
    results = []
    for case, transformed, spec in loaded:
        card = fixture_card(transformed, spec)
        validation_errors = validate(card, transformed, spec, registry.schema)
        required = check_required_metrics(transformed, case.get("required_metric_ids", []))
        results.append({
            "case_id": case["case_id"],
            "input_readiness_from_spec": case["input_readiness"],
            "required_input_check": required,
            "fake_validation": "PASS_PLUMBING_ONLY" if not validation_errors else "FAIL_PLUMBING",
            "validation_errors": validation_errors,
            "fake_card_sha256": sha256(canonical(card).encode()),
            "semantic_expectations_evaluated": False,
            "expectations": case["expectations"],
        })
    failures = [result for result in results if result["fake_validation"] != "PASS_PLUMBING_ONLY"]
    return {
        "suite_id": manifest["suite_id"],
        "provider_profile": "deterministic-fake",
        "provider_kind": "deterministic local fake",
        "live_calls": 0,
        "cases_total": len(results),
        "fake_validation_passed": len(results) - len(failures),
        "fake_validation_failed": len(failures),
        "semantic_consistency": "NOT_EVALUATED_FAKE_PROVIDER",
        "report_scope": "INPUT_SNAPSHOT_INTEGRITY_AND_VALIDATOR_PLUMBING_ONLY",
        "results": results,
        "source_manifest_entries_verified": source_count,
    }


def _summarize_live_result(result: dict[str, Any]) -> dict[str, Any]:
    card = result.get("card") or {}
    refs = sorted({
        f"{ref.get('kind')}:{ref.get('id')}"
        for observation in card.get("observations", [])
        for ref in observation.get("refs", [])
    })
    return {
        "status": result.get("status"),
        "provider_model": result.get("model"),
        "stance": card.get("judgement", {}).get("stance"),
        "parameter_families": sorted({
            direction.get("parameter_family")
            for direction in card.get("revision_directions", [])
            if direction.get("parameter_family")
        }),
        "key_refs": refs,
        "validation_errors": result.get("validation_errors", []),
    }


def _expectation_checks(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") != "VALIDATED":
        return {"stance": "NOT_COMPARABLE", "parameter_families": "NOT_COMPARABLE", "forbidden_content": "NOT_COMPARABLE", "claims": "REQUIRES_SEMANTIC_REVIEW"}
    card = result.get("card") or {}
    expected = case["expectations"]
    stance_rule = expected.get("stance", {})
    allowed = stance_rule.get("allowed")
    stance = card.get("judgement", {}).get("stance")
    required_families = expected.get("parameter_families", {}).get("must_include_any", [])
    actual_families = {d.get("parameter_family") for d in card.get("revision_directions", [])}
    text = "\n".join(narrative(card)) if card else ""
    forbidden = expected.get("forbidden_content", [])
    return {
        "stance": "PASS" if allowed is None or stance in allowed else "FAIL",
        "parameter_families": "PASS" if not required_families or actual_families.intersection(required_families) else "FAIL",
        "forbidden_content": "PASS" if not any(term in text for term in forbidden) else "FAIL",
        "claims": "REQUIRES_SEMANTIC_REVIEW",
    }


def run_live(profile_ids: list[str], args: argparse.Namespace) -> dict[str, Any]:
    if not args.confirm_live:
        raise EvalBlocked("live dispatch requires --confirm-live")
    if os.environ.get("PROJECT_AI_AUTHORIZED", "").strip() != "1" or os.environ.get("ARIADNE_LIVE", "").strip() != "1":
        raise EvalBlocked("live dispatch requires PROJECT_AI_AUTHORIZED=1 and ARIADNE_LIVE=1")
    if not args.project_db or not args.judgement_db or not args.project_id:
        raise EvalBlocked("live dispatch requires --project-db, --judgement-db, and --project-id")
    project_db = Path(args.project_db).expanduser().resolve()
    judgement_db = Path(args.judgement_db).expanduser().resolve()
    if not project_db.is_file():
        raise EvalBlocked("--project-db must name an existing project database; no project database will be created")
    if judgement_db == project_db:
        raise EvalBlocked("--judgement-db must be separate from --project-db")
    if not judgement_db.parent.is_dir():
        raise EvalBlocked("--judgement-db parent directory must already exist")

    from urban_design.model_profiles import load_model_provider_config
    from urban_design.model_provider import ModelProviderRouter, create_profile_provider
    from urban_design.store import ProjectStateStore
    from urban_design.judgement import service as service_module
    from urban_design.judgement.service import JudgementService, RunRequest

    config = load_model_provider_config()
    profiles = {profile.id: profile for profile in config.profiles}
    for profile_id in profile_ids:
        profile = profiles.get(profile_id)
        if profile is None or not profile.enabled:
            raise EvalBlocked(f"provider profile is missing or disabled: {profile_id}")
        if not profile.use_ariadne_persona:
            raise EvalBlocked(f"provider profile must explicitly set use_ariadne_persona=true: {profile_id}")
        if profile.keychain_service:
            raise EvalBlocked(f"profile requires a credentialed adapter; this evaluator does not read Keychain or secrets and will not fall back: {profile_id}")

    manifest, registry, loaded = load_suite()
    store = ProjectStateStore(project_db)
    all_results: dict[str, dict[str, Any]] = {}
    try:
        for profile_id in profile_ids:
            profile = profiles[profile_id]
            adapter = create_profile_provider(
                profile,
                api_key=None,
                timeout_seconds=config.timeout_seconds,
                max_output_tokens=config.max_output_tokens,
                cli_timeout_seconds=config.skill_timeout_seconds,
                use_ariadne_persona=profile.use_ariadne_persona,
            )
            router = ModelProviderRouter(
                providers={profile_id: adapter},
                fallback_order=[profile_id],
                store=store,
                project_id=args.project_id,
                weekly_call_limit=config.weekly_call_limit,
            )
            if not router.has_durable_accounting or router.model_run_project_id != args.project_id:
                raise EvalBlocked("durable project ModelRun accounting is required")
            if not router.is_live_available:
                raise EvalBlocked(f"profile is not live-available: {profile_id}; no fallback profile was used")
            service = JudgementService(
                store,
                judgement_db,
                registry=registry,
                provider_factory=lambda _store, _project, _router=router: _router,
            )
            profile_results = {}
            for case_index, (case, bundle, spec) in enumerate(loaded):
                # Feed the exact, hash-verified offline snapshot plus declared
                # ablation into the production service; never use expectations
                # to shape a model prompt or response.
                original_assemble = service_module.assemble
                service_module.assemble = lambda *_a, _bundle=bundle, **_kw: copy.deepcopy(_bundle)
                try:
                    run_result = service.run(
                        args.project_id,
                        RunRequest(skill_id=spec["skill_id"], subject_ids=case["snapshot"]["subject_ids"], force=True),
                    )
                finally:
                    service_module.assemble = original_assemble
                profile_results[case["case_id"]] = {
                    **_summarize_live_result(run_result),
                    "expectation_checks": _expectation_checks(case, run_result),
                }
                if run_result.get("status") != "VALIDATED":
                    for skipped_case, _skipped_bundle, _skipped_spec in loaded[case_index + 1:]:
                        profile_results[skipped_case["case_id"]] = {
                            "status": "SKIPPED_AFTER_PRIOR_NONVALIDATED_RESULT",
                            "provider_model": None,
                            "stance": None,
                            "parameter_families": [],
                            "key_refs": [],
                            "validation_errors": [],
                            "expectation_checks": {"stance": "NOT_COMPARABLE", "parameter_families": "NOT_COMPARABLE", "forbidden_content": "NOT_COMPARABLE", "claims": "REQUIRES_SEMANTIC_REVIEW"},
                        }
                    break
            all_results[profile_id] = profile_results
            if any(value["status"] != "VALIDATED" for value in profile_results.values()):
                break
    finally:
        store.close()

    comparisons = []
    if len(profile_ids) == 2:
        first, second = profile_ids
        for case_id in all_results[first]:
            a = all_results[first][case_id]
            b = all_results.get(second, {}).get(case_id, {"status": "NOT_RUN", "stance": None, "parameter_families": [], "key_refs": []})
            if a.get("status") != "VALIDATED" or b.get("status") != "VALIDATED":
                comparisons.append({"case_id": case_id, "status": "NOT_COMPARABLE", "stance_match": None, "parameter_family_intersection": [], "parameter_family_union": [], "key_ref_intersection": [], "key_ref_union": []})
                continue
            a_refs, b_refs = set(a["key_refs"]), set(b["key_refs"])
            a_families, b_families = set(a["parameter_families"]), set(b["parameter_families"])
            comparisons.append({
                "case_id": case_id,
                "status": "COMPARED",
                "stance_match": a["stance"] == b["stance"],
                "parameter_family_intersection": sorted(a_families & b_families),
                "parameter_family_union": sorted(a_families | b_families),
                "key_ref_intersection": sorted(a_refs & b_refs),
                "key_ref_union": sorted(a_refs | b_refs),
            })
    return {
        "status": "OK" if len(all_results) == len(profile_ids) and all(
            value['status'] == 'VALIDATED' for results in all_results.values() for value in results.values()
        ) else "INCOMPLETE_EVALUATION",
        "suite_id": manifest["suite_id"],
        "provider_profiles": profile_ids,
        "provider_kind": "production JudgementService; explicit profile(s), no fallback",
        "semantic_consistency": "DESCRIPTIVE_FIXED_CASE_COMPARISON" if len(profile_ids) == 2 else "SINGLE_PROFILE_NO_CONSISTENCY_COMPARISON",
        "report_scope": "STANCE_PARAMETER_FAMILIES_KEY_REFERENCES_AND_FORBIDDEN_CONTENT; claims remain manual review",
        "live_call_count_is_accounted_by_project_model_runs": True,
        "profile_results": all_results,
        "profile_comparison": comparisons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-profile", default="deterministic-fake", help="deterministic-fake or an enabled id from config/model-providers.json")
    parser.add_argument("--comparison-provider-profile", help="Optional second enabled provider id; generates a two-profile comparison")
    parser.add_argument("--project-db", type=Path, help="Existing project-state SQLite, required for explicitly authorized live evaluation")
    parser.add_argument("--judgement-db", type=Path, help="Separate judgement-run SQLite path, required for explicitly authorized live evaluation")
    parser.add_argument("--project-id", help="Project id for durable ModelRun accounting")
    parser.add_argument("--confirm-live", action="store_true", help="Permit external model requests through JudgementService")
    args = parser.parse_args()
    try:
        if args.provider_profile == "deterministic-fake":
            if args.comparison_provider_profile or args.project_db or args.judgement_db or args.project_id or args.confirm_live:
                raise EvalError("live-only flags cannot be combined with --provider-profile deterministic-fake")
            report = run_fake()
        else:
            profiles = [args.provider_profile]
            if args.comparison_provider_profile:
                if args.comparison_provider_profile == args.provider_profile:
                    raise EvalError("comparison requires two distinct provider profiles")
                profiles.append(args.comparison_provider_profile)
            report = run_live(profiles, args)
    except EvalBlocked as exc:
        print(json.dumps({"status": "BLOCKED_LIVE_PREFLIGHT", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    except (EvalError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAIL_EVAL_INTEGRITY", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report.get("fake_validation_failed", 0) == 0 and report.get("status", "OK") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
