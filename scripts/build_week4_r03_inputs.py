#!/usr/bin/env python3
"""Build the R03 observational bundle and figure record from existing inputs only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from urban_design.r03_evidence import build_observational_evidence_bundle
from urban_design.r03_syntax import load_verified_exploratory_syntax
from urban_design.store import ProjectStateStore
from urban_design.workspace_sources import DEFAULT_SPATIAL_R01_ROOT, WorkspaceSourceCatalog


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts/week4-repair-r03"
DATABASE = ROOT / ".urban_design_runtime/state.sqlite3"
SYNTAX_OUTPUT = PACKAGE / "syntax/800m-integration-exploratory.png"
SYNTAX_SVG = SYNTAX_OUTPUT.with_suffix(".svg")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"append-only R03 output already exists: {path.relative_to(ROOT)}")
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_only_state_summary(path: Path) -> dict[str, object]:
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        project = connection.execute(
            "SELECT current_revision FROM state_heads WHERE entity_id=? AND entity_type='Project'",
            ("rotterdam-m4h-pilot-project",),
        ).fetchone()
        project_payload = json.loads(connection.execute(
            "SELECT payload_json FROM state_versions WHERE entity_id=? AND entity_type='Project' AND revision=?",
            ("rotterdam-m4h-pilot-project", project[0]),
        ).fetchone()[0])
        area_id = project_payload["active_study_area_id"]
        area = connection.execute(
            "SELECT current_revision FROM state_heads WHERE entity_id=? AND entity_type='StudyArea'", (area_id,)
        ).fetchone()
        area_payload = json.loads(connection.execute(
            "SELECT payload_json FROM state_versions WHERE entity_id=? AND entity_type='StudyArea' AND revision=?",
            (area_id, area[0]),
        ).fetchone()[0])
        workspace_id = "workspace-rotterdam-m4h-pilot-project"
        workspace = connection.execute(
            "SELECT current_revision FROM state_heads WHERE entity_id=? AND entity_type='WorkspaceRevision'", (workspace_id,)
        ).fetchone()
        workspace_payload = json.loads(connection.execute(
            "SELECT payload_json FROM state_versions WHERE entity_id=? AND entity_type='WorkspaceRevision' AND revision=?",
            (workspace_id, workspace[0]),
        ).fetchone()[0])
        ledger_count, ledger_max = connection.execute(
            "SELECT count(*), COALESCE(max(sequence),0) FROM ledger_events"
        ).fetchone()
        snapshots = connection.execute("SELECT count(*) FROM state_heads WHERE entity_type='DatasetSnapshot'").fetchone()[0]
        artifacts = connection.execute("SELECT count(*) FROM state_heads WHERE entity_type='Artifact'").fetchone()[0]
        return {
            "database_path": str(path.relative_to(ROOT)),
            "database_size_bytes": path.stat().st_size,
            "database_sha256": sha256(path),
            "project_id": "rotterdam-m4h-pilot-project",
            "project_revision": int(project[0]),
            "active_study_area_id": area_id,
            "study_area_revision": int(area[0]),
            "study_area_status": area_payload.get("status"),
            "study_area_geometry_sha256": area_payload.get("geometry_sha256"),
            "workspace_id": workspace_id,
            "workspace_revision": int(workspace[0]),
            "workspace_status": workspace_payload.get("status"),
            "ledger_event_count": int(ledger_count),
            "ledger_max_sequence": int(ledger_max),
            "dataset_snapshot_count": int(snapshots),
            "artifact_count": int(artifacts),
        }
    finally:
        connection.close()


def main() -> None:
    if not DATABASE.is_file():
        raise FileNotFoundError("authoritative SQLite database is missing")
    if not SYNTAX_OUTPUT.is_file() or not SYNTAX_SVG.is_file():
        raise FileNotFoundError("R03 exploratory Syntax SVG and PNG must be rendered before building records")
    before = read_only_state_summary(DATABASE)

    with tempfile.TemporaryDirectory(prefix="week4-r03-evidence-", dir="/private/tmp") as temporary:
        disposable_db = Path(temporary) / "state.sqlite3"
        with sqlite3.connect(DATABASE.resolve().as_uri() + "?mode=ro", uri=True) as source:
            source.execute("PRAGMA query_only=ON")
            with sqlite3.connect(disposable_db) as destination:
                source.backup(destination)
        store = ProjectStateStore(disposable_db)
        try:
            catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
            bundle = build_observational_evidence_bundle(catalog, store)
            syntax = load_verified_exploratory_syntax(ROOT, catalog)
        finally:
            store.close()

    write_once(PACKAGE / "evidence-bundle.json", bundle)
    summary = {
        "schema_version": "week4-r03-syntax-summary-v1",
        "status": syntax["status"],
        "package_id": syntax["package_id"],
        "package_revision": syntax["package_revision"],
        "study_area_id": syntax["study_area_id"],
        "study_area_geometry_sha256": syntax["study_area_geometry_sha256"],
        "r02_integrity_manifest_sha256": syntax["r02_integrity_manifest_sha256"],
        "source_manifest_sha256": syntax["source_manifest_sha256"],
        "syntax_result_sha256": syntax["syntax_result_sha256"],
        "layer_plan": syntax["layer_plan"],
        "figure_lineage": syntax["figure"],
        "limitations": syntax["limitations"],
    }
    write_once(PACKAGE / "syntax/syntax-status.json", summary)
    figure_record = {
        "schema_version": "week4-r03-exploratory-figure-v1",
        "status": "EXPLORATORY_RENDERED",
        "formal_result_eligible": False,
        "exploratory_only": True,
        "warning": syntax["figure"]["warning"],
        "project_id": catalog.project_id,
        "source_package_id": catalog.package_id,
        "source_package_revision": catalog.package_revision,
        "study_area_id": catalog.study_area_id,
        "study_area_geometry_sha256": catalog.study_area_geometry_sha256,
        "r02_integrity_manifest_sha256": syntax["r02_integrity_manifest_sha256"],
        "source_manifest_sha256": syntax["source_manifest_sha256"],
        "syntax_result_sha256": syntax["syntax_result_sha256"],
        "mapping": {
            "mapped_segment_count": syntax["figure"]["mapped_segment_count"],
            "display_segment_count": syntax["figure"]["display_segment_count"],
            "mapped_display_segment_count": syntax["figure"]["mapped_display_segment_count"],
            "display_mapping_coverage_pct": syntax["figure"]["display_mapping_coverage_pct"],
            "uncomputed_radii_m": [2000, 10000],
        },
        "files": {
            "svg": {
                "path": str(SYNTAX_SVG.relative_to(ROOT)),
                "size_bytes": SYNTAX_SVG.stat().st_size,
                "sha256": sha256(SYNTAX_SVG),
            },
            "png": {
                "path": str(SYNTAX_OUTPUT.relative_to(ROOT)),
                "size_bytes": SYNTAX_OUTPUT.stat().st_size,
                "sha256": sha256(SYNTAX_OUTPUT),
            },
        },
    }
    write_once(PACKAGE / "syntax/figure-record.json", figure_record)
    after = read_only_state_summary(DATABASE)
    if before != after:
        raise RuntimeError("authoritative SQLite state changed while generating R03 evidence")
    write_once(PACKAGE / "runtime-state-before.json", before)
    write_once(PACKAGE / "runtime-state-after.json", after)
    print(json.dumps({
        "status": "PASS",
        "cards": len(bundle["cards"]),
        "syntax_computed": [item["layer_id"] for item in syntax["layer_plan"] if item["calculation_status"] == "COMPUTED"],
        "syntax_uncomputed": [item["layer_id"] for item in syntax["layer_plan"] if item["calculation_status"] != "COMPUTED"],
        "figure_record": str((PACKAGE / "syntax/figure-record.json").relative_to(ROOT)),
        "authoritative_database_hash_unchanged": before["database_sha256"] == after["database_sha256"],
        "ledger_before_after": [before["ledger_event_count"], after["ledger_event_count"]],
    }, indent=2))


if __name__ == "__main__":
    main()

