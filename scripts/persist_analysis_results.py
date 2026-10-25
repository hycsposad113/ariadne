#!/usr/bin/env python3
"""Persist verified WC-2 analysis to a disposable DB copy by default.

Authority writes require --write-authority plus the exact expected DB SHA-256.
The script never fetches sources or computes GIS/PST metrics.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence
from uuid import uuid4

from shapely.geometry import LineString, shape

from urban_design.analysis_persistence import (
    get_persisted_site_analysis,
    get_persisted_syntax_bundle,
    persist_site_analysis_bundle,
    persist_syntax_bundle,
)
from urban_design.geometry import canonical_geometry_hash
from urban_design.models import (
    ActorKind,
    Artifact,
    DatasetSnapshot,
    EvidenceCard,
)
from urban_design.pst_syntax import prepare_pst_lines
from urban_design.r03_syntax import load_verified_exploratory_syntax
from urban_design.r04_evidence import build_r04_observational_evidence_bundle
from urban_design.syntax_engines.pst_adapter import PSTAdapter, PSTRequest
from urban_design.store import EntityNotFoundError, ProjectStateStore
from urban_design.three_d_bag import (
    append_snapshot_registration_to_store,
    build_snapshot_registration_bundle,
)
from urban_design.workspace_sources import DEFAULT_SPATIAL_R01_ROOT, WorkspaceSourceCatalog

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_DB = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3").resolve()
DEFAULT_SYNTAX_PACKAGE = PROJECT_ROOT / "artifacts/week4-wc3-regional-syntax"
DEFAULT_SYNTAX_MODES_RUN = Path.home() / ".local/share/urban-design-data/week5-syntax-modes/syntax/run-week5-modes-01"
DEFAULT_3DBAG_MANIFEST = PROJECT_ROOT / "config/3dbag-height-source-manifest-v1.json"
ACTOR = "agent-automation"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sqlite_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _stabilize_sqlite_copy(path: Path) -> None:
    """Checkpoint and use rollback journaling on a disposable/backup copy only."""
    connection=sqlite3.connect(path)
    try:
        quick=connection.execute("PRAGMA quick_check").fetchone()[0]
        integrity=connection.execute("PRAGMA integrity_check").fetchone()[0]
        if quick != "ok" or integrity != "ok":
            raise RuntimeError(f"SQLite copy failed checks: quick={quick}, integrity={integrity}")
        mode=connection.execute("PRAGMA journal_mode").fetchone()[0]
        if str(mode).casefold()=="wal":
            checkpoint=connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint and checkpoint[0] != 0:
                raise RuntimeError("could not checkpoint disposable SQLite copy")
            changed=connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if str(changed).casefold() != "delete":
                raise RuntimeError("could not make disposable SQLite copy self-contained")
    finally:
        connection.close()


def backup_database_readonly(source: Path, destination: Path) -> None:
    """Clone SQLite through its backup API while keeping the source connection read-only."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite database copy: {destination}")
    source_connection=_sqlite_readonly(source)
    destination_connection=sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        source_connection.close()
        destination_connection.close()
    _stabilize_sqlite_copy(destination)


def _database_signature(
    path: Path,
    *,
    event_columns: Sequence[str] | None = None,
    event_through_sequence: int | None = None,
    read_only: bool = True,
) -> dict[str, Any]:
    connection=_sqlite_readonly(path) if read_only else sqlite3.connect(path)
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        integrity_check = connection.execute("PRAGMA integrity_check").fetchone()[0]
        ledger_columns = [row[1] for row in connection.execute("PRAGMA table_info(ledger_events)")]
        chosen = list(event_columns) if event_columns is not None else [
            name for name in (
                "sequence", "event_id", "timestamp", "actor", "action", "target_id", "target_type",
                "project_id", "prior_status", "changed_refs_json", "reason", "resulting_refs_json",
                "supersedes", "parent_event_id", "state_revision", "payload_json",
            ) if name in ledger_columns
        ]
        if not chosen or any(name not in ledger_columns for name in chosen):
            raise RuntimeError("ledger schema does not contain the expected stable columns")
        col_sql = ", ".join('"' + name + '"' for name in chosen)
        event_hash_all = hashlib.sha256()
        event_hash_prefix = hashlib.sha256()
        event_count = connection.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0]
        max_sequence = connection.execute("SELECT COALESCE(MAX(sequence), 0) FROM ledger_events").fetchone()[0]
        prefix_count = 0
        for row in connection.execute(f"SELECT {col_sql} FROM ledger_events ORDER BY sequence"):
            encoded = _canonical_bytes(row) + b"\n"
            event_hash_all.update(encoded)
            if event_through_sequence is None or row[0] <= event_through_sequence:
                event_hash_prefix.update(encoded)
                prefix_count += 1
        state_heads = connection.execute(
            "SELECT entity_id, entity_type, project_id, current_revision FROM state_heads ORDER BY entity_id"
        ).fetchall()
        protected_heads = [row for row in state_heads if str(row[1]).casefold() in {"humandecision", "constraint"}]
        protected_hash = hashlib.sha256(_canonical_bytes(protected_heads)).hexdigest()
        project_id = "rotterdam-m4h-pilot-project"
        project_head = connection.execute(
            "SELECT current_revision FROM state_heads WHERE entity_id=? AND entity_type='Project'", (project_id,)
        ).fetchone()
        project_payload = None
        if project_head:
            row = connection.execute(
                "SELECT payload_json FROM state_versions WHERE entity_id=? AND revision=?",
                (project_id, project_head[0]),
            ).fetchone()
            if row:
                project_payload = json.loads(row[0])
        entities = connection.execute(
            "SELECT entity_type, COUNT(*) FROM state_heads GROUP BY entity_type ORDER BY entity_type"
        ).fetchall()
        return {
            "quick_check": quick_check,
            "integrity_check": integrity_check,
            "ledger_event_count": event_count,
            "ledger_max_sequence": max_sequence,
            "ledger_event_sha256": event_hash_all.hexdigest(),
            "ledger_event_prefix_sha256": event_hash_prefix.hexdigest(),
            "ledger_event_prefix_count": prefix_count,
            "ledger_columns": ledger_columns,
            "stable_event_columns": chosen,
            "protected_head_count": len(protected_heads),
            "protected_heads_sha256": protected_hash,
            "project_revision": project_head[0] if project_head else None,
            "active_study_area_id": project_payload.get("active_study_area_id") if project_payload else None,
            "entity_head_counts": {str(name): count for name, count in entities},
        }
    finally:
        connection.close()


def _verify_wc3_inputs(package_dir: Path, requested_run_dir: Path | None) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    package_dir = package_dir.resolve()
    verifier = package_dir / "verify_package.py"
    if not verifier.is_file():
        raise ValueError("WC3 package verifier is missing")
    completed = subprocess.run(
        [sys.executable, str(verifier), "--package-dir", str(package_dir)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if completed.returncode != 0:
        raise ValueError(f"WC3 package verification failed: {completed.stdout.strip()} {completed.stderr.strip()}")
    record = json.loads((package_dir / "package-record.json").read_text(encoding="utf-8"))
    run_dir = Path(record["execution"]["syntax_run_dir"]).resolve()
    if requested_run_dir is not None and requested_run_dir.resolve() != run_dir:
        raise ValueError("requested syntax run directory is not the hash-bound WC3 run")
    run_path = run_dir / "run-manifest.json"
    candidate_path = Path(record["execution"]["candidate_path"]).resolve()
    run = json.loads(run_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if sha256_file(run_path) != record["execution"]["run_manifest_sha256"]:
        raise ValueError("WC3 run manifest differs from its package record")
    if sha256_file(candidate_path) != record["execution"]["candidate_sha256"]:
        raise ValueError("WC3 syntax candidate differs from its package record")
    if run.get("source_requests") != 0 or run.get("authority_database_writes") != 0:
        raise ValueError("WC3 run records a prohibited request or authority write")
    if candidate.get("status") != "EXPLORATORY_CANDIDATE" or len(candidate.get("layers", [])) != 6:
        raise ValueError("WC3 candidate status or six-layer plan is invalid")
    if any("source_complete" in layer for layer in candidate.get("layers", [])) or "source_complete" in candidate:
        raise ValueError("WC3 candidate contains a prohibited OSM completeness claim")
    if record.get("status") != "EXPLORATORY_CANDIDATE_PARTIAL_BLOCKED_FOR_ACCEPTANCE":
        raise ValueError("WC3 package is not the expected partial exploratory result")
    return record, candidate, run_path, candidate_path


def _source_records(package_record: Mapping[str, Any], project_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    retrieval_path = Path(package_record["source"]["retrieval_record_path"])
    retrieval = json.loads(retrieval_path.read_text(encoding="utf-8"))
    base = {
        "pbf": {
            "path": Path("/Users/jackhsieh/.local/share/urban-design-data/osm/zuid-holland-260922.osm.pbf"),
            "url": package_record["source"]["pbf_url"],
            "key": "pbf",
            "mime": "application/octet-stream",
        },
        "poly": {
            "path": PROJECT_ROOT / "artifacts/week4-regional-osm/raw/zuid-holland.poly",
            "url": package_record["source"]["poly_url"],
            "key": "poly",
            "mime": "text/plain",
        },
    }
    artifacts: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    for name, config in base.items():
        response = retrieval.get("files", {}).get(name)
        path = config["path"].resolve()
        if not isinstance(response, Mapping) or response.get("status_code") != 200 or response.get("success") is not True:
            raise ValueError(f"retained retrieval evidence for {name} is not a successful HTTP 200")
        actual_hash = sha256_file(path)
        actual_size = path.stat().st_size
        if actual_hash != response.get("sha256") or actual_size != response.get("size_bytes"):
            raise ValueError(f"retained {name} bytes differ from their original retrieval record")
        if response.get("url") != config["url"]:
            raise ValueError(f"retained {name} URL differs from WC3 package source record")
        hex_hash = actual_hash
        artifact_id = f"artifact-wc3-geofabrik-{name}-{hex_hash[:16]}"
        snapshot_id = f"snapshot-wc3-geofabrik-{name}-{hex_hash[:16]}"
        headers = response.get("headers", {})
        version = "Geofabrik Last-Modified " + str(headers.get("last-modified", "UNKNOWN"))
        if headers.get("etag"):
            version += "; ETag " + str(headers["etag"])
        retrieved_at = response.get("completed_at")
        if not isinstance(retrieved_at, str):
            raise ValueError(f"retained {name} retrieval time is missing")
        artifact_payload = Artifact.model_validate({
            "id": artifact_id,
            "type": "raw_source_response",
            "uri": path.as_uri(),
            "sha256": f"sha256:{actual_hash}",
            "mime": config["mime"],
            "producer": "Geofabrik Download Server",
            "created_at": retrieved_at,
            "project_id": project_id,
            "size_bytes": actual_size,
            "parent_artifact_ids": [],
        }).model_dump(mode="json", exclude_none=True)
        snapshot_payload = DatasetSnapshot.model_validate({
            "id": snapshot_id,
            "project_id": project_id,
            "source": config["url"],
            "query": json.dumps({
                "retained_file": str(path),
                "original_http_status": response["status_code"],
                "retrieval_record": str(retrieval_path),
                "retrieval_completed_at": retrieved_at,
                "sha256": actual_hash,
                "size_bytes": actual_size,
                "note": "Reused exact retained response bytes; no request was made during WC3 recomputation.",
            }, sort_keys=True, separators=(",", ":")),
            "retrieved_at": retrieved_at,
            "publisher": "Geofabrik Download Server",
            "license": "ODbL 1.0; © OpenStreetMap contributors",
            "version": version,
            "sha256": f"sha256:{actual_hash}",
            "raw_artifact_id": artifact_id,
        }).model_dump(mode="json", exclude_none=True)
        artifacts.append(artifact_payload)
        snapshots.append(snapshot_payload)
    return artifacts, snapshots


def _manifest_artifacts(
    package_dir: Path,
    project_id: str,
    raw_artifacts: Sequence[Mapping[str, Any]],
    run_path: Path,
    candidate_path: Path,
    run: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_ids = [str(item["id"]) for item in raw_artifacts]
    package_manifest = (package_dir / "integrity-manifest.json").resolve()
    created_at = str(run["completed_at_utc"])
    inputs = [
        ("wc3-provenance-manifest", package_manifest, "evidence_package_manifest"),
        ("wc3-run-manifest", run_path, "analysis_run_manifest"),
        ("wc3-six-layer-candidate", candidate_path, "analysis_result_candidate"),
    ]
    records=[]
    for label, path, artifact_type in inputs:
        content_hash=sha256_file(path)
        artifact_id=f"artifact-wc3-{label}-{content_hash[:16]}"
        records.append(Artifact.model_validate({
            "id":artifact_id,
            "type":artifact_type,
            "uri":path.resolve().as_uri(),
            "sha256":f"sha256:{content_hash}",
            "mime":"application/json",
            "producer":"WC3 regional syntax evidence package",
            "created_at":created_at,
            "project_id":project_id,
            "size_bytes":path.stat().st_size,
            "parent_artifact_ids":raw_ids,
        }).model_dump(mode="json",exclude_none=True))
    return records


def _ensure_record(
    store: ProjectStateStore,
    entity_type: str,
    payload: Mapping[str, Any],
    *,
    project_id: str,
    session_id: str,
    action: str,
) -> Any:
    entity_id = str(payload["id"])
    try:
        existing = store.current(entity_id)
    except EntityNotFoundError:
        existing = None
    if existing is not None:
        existing_payload = dict(existing.payload)
        expected_payload = dict(payload)
        if entity_type == "EvidenceCard":
            # A hash-derived card ID makes identical source evidence idempotent;
            # retain the first persisted timestamp when a later run rebuilds it.
            existing_payload.pop("created_at", None)
            expected_payload.pop("created_at", None)
        if existing.entity_type != entity_type or _canonical_bytes(existing_payload) != _canonical_bytes(expected_payload):
            raise ValueError(f"existing {entity_type} {entity_id} differs from the verified source record")
        return existing
    return store.create(
        entity_type=entity_type,
        payload=payload,
        entity_id=entity_id,
        project_id=project_id,
        actor=ACTOR,
        actor_kind=ActorKind.AGENT_AUTOMATION,
        actor_session_id=session_id,
        action=action,
    )


def enrich_week5_syntax_candidate(
    candidate: Mapping[str, Any],
    *,
    candidate_sha256: str,
    run_manifest_sha256: str,
    layer_provenance: Mapping[str, Mapping[str, Any]],
    segments_by_mode: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Attach verified provenance to the six PD-20 mode-specific result layers."""
    layers = candidate.get("layers")
    plans = candidate.get("layer_plan")
    if not isinstance(layers, list) or len(layers) != 6:
        raise ValueError("PD-20 Syntax candidate must contain exactly six layers")
    if not isinstance(plans, list) or len(plans) != 6:
        raise ValueError("PD-20 Syntax candidate must contain exactly six layer plans")
    if candidate.get("schema_version") != "week5-six-syntax-layer-candidate-v1":
        raise ValueError("unsupported PD-20 Syntax candidate schema")
    if candidate.get("status") != "EXPLORATORY_CANDIDATE":
        raise ValueError("PD-20 Syntax candidate is not marked EXPLORATORY_CANDIDATE")

    def valid_hash(value: Any, label: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{label} must be a SHA-256 value")
        digest = value.removeprefix("sha256:").lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"{label} must be a SHA-256 value")
        return digest

    result = copy.deepcopy(dict(candidate))
    candidate_hash = valid_hash(candidate_sha256, "candidate_sha256")
    manifest_hash = valid_hash(run_manifest_sha256, "run_manifest_sha256")
    area_hash = valid_hash(candidate.get("study_area_sha256"), "study_area_sha256")
    expected_modes = {800.0: "pedestrian", 2000.0: "bicycle", 10000.0: "motor_vehicle"}
    plan_by_id = {str(item.get("layer_id")): item for item in plans if isinstance(item, Mapping)}
    if len(plan_by_id) != 6:
        raise ValueError("PD-20 Syntax layer plans must have six unique IDs")
    if set(plan_by_id) != {str(item.get("layer_id")) for item in layers if isinstance(item, Mapping)}:
        raise ValueError("PD-20 Syntax layer plan IDs do not match result layers")

    mapped_layers: list[dict[str, Any]] = []
    mapped_plans: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    used_modes: set[str] = set()
    layer_keys_by_mode: dict[str, set[str]] = {}
    geometry_by_mode: dict[str, dict[str, Mapping[str, Any]]] = {}
    for mode, rows in segments_by_mode.items():
        if mode not in {"pedestrian", "bicycle", "motor_vehicle"}:
            raise ValueError(f"unsupported PD-20 network mode: {mode}")
        geometry_by_mode[mode] = {}
        for row in rows:
            source_segment_id = row.get("source_segment_id")
            segment_id = row.get("id")
            if not isinstance(source_segment_id, str) or not source_segment_id:
                raise ValueError("Syntax geometry requires an original source segment ID")
            if segment_id != f"{mode}:{source_segment_id}":
                raise ValueError("Syntax geometry ID must be namespaced by network mode")
            if source_segment_id in geometry_by_mode[mode]:
                raise ValueError(f"duplicate Syntax segment geometry: {mode}:{source_segment_id}")
            geometry_by_mode[mode][source_segment_id] = row
            segments.append(dict(row))

    limitations = [str(item) for item in result.get("limitations", []) if str(item).strip()]
    comparison_limit = "method-comparison-v1: FAIL; PST 3.3.1 is retained as method of record per PD-15, without method-comparison acceptance."
    if comparison_limit not in limitations:
        limitations.append(comparison_limit)
    if "All six mode-specific layers are EXPLORATORY; no design conclusion is approved." not in limitations:
        limitations.append("All six mode-specific layers are EXPLORATORY; no design conclusion is approved.")

    for raw in layers:
        if not isinstance(raw, Mapping):
            raise ValueError("PD-20 Syntax layers must be objects")
        layer = dict(raw)
        layer_id = str(layer.get("layer_id", ""))
        radius = float(layer.get("radius_m", 0))
        metric = str(layer.get("metric_key", "")).lower()
        mode = expected_modes.get(radius)
        if mode is None or layer.get("network_mode") != mode:
            raise ValueError(f"PD-20 Syntax layer {layer_id!r} has an unexpected mode/radius pair")
        if metric not in {"nain", "nach"} or layer.get("calculation_status") != "COMPUTED":
            raise ValueError(f"PD-20 Syntax layer {layer_id!r} is not a computed angular metric")
        if layer.get("engine") != "PST 3.3.1":
            raise ValueError(f"PD-20 Syntax layer {layer_id!r} does not use PST 3.3.1")
        values = layer.get("segment_values")
        if not isinstance(values, Mapping) or not values:
            raise ValueError(f"PD-20 Syntax layer {layer_id!r} has no segment values")
        normalized_values: dict[str, float] = {}
        for segment_id, value in values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"PD-20 Syntax layer {layer_id!r} has an invalid metric value")
            normalized_values[str(segment_id)] = float(value)
        key_set = set(normalized_values)
        if mode in layer_keys_by_mode and layer_keys_by_mode[mode] != key_set:
            raise ValueError(f"PD-20 {mode} integration/choice segment IDs differ")
        layer_keys_by_mode[mode] = key_set
        if key_set != set(geometry_by_mode.get(mode, {})):
            raise ValueError(f"PD-20 {mode} metric IDs do not exactly match reconstructed segment geometry")

        provenance = layer_provenance.get(layer_id)
        if not isinstance(provenance, Mapping):
            raise ValueError(f"PD-20 Syntax layer {layer_id!r} has no verified provenance")
        output_hash = valid_hash(provenance.get("primary_output_sha256"), f"{layer_id}.output_file_sha256")
        envelope = provenance.get("download_envelope")
        stability = provenance.get("stability_result")
        boundary_limit = provenance.get("boundary_effect_limitation")
        if not isinstance(envelope, Mapping) or not isinstance(stability, Mapping):
            raise ValueError(f"PD-20 Syntax layer {layer_id!r} provenance is incomplete")
        if not isinstance(boundary_limit, str) or not boundary_limit.strip():
            raise ValueError(f"PD-20 Syntax layer {layer_id!r} requires a boundary-effect limitation")
        if radius == 800.0 and stability.get("status") != "NOT_ASSESSED":
            raise ValueError("800 m PD-20 Syntax stability must remain NOT_ASSESSED")
        if radius > 800.0 and stability.get("status") not in {"PASS", "FAIL"}:
            raise ValueError(f"PD-20 {radius:g} m stability result must be explicit")

        prefixed_values = {f"{mode}:{key}": value for key, value in normalized_values.items()}
        layer.update({
            "evidence_level": "EXPLORATORY",
            "exploratory_only": True,
            "formal_result_eligible": False,
            "network_mode": mode,
            "network_policy_version": str(candidate.get("policy_version")),
            "method_of_record": "PST 3.3.1 (PD-15)",
            "study_area_sha256": area_hash,
            "output_file_sha256": output_hash,
            "source_output_file": provenance.get("primary_output_path"),
            "syntax_result_sha256": candidate_hash,
            "source_manifest_sha256": manifest_hash,
            "download_envelope": dict(envelope),
            "stability_result": dict(stability),
            "boundary_effect_limitation": boundary_limit,
            "segment_values": prefixed_values,
            "limitations": " ".join(filter(None, (
                str(layer.get("limitations", "")).strip(),
                boundary_limit.strip(),
                comparison_limit,
                "OSM feature/semantic completeness and directional network effects are not established.",
            ))),
        })
        mapped_layers.append(layer)
        used_modes.add(mode)

        plan = dict(plan_by_id[layer_id])
        plan.update({
            "network_mode": mode,
            "evidence_level": "EXPLORATORY",
            "exploratory_only": True,
            "formal_result_eligible": False,
            "segment_value_count": len(prefixed_values),
            "network_policy_version": str(candidate.get("policy_version")),
            "study_area_sha256": area_hash,
            "output_file_sha256": output_hash,
            "download_envelope": dict(envelope),
            "stability_result": dict(stability),
            "boundary_effect_limitation": boundary_limit,
            "limitations": layer["limitations"],
        })
        plan.pop("segment_values", None)
        mapped_plans.append(plan)

    if used_modes != set(expected_modes.values()):
        raise ValueError("PD-20 Syntax candidate does not cover all three required network modes")
    result["layers"] = mapped_layers
    result["layer_plan"] = mapped_plans
    result["segments"] = segments
    result["evidence_level"] = "EXPLORATORY"
    result["method_of_record"] = "PST 3.3.1 (PD-15)"
    result["network_policy_version"] = str(candidate.get("policy_version"))
    result["syntax_result_sha256"] = candidate_hash
    result["run_manifest_sha256"] = manifest_hash
    result["formal_result_eligible"] = False
    result["exploratory_only"] = True
    result["limitations"] = limitations
    if not any("method-comparison-v1: FAIL" in item for item in result["limitations"]):
        raise ValueError("PD-20 Syntax limitations must record method-comparison-v1: FAIL")
    return result


def _verified_file_record(
    path: Path,
    expected_sha256: str,
    *,
    expected_size_bytes: int | None = None,
) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"hash-bound Syntax input file is missing: {resolved}")
    digest = sha256_file(resolved)
    expected = str(expected_sha256).removeprefix("sha256:").lower()
    if digest != expected:
        raise ValueError(f"hash-bound Syntax input file SHA-256 mismatch: {resolved}")
    size = resolved.stat().st_size
    if expected_size_bytes is not None and size != expected_size_bytes:
        raise ValueError(f"hash-bound Syntax input file size mismatch: {resolved}")
    return {"path": resolved, "sha256": digest, "size_bytes": size}


def _load_week5_syntax_inputs(
    run_dir: Path,
    *,
    expected_study_area_sha256: str,
) -> dict[str, Any]:
    run_dir = run_dir.expanduser().resolve()
    run_path = run_dir / "run-manifest.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if not isinstance(run, Mapping) or run.get("schema_version") != "week5-syntax-run-manifest-v1":
        raise ValueError("unsupported Week 5 Syntax run manifest")
    if run.get("source_requests") != 0 or run.get("authority_database_writes") != 0:
        raise ValueError("Week 5 Syntax run must record zero source requests and authority writes")
    if run.get("policy_version") != "syntax-network-policy-v2":
        raise ValueError("Week 5 Syntax network policy is not syntax-network-policy-v2")
    run_hash = sha256_file(run_path)
    output_manifest = run.get("outputs")
    if not isinstance(output_manifest, Mapping):
        raise ValueError("Week 5 Syntax run manifest outputs are missing")

    verified_outputs: dict[str, dict[str, Any]] = {}
    for name, entry in output_manifest.items():
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            raise ValueError(f"Week 5 Syntax output manifest entry is malformed: {name}")
        expected_path = (run_dir / str(name)).resolve()
        if Path(str(entry["path"])).expanduser().resolve() != expected_path:
            raise ValueError(f"Week 5 Syntax output path does not match its run directory: {name}")
        verified_outputs[str(name)] = _verified_file_record(
            expected_path,
            str(entry.get("sha256", "")),
            expected_size_bytes=entry.get("size_bytes"),
        )
    required_outputs = {
        "syntax_six_layer_candidate.json",
        "syntax_800m_1500m.json",
        "syntax_2000m_4000m.json",
        "syntax_2000m_6000m.json",
        "syntax_10000m_15000m.json",
        "syntax_10000m_20000m.json",
        "stability_2000m_4000m_vs_6000m.json",
        "stability_10000m_15000m_vs_20000m.json",
    }
    if not required_outputs.issubset(verified_outputs):
        raise ValueError("Week 5 Syntax run is missing a required result or stability output")

    candidate_path = run_dir / "syntax_six_layer_candidate.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not isinstance(candidate, Mapping):
        raise ValueError("Week 5 Syntax candidate is not a JSON object")
    candidate_hash = verified_outputs["syntax_six_layer_candidate.json"]["sha256"]
    expected_area_hash = str(expected_study_area_sha256).removeprefix("sha256:").lower()
    run_study_area_file_hash = str(run.get("study_area_sha256", "")).removeprefix("sha256:").lower()
    candidate_study_area_file_hash = str(candidate.get("study_area_sha256", "")).removeprefix("sha256:").lower()
    if candidate_study_area_file_hash != run_study_area_file_hash:
        raise ValueError("Week 5 Syntax candidate and run manifest StudyArea file hashes differ")
    if candidate.get("method_manifest_sha256") != run.get("method_manifest_sha256"):
        raise ValueError("Week 5 Syntax candidate and run method-manifest hashes differ")
    if candidate.get("policy_version") != run.get("policy_version"):
        raise ValueError("Week 5 Syntax candidate and run network policy versions differ")

    method_path = Path(str(run.get("method_manifest_path", ""))).expanduser().resolve()
    method_file = _verified_file_record(method_path, str(run.get("method_manifest_sha256", "")))
    method = json.loads(method_path.read_text(encoding="utf-8"))
    if method.get("engine", {}).get("version") != "3.3.1":
        raise ValueError("Week 5 Syntax method manifest is not for PST 3.3.1")
    if method.get("status") != "APPROVED_AS_RECORD_METHOD_PER_PD15":
        raise ValueError("PST 3.3.1 is not declared as the PD-15 method of record")
    prior_comparison = method.get("prior_comparisons", {}).get("syntax_method_comparison_v1", {})
    if not str(prior_comparison.get("status", "")).startswith("FAIL"):
        raise ValueError("method-comparison-v1 must remain FAIL in the retained method manifest")

    runtime_path = Path(str(run.get("runtime_manifest_path", ""))).expanduser().resolve()
    runtime_file = _verified_file_record(runtime_path, str(run.get("runtime_manifest_sha256", "")))
    if method.get("engine", {}).get("runtime_manifest_sha256") != runtime_file["sha256"]:
        raise ValueError("PST method and runtime manifest hashes differ")

    study_area_path = Path(str(run.get("study_area_path", ""))).expanduser().resolve()
    study_area_file = _verified_file_record(study_area_path, str(run.get("study_area_sha256", "")))
    study_document = json.loads(study_area_path.read_text(encoding="utf-8"))
    study_geometry = shape(study_document.get("geometry", study_document))
    canonical_geometry_sha256 = canonical_geometry_hash(study_geometry.__geo_interface__).removeprefix("sha256:")
    if canonical_geometry_sha256 != expected_area_hash:
        raise ValueError("Week 5 Syntax StudyArea bytes do not resolve to the active geometry")

    extraction_refs = run.get("extraction_manifests")
    if not isinstance(extraction_refs, Mapping):
        raise ValueError("Week 5 Syntax run has no extraction manifest references")
    cached_files: dict[tuple[str, str], dict[str, Any]] = {}

    def verified_input(entry: Mapping[str, Any]) -> dict[str, Any]:
        key = (str(entry.get("path")), str(entry.get("sha256")))
        if key not in cached_files:
            cached_files[key] = _verified_file_record(
                Path(key[0]),
                key[1],
                expected_size_bytes=entry.get("size_bytes"),
            )
        return cached_files[key]

    extractions: dict[int, dict[str, Any]] = {}
    for envelope_m in (1500, 4000, 6000, 15000, 20000):
        ref = extraction_refs.get(str(envelope_m))
        if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str):
            raise ValueError(f"Week 5 Syntax extraction manifest {envelope_m}m is missing")
        path = Path(str(ref["path"])).expanduser().resolve()
        file_record = _verified_file_record(path, str(ref.get("sha256", "")))
        extraction = json.loads(path.read_text(encoding="utf-8"))
        if extraction.get("schema_version") != "regional-osm-extraction-manifest-v1":
            raise ValueError(f"unsupported OSM extraction manifest: {path}")
        data = extraction.get("extraction")
        inputs = extraction.get("inputs")
        outputs = extraction.get("outputs")
        if not all(isinstance(section, Mapping) for section in (data, inputs, outputs)):
            raise ValueError(f"OSM extraction manifest is incomplete: {path}")
        if data.get("buffer_radius_m") != float(envelope_m) or data.get("extract_covers_envelope") is not True:
            raise ValueError(f"OSM extraction envelope is not verified at {envelope_m}m")
        if data.get("network_mode") not in {"pedestrian", "bicycle", "motor_vehicle"}:
            raise ValueError("OSM extraction manifest has an unsupported network mode")
        pbf = verified_input(inputs["pbf"])
        poly = verified_input(inputs["poly"])
        study_input = verified_input(inputs["study_area"])
        network = verified_input(outputs["network"])
        unlinks = verified_input(outputs["unlinks"])
        if study_input["sha256"] != study_area_file["sha256"]:
            raise ValueError("OSM extraction StudyArea input differs from the syntax run")
        extractions[envelope_m] = {
            "path": path,
            "sha256": file_record["sha256"],
            "document": extraction,
            "network": network,
            "unlinks": unlinks,
            "pbf": pbf,
            "poly": poly,
        }

    source = extractions[1500]["document"]["inputs"]["source"]
    retrieval_path = Path(str(source.get("retrieval_record_path", ""))).expanduser().resolve()
    retrieval_record = _verified_file_record(
        retrieval_path,
        str(source.get("retrieval_record_sha256", "")),
        expected_size_bytes=source.get("retrieval_record_size_bytes"),
    )
    retrieval = json.loads(retrieval_path.read_text(encoding="utf-8"))
    for entry in extractions.values():
        entry_source = entry["document"]["inputs"]["source"]
        if entry_source.get("pbf_url") != source.get("pbf_url") or entry["pbf"]["sha256"] != extractions[1500]["pbf"]["sha256"]:
            raise ValueError("Week 5 Syntax modes do not share one hash-bound regional OSM snapshot")
        if entry_source.get("retrieval_record_sha256") != retrieval_record["sha256"]:
            raise ValueError("Week 5 Syntax modes do not share one retrieval record")

    primary_by_mode = {
        "pedestrian": (800, 1500, "syntax_800m_1500m.json"),
        "bicycle": (2000, 6000, "syntax_2000m_6000m.json"),
        "motor_vehicle": (10000, 20000, "syntax_10000m_20000m.json"),
    }
    layer_provenance: dict[str, dict[str, Any]] = {}
    for layer in candidate.get("layers", []):
        if not isinstance(layer, Mapping):
            raise ValueError("Week 5 Syntax candidate contains a malformed layer")
        mode = str(layer.get("network_mode", ""))
        if mode not in primary_by_mode:
            raise ValueError(f"Week 5 Syntax candidate contains an unsupported mode: {mode}")
        radius, primary_envelope_m, output_name = primary_by_mode[mode]
        if float(layer.get("radius_m", 0)) != float(radius):
            raise ValueError(f"Week 5 Syntax candidate mode/radius mismatch: {mode}")
        source_output = json.loads(verified_outputs[output_name]["path"].read_text(encoding="utf-8"))
        source_layer = next((item for item in source_output.get("layers", []) if item.get("layer_id") == layer.get("layer_id")), None)
        if not isinstance(source_layer, Mapping) or source_layer.get("calculation_status") != "COMPUTED":
            raise ValueError(f"Week 5 Syntax output file has no computed layer {layer.get('layer_id')}")
        if source_layer.get("segment_values") != layer.get("segment_values"):
            raise ValueError(f"Week 5 Syntax candidate values differ from its source output file: {layer.get('layer_id')}")
        primary = extractions[primary_envelope_m]
        mode_extract = primary["document"]["extraction"]
        source_download = primary["document"]["inputs"]["source"]
        compare_envelope = {"bicycle": 4000, "motor_vehicle": 15000}.get(mode)
        if compare_envelope is None:
            stability = {
                "status": "NOT_ASSESSED",
                "reason": "800 m results have no independently computed second-envelope comparison.",
                "compared_envelopes_m": [1500],
            }
            boundary_limit = (
                "800 m values use the 1,500 m pedestrian extraction. Boundary stability was not independently assessed; "
                "OSM completeness and network-policy approval remain unresolved."
            )
        else:
            stability_name = (
                "stability_2000m_4000m_vs_6000m.json" if mode == "bicycle"
                else "stability_10000m_15000m_vs_20000m.json"
            )
            stability_file = verified_outputs[stability_name]
            stability_data = json.loads(stability_file["path"].read_text(encoding="utf-8"))
            candidate_stability = candidate.get("stability_2000m" if mode == "bicycle" else "stability_10000m")
            if stability_data != candidate_stability:
                raise ValueError(f"Week 5 Syntax stability file differs from candidate metadata at {radius}m")
            metric_key = str(layer.get("metric_key", "")).lower()
            metric_stability = stability_data.get("metrics", {}).get(metric_key, {})
            stability_status = "PASS" if stability_data.get("stability_pass") is True and metric_stability.get("spearman_pass") is True else "FAIL"
            stability = {
                "status": stability_status,
                "radius_m": float(radius),
                "compared_envelopes_m": [compare_envelope, primary_envelope_m],
                "criterion": stability_data.get("criterion"),
                "common_segment_count": stability_data.get("common_segment_count"),
                "spearman_correlation": metric_stability.get("spearman_correlation"),
                "spearman_pass": metric_stability.get("spearman_pass"),
                "edge_affected_count": metric_stability.get("edge_affected_count"),
                "edge_affected_percent": metric_stability.get("edge_affected_percent"),
                "evidence_file": str(stability_file["path"]),
                "evidence_file_sha256": stability_file["sha256"],
            }
            boundary_limit = (
                f"The {primary_envelope_m}m/{compare_envelope}m envelope comparison is {stability_status} for this metric only; "
                "it does not establish source completeness or remove boundary effects beyond the larger retained envelope. "
                "OSM feature/semantic completeness and directionality are unresolved."
            )
        if mode_extract.get("network_mode") != mode:
            raise ValueError(f"Week 5 Syntax extraction mode mismatch for {mode}")
        layer_provenance[str(layer["layer_id"])] = {
            "primary_output_path": str(verified_outputs[output_name]["path"]),
            "primary_output_sha256": verified_outputs[output_name]["sha256"],
            "primary_output_size_bytes": verified_outputs[output_name]["size_bytes"],
            "primary_envelope_m": primary_envelope_m,
            "download_envelope": {
                "provider": source_download.get("provider"),
                "pbf_url": source_download.get("pbf_url"),
                "pbf_version": Path(str(source_download.get("pbf_url", ""))).name,
                "pbf_sha256": primary["pbf"]["sha256"],
                "retrieved_at": retrieval.get("timestamp_utc"),
                "license": source_download.get("license"),
                "attribution": source_download.get("attribution"),
                "regional_poly_url": source_download.get("poly_url"),
                "regional_poly_sha256": primary["poly"]["sha256"],
                "metric_network_buffer_m": float(mode_extract["buffer_radius_m"]),
                "extract_covers_envelope": bool(mode_extract["extract_covers_envelope"]),
                "coverage_basis": mode_extract.get("coverage_basis"),
                "extraction_manifest_path": str(primary["path"]),
                "extraction_manifest_sha256": primary["sha256"],
                "network_output_path": str(primary["network"]["path"]),
                "network_output_sha256": primary["network"]["sha256"],
                "unlinks_output_path": str(primary["unlinks"]["path"]),
                "unlinks_output_sha256": primary["unlinks"]["sha256"],
                "stability_comparison_envelope_m": compare_envelope,
                "stability_comparison_network_sha256": extractions[compare_envelope]["network"]["sha256"] if compare_envelope is not None else None,
                "stability_comparison_unlinks_sha256": extractions[compare_envelope]["unlinks"]["sha256"] if compare_envelope is not None else None,
            },
            "stability_result": stability,
            "boundary_effect_limitation": boundary_limit,
        }

    return {
        "run_dir": run_dir,
        "run": dict(run),
        "run_path": run_path,
        "run_manifest_sha256": run_hash,
        "candidate": dict(candidate),
        "candidate_path": candidate_path,
        "candidate_sha256": candidate_hash,
        "method": method,
        "method_path": method_path,
        "method_file": method_file,
        "runtime_path": runtime_path,
        "runtime_file": runtime_file,
        "study_area_file": study_area_file,
        "study_area_path": study_area_path,
        "retrieval": retrieval,
        "retrieval_path": retrieval_path,
        "retrieval_file": retrieval_record,
        "extractions": extractions,
        "outputs": verified_outputs,
        "layer_provenance": layer_provenance,
    }


def _build_week5_segments(
    context: Mapping[str, Any],
    *,
    catalog: WorkspaceSourceCatalog,
    source_ids_by_mode: Mapping[str, Mapping[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    method = context["method"]
    parameters = method.get("method_specification", {}).get("segmentation_and_topology", {}).get("parameters", {})
    angular = method.get("method_specification", {}).get("angular_cost", {}).get("pst_parameters", {})
    adapter = PSTAdapter(manifest_path=Path(context["runtime_path"]))
    results: dict[str, list[dict[str, Any]]] = {}
    extraction_by_mode = {1500: "pedestrian", 6000: "bicycle", 20000: "motor_vehicle"}
    for envelope_m, mode in extraction_by_mode.items():
        extraction = context["extractions"][envelope_m]
        network_doc = json.loads(extraction["network"]["path"].read_text(encoding="utf-8"))
        if not isinstance(network_doc.get("features"), list):
            raise ValueError(f"{mode} network output is not GeoJSON FeatureCollection")
        crs_name = str(network_doc.get("crs", {}).get("properties", {}).get("name", ""))
        if "28992" not in crs_name:
            raise ValueError(f"{mode} Syntax network is not in EPSG:28992")
        features = network_doc["features"]
        lines = prepare_pst_lines(features)
        unlinks_raw = json.loads(extraction["unlinks"]["path"].read_text(encoding="utf-8"))
        if not isinstance(unlinks_raw, list):
            raise ValueError(f"{mode} unlink output must be a coordinate list")
        request = PSTRequest(
            lines=lines,
            radius_m=1.0,
            radius_mode="walking",
            metric_mode="integration",
            unlinks=tuple((float(point[0]), float(point[1])) for point in unlinks_raw),
            angle_threshold=float(angular.get("angle_threshold", 0.0)),
            angle_precision=int(angular.get("angle_precision", 1)),
            weigh_by_length=False,
            segment_map_snap_m=float(parameters.get("snap_m", 0.0)),
            segment_map_min_tail_m=float(parameters.get("min_tail_m", 0.0)),
            segment_map_colinear_deviation=float(parameters.get("colinear_deviation", 1.0)),
            segment_map_extrude_m=float(parameters.get("extrude_m", 0.0)),
        )
        pst_result = adapter.compute(request)
        source_features = {
            str(feature.get("id") or (feature.get("properties") or {}).get("osm_id")): feature
            for feature in features
        }
        network_artifact_id = str(source_ids_by_mode[mode]["network_artifact_id"])
        snapshot_id = str(source_ids_by_mode[mode]["dataset_snapshot_id"])
        mode_segments: list[dict[str, Any]] = []
        for segment in pst_result.segments:
            geometry = LineString([segment.start, segment.end])
            if not geometry.intersects(catalog.study_area_shape):
                continue
            parent = source_features.get(segment.source_line_id)
            if parent is None and segment.source_line_id.endswith(("_a", "_b")):
                parent = source_features.get(segment.source_line_id[:-2])
            if parent is None:
                raise ValueError(f"PST segment {segment.id} refers to a missing source line")
            properties = parent.get("properties") or {}
            mode_segments.append({
                "id": f"{mode}:{segment.id}",
                "source_segment_id": segment.id,
                "source_line_id": segment.source_line_id,
                "source_feature_id": segment.source_line_id,
                "geometry": geometry.__geo_interface__,
                "length_m": float(geometry.length),
                "layer": properties.get("layer", 0),
                "highway": properties.get("highway"),
                "feature_kind": "syntax-segment",
                "network_mode": mode,
                "source_artifact_id": network_artifact_id,
                "source_snapshot_id": snapshot_id,
                "lineage_status": "VERIFIED_EXPLORATORY_SOURCE_MATCH",
            })
        results[mode] = mode_segments
    return results


def _persist_syntax_cards(
    store: ProjectStateStore,
    catalog: WorkspaceSourceCatalog,
    bundle: Mapping[str, Any],
    artifact_id: str,
    artifact_sha256: str,
    *,
    actor_session_id: str,
    tool: str,
    tool_version: str,
    created_at: str,
    source_snapshot_ids: Sequence[str],
    source_artifact_ids: Sequence[str],
) -> list[str]:
    cards: list[str] = []
    for layer in bundle.get("layers", []):
        layer_id = str(layer["layer_id"])
        card_id = f"card-syntax-{layer_id}-{artifact_sha256.removeprefix('sha256:')[:12]}"
        computed = layer.get("calculation_status") == "COMPUTED"
        status = "computed" if computed else "unavailable"
        statistics = layer.get("statistics", {}) if computed else {}
        values = {
            key: statistics[key]
            for key in ("count", "mean", "min", "max")
            if key in statistics
        }
        radius = float(layer["radius_m"])
        metric_key = str(layer["metric_key"])
        unit = str(layer.get("unit") or f"{metric_key.upper()} (normalized)")
        readiness = str(layer.get("data_readiness", "UNKNOWN"))
        statement = (
            f"{tool} {metric_key.upper()} at {radius:g} m was computed for the active StudyArea; "
            f"readiness is {readiness}."
            if computed else
            f"{tool} {metric_key.upper()} at {radius:g} m was not computed ({layer.get('calculation_status')}); no metric values are asserted."
        )
        dataset_refs=[]
        for snapshot_id in source_snapshot_ids:
            snapshot=store.current(str(snapshot_id))
            dataset_refs.append({
                "id":snapshot.entity_id,
                "project_id":snapshot.project_id,
                "version":snapshot.payload["version"],
                "sha256":snapshot.payload["sha256"],
            })
        evidence_artifact_hash = artifact_sha256 if artifact_sha256.startswith("sha256:") else f"sha256:{artifact_sha256}"
        card_payload=EvidenceCard.model_validate({
            "id":card_id,
            "project_id":catalog.project_id,
            "scenario_id":None,
            "input_versions":[catalog.study_area_id,*list(source_snapshot_ids)],
            "claim":{
                "id":f"claim-{card_id}",
                "type":"observation",
                "statement":statement,
                "evidence_ids":[],
                "assumption_ids":[],
                "scope":catalog.study_area_id,
            },
            "source_refs":[artifact_id,*list(source_artifact_ids)],
            "dataset_refs":dataset_refs,
            "metric":{"id":f"metric-{layer_id}","name":str(layer.get("title") or layer_id),"unit":unit},
            "parameters":[
                f"radius_m={radius:g}",
                f"formula_version={layer.get('formula_version','unspecified')}",
                f"calculation_status={layer.get('calculation_status')}",
                f"data_readiness={readiness}",
            ],
            "method":{"id":str(layer.get("formula_version") or tool_version),"description":f"Deterministic {tool} segment metric with the hash-bound WC3 method and runtime manifests."},
            "tool":tool,
            "tool_version":tool_version,
            "result":{
                "artifact_refs":[artifact_id] if computed else [],
                "artifact_hashes":[evidence_artifact_hash] if computed else [],
                "values":values,
                "status":status,
                "project_id":catalog.project_id,
                "dataset_ids":list(source_snapshot_ids),
                "units":unit,
                "validation_status":"unverified",
            },
            "units":unit,
            "assumptions":["The layer is an exploratory deterministic metric and is not a design decision or behavioral prediction."],
            "limitations":[str(layer.get("limitations", ""))],
            "confidence":{"level":"low","basis":"Deterministic calculation with explicit coverage and readiness status.","uncertainty":"Network-policy approval and OSM feature/semantic completeness remain unresolved where stated.","assessed_by":"WC-2 persistence validation"},
            "validation_status":"unverified",
            "semantic_type":"COMPUTED_RESULT" if computed else "DATA_GAP",
            "human_status":"not_reviewed",
            "created_at":created_at,
        }).model_dump(mode="json",exclude_none=True)
        _ensure_record(
            store,
            "EvidenceCard",
            card_payload,
            project_id=catalog.project_id,
            session_id=actor_session_id,
            action="CreateEvidenceCard",
        )
        cards.append(card_id)
    return cards


def _persist_to_open_store(
    db_path: Path,
    *,
    package_dir: Path,
    requested_run_dir: Path | None,
    session_id: str,
) -> dict[str, Any]:
    package_record,candidate,run_path,candidate_path=_verify_wc3_inputs(package_dir,requested_run_dir)
    run=json.loads(run_path.read_text(encoding="utf-8"))
    store=ProjectStateStore(db_path)
    try:
        catalog=WorkspaceSourceCatalog.load(store,DEFAULT_SPATIAL_R01_ROOT)
        if catalog.study_area_id != "study-area-rotterdam-m4h-pilot-project-v5":
            raise ValueError("active StudyArea is not the confirmed v5 target")
        if catalog.project_id != "rotterdam-m4h-pilot-project":
            raise ValueError("active project differs from the WC3 project")
        study_area_path=Path(run["study_area_path"]).resolve()
        if sha256_file(study_area_path) != run.get("study_area_sha256"):
            raise ValueError("WC3 StudyArea input bytes differ from the run manifest")
        study_document=json.loads(study_area_path.read_text(encoding="utf-8"))
        geometry=shape(study_document.get("geometry",study_document))
        if canonical_geometry_hash(geometry.__geo_interface__) != catalog.study_area_geometry_sha256:
            raise ValueError("active StudyArea geometry differs from the hash-bound WC3 run")
        raw_artifacts,source_snapshots=_source_records(package_record,catalog.project_id)
        manifest_artifacts=_manifest_artifacts(package_dir,catalog.project_id,raw_artifacts,run_path,candidate_path,run)

        # R04 source-scoped Site Analysis remains bound to the original spatial-r01 catalog.
        site_bundle=build_r04_observational_evidence_bundle(catalog,store)
        site_exec,site_artifact,site_cards=persist_site_analysis_bundle(
            store,catalog,site_bundle,actor=ACTOR,actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id=session_id,idempotency_key=f"site-analysis-r04-{catalog.study_area_id}-{catalog.package_revision}",
        )

        # Preserve verified R02 as a separate historical exploratory execution.
        r02_bundle=load_verified_exploratory_syntax(PROJECT_ROOT,catalog)
        r02_exec,r02_artifact=persist_syntax_bundle(
            store,catalog,r02_bundle,is_historical_r02=True,actor=ACTOR,
            actor_kind=ActorKind.AGENT_AUTOMATION,actor_session_id=session_id,
            idempotency_key=f"r02-historical-{catalog.study_area_id}-{r02_bundle['r02_integrity_manifest_sha256'][:16]}",
        )
        r02_snapshot_ids=sorted({str(x.get("source_snapshot_id")) for x in r02_bundle.get("segments",[]) if x.get("source_snapshot_id")})
        r02_source_artifact_ids=sorted({str(x.get("source_artifact_id")) for x in r02_bundle.get("segments",[]) if x.get("source_artifact_id")})
        r02_cards=_persist_syntax_cards(
            store,catalog,r02_bundle,r02_artifact.entity_id,r02_artifact.payload["sha256"],
            actor_session_id=session_id,tool="space-syntax-historical",tool_version="r02-historical",
            created_at=str(r02_bundle.get("created_at") or run["completed_at_utc"]),
            source_snapshot_ids=r02_snapshot_ids,source_artifact_ids=r02_source_artifact_ids,
        )

        for payload in raw_artifacts:
            _ensure_record(store,"Artifact",payload,project_id=catalog.project_id,session_id=session_id,action="RecordAnalysisInputArtifact")
        for payload in source_snapshots:
            _ensure_record(store,"DatasetSnapshot",payload,project_id=catalog.project_id,session_id=session_id,action="RecordAnalysisInputSnapshot")
        for payload in manifest_artifacts:
            _ensure_record(store,"Artifact",payload,project_id=catalog.project_id,session_id=session_id,action="RecordWC3ManifestArtifact")
        all_artifacts=[*raw_artifacts,*manifest_artifacts]
        all_snapshots=source_snapshots
        syntax_catalog=replace(
            catalog,
            snapshots={**dict(catalog.snapshots),**{str(item["id"]):item for item in all_snapshots}},
        )
        candidate_bundle=dict(candidate)
        snapshot_ids=sorted(str(item["id"]) for item in all_snapshots)
        artifact_ids=sorted(str(item["id"]) for item in all_artifacts)
        candidate_bundle["source_input_snapshot_ids"]=snapshot_ids
        candidate_bundle["source_input_artifact_ids"]=artifact_ids
        candidate_bundle["source_provenance"]={
            "source_package_manifest_path":str((package_dir/"integrity-manifest.json").resolve()),
            "source_package_manifest_sha256":sha256_file(package_dir/"integrity-manifest.json"),
            "run_manifest_path":str(run_path),
            "run_manifest_sha256":sha256_file(run_path),
            "candidate_path":str(candidate_path),
            "candidate_sha256":sha256_file(candidate_path),
            "source_request_count":0,
            "source_license":"ODbL 1.0; © OpenStreetMap contributors",
        }
        candidate_hash=sha256_file(candidate_path)
        syntax_key=f"pst-331-{catalog.study_area_id}-{candidate_hash[:16]}"
        syntax_exec,syntax_artifact=persist_syntax_bundle(
            store,syntax_catalog,candidate_bundle,tool="PST 3.3.1",tool_version="3.3.1",
            is_historical_r02=False,actor=ACTOR,actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id=session_id,idempotency_key=syntax_key,
        )
        syntax_cards=_persist_syntax_cards(
            store,syntax_catalog,candidate_bundle,syntax_artifact.entity_id,syntax_artifact.payload["sha256"],
            actor_session_id=session_id,tool="PST 3.3.1",tool_version="3.3.1",
            created_at=str(run["completed_at_utc"]),source_snapshot_ids=snapshot_ids,source_artifact_ids=artifact_ids,
        )

        site_readback=get_persisted_site_analysis(store,catalog.project_id,catalog)
        syntax_readback=get_persisted_syntax_bundle(store,catalog.project_id,catalog,PROJECT_ROOT)
        if site_readback[2] != "VERIFIED_SOURCE_RESULT_ALIGNMENT":
            raise RuntimeError(f"persisted Site Analysis did not verify: {site_readback[2]}")
        if len(syntax_readback.get("layers",[])) != 6:
            raise RuntimeError("persisted Syntax API bundle does not expose exactly six layers")
        statuses={x.get("layer_id"):x.get("calculation_status") for x in syntax_readback.get("layers",[])}
        expected={x["layer_id"]:x["calculation_status"] for x in candidate_bundle["layers"]}
        if statuses != expected:
            raise RuntimeError("persisted Syntax layer statuses differ from the hash-bound WC3 candidate")
        if any(statuses.get(layer_id)!="NOT_COMPUTED_RUNTIME_BUDGET" for layer_id in ("syntax_regional_10000m_integration","syntax_regional_10000m_choice")):
            raise RuntimeError("10 km layers must remain NOT_COMPUTED_RUNTIME_BUDGET")
        return {
            "site_analysis": {"execution_id":site_exec.entity_id,"artifact_id":site_artifact.entity_id,"evidence_card_ids":[x.entity_id for x in site_cards],"status":site_readback[2]},
            "r02_historical_syntax": {"execution_id":r02_exec.entity_id,"artifact_id":r02_artifact.entity_id,"evidence_card_ids":r02_cards},
            "wc3_syntax": {"execution_id":syntax_exec.entity_id,"artifact_id":syntax_artifact.entity_id,"evidence_card_ids":syntax_cards,"source_snapshot_ids":snapshot_ids,"source_artifact_ids":artifact_ids,"layer_statuses":statuses},
            "ledger_event_count":store._connection.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0],
            "source_requests":0,
        }
    finally:
        store.close()


def _artifact_record(
    path: Path,
    *,
    project_id: str,
    producer: str,
    created_at: str,
    artifact_type: str,
    parent_ids: Sequence[str] = (),
) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    digest = sha256_file(resolved)
    artifact_id = f"artifact-pd20-{artifact_type}-{digest[:20]}"
    mime = "application/json" if resolved.suffix.lower() in {".json", ".geojson"} else "application/octet-stream"
    return Artifact.model_validate({
        "id": artifact_id,
        "type": artifact_type,
        "uri": resolved.as_uri(),
        "sha256": f"sha256:{digest}",
        "mime": mime,
        "crs": "EPSG:28992" if resolved.suffix.lower() == ".geojson" else None,
        "producer": producer,
        "created_at": created_at,
        "project_id": project_id,
        "size_bytes": resolved.stat().st_size,
        "parent_artifact_ids": list(parent_ids),
    }).model_dump(mode="json", exclude_none=True)


def _append_3dbag_bundle(
    store: ProjectStateStore,
    manifest_path: Path,
    *,
    backup_path: Path,
    backup_sha256: str,
) -> dict[str, Any]:
    bundle = build_snapshot_registration_bundle(manifest_path)
    new_artifacts = []
    new_snapshots = []
    for item in bundle.artifacts:
        try:
            existing = store.current(item.id)
        except EntityNotFoundError:
            new_artifacts.append(item)
        else:
            if existing.entity_type != "Artifact" or _canonical_bytes(existing.payload) != _canonical_bytes(item.model_dump(mode="json")):
                raise ValueError(f"existing 3D BAG Artifact {item.id} differs from the verified manifest")
    for item in bundle.dataset_snapshots:
        try:
            existing = store.current(item.id)
        except EntityNotFoundError:
            new_snapshots.append(item)
        else:
            if existing.entity_type != "DatasetSnapshot" or _canonical_bytes(existing.payload) != _canonical_bytes(item.model_dump(mode="json")):
                raise ValueError(f"existing 3D BAG DatasetSnapshot {item.id} differs from the verified manifest")
    if new_artifacts or new_snapshots:
        partial = replace(bundle, artifacts=tuple(new_artifacts), dataset_snapshots=tuple(new_snapshots))
        state_records, events = append_snapshot_registration_to_store(
            store,
            partial,
            backup_path=backup_path,
            expected_backup_sha256=f"sha256:{backup_sha256.removeprefix('sha256:')}",
        )
    else:
        state_records, events = [], []
    return {
        "manifest_sha256": bundle.manifest_sha256,
        "artifact_ids": [item.id for item in bundle.artifacts],
        "dataset_snapshot_ids": [item.id for item in bundle.dataset_snapshots],
        "appended_state_record_ids": [item.entity_id for item in state_records],
        "ledger_event_ids": [item.event_id for item in events],
        "idempotent_existing_count": len(bundle.artifacts) + len(bundle.dataset_snapshots) - len(state_records),
        "human_decision_count_created": 0,
    }


def _persist_pd20_to_open_store(
    db_path: Path,
    *,
    run_dir: Path,
    manifest_path: Path,
    backup_path: Path,
    backup_sha256: str,
    session_id: str,
) -> dict[str, Any]:
    store = ProjectStateStore(db_path)
    try:
        catalog = WorkspaceSourceCatalog.load(store, DEFAULT_SPATIAL_R01_ROOT)
        if catalog.study_area_id != "study-area-rotterdam-m4h-pilot-project-v5":
            raise ValueError("active StudyArea is not the confirmed v5 target")
        if catalog.project_id != "rotterdam-m4h-pilot-project":
            raise ValueError("active project differs from the PD-20 project")
        context = _load_week5_syntax_inputs(
            run_dir,
            expected_study_area_sha256=catalog.study_area_geometry_sha256,
        )
        run = context["run"]
        run_created = str(run.get("completed_at_utc") or datetime.now(timezone.utc).isoformat())
        pbf = context["extractions"][1500]["pbf"]
        pbf_source = context["extractions"][1500]["document"]["inputs"]["source"]
        retrieval = context["retrieval"]
        pbf_artifact = _artifact_record(
            pbf["path"], project_id=catalog.project_id, producer="Geofabrik regional OSM download",
            created_at=str(retrieval.get("timestamp_utc") or run_created), artifact_type="osm-pbf",
        )
        pbf_snapshot = DatasetSnapshot.model_validate({
            "id": f"dataset-snapshot-osm-geofabrik-{pbf['sha256'][:20]}",
            "project_id": catalog.project_id,
            "source": str(pbf_source.get("pbf_url")),
            "query": "Regional OSM PBF reused for pedestrian, bicycle, and motor_vehicle syntax extractions; envelopes 1500, 4000, 6000, 15000, and 20000 m.",
            "retrieved_at": str(retrieval.get("timestamp_utc")),
            "publisher": str(pbf_source.get("provider") or "Geofabrik and OpenStreetMap contributors"),
            "license": str(pbf_source.get("license") or "ODbL 1.0"),
            "version": Path(str(pbf_source.get("pbf_url", ""))).name,
            "sha256": f"sha256:{pbf['sha256']}",
            "raw_artifact_id": pbf_artifact["id"],
        }).model_dump(mode="json", exclude_none=True)

        extraction_records: dict[int, dict[str, Any]] = {}
        input_artifacts: dict[str, dict[str, Any]] = {pbf_artifact["id"]: pbf_artifact}
        producer = "PD-20 hash-verified OSM extraction run"
        for envelope_m, extraction in context["extractions"].items():
            document = extraction["document"]
            parent_ids = [pbf_artifact["id"]]
            row: dict[str, Any] = {}
            for key in ("network", "unlinks"):
                artifact = _artifact_record(
                    extraction[key]["path"], project_id=catalog.project_id, producer=producer,
                    created_at=run_created, artifact_type=f"pd20-{key}-{envelope_m}m", parent_ids=parent_ids,
                )
                row[f"{key}_artifact_id"] = artifact["id"]
                input_artifacts[artifact["id"]] = artifact
            for key in ("poly",):
                artifact = _artifact_record(
                    extraction[key]["path"], project_id=catalog.project_id, producer=producer,
                    created_at=run_created, artifact_type=f"pd20-{key}-{envelope_m}m", parent_ids=parent_ids,
                )
                input_artifacts[artifact["id"]] = artifact
            extraction_manifest = _artifact_record(
                extraction["path"], project_id=catalog.project_id, producer=producer,
                created_at=run_created, artifact_type=f"pd20-extraction-manifest-{envelope_m}m",
                parent_ids=[pbf_artifact["id"], *[row[f"{key}_artifact_id"] for key in ("network", "unlinks")]],
            )
            input_artifacts[extraction_manifest["id"]] = extraction_manifest
            row["extraction_manifest_artifact_id"] = extraction_manifest["id"]
            extraction_records[envelope_m] = row

        supporting_paths = {
            "study-area": context["study_area_path"],
            "retrieval-record": context["retrieval_path"],
            "method-manifest": context["method_path"],
            "runtime-manifest": context["runtime_path"],
            "run-manifest": context["run_path"],
            "candidate": context["candidate_path"],
        }
        for output_name, file_record in context["outputs"].items():
            supporting_paths[f"output-{output_name.removesuffix('.json')}"] = file_record["path"]
        for key, path in supporting_paths.items():
            artifact = _artifact_record(
                path, project_id=catalog.project_id, producer=producer, created_at=run_created,
                artifact_type="pd20-" + key.replace("_", "-"), parent_ids=[pbf_artifact["id"]],
            )
            input_artifacts[artifact["id"]] = artifact

        mode_to_envelope = {"pedestrian": 1500, "bicycle": 6000, "motor_vehicle": 20000}
        source_ids_by_mode = {}
        for mode, envelope_m in mode_to_envelope.items():
            source_ids_by_mode[mode] = {
                "network_artifact_id": extraction_records[envelope_m]["network_artifact_id"],
                "dataset_snapshot_id": pbf_snapshot["id"],
            }
        segments_by_mode = _build_week5_segments(context, catalog=catalog, source_ids_by_mode=source_ids_by_mode)
        candidate_bundle = enrich_week5_syntax_candidate(
            context["candidate"],
            candidate_sha256=context["candidate_sha256"],
            run_manifest_sha256=context["run_manifest_sha256"],
            layer_provenance=context["layer_provenance"],
            segments_by_mode=segments_by_mode,
        )
        all_artifacts = sorted(input_artifacts)
        candidate_bundle["source_input_snapshot_ids"] = [pbf_snapshot["id"]]
        candidate_bundle["source_input_artifact_ids"] = all_artifacts
        candidate_bundle["source_provenance"] = {
            "run_manifest_path": str(context["run_path"]),
            "run_manifest_sha256": context["run_manifest_sha256"],
            "candidate_path": str(context["candidate_path"]),
            "candidate_sha256": context["candidate_sha256"],
            "method_manifest_path": str(context["method_path"]),
            "method_manifest_sha256": context["method_file"]["sha256"],
            "runtime_manifest_path": str(context["runtime_path"]),
            "runtime_manifest_sha256": context["runtime_file"]["sha256"],
            "study_area_geometry_sha256": catalog.study_area_geometry_sha256,
            "source_request_count": 0,
            "source_license": "ODbL 1.0; © OpenStreetMap contributors",
            "evidence_level": "EXPLORATORY",
        }
        # Finish all hash, metrics, and geometry preflight before the first record is
        # appended, so malformed segment lineage cannot leave a partial BAG/input set.
        snapshot_registration = _append_3dbag_bundle(
            store,
            manifest_path,
            backup_path=backup_path,
            backup_sha256=backup_sha256,
        )
        for payload in [*input_artifacts.values(), pbf_snapshot]:
            _ensure_record(
                store,
                "DatasetSnapshot" if payload.get("id") == pbf_snapshot["id"] else "Artifact",
                payload,
                project_id=catalog.project_id,
                session_id=session_id,
                action="RecordPD20SyntaxInput",
            )
        syntax_catalog = replace(
            catalog,
            snapshots={**dict(catalog.snapshots), pbf_snapshot["id"]: pbf_snapshot},
        )
        syntax_key = f"pd20-pst-331-{catalog.study_area_id}-{context['candidate_sha256'][:20]}"
        syntax_exec, syntax_artifact = persist_syntax_bundle(
            store,
            syntax_catalog,
            candidate_bundle,
            tool="PST 3.3.1",
            tool_version="3.3.1",
            is_historical_r02=False,
            actor=ACTOR,
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id=session_id,
            idempotency_key=syntax_key,
        )
        card_ids = _persist_syntax_cards(
            store,
            syntax_catalog,
            candidate_bundle,
            syntax_artifact.entity_id,
            str(syntax_artifact.payload["sha256"]),
            actor_session_id=session_id,
            tool="PST 3.3.1",
            tool_version="3.3.1",
            created_at=run_created,
            source_snapshot_ids=[pbf_snapshot["id"]],
            source_artifact_ids=all_artifacts,
        )
        readback = get_persisted_syntax_bundle(store, catalog.project_id, catalog, PROJECT_ROOT)
        if readback.get("status") != "EXPLORATORY_CANDIDATE" or len(readback.get("layers", [])) != 6:
            raise RuntimeError(f"PD-20 syntax readback did not expose six layers: {readback.get('status')}")
        if readback.get("evidence_level") != "EXPLORATORY" or readback.get("formal_result_eligible") is not False:
            raise RuntimeError("PD-20 Syntax readback lost its EXPLORATORY eligibility guard")
        for expected, actual in zip(candidate_bundle["layers"], readback["layers"]):
            if (
                expected.get("layer_id") != actual.get("layer_id")
                or expected.get("segment_values") != actual.get("segment_values")
                or expected.get("output_file_sha256") != actual.get("output_file_sha256")
                or actual.get("network_mode") != expected.get("network_mode")
            ):
                raise RuntimeError("PD-20 syntax layer values or provenance changed during database readback")
        if not any("method-comparison-v1: FAIL" in item for item in readback.get("limitations", [])):
            raise RuntimeError("PD-20 syntax readback dropped the required method comparison limitation")
        return {
            "syntax": {
                "execution_id": syntax_exec.entity_id,
                "artifact_id": syntax_artifact.entity_id,
                "artifact_sha256": syntax_artifact.payload["sha256"],
                "evidence_card_ids": card_ids,
                "status": readback["status"],
                "evidence_level": readback["evidence_level"],
                "layer_ids": [item["layer_id"] for item in readback["layers"]],
                "layer_modes": {item["layer_id"]: item["network_mode"] for item in readback["layers"]},
            },
            "three_d_bag": snapshot_registration,
            "ledger_event_count": store._connection.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0],
            "source_requests": 0,
            "human_decision_count_created": 0,
        }
    finally:
        store.close()


def _verify_write_invariants(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    if after["quick_check"] != "ok" or after["integrity_check"] != "ok":
        raise RuntimeError("database quick_check/integrity_check failed after persistence")
    if before["ledger_event_count"] != before["ledger_max_sequence"]:
        raise RuntimeError("baseline ledger sequence/count mismatch; refusing write result certification")
    if after["ledger_max_sequence"] < before["ledger_max_sequence"] or after["ledger_event_count"] < before["ledger_event_count"]:
        raise RuntimeError("ledger regressed after persistence")
    if before["ledger_event_prefix_sha256"] != after["ledger_event_prefix_sha256"]:
        raise RuntimeError("pre-existing ledger rows changed during append-only persistence")
    if before["project_revision"] != after["project_revision"] or before["active_study_area_id"] != after["active_study_area_id"]:
        raise RuntimeError("Project revision or active StudyArea pointer changed")
    if before["protected_head_count"] != after["protected_head_count"] or before["protected_heads_sha256"] != after["protected_heads_sha256"]:
        raise RuntimeError("HumanDecision or Constraint heads changed")


def persist_database(
    database: Path,
    *,
    package_dir: Path=DEFAULT_SYNTAX_PACKAGE,
    syntax_run_dir: Path | None=None,
    syntax_modes_run_dir: Path | None=None,
    three_d_bag_manifest: Path | None=None,
    dry_run_copy_out: Path | None=None,
    write_authority: bool=False,
    expected_sha256: str | None=None,
    backup_dir: Path | None=None,
    session_id: str | None=None,
) -> dict[str, Any]:
    operation_started_at_utc=datetime.now(timezone.utc).isoformat()
    database=database.expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(f"database does not exist: {database}")
    package_dir=package_dir.expanduser().resolve()
    syntax_modes_run_dir = syntax_modes_run_dir.expanduser().resolve() if syntax_modes_run_dir else None
    three_d_bag_manifest = three_d_bag_manifest.expanduser().resolve() if three_d_bag_manifest else None
    if (syntax_modes_run_dir is None) != (three_d_bag_manifest is None):
        raise ValueError("PD-20 persistence requires both --syntax-modes-run-dir and --3dbag-manifest")
    if syntax_modes_run_dir is None:
        _verify_wc3_inputs(package_dir,syntax_run_dir)
    pre_sha=sha256_file(database)
    before=_database_signature(database)
    if before["quick_check"] != "ok" or before["integrity_check"] != "ok":
        raise RuntimeError("database failed pre-write integrity checks")
    if before["active_study_area_id"] != "study-area-rotterdam-m4h-pilot-project-v5":
        raise RuntimeError("active StudyArea is not the confirmed v5 target")
    if before["project_revision"] is None:
        raise RuntimeError("expected project head is missing")
    session_id=session_id or str(uuid4())
    if write_authority:
        if database != AUTHORITY_DB:
            raise ValueError(f"--write-authority is limited to the designated DB: {AUTHORITY_DB}")
        if not expected_sha256 or pre_sha != expected_sha256:
            raise ValueError("authority DB SHA-256 does not match --expected-sha256")
        backup_dir=(backup_dir or Path.home()/".local/share/urban-design-backups").expanduser().resolve()
        backup_dir.mkdir(parents=True,exist_ok=True)
        backup_path=backup_dir/f"state_pre_wc2_wc3_persistence_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}.sqlite3"
        backup_database_readonly(database,backup_path)
        backup_sha=sha256_file(backup_path)
        backup_sig=_database_signature(backup_path,event_columns=before["stable_event_columns"])
        if backup_sig["ledger_event_count"] != before["ledger_event_count"] or backup_sig["ledger_event_prefix_sha256"] != before["ledger_event_prefix_sha256"]:
            raise RuntimeError("sqlite3 .backup does not preserve the pre-write ledger snapshot")
        target=database
        mode="authority_write_after_sqlite3_backup"
    else:
        temp_dir = None
        if dry_run_copy_out is not None:
            target=dry_run_copy_out.expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise FileExistsError(f"refusing to overwrite dry-run database copy: {target}")
        else:
            temp_dir=tempfile.TemporaryDirectory(prefix="wc2-analysis-dry-run-",dir="/private/tmp")
            target=Path(temp_dir.name)/"state-copy.sqlite3"
        backup_database_readonly(database,target)
        backup_path=target.with_name(target.stem + ".prewrite-backup.sqlite3")
        backup_database_readonly(target, backup_path)
        backup_sha=sha256_file(backup_path)
        backup_sig=_database_signature(backup_path,event_columns=before["stable_event_columns"])
        if backup_sig["ledger_event_count"] != before["ledger_event_count"] or backup_sig["ledger_event_prefix_sha256"] != before["ledger_event_prefix_sha256"]:
            raise RuntimeError("pre-write SQLite backup does not preserve the dry-run ledger snapshot")
        mode="dry_run_disposable_copy"
    target_sha_before=sha256_file(target)
    if write_authority and target_sha_before != expected_sha256:
        raise RuntimeError("authority DB changed after expected SHA-256 validation and backup")
    target_before=_database_signature(target,event_columns=before["stable_event_columns"])
    if target_before["ledger_event_prefix_sha256"] != before["ledger_event_prefix_sha256"]:
        raise RuntimeError("dry-run SQLite copy differs from the read-only source baseline")
    if syntax_modes_run_dir is not None and three_d_bag_manifest is not None:
        result=_persist_pd20_to_open_store(
            target,
            run_dir=syntax_modes_run_dir,
            manifest_path=three_d_bag_manifest,
            backup_path=backup_path,
            backup_sha256=backup_sha,
            session_id=session_id,
        )
    else:
        result=_persist_to_open_store(target,package_dir=package_dir,requested_run_dir=syntax_run_dir,session_id=session_id)
    # Only checkpoint after writes have completed on the designated database or disposable clone.
    connection=sqlite3.connect(target)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        quick=connection.execute("PRAGMA quick_check").fetchone()[0]
        integrity=connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if not write_authority:
        _stabilize_sqlite_copy(target)
    after=_database_signature(
        target,event_columns=before["stable_event_columns"],
        event_through_sequence=before["ledger_max_sequence"],
        read_only=not write_authority,
    )
    after["quick_check"]=quick
    after["integrity_check"]=integrity
    _verify_write_invariants(before,after)
    if not write_authority:
        post_source_sha=sha256_file(database)
        post_source=_database_signature(
            database,event_columns=before["stable_event_columns"],
            event_through_sequence=before["ledger_max_sequence"],
        )
        if post_source_sha != pre_sha or post_source["ledger_event_prefix_sha256"] != before["ledger_event_prefix_sha256"]:
            raise RuntimeError("default dry-run changed the source database")
        result["source_database_sha256_before"]=pre_sha
        result["source_database_sha256_after"]=post_source_sha
        result["dry_run_copy_database_sha256_before"]=target_sha_before
        result["dry_run_copy_database_sha256_after"]=sha256_file(target)
        result["dry_run_copy_path"] = str(target)
        result["prewrite_backup_path"] = str(backup_path)
        result["prewrite_backup_sha256"] = backup_sha
    else:
        result["database_sha256_before"]=pre_sha
        result["backup_path"]=str(backup_path)
        result["backup_sha256"]=backup_sha
        result["backup_signature"]=backup_sig
        result["database_sha256_after"]=sha256_file(database)
        result["ledger_prefix_sha256_before"]=before["ledger_event_prefix_sha256"]
        result["ledger_prefix_sha256_after"]=after["ledger_event_prefix_sha256"]
    result["operation_started_at_utc"]=operation_started_at_utc
    result["operation_completed_at_utc"]=datetime.now(timezone.utc).isoformat()
    result["mode"]=mode
    result["database_path"]=str(database)
    result["authority_signature_before"]=before
    result["target_signature_after"]=after
    result["session_id"]=session_id
    result["backup_was_created_before_writable_store_open"]=bool(write_authority)
    if not write_authority and temp_dir is not None:
        temp_dir.cleanup()
    return result


def write_receipt(result: Mapping[str, Any], receipt_path: Path) -> dict[str, str]:
    receipt_path=receipt_path.expanduser().resolve()
    receipt_path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(dict(result),indent=2,ensure_ascii=False)+"\n"
    with receipt_path.open("x",encoding="utf-8") as stream:
        stream.write(payload)
    return {"path":str(receipt_path),"sha256":sha256_file(receipt_path)}


def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(description="Persist verified analysis; default is a disposable DB copy.")
    parser.add_argument("--database",type=Path,required=True,help="Read-only source DB for dry-run; exact authority DB when --write-authority is used.")
    parser.add_argument("--syntax-package-dir",type=Path,default=DEFAULT_SYNTAX_PACKAGE)
    parser.add_argument("--syntax-run-dir",type=Path,default=None,help="Must match the WC3 package record; defaults to its hash-bound run.")
    parser.add_argument("--syntax-modes-run-dir",type=Path,default=None,help="Hash-bound PD-20 six-layer run directory.")
    parser.add_argument("--3dbag-manifest",dest="three_d_bag_manifest",type=Path,default=None,help="Verified local 3D BAG source manifest to register with the Syntax layers.")
    parser.add_argument("--dry-run-copy-out",type=Path,default=None,help="Retain the default disposable database copy at this new path.")
    parser.add_argument("--session-id",type=str,default=None,help="Optional automation session ID; a random ID is generated by default.")
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run",action="store_true",help="Explicitly run on a temporary SQLite backup copy (default).")
    modes.add_argument("--write-authority",action="store_true",help="Append to the designated authority DB after SQLite backup-API backup and exact hash match.")
    parser.add_argument("--expected-sha256",type=str,default=None,help="Required live DB SHA-256 for --write-authority.")
    parser.add_argument("--backup-dir",type=Path,default=None,help="Authority backup destination (default ~/.local/share/urban-design-backups).")
    parser.add_argument("--receipt-out",type=Path,default=None,help="Write a non-overwriting JSON execution receipt to this path.")
    return parser


def main(argv: Sequence[str] | None=None) -> int:
    parser=build_parser()
    args=parser.parse_args(argv)
    if args.write_authority and not args.expected_sha256:
        parser.error("--write-authority requires --expected-sha256")
    if not args.write_authority and args.expected_sha256:
        parser.error("--expected-sha256 is only valid with --write-authority")
    receipt_path=args.receipt_out
    if receipt_path is None and args.write_authority:
        receipt_path=PROJECT_ROOT/"artifacts/week4-wc2-persistence/receipts"/f"receipt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:12]}.json"
    if receipt_path is not None:
        receipt_path=receipt_path.expanduser().resolve()
        if receipt_path.exists():
            parser.error(f"refusing to overwrite receipt: {receipt_path}")
        try:
            receipt_path.parent.mkdir(parents=True,exist_ok=True)
        except Exception as exc:
            print(json.dumps({"status":"BLOCKED","error":f"receipt path preflight failed: {type(exc).__name__}: {exc}"},indent=2))
            return 1
    try:
        result=persist_database(
            args.database,package_dir=args.syntax_package_dir,syntax_run_dir=args.syntax_run_dir,
            syntax_modes_run_dir=args.syntax_modes_run_dir,three_d_bag_manifest=args.three_d_bag_manifest,
            dry_run_copy_out=args.dry_run_copy_out,
            write_authority=args.write_authority,expected_sha256=args.expected_sha256,
            backup_dir=args.backup_dir,session_id=args.session_id,
        )
    except Exception as exc:
        print(json.dumps({"status":"BLOCKED","error":f"{type(exc).__name__}: {exc}"},indent=2))
        return 1
    result["status"]="PASS" if result["target_signature_after"]["quick_check"]=="ok" else "BLOCKED"
    if receipt_path is not None:
        try:
            result["receipt"]=write_receipt(result,receipt_path)
        except Exception as exc:
            print(json.dumps({"status":"BLOCKED","error":f"receipt write failed: {type(exc).__name__}: {exc}","persistence_result":result},indent=2,ensure_ascii=False))
            return 1
    print(json.dumps(result,indent=2,ensure_ascii=False))
    return 0 if result["status"]=="PASS" else 1


if __name__=="__main__":
    raise SystemExit(main())
