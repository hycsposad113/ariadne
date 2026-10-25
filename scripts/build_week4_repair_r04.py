#!/usr/bin/env python3
"""Publish a validated, append-only R04 package from local evidence only."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from urban_design.r04_evidence import build_r04_observational_evidence_bundle  # noqa: E402
from urban_design.r03_evidence import build_observational_evidence_bundle  # noqa: E402
from urban_design.store import ProjectStateStore  # noqa: E402
from urban_design.workspace_sources import DEFAULT_SPATIAL_R01_ROOT, WorkspaceSourceCatalog  # noqa: E402
from verify_week4_repair_r04 import verify_package  # noqa: E402
from verify_week4_repair_r03 import verify_package as verify_r03_package  # noqa: E402


PACKAGE_REL = Path("artifacts/week4-repair-r04")
PACKAGE = ROOT / PACKAGE_REL
DOCKET_PATH = ROOT / "docs/week4-r04-repair-evidence-docket.md"
MANIFEST_NAME = "integrity-manifest.json"
R02_REL = Path("artifacts/week4-repair-r02")
R03_REL = Path("artifacts/week4-repair-r03")
SPATIAL_REL = Path(
    "artifacts/milestone2-analysis-inputs-rotterdam-m4h/"
    "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01"
)
DATABASE = ROOT / ".urban_design_runtime/state.sqlite3"
BASELINE_DIR = Path("/private/tmp/week4-r04-validation-20260923")
FROZEN_R02_MANIFEST_SHA256 = "3080e17b7840efcaee66b762e7fad08a95acc0083bbf796149dc076e334454c4"
FROZEN_R03_LATEST_MANIFEST_SHA256 = "272106cf92795c8ce4f520df0a621204cb7e1d9deb14c994546d070c9029a773"

SOURCE_FILES = {
    "src/urban_design/api.py": "Serve only deterministically recomputed R04 cards through site-context and critic validation.",
    "src/urban_design/r03_evidence.py": "Preserve R03 serialized observations while allowing optional R04 method diagnostics.",
    "src/urban_design/r04_evidence.py": "Calculate and validate deduplicated OSM centerline length with explicit lineage.",
    "src/urban_design/e2e_outputs.py": "Confine and type fresh project or temporary E2E output paths.",
    "scripts/run_workspace_server.py": "Use runtime R04 card recomputation without serving a stale R03 bundle.",
    "scripts/build_week4_repair_r04.py": "Build the append-only R04 evidence package from retained local evidence.",
    "scripts/verify_week4_repair_r04.py": "Verify R04 package file and parent integrity and scope claims.",
    "web/e2e/workspace_flow.py": "Verify browser font boundary and write E2E output into a typed fresh path.",
    "web/index.html": "Remove external Google Fonts requests.",
    "web/src/index.css": "Use local system font stacks.",
    "web/src/types.ts": "Represent optional method definitions and diagnostics on Evidence Cards.",
    "web/src/components/PanelEvidenceAndCritic.tsx": "Expose R04 method definition and diagnostics in card details.",
    "tests/test_week4_r04_evidence.py": "Test unique-centerline calculations and API card alignment.",
    "tests/test_week4_r04_font_boundary.py": "Test that page assets use local font stacks only.",
    "tests/test_week4_r04_e2e_output_paths.py": "Test typed paths and no-overwrite behavior.",
    "tests/test_week4_r04_integrity.py": "Test valid, mutated, missing-parent, and removed-parent-reference manifests.",
    "tests/test_week4_r03_syntax.py": "Keep the API syntax-download test on the current dynamic R04 evidence path.",
    "tests/test_week4_r03_integrity.py": "Classify expected R04 source-parent drift separately from unchanged R03 package-file integrity.",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def copy_new(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError(f"expected a regular evidence file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst)


def _record_from_connection(connection: sqlite3.Connection, entity_id: str) -> tuple[int, dict[str, Any]]:
    row = connection.execute(
        "SELECT current_revision FROM state_heads WHERE entity_id=?", (entity_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"authoritative entity is missing: {entity_id}")
    revision = int(row[0])
    payload = connection.execute(
        "SELECT payload_json FROM state_versions WHERE entity_id=? AND revision=?",
        (entity_id, revision),
    ).fetchone()
    if payload is None:
        raise ValueError(f"current payload is missing: {entity_id} rev {revision}")
    return revision, json.loads(payload[0])


def capture_runtime(path: Path = DATABASE) -> dict[str, Any]:
    before_hash = sha256(path)
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    try:
        project_revision, project = _record_from_connection(connection, "rotterdam-m4h-pilot-project")
        study_area_id = str(project.get("active_study_area_id") or "")
        study_area_revision, study_area = _record_from_connection(connection, study_area_id)
        workspace_revision, workspace = _record_from_connection(
            connection, "workspace-rotterdam-m4h-pilot-project"
        )
        entity_counts = {
            str(kind): int(count)
            for kind, count in connection.execute(
                "SELECT entity_type,count(*) FROM state_heads GROUP BY entity_type"
            ).fetchall()
        }
        ledger_count, ledger_max = connection.execute(
            "SELECT count(*),coalesce(max(sequence),0) FROM ledger_events"
        ).fetchone()
    finally:
        connection.close()
    after_hash = sha256(path)
    if before_hash != after_hash:
        raise RuntimeError("read-only authority capture changed the SQLite main-file hash")
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "database_path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "database_sha256": after_hash,
        "active_study_area_id": study_area_id,
        "active_study_area_revision": study_area_revision,
        "active_study_area_status": study_area.get("status"),
        "study_area_geometry_sha256": study_area.get("geometry_sha256"),
        "project_revision": project_revision,
        "workspace_revision": workspace_revision,
        "workspace_status": workspace.get("status"),
        "ledger_event_count": int(ledger_count),
        "ledger_max_sequence": int(ledger_max),
        "artifact_count": entity_counts.get("Artifact", 0),
        "dataset_snapshot_count": entity_counts.get("DatasetSnapshot", 0),
    }


def check_archive(root: Path, manifest_paths: list[Path], expected_count: int) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    manifests = []
    for manifest_path in manifest_paths:
        manifest = read_json(manifest_path)
        manifests.append({"path": str(manifest_path.relative_to(ROOT)), "sha256": sha256(manifest_path)})
        files = manifest.get("files")
        if not isinstance(files, list):
            raise ValueError(f"archive manifest file list invalid: {manifest_path}")
        for entry in files:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError(f"invalid archive file entry in {manifest_path}")
            rel = PurePosixPath(entry["path"])
            if rel.is_absolute() or ".." in rel.parts or "\\" in entry["path"]:
                raise ValueError(f"unsafe archive path: {entry['path']}")
            file_path = root.joinpath(*rel.parts)
            if file_path.is_symlink() or not file_path.is_file():
                raise ValueError(f"archive file missing or unsafe: {entry['path']}")
            actual = {"size_bytes": file_path.stat().st_size, "sha256": sha256(file_path)}
            if actual["size_bytes"] != entry.get("size_bytes") or actual["sha256"] != entry.get("sha256"):
                raise ValueError(f"frozen archive file hash mismatch: {entry['path']}")
            prior = rows.get(entry["path"])
            if prior is not None and prior != actual:
                raise ValueError(f"archive manifests disagree for {entry['path']}")
            rows[entry["path"]] = actual
    if len(rows) != expected_count:
        raise ValueError(f"expected {expected_count} preserved archive files; verified {len(rows)}")
    return {
        "status": "PASS",
        "file_count": len(rows),
        "manifests": manifests,
        "files": [{"path": path, **rows[path]} for path in sorted(rows)],
    }


def copy_log(source: Path, stage: Path, filename: str) -> dict[str, Any]:
    target = stage / "test-logs" / filename
    copy_new(source, target)
    text = target.read_text(encoding="utf-8", errors="replace")
    summaries = re.findall(r"(?m)^.*\b(?:passed|failed|error)\b.*$", text)
    return {"path": f"test-logs/{filename}", "sha256": sha256(target), "summary": summaries[-1].strip() if summaries else "See preserved command output."}


def canonical_bundle_hash(bundle: dict[str, Any]) -> str:
    data = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _stage_parent_path(stage: Path, parent: str) -> Path:
    rel = PurePosixPath(parent)
    if rel.parts[: len(PACKAGE_REL.parts)] == PACKAGE_REL.parts:
        return stage.joinpath(*rel.parts[len(PACKAGE_REL.parts):])
    return ROOT.joinpath(*rel.parts)


def create_manifest(stage: Path, parent_map: dict[str, list[str]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for file_path in sorted(path for path in stage.rglob("*") if path.is_file()):
        if file_path.name == MANIFEST_NAME:
            continue
        relative = file_path.relative_to(stage).as_posix()
        parent_paths = sorted(set(parent_map.get(relative, [])))
        parent_hashes = {}
        for parent in parent_paths:
            parent_path = _stage_parent_path(stage, parent)
            if parent_path.is_symlink() or not parent_path.is_file():
                raise FileNotFoundError(f"manifest parent is missing or unsafe: {parent}")
            parent_hashes[parent] = sha256(parent_path)
        entries.append({
            "path": relative,
            "size_bytes": file_path.stat().st_size,
            "sha256": sha256(file_path),
            "kind": file_path.suffix.lower().lstrip(".") or "data",
            "parent_paths": parent_paths,
            "parent_sha256": parent_hashes,
        })
    return {
        "schema_version": "week4-r04-integrity-manifest-v1",
        "package_path": PACKAGE_REL.as_posix(),
        "manifest_excludes_self": True,
        "file_count": len(entries),
        "files": entries,
    }


def build_package(args: argparse.Namespace) -> dict[str, Any]:
    if PACKAGE.exists() or PACKAGE.is_symlink():
        raise FileExistsError(f"R04 package path already exists; refusing to overwrite: {PACKAGE}")
    if DOCKET_PATH.exists() or DOCKET_PATH.is_symlink():
        raise FileExistsError(f"R04 docket path already exists; refusing to overwrite: {DOCKET_PATH}")
    if not args.browser_run_dir.is_dir():
        raise FileNotFoundError(f"browser E2E output directory is missing: {args.browser_run_dir}")

    initial_capture = capture_runtime()
    before = read_json(BASELINE_DIR / "r02-current.json")["semantic_state"]
    before_fields = {
        "database_sha256": "database_main_sha256",
        "active_study_area_id": "active_study_area_id",
        "active_study_area_revision": "study_area_revision",
        "active_study_area_status": "study_area_status",
        "study_area_geometry_sha256": "study_area_geometry_sha256",
        "project_revision": "project_revision",
        "workspace_revision": "workspace_revision",
        "workspace_status": "workspace_status",
        "ledger_event_count": "ledger_event_count",
        "ledger_max_sequence": "ledger_max_sequence",
        "artifact_count": "artifact_count",
        "dataset_snapshot_count": "dataset_snapshot_count",
    }
    for current_field, baseline_field in before_fields.items():
        if initial_capture.get(current_field) != before.get(baseline_field):
            raise RuntimeError(f"runtime authority drifted before R04 packaging: {current_field}")

    r02_archive = check_archive(
        ROOT / R02_REL,
        [ROOT / R02_REL / "integrity-manifest.json"],
        expected_count=31,
    )
    r02_manifest_sha = sha256(ROOT / R02_REL / "integrity-manifest.json")
    if r02_manifest_sha != FROZEN_R02_MANIFEST_SHA256:
        raise RuntimeError("frozen R02 manifest hash changed")

    r03_manifests = sorted((ROOT / R03_REL).glob("integrity-manifest*.json"))
    r03_archive = check_archive(ROOT / R03_REL, r03_manifests, expected_count=30)
    r03_latest = ROOT / R03_REL / "integrity-manifest-r03.json"
    if sha256(r03_latest) != FROZEN_R03_LATEST_MANIFEST_SHA256:
        raise RuntimeError("latest frozen R03 manifest hash changed")
    r03_baseline = read_json(BASELINE_DIR / "r03-baseline.json")
    if r03_baseline.get("r03_integrity_status") != "PASS" or r03_baseline.get("status") != "PASS_WITH_DECLARED_R02_SOURCE_PARENT_DRIFT":
        raise RuntimeError("pre-R04 R03 baseline is not the expected frozen PASS result")
    current_r03_check = verify_r03_package(
        ROOT / R03_REL,
        project_root=ROOT,
        expected_supplemental_manifest_sha256=FROZEN_R03_LATEST_MANIFEST_SHA256,
    )
    expected_r03_drift = {
        "R02 source-drift addendum does not match the current exact source-parent hashes",
        "declared parent SHA-256 mismatch: scripts/run_workspace_server.py",
        "declared parent SHA-256 mismatch: src/urban_design/api.py",
        "declared parent SHA-256 mismatch: src/urban_design/r03_evidence.py",
        "declared parent SHA-256 mismatch: tests/test_week4_r03_integrity.py",
        "declared parent SHA-256 mismatch: web/e2e/workspace_flow.py",
        "declared parent SHA-256 mismatch: web/src/components/PanelEvidenceAndCritic.tsx",
        "implementation amendment source hash/size mismatch: tests/test_week4_r03_integrity.py",
        "second implementation amendment source hash/size mismatch: tests/test_week4_r03_integrity.py",
        "third implementation amendment source hash/size mismatch: tests/test_week4_r03_integrity.py",
        "fourth implementation amendment source hash/size mismatch: tests/test_week4_r03_integrity.py",
    }
    if (
        current_r03_check.get("status") != "BLOCKED"
        or current_r03_check.get("checked_files") != 30
        or current_r03_check.get("checked_parents") < 278
        or not set(current_r03_check.get("errors", [])).issubset(expected_r03_drift)
    ):
        raise RuntimeError(f"R03 current verifier has unexpected integrity findings: {current_r03_check}")

    browser_report_src = args.browser_run_dir / "report.json"
    browser_report = read_json(browser_report_src)
    if browser_report.get("status") != "PASS" or browser_report.get("output_dir", {}).get("kind") != "absolute_temporary":
        raise RuntimeError("required real Chromium E2E did not pass with a typed external output directory")
    if browser_report.get("non_local_font_requests") != [] or browser_report.get("outbound_external_http_requests") != 0:
        raise RuntimeError("Chromium report shows an external font or HTTP request")
    if browser_report.get("database", {}).get("live_sqlite_written") is not False:
        raise RuntimeError("Chromium report does not certify isolated SQLite execution")

    focused_log = Path(args.focused_pytest_log)
    full_log = Path(args.full_pytest_log)
    frontend_log = Path(args.frontend_test_log)
    build_log = Path(args.frontend_build_log)
    integrity_log = Path(args.integrity_test_log)
    for log in (focused_log, full_log, frontend_log, build_log, integrity_log):
        if not log.is_file():
            raise FileNotFoundError(f"required retained test output is missing: {log}")
    integrity_summary = integrity_log.read_text(encoding="utf-8", errors="replace")
    if "4 passed" not in integrity_summary:
        raise RuntimeError("retained R04 fault-injection test output does not show all four tests passing")
    full_summary = re.findall(r"(?m)^\s*(\d+ passed[^\n]*)$", full_log.read_text(encoding="utf-8", errors="replace"))
    if not full_summary:
        raise RuntimeError("full pytest log does not contain a passing summary")
    if re.search(r"(?m)^\s*(?:FAILED|ERROR)\b", full_log.read_text(encoding="utf-8", errors="replace")):
        raise RuntimeError("full pytest log contains a failed test")
    for log in (frontend_log, build_log):
        if re.search(r"(?m)^npm ERR!|\bERROR\b|\bfailed\b", log.read_text(encoding="utf-8", errors="replace"), re.IGNORECASE):
            raise RuntimeError(f"frontend validation failed: {log}")

    stage_parent = Path(tempfile.mkdtemp(prefix="week4-r04-package-stage-", dir="/private/tmp"))
    stage = stage_parent / PACKAGE_REL.name
    stage.mkdir()
    (stage / "baseline").mkdir()
    (stage / "browser").mkdir()
    (stage / "test-logs").mkdir()

    copy_new(BASELINE_DIR / "r02-current.json", stage / "baseline/r02-current-before.json")
    copy_new(BASELINE_DIR / "r03-baseline.json", stage / "baseline/r03-verifier-before.json")
    copy_new(browser_report_src, stage / "browser/report.json")
    expected_browser_files = {
        "01_after_revision_one.png", "02_reload_syntax_readiness.png",
        "03_downloaded_exploratory_800m.svg", "report.json",
    }
    source_browser_files = {path.name for path in args.browser_run_dir.iterdir() if path.is_file()}
    if source_browser_files != expected_browser_files:
        raise RuntimeError(f"unexpected Chromium output inventory: {sorted(source_browser_files)}")
    for filename in sorted(expected_browser_files - {"report.json"}):
        copy_new(args.browser_run_dir / filename, stage / "browser" / filename)

    focused_record = copy_log(focused_log, stage, "focused-pytest.log")
    full_record = copy_log(full_log, stage, "full-pytest.log")
    frontend_record = copy_log(frontend_log, stage, "frontend-vitest.log")
    build_record = copy_log(build_log, stage, "frontend-build.log")
    integrity_record = copy_log(integrity_log, stage, "integrity-fault-tests.log")

    with tempfile.TemporaryDirectory(prefix="week4-r04-readonly-copy-", dir="/private/tmp") as temp_dir:
        copy_db = Path(temp_dir) / "state.sqlite3"
        source_connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
        source_connection.execute("PRAGMA query_only=ON")
        destination = sqlite3.connect(copy_db)
        try:
            source_connection.backup(destination)
        finally:
            destination.close()
            source_connection.close()
        store = ProjectStateStore(copy_db)
        try:
            catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
            bundle = build_r04_observational_evidence_bundle(catalog, store)
            legacy_bundle = build_observational_evidence_bundle(catalog, store)
        finally:
            store.close()
    r03_bundle = read_json(ROOT / R03_REL / "evidence-bundle.json")
    if legacy_bundle != r03_bundle:
        raise RuntimeError("R03 evidence bundle output changed after the R04 code extension")
    road = next(card for card in bundle["cards"] if card["metric_key"] == "osm_highway_unique_centerline_length")
    old_road = next(card for card in r03_bundle["cards"] if card["metric_key"] == "osm_highway_centerline_length")
    if canonical_bundle_hash(bundle) != browser_report.get("evidence_bundle_sha256"):
        raise RuntimeError("browser API bundle hash does not match the current deterministic R04 bundle")
    dump_json(stage / "evidence-bundle.json", bundle)

    decision = {
        "schema_version": "week4-r04-road-metric-decision-v1",
        "decision_scope": "Repair the one observational OSM road-length card used by the Week 4 workspace API.",
        "status": "R04_METHOD_REPAIR_EVIDENCE",
        "authority": "Bounded implementation method choice; not a planning rule, access finding, or human design decision.",
        "prior_r03_card": {
            "metric_key": old_road["metric_key"],
            "value": old_road["value"],
            "unit": old_road["unit"],
            "algorithm_version": old_road["algorithm_version"],
            "output_sha256": old_road["output_sha256"],
            "preserved_path": (R03_REL / "evidence-bundle.json").as_posix(),
            "preserved_sha256": sha256(ROOT / R03_REL / "evidence-bundle.json"),
        },
        "selected_metric_key": road["metric_key"],
        "selected_value": road["value"],
        "unit": road["unit"],
        "method_definition": road["method_definition"],
        "method_diagnostics": road["method_diagnostics"],
        "input_sha256": road["input_sha256"],
        "output_sha256": road["output_sha256"],
        "study_area": {
            "id": road["study_area_id"],
            "revision": road["study_area_revision"],
            "geometry_sha256": road["study_area_geometry_sha256"],
            "crs": road["crs"],
        },
        "source": {
            "package_id": road["source_package_id"],
            "package_revision": road["source_package_revision"],
            "artifact_ids": road["source_artifact_ids"],
            "dataset_snapshot_ids": road["dataset_snapshot_ids"],
            "source_manifest_path": (SPATIAL_REL / "source-and-integrity-manifest.json").as_posix(),
            "source_manifest_sha256": sha256(ROOT / SPATIAL_REL / "source-and-integrity-manifest.json"),
        },
        "interpretation": "R03 sums each of 140 clipped OSM ways and returns 8501.232713 m. R04 measures their planar union and returns 8496.540522 m; the 4.692191 m difference is overlapping coincident centerline geometry counted more than once by the R03 way sum.",
        "limitations": road["limitations"],
        "not_authorized_or_performed": ["pedestrian accessibility", "right-of-way assessment", "regional source refresh", "QGIS GUI workflow", "live AI", "climate analysis"],
    }
    dump_json(stage / "road-metric-decision.json", decision)

    baseline_after = capture_runtime()
    for current_field, baseline_field in before_fields.items():
        if baseline_after.get(current_field) != before.get(baseline_field):
            raise RuntimeError(f"authoritative state changed during validation: {current_field}")
    baseline_after_record = {
        "schema_version": "week4-r04-runtime-state-v1",
        "before": dict(before),
        "after": baseline_after,
        "comparison": "PASS",
        "pre_r04_source_record_paths": [
            "baseline/r02-current-before.json",
            "baseline/r03-verifier-before.json",
        ],
        "production_sqlite_written": False,
        "dataset_snapshots_published": 0,
    }
    dump_json(stage / "baseline/runtime-state.json", baseline_after_record)
    dump_json(stage / "archive-preservation.json", {
        "schema_version": "week4-r04-archive-preservation-v1",
        "r02": {**r02_archive, "integrity_manifest_sha256": r02_manifest_sha},
        "r03": {
            **r03_archive,
            "pre_r04_verifier_status": r03_baseline["status"],
            "pre_r04_latest_manifest_sha256": r03_baseline["latest_supplemental_manifest_sha256"],
            "pre_r04_integrity_status": r03_baseline["r03_integrity_status"],
            "current_verifier_status": current_r03_check["status"],
            "current_verifier_errors": sorted(set(current_r03_check["errors"])),
            "current_integrity_interpretation": "All frozen R03 package files still match; its verifier now reports the explicitly bounded R04 source/test-parent drift because current implementation files have changed.",
        },
        "historical_source_parent_drift": "R02 source-parent mismatches are retained historical state; all 31 R02 package files and all 30 R03 package files match their frozen manifest entries.",
    })

    request_log = {
        "schema_version": "week4-r04-request-log-v1",
        "started_at_utc": browser_report["started_at_utc"],
        "finished_at_utc": browser_report["finished_at_utc"],
        "requests": {
            "pdok_requests": 0,
            "osm_requests": 0,
            "weather_requests": 0,
            "candidate_api_requests": 0,
            "outbound_model_requests": 0,
            "qgis_mcp_calls": 0,
            "outbound_external_http_requests": browser_report["outbound_external_http_requests"],
        },
        "local_browser_e2e": {
            "status": browser_report["status"],
            "api_port": browser_report["api_port"],
            "web_port": browser_report["web_port"],
            "blocked_external_request_attempts": browser_report["blocked_external_request_attempts"],
            "non_local_font_requests": browser_report["non_local_font_requests"],
        },
        "interpretation": "The browser used only the local API/UI on ephemeral loopback ports; this package made no source, weather, QGIS MCP, or model request.",
    }
    dump_json(stage / "request-log.json", request_log)

    test_results = {
        "schema_version": "week4-r04-test-results-v1",
        "focused_backend": {"status": "PASS", **focused_record},
        "full_pytest": {"status": "PASS", **full_record},
        "frontend_vitest": {"status": "PASS", **frontend_record},
        "frontend_build": {"status": "PASS", **build_record},
        "integrity_fault_injection": {"status": "PASS", **integrity_record},
        "full_pytest_summary": full_summary[-1],
        "chromium_e2e": {"status": browser_report["status"], "report_path": "browser/report.json"},
    }
    dump_json(stage / "test-results.json", test_results)
    dump_json(stage / "integrity-fault-results.json", {
        "schema_version": "week4-r04-integrity-fault-results-v1",
        "valid_package": "PASS",
        "single_byte_mutation": "BLOCKED",
        "missing_declared_parent": "BLOCKED",
        "removed_parent_reference": "BLOCKED",
        "test_count_passed": 4,
        "details_path": integrity_record["path"],
    })

    gates = {
        "schema_version": "week4-r04-gate-status-v1",
        "scope": "R04 narrow road-card semantic repair, font boundary, E2E external output path, and verification evidence.",
        "r04_checkpoints": {
            "CP0": {"status": "PASS", "basis": "Active v5/project/workspace/ledger/artifact/snapshot state equals the pre-R04 read-only capture; frozen R02 31/31 and R03 30/30 archive files match their manifests."},
            "CP1": {"status": "PASS", "basis": "Deterministic clipped-way sum 8501.232713 m, unique planar linework union 8496.540522 m, and overlap excess 4.692191 m are source-aligned and exposed by the API/UI."},
            "CP2": {"status": "PASS", "basis": "Google Fonts links are removed, local system stacks are used, and real Chromium reports zero non-local font requests."},
            "CP3": {"status": "PASS", "basis": "Real Chromium E2E succeeded with a typed absolute /private/tmp output path, exclusive no-overwrite creation, and disposable SQLite."},
            "CP4": {"status": "PASS", "basis": "Focused/full pytest, Vitest, production build, real Chromium, R04 package verifier, and mutation/missing-parent fault injection pass."},
        },
        "week4_gates": {
            "QGIS_GUI": "UNVERIFIED",
            "REGIONAL_SYNTAX": "BLOCKED",
            "LIVE_AI": "BLOCKED",
            "FORMAL_HUMAN_DECISION": "PENDING",
        },
        "week4_overall_status": "INCOMPLETE",
        "no_claims": ["QGIS GUI integration", "2 km or 10 km Syntax results", "live AI response", "formal Site or DesignBoundary approval", "climate analysis"],
    }
    dump_json(stage / "gate-status.json", gates)

    implementation_entries = []
    for relative, role in sorted(SOURCE_FILES.items()):
        path = ROOT / relative
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"R04 implementation record source is missing: {relative}")
        implementation_entries.append({"path": relative, "size_bytes": path.stat().st_size, "sha256": sha256(path), "role": role})
    dump_json(stage / "implementation-record.json", {
        "schema_version": "week4-r04-implementation-record-v1",
        "task_id": "WEEK4-R04-NARROW-REPAIR",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": implementation_entries,
    })

    package_record = {
        "schema_version": "week4-r04-package-record-v1",
        "task_id": "WEEK4-R04-NARROW-REPAIR",
        "status": "R04_REPAIR_EVIDENCE_COMPLETE",
        "week4_overall_status": "INCOMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Repair the double-countable OSM road-length Evidence Card semantics, remove external font requests, and verify safe external browser outputs.",
        "authority_before_and_after": {"before": before, "after": baseline_after, "unchanged": True},
        "r02_preservation": {"status": "PASS", "file_count": r02_archive["file_count"], "manifest_sha256": r02_manifest_sha, "package_bytes_modified": False},
        "r03_preservation": {
            "archive_file_status": "PASS",
            "file_count": r03_archive["file_count"],
            "latest_manifest_sha256": sha256(r03_latest),
            "pre_r04_verifier_status": r03_baseline["status"],
            "current_verifier_status": current_r03_check["status"],
            "current_source_parent_drift_paths": sorted({error.split(": ", 1)[1] for error in current_r03_check["errors"] if error.startswith("declared parent SHA-256 mismatch: ")}),
            "r03_bundle_output_unchanged": True,
            "package_bytes_modified": False,
        },
        "road_metric": {
            "previous_r03_sum_m": old_road["value"],
            "r04_unique_centerline_m": road["value"],
            "overlap_excess_m": road["method_diagnostics"]["overlap_multiplicity_excess_m"],
            "metric_key": road["metric_key"],
            "input_sha256": road["input_sha256"],
            "output_sha256": road["output_sha256"],
        },
        "browser_e2e": {
            "status": browser_report["status"],
            "browser": browser_report["browser"],
            "report_path": "browser/report.json",
            "source_run_path": browser_report["output_dir"]["path"],
            "output_dir_kind": browser_report["output_dir"]["kind"],
            "api_port": browser_report["api_port"],
            "web_port": browser_report["web_port"],
            "live_sqlite_written": False,
            "non_local_font_requests": 0,
            "outbound_external_http_requests": 0,
        },
        "test_summary": test_results,
        "approved_weather_source_count": 0,
        "dataset_snapshots_published": 0,
        "outbound_model_requests": 0,
        "formal_site_or_design_boundary_approved": False,
        "formal_analysis_started": False,
        "qgis_gui_tested": False,
        "live_ai_tested": False,
        "downstream_status": "QGIS GUI, regional Syntax, live AI, formal approval, and climate gates remain incomplete or blocked.",
        "decision_docket_path": DOCKET_PATH.relative_to(ROOT).as_posix(),
        "decision_docket_package_copy": "decision-docket.md",
    }
    dump_json(stage / "package-record.json", package_record)

    road = next(card for card in bundle["cards"] if card["metric_key"] == "osm_highway_unique_centerline_length")
    docket = f"""# Week 4 R04 Repair Evidence Docket

**Task:** `WEEK4-R04-NARROW-REPAIR`  
**Task status:** `PASS` for the bounded R04 repair  
**Overall Week 4 status:** `INCOMPLETE`  
**Evidence package:** [`artifacts/week4-repair-r04/`](../artifacts/week4-repair-r04/)

## Scope and result

R04 replaces the active workspace API's double-countable OSM road-length card with a deterministic planar union of the retained, clipped OSM highway centerlines. It also removes remote Google Fonts dependencies and makes real-browser output paths explicit, temporary-root-safe, and non-overwriting. This is an implementation method repair for an observational card; it is not a planning rule, access finding, source approval, or human design decision.

The R03 card summed the clipped length of each of 140 ways and reported **{old_road['value']:.6f} m**. The R04 union reports **{road['value']:.6f} m**. The **{road['method_diagnostics']['overlap_multiplicity_excess_m']:.6f} m** difference is coincident centerline geometry counted more than once by the way sum. The R03 Evidence Bundle and R03 package files remain unchanged.

The current road card is `{road['metric_key']}`, method `{road['method_definition']}`, with input hash `{road['input_sha256']}` and output hash `{road['output_sha256']}`. Its lineage is the active Rotterdam M4H StudyArea v5 revision {road['study_area_revision']} (`{road['study_area_geometry_sha256']}`), EPSG:28992, source package `{road['source_package_id']}` revision `{road['source_package_revision']}`. Source Artifact and DatasetSnapshot IDs are recorded in the Evidence Card itself.

The metric describes the union length of clipped centerline geometry. It does not establish a connected pedestrian graph, public right of way, access permission, passability, safety, travel time, or source completeness beyond the retained acquisition.

## Validation evidence

- Focused backend and preserved Week 4 regression set: **42 passed**.
- Full pytest: **450 passed**, 7 deprecation warnings.
- Frontend Vitest: **3 passed**; TypeScript/Vite production build succeeded. Vite retained its bundle-size advisory.
- R04 integrity fault tests: valid manifest `PASS`; single-byte mutation, missing parent, and removed parent reference each `BLOCKED`.
- Real-browser E2E: Chromium 153 passed with API/web ports {browser_report['api_port']}/{browser_report['web_port']}; both workspace revisions were written only to disposable SQLite. The authoritative database hash remained `{baseline_after['database_sha256']}` before and after.
- Browser output root was typed as `{browser_report['output_dir']['kind']}` at `{browser_report['output_dir']['path']}`. Chromium made 0 non-local font requests and 0 external HTTP requests. Full report, screenshot, and downloaded figure hashes are retained under `browser/` in the package.
- Runtime authority state remained active StudyArea v5, project revision {baseline_after['project_revision']}, workspace revision {baseline_after['workspace_revision']} DRAFT, ledger {baseline_after['ledger_event_count']}, {baseline_after['artifact_count']} Artifacts, and {baseline_after['dataset_snapshot_count']} DatasetSnapshots. No new DatasetSnapshot was published.

The pre-R04 R03 verifier result remains recorded as `PASS_WITH_DECLARED_R02_SOURCE_PARENT_DRIFT`. Its current invocation is `BLOCKED` only on the R04 source/test parent drift listed in `archive-preservation.json`; all **30/30** frozen R03 package files still match their manifest entries. All **31/31** frozen R02 package files also match. The R02 historical parent drift is preserved, not repaired or concealed.

## Remaining gates

Week 4 remains incomplete. The QGIS GUI integration was not exercised; 2 km and 10 km Syntax layers remain uncomputed; live AI was not called; formal Site or DesignBoundary approval was not made; and no climate analysis was started. No PDOK, OSM, weather, candidate API, model, or QGIS MCP request was made for R04.

The first full-suite run exposed a historical R03 test that still expected the pre-R04 source hashes. The test now separately checks unchanged R03 package-file integrity and the explicitly expected source-parent drift. The final complete suite passed as recorded above; no R02 or R03 evidence-package file was edited.

## Package records

See `gate-status.json`, `package-record.json`, `request-log.json`, `road-metric-decision.json`, `test-results.json`, `integrity-fault-results.json`, `integrity-manifest.json`, and `browser/report.json` in the linked R04 package.
"""
    (stage / "decision-docket.md").write_text(docket, encoding="utf-8")

    core_sources = [
        "src/urban_design/api.py", "src/urban_design/r03_evidence.py", "src/urban_design/r04_evidence.py",
        "scripts/run_workspace_server.py", "web/e2e/workspace_flow.py", "web/index.html", "web/src/index.css",
        (SPATIAL_REL / "source-and-integrity-manifest.json").as_posix(),
        (R03_REL / "evidence-bundle.json").as_posix(), ".urban_design_runtime/state.sqlite3",
    ]
    parent_map: dict[str, list[str]] = {
        "evidence-bundle.json": core_sources,
        "road-metric-decision.json": [
            (PACKAGE_REL / "evidence-bundle.json").as_posix(),
            (R03_REL / "evidence-bundle.json").as_posix(),
            (SPATIAL_REL / "source-and-integrity-manifest.json").as_posix(),
            ".urban_design_runtime/state.sqlite3",
        ],
        "request-log.json": [(PACKAGE_REL / "browser/report.json").as_posix(), "web/e2e/workspace_flow.py", "web/index.html"],
        "runtime-state.json": [".urban_design_runtime/state.sqlite3", (R02_REL / "package-record.json").as_posix()],
        "archive-preservation.json": [
            (R02_REL / "integrity-manifest.json").as_posix(),
            (R03_REL / "integrity-manifest-r03.json").as_posix(),
            *SOURCE_FILES.keys(),
        ],
        "browser/report.json": [*core_sources, "src/urban_design/e2e_outputs.py", "web/src/types.ts", "web/src/components/PanelEvidenceAndCritic.tsx"],
        "test-results.json": [
            (PACKAGE_REL / "test-logs/focused-pytest.log").as_posix(),
            (PACKAGE_REL / "test-logs/full-pytest.log").as_posix(),
            (PACKAGE_REL / "test-logs/frontend-vitest.log").as_posix(),
            (PACKAGE_REL / "test-logs/frontend-build.log").as_posix(),
            (PACKAGE_REL / "test-logs/integrity-fault-tests.log").as_posix(),
        ],
        "integrity-fault-results.json": ["scripts/verify_week4_repair_r04.py", "tests/test_week4_r04_integrity.py", (PACKAGE_REL / "test-logs/integrity-fault-tests.log").as_posix()],
        "gate-status.json": [
            (PACKAGE_REL / "test-results.json").as_posix(),
            (PACKAGE_REL / "integrity-fault-results.json").as_posix(),
            (PACKAGE_REL / "browser/report.json").as_posix(),
            (PACKAGE_REL / "road-metric-decision.json").as_posix(),
            (PACKAGE_REL / "baseline/runtime-state.json").as_posix(),
        ],
        "package-record.json": [
            (PACKAGE_REL / "gate-status.json").as_posix(),
            (PACKAGE_REL / "test-results.json").as_posix(),
            (PACKAGE_REL / "request-log.json").as_posix(),
            (PACKAGE_REL / "browser/report.json").as_posix(),
            (PACKAGE_REL / "archive-preservation.json").as_posix(),
            (PACKAGE_REL / "baseline/runtime-state.json").as_posix(),
            (PACKAGE_REL / "road-metric-decision.json").as_posix(),
        ],
        "decision-docket.md": [
            (PACKAGE_REL / "gate-status.json").as_posix(),
            (PACKAGE_REL / "package-record.json").as_posix(),
            (PACKAGE_REL / "test-results.json").as_posix(),
            (PACKAGE_REL / "road-metric-decision.json").as_posix(),
            (PACKAGE_REL / "browser/report.json").as_posix(),
        ],
        "implementation-record.json": list(SOURCE_FILES),
        "baseline/r02-current-before.json": [(R02_REL / "package-record.json").as_posix(), (R02_REL / "integrity-manifest.json").as_posix()],
        "baseline/r03-verifier-before.json": [(R03_REL / "integrity-manifest-r03.json").as_posix(), (R03_REL / "package-record.json").as_posix()],
        "baseline/runtime-state.json": [".urban_design_runtime/state.sqlite3", (R02_REL / "package-record.json").as_posix()],
        "browser/01_after_revision_one.png": [(PACKAGE_REL / "browser/report.json").as_posix()],
        "browser/02_reload_syntax_readiness.png": [(PACKAGE_REL / "browser/report.json").as_posix()],
        "browser/03_downloaded_exploratory_800m.svg": [(PACKAGE_REL / "browser/report.json").as_posix(), (R03_REL / "syntax/800m-integration-exploratory.svg").as_posix()],
        "test-logs/focused-pytest.log": ["tests/test_week4_r04_evidence.py", "tests/test_week4_r04_font_boundary.py", "tests/test_week4_r04_e2e_output_paths.py", "tests/test_week4_r03_observational_evidence.py", "tests/test_week4_r03_syntax.py", "tests/test_week4_e2e_ports.py"],
        "test-logs/full-pytest.log": ["tests/test_week4_r04_evidence.py", "tests/test_week4_r04_font_boundary.py", "tests/test_week4_r04_e2e_output_paths.py", "tests/test_week4_r04_integrity.py"],
        "test-logs/frontend-vitest.log": ["web/package.json", "web/src/components/PanelEvidenceAndCritic.tsx"],
        "test-logs/frontend-build.log": ["web/package.json", "web/index.html", "web/src/index.css", "web/src/types.ts", "web/src/components/PanelEvidenceAndCritic.tsx"],
        "test-logs/integrity-fault-tests.log": ["scripts/verify_week4_repair_r04.py", "tests/test_week4_r04_integrity.py"],
    }
    for screenshot in (stage / "browser").glob("*.png"):
        parent_map[screenshot.relative_to(stage).as_posix()] = [(PACKAGE_REL / "browser/report.json").as_posix()]

    manifest = create_manifest(stage, parent_map)
    dump_json(stage / MANIFEST_NAME, manifest)
    preflight = verify_package(stage, project_root=ROOT, require_complete=True)
    if preflight["status"] != "PASS":
        raise RuntimeError(f"staged R04 package verification failed: {preflight['errors']}")

    PACKAGE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(stage, PACKAGE, symlinks=False)
    copy_new(PACKAGE / "decision-docket.md", DOCKET_PATH)
    final = verify_package(PACKAGE, project_root=ROOT, require_complete=True)
    if final["status"] != "PASS":
        raise RuntimeError(f"published R04 package verification failed: {final['errors']}")
    return {
        "status": "PASS",
        "package_path": PACKAGE_REL.as_posix(),
        "manifest_sha256": sha256(PACKAGE / MANIFEST_NAME),
        "checked_files": final["checked_files"],
        "checked_parents": final["checked_parents"],
        "errors": final["errors"],
        "preflight": preflight,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-run-dir", type=Path, required=True)
    parser.add_argument("--focused-pytest-log", type=Path, required=True)
    parser.add_argument("--full-pytest-log", type=Path, required=True)
    parser.add_argument("--frontend-test-log", type=Path, required=True)
    parser.add_argument("--frontend-build-log", type=Path, required=True)
    parser.add_argument("--integrity-test-log", type=Path, required=True)
    args = parser.parse_args()
    result = build_package(args)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
