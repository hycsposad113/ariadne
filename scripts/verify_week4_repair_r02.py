#!/usr/bin/env python3
"""Fail-closed integrity and lineage verifier for the Week 4 R02 package.

The verifier is read-only. It checks the package's own files and parent hashes,
the source/result/figure relationships, and a read-only view of the live project
SQLite state. It never writes into the package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path, PurePosixPath
from typing import Any


PACKAGE_RELATIVE_PATH = Path("artifacts/week4-repair-r02")
MANIFEST_NAME = "integrity-manifest.json"
EXPECTED_PROJECT_ID = "rotterdam-m4h-pilot-project"
EXPECTED_STUDY_AREA_ID = "study-area-rotterdam-m4h-pilot-project-v5"
EXPECTED_SOURCE_PACKAGE_ID = "m2-a03-spatial-input-study-area-rotterdam-m4h-pilot-project-v5-spatial-r01"
EXPECTED_SOURCE_REVISION = "spatial-r01"
EXPECTED_LAYERS = {
    "syntax_local_800m_integration": 800.0,
    "syntax_local_800m_choice": 800.0,
    "syntax_mid_2000m_integration": 2000.0,
    "syntax_mid_2000m_choice": 2000.0,
    "syntax_regional_10000m_integration": 10000.0,
    "syntax_regional_10000m_choice": 10000.0,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_child(root: Path, raw_path: str, *, label: str) -> Path:
    candidate = PurePosixPath(raw_path)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ValueError(f"{label} path is not a confined relative path: {raw_path!r}")
    root_resolved = root.resolve()
    resolved = root_resolved.joinpath(*candidate.parts).resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"{label} path escapes its root: {raw_path!r}")
    return resolved


def _add(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _read_current_entity(connection: sqlite3.Connection, entity_id: str, entity_type: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT current_revision FROM state_heads WHERE entity_id=? AND entity_type=?",
        (entity_id, entity_type),
    ).fetchone()
    if row is None:
        raise ValueError(f"SQLite state head is missing: {entity_type}/{entity_id}")
    revision = int(row[0])
    version = connection.execute(
        "SELECT payload_json FROM state_versions WHERE entity_id=? AND entity_type=? AND revision=?",
        (entity_id, entity_type, revision),
    ).fetchone()
    if version is None:
        raise ValueError(f"SQLite current version is missing: {entity_type}/{entity_id}@{revision}")
    payload = json.loads(version[0])
    payload["_stored_revision"] = revision
    return payload


def _verify_live_database(project_root: Path, runtime: dict[str, Any], errors: list[str]) -> dict[str, Any] | None:
    db_rel = runtime.get("database_path")
    if not isinstance(db_rel, str):
        errors.append("runtime-state-check.json has no relative database_path")
        return None
    try:
        db_path = _safe_child(project_root, db_rel, label="SQLite")
        if not db_path.is_file():
            raise ValueError(f"authoritative SQLite file is missing: {db_rel}")
        db_hash = sha256_file(db_path)
        expected_hash = runtime.get("database_main_sha256")
        uri = db_path.as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            project = _read_current_entity(connection, EXPECTED_PROJECT_ID, "Project")
            area = _read_current_entity(connection, EXPECTED_STUDY_AREA_ID, "StudyArea")
            area_artifact = _read_current_entity(connection, str(area.get("geometry_artifact_id")), "Artifact")
            workspace_id = f"workspace-{EXPECTED_PROJECT_ID}"
            workspace = _read_current_entity(connection, workspace_id, "WorkspaceRevision")
            ledger_count, ledger_max = connection.execute(
                "SELECT count(*), COALESCE(max(sequence),0) FROM ledger_events"
            ).fetchone()
            snapshot_count = connection.execute(
                "SELECT count(*) FROM state_heads WHERE entity_type='DatasetSnapshot'"
            ).fetchone()[0]
            artifact_count = connection.execute(
                "SELECT count(*) FROM state_heads WHERE entity_type='Artifact'"
            ).fetchone()[0]
            state = {
                "database_main_sha256": db_hash,
                "database_hash_matches_capture": db_hash == expected_hash,
                "ledger_event_count": int(ledger_count),
                "ledger_max_sequence": int(ledger_max),
                "dataset_snapshot_count": int(snapshot_count),
                "artifact_count": int(artifact_count),
                "project_revision": project["_stored_revision"],
                "active_study_area_id": project.get("active_study_area_id"),
                "study_area_revision": area["_stored_revision"],
                "study_area_status": area.get("status"),
                "study_area_geometry_artifact_id": area.get("geometry_artifact_id"),
                "study_area_geometry_sha256": area.get("geometry_sha256"),
                "study_area_artifact_sha256": area_artifact.get("sha256"),
                "study_area_artifact_size_bytes": area_artifact.get("size_bytes"),
                "study_area_artifact_uri": area_artifact.get("uri"),
                "workspace_revision": workspace["_stored_revision"],
                "workspace_status": workspace.get("status"),
                "workspace_study_area_id": workspace.get("study_area_id"),
            }
        finally:
            connection.close()
    except (OSError, sqlite3.Error, ValueError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"read-only SQLite verification failed: {exc}")
        return None

    expected = {
        "ledger_event_count": 183,
        "ledger_max_sequence": 183,
        "dataset_snapshot_count": 52,
        "artifact_count": 109,
        "project_revision": 6,
        "active_study_area_id": EXPECTED_STUDY_AREA_ID,
        "study_area_revision": 1,
        "study_area_status": "CONFIRMED_FOR_EXPLORATION",
        "study_area_geometry_artifact_id": "study-area-artifact-9a59159505505dbe658ec666",
        "study_area_geometry_sha256": "sha256:3dedb804fa4f07f4c9570bcc64e68c8d576c03340455ab35fd4963bca52aa4f5",
        "study_area_artifact_sha256": "sha256:9a59159505505dbe658ec6667ecfeb9024b868faf6377e7cd91889c763170d32",
        "study_area_artifact_size_bytes": 347,
        "workspace_revision": 2,
        "workspace_status": "DRAFT",
        "workspace_study_area_id": EXPECTED_STUDY_AREA_ID,
    }
    for key, value in expected.items():
        _add(errors, state.get(key) == value, f"authoritative SQLite semantic state mismatch for {key}")
    recorded = runtime.get("active_study_area", {})
    _add(errors, recorded.get("id") == state["active_study_area_id"], "runtime capture StudyArea ID differs from SQLite")
    _add(errors, recorded.get("revision") == state["study_area_revision"], "runtime capture StudyArea revision differs from SQLite")
    _add(errors, recorded.get("geometry_sha256") == state["study_area_geometry_sha256"], "runtime capture StudyArea hash differs from SQLite")
    _add(errors, runtime.get("ledger_event_count") == state["ledger_event_count"], "runtime capture ledger count differs from SQLite")
    _add(errors, runtime.get("dataset_snapshot_count") == state["dataset_snapshot_count"], "runtime capture snapshot count differs from SQLite")
    _add(errors, runtime.get("artifact_count") == state["artifact_count"], "runtime capture artifact count differs from SQLite")
    try:
        raw_artifact_uri = state.get("study_area_artifact_uri")
        if not isinstance(raw_artifact_uri, str):
            raise ValueError("StudyArea Artifact URI is absent")
        artifact_rel = runtime.get("active_study_area_artifact_path")
        if not isinstance(artifact_rel, str):
            raise ValueError("captured StudyArea Artifact path is absent")
        artifact_path = _safe_child(project_root, artifact_rel, label="StudyArea Artifact")
        _add(errors, Path(raw_artifact_uri).name == artifact_path.name, "captured StudyArea Artifact path does not match SQLite URI")
        _add(errors, artifact_path.is_file(), "active StudyArea Artifact file is missing")
        if artifact_path.is_file():
            _add(errors, artifact_path.stat().st_size == state["study_area_artifact_size_bytes"], "active StudyArea Artifact size differs from SQLite")
            expected_artifact_hash = str(state["study_area_artifact_sha256"]).removeprefix("sha256:")
            _add(errors, sha256_file(artifact_path) == expected_artifact_hash, "active StudyArea Artifact hash differs from SQLite")
    except (OSError, ValueError, TypeError) as exc:
        errors.append(f"active StudyArea Artifact verification failed: {exc}")
    return state


def verify_package(
    package_root: Path,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    project_root = (project_root or package_root.parents[1]).resolve()
    errors: list[str] = []
    checked_files = 0
    checked_parents = 0
    semantic_state: dict[str, Any] | None = None

    def package_file_hash(relative_path: str) -> str | None:
        try:
            return sha256_file(_safe_child(package_root, relative_path, label="package reference"))
        except (OSError, ValueError) as exc:
            errors.append(f"cannot hash package reference {relative_path}: {exc}")
            return None

    manifest_path = package_root / MANIFEST_NAME
    if not manifest_path.is_file():
        return {"status": "BLOCKED", "errors": [f"missing {MANIFEST_NAME}"], "checked_files": 0, "checked_parents": 0}
    try:
        manifest = _json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "BLOCKED", "errors": [f"cannot parse integrity manifest: {exc}"], "checked_files": 0, "checked_parents": 0}

    _add(errors, manifest.get("schema_version") == "week4-r02-integrity-v1", "integrity manifest schema version mismatch")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        entries = []
        errors.append("integrity manifest files must be a list")
    listed: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append("integrity manifest contains an invalid file entry")
            continue
        rel = entry["path"]
        if rel in listed:
            errors.append(f"duplicate manifest file path: {rel}")
            continue
        listed[rel] = entry
        try:
            path = _safe_child(package_root, rel, label="package file")
            if not path.is_file():
                errors.append(f"package file is missing: {rel}")
                continue
            data = path.read_bytes()
            checked_files += 1
            _add(errors, len(data) == entry.get("size_bytes"), f"package file size mismatch: {rel}")
            _add(errors, hashlib.sha256(data).hexdigest() == entry.get("sha256"), f"package file SHA-256 mismatch: {rel}")
        except (OSError, ValueError) as exc:
            errors.append(f"invalid package file {rel}: {exc}")

        parents = entry.get("parent_paths", [])
        parent_hashes = entry.get("parent_sha256", {})
        if not isinstance(parents, list) or not isinstance(parent_hashes, dict) or set(parents) != set(parent_hashes):
            errors.append(f"parent path/hash declaration mismatch: {rel}")
            continue
        for parent in parents:
            try:
                parent_path = _safe_child(project_root, str(parent), label="parent")
                if not parent_path.is_file():
                    errors.append(f"parent file is missing: {parent}")
                    continue
                checked_parents += 1
                _add(errors, sha256_file(parent_path) == parent_hashes[parent], f"parent SHA-256 mismatch: {parent}")
            except (OSError, ValueError) as exc:
                errors.append(f"invalid parent {parent!r}: {exc}")

    try:
        actual_files = {
            path.relative_to(package_root).as_posix()
            for path in package_root.rglob("*")
            if path.is_file() and path.name != MANIFEST_NAME
        }
        _add(errors, actual_files == set(listed), "integrity manifest does not enumerate exactly the package files (excluding itself)")
    except OSError as exc:
        errors.append(f"cannot enumerate package files: {exc}")

    try:
        package = _json(package_root / "package-record.json")
        source = _json(package_root / "syntax/source-manifest.json")
        context = _json(package_root / "syntax/context.geojson")
        study = _json(package_root / "syntax/study-area.geojson")
        result = _json(package_root / "syntax/syntax-result.json")
        figure = _json(package_root / "syntax/figure-review-report.json")
        cards_doc = _json(package_root / "evidence-cards.json")
        handoff = _json(package_root / "handoff.json")
        runtime = _json(package_root / "runtime-state-check.json")
        request_log = _json(package_root / "request-log.json")
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        errors.append(f"required package evidence is missing or invalid: {exc}")
        package = source = context = study = result = figure = cards_doc = handoff = runtime = request_log = {}

    for key, expected in {
        "schema_version": "week4-r02-package-v1",
        "task_id": "M2-A03-R02",
        "project_id": EXPECTED_PROJECT_ID,
        "study_area_id": EXPECTED_STUDY_AREA_ID,
        "source_package_id": EXPECTED_SOURCE_PACKAGE_ID,
        "source_package_revision": EXPECTED_SOURCE_REVISION,
        "status": "EXECUTOR_SELF_CHECKED",
    }.items():
        _add(errors, package.get(key) == expected, f"package record mismatch for {key}")

    for doc_name, doc in (("source manifest", source), ("syntax result", result)):
        _add(errors, doc.get("project_id") == EXPECTED_PROJECT_ID, f"{doc_name} project ID mismatch")
        _add(errors, doc.get("study_area_id") == EXPECTED_STUDY_AREA_ID, f"{doc_name} StudyArea ID mismatch")
        _add(errors, doc.get("package_id") == EXPECTED_SOURCE_PACKAGE_ID, f"{doc_name} source package ID mismatch")
        _add(errors, doc.get("package_revision") == EXPECTED_SOURCE_REVISION, f"{doc_name} source revision mismatch")
        _add(errors, doc.get("crs") == "EPSG:28992", f"{doc_name} CRS mismatch")
    _add(errors, source.get("source_completeness_evidence") is None, "source manifest unexpectedly claims completeness evidence")
    _add(errors, source.get("boundary_stability_evidence_by_radius_m") == {}, "source manifest unexpectedly claims boundary stability")
    _add(errors, result.get("status") == "BLOCKED_SOURCE_COVERAGE_UNVERIFIED", "Syntax result no longer carries its blocked coverage status")
    _add(errors, result.get("source_complete") is False, "Syntax result unexpectedly claims complete source coverage")

    feature_ids: set[str] = set()
    try:
        features = context.get("features", [])
        for feature in features:
            properties = feature.get("properties") or {}
            feature_id = str(properties.get("source_feature_id") or "")
            _add(errors, bool(feature_id), "context feature has no source feature ID")
            feature_ids.add(feature_id)
            _add(errors, properties.get("source_artifact_id") == "artifact-osm-overpass-v5-normalized-3390e215019805a1", f"context feature has wrong source Artifact: {feature_id}")
            _add(errors, properties.get("source_snapshot_id") == "snapshot-osm-overpass-v5-3390e215019805a1", f"context feature has wrong DatasetSnapshot: {feature_id}")
        _add(errors, len(features) == 140, "context source feature count differs from the captured R02 build")
    except (AttributeError, TypeError) as exc:
        errors.append(f"invalid context feature collection: {exc}")

    segment_mapping = source.get("segment_mapping", {})
    _add(errors, isinstance(segment_mapping, dict) and len(segment_mapping) == 1355, "segment mapping count differs from the captured R02 build")
    if isinstance(segment_mapping, dict):
        for segment_id, mapping in segment_mapping.items():
            _add(errors, mapping.get("source_feature_id") in feature_ids, f"segment mapping references absent source feature: {segment_id}")
            _add(errors, mapping.get("source_artifact_id") == "artifact-osm-overpass-v5-normalized-3390e215019805a1", f"segment mapping has wrong Artifact: {segment_id}")
            _add(errors, mapping.get("source_snapshot_id") == "snapshot-osm-overpass-v5-3390e215019805a1", f"segment mapping has wrong DatasetSnapshot: {segment_id}")

    source_artifacts = source.get("source_artifacts", [])
    source_snapshots = source.get("source_snapshots", [])
    _add(errors, len(source_artifacts) == 1, "Syntax source manifest must identify exactly one normalized OSM Artifact")
    _add(errors, len(source_snapshots) == 1, "Syntax source manifest must identify exactly one OSM DatasetSnapshot")
    if source_artifacts and source_snapshots:
        source_artifact = source_artifacts[0]
        source_snapshot = source_snapshots[0]
        _add(errors, source_snapshot.get("normalized_artifact_id") == source_artifact.get("id"), "source DatasetSnapshot does not reference the normalized Artifact")
        _add(errors, source_snapshot.get("project_id") == EXPECTED_PROJECT_ID, "source DatasetSnapshot belongs to another project")
        try:
            source_manifest_path = _safe_child(
                project_root,
                str(source.get("spatial_r01_manifest_path", "")),
                label="spatial-r01 manifest",
            )
            _add(errors, source_manifest_path.is_file(), "retained spatial-r01 integrity manifest is missing")
            if source_manifest_path.is_file():
                _add(errors, sha256_file(source_manifest_path) == source.get("spatial_r01_manifest_sha256"), "retained spatial-r01 manifest hash mismatch")
                upstream_manifest = _json(source_manifest_path)
                source_file = _safe_child(
                    source_manifest_path.parent,
                    str(source_artifact.get("uri", "")),
                    label="normalized OSM Artifact",
                )
                _add(errors, source_file.is_file(), "normalized OSM source Artifact file is missing")
                if source_file.is_file():
                    expected_hash = str(source_artifact.get("sha256", "")).removeprefix("sha256:")
                    _add(errors, source_file.stat().st_size == source_artifact.get("size_bytes"), "normalized OSM source Artifact size mismatch")
                    _add(errors, sha256_file(source_file) == expected_hash, "normalized OSM source Artifact hash mismatch")
                    upstream_entry = next(
                        (item for item in upstream_manifest.get("normalized_artifacts", []) if item.get("id") == source_artifact.get("id")),
                        None,
                    )
                    _add(errors, isinstance(upstream_entry, dict), "normalized OSM source Artifact is absent from spatial-r01 integrity manifest")
                    if isinstance(upstream_entry, dict):
                        _add(errors, str(upstream_entry.get("sha256", "")).removeprefix("sha256:") == expected_hash, "spatial-r01 manifest has a different normalized OSM source hash")
                        _add(errors, upstream_entry.get("size_bytes") == source_artifact.get("size_bytes"), "spatial-r01 manifest has a different normalized OSM source size")
                    package_manifest_path = source_manifest_path.with_name("package-manifest.json")
                    _add(errors, package_manifest_path.is_file(), "retained spatial-r01 package-manifest.json is missing")
                    if package_manifest_path.is_file():
                        upstream_package_manifest = _json(package_manifest_path)
                        normalized_rel = source_file.relative_to(source_manifest_path.parent).as_posix()
                        file_entry = next(
                            (item for item in upstream_package_manifest.get("files", []) if item.get("path") == normalized_rel),
                            None,
                        )
                        _add(errors, isinstance(file_entry, dict), "normalized OSM source file is absent from spatial-r01 package manifest")
                        if isinstance(file_entry, dict):
                            _add(errors, str(file_entry.get("sha256", "")).removeprefix("sha256:") == expected_hash, "spatial-r01 package manifest has a different OSM source hash")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"cannot verify retained spatial-r01 source: {exc}")

    source_manifest_hash = package_file_hash("syntax/source-manifest.json")
    context_hash = package_file_hash("syntax/context.geojson")
    study_hash = package_file_hash("syntax/study-area.geojson")
    result_hash = package_file_hash("syntax/syntax-result.json")
    _add(errors, result.get("source_manifest_sha256") == source_manifest_hash, "Syntax result source-manifest hash mismatch")
    _add(errors, result.get("context_geojson_sha256") == context_hash, "Syntax result context hash mismatch")
    _add(errors, result.get("study_area_geojson_sha256") == study_hash, "Syntax result StudyArea hash mismatch")
    _add(errors, source.get("context_geojson_sha256") == context_hash, "source-manifest context hash mismatch")
    _add(errors, source.get("study_area_geojson_sha256") == study_hash, "source-manifest StudyArea hash mismatch")
    _add(errors, study.get("id") == EXPECTED_STUDY_AREA_ID, "Syntax StudyArea artifact ID mismatch")
    _add(errors, (study.get("properties") or {}).get("crs") == "EPSG:28992", "Syntax StudyArea artifact CRS mismatch")

    layers = result.get("layers", [])
    by_id = {item.get("layer_id"): item for item in layers if isinstance(item, dict)}
    _add(errors, set(by_id) == set(EXPECTED_LAYERS), "Syntax result must contain the six declared layers")
    for layer_id, radius in EXPECTED_LAYERS.items():
        layer = by_id.get(layer_id, {})
        _add(errors, layer.get("radius_m") == radius, f"Syntax layer radius mismatch: {layer_id}")
        values = layer.get("segment_values", {})
        _add(errors, isinstance(values, dict), f"Syntax layer values are not an object: {layer_id}")
        if radius > 800.0:
            _add(errors, layer.get("calculation_status") == "NOT_COMPUTED_COVERAGE_BLOCKED", f"blocked radius unexpectedly computed: {layer_id}")
            _add(errors, values == {}, f"uncomputed radius contains values: {layer_id}")
        else:
            _add(errors, layer.get("calculation_status") == "COMPUTED", f"800m exploratory layer is missing its calculation: {layer_id}")
            _add(errors, layer.get("data_readiness") == "BLOCKED_COVERAGE_EVIDENCE_ABSENT", f"800m layer readiness is not blocked: {layer_id}")
            _add(errors, set(values).issubset(segment_mapping), f"Syntax values are not source-mapped: {layer_id}")

    _add(errors, figure.get("data_readiness") == "BLOCKED_COVERAGE_EVIDENCE_ABSENT", "figure is missing its blocked readiness label")
    _add(errors, figure.get("source_manifest_sha256") == source_manifest_hash, "figure source-manifest hash mismatch")
    _add(errors, figure.get("syntax_result_sha256") == result_hash, "figure Syntax-result hash mismatch")
    _add(errors, figure.get("context_sha256") == context_hash, "figure context hash mismatch")
    _add(errors, figure.get("study_area_sha256") == study_hash, "figure StudyArea hash mismatch")
    for field, path_key in (("png_sha256", "png_path"), ("svg_sha256", "svg_path")):
        raw_path = figure.get(path_key)
        try:
            figure_path = _safe_child(project_root, str(raw_path), label="figure")
            _add(errors, figure_path.is_file(), f"figure file is missing: {raw_path}")
            if figure_path.is_file():
                _add(errors, sha256_file(figure_path) == figure.get(field), f"figure file hash mismatch: {raw_path}")
        except (OSError, ValueError) as exc:
            errors.append(f"invalid figure path {raw_path!r}: {exc}")

    cards = cards_doc.get("cards", [])
    _add(errors, cards_doc.get("status") == "BLOCKED_SOURCE_RESULT_ALIGNMENT", "Evidence Card bundle is not marked blocked")
    _add(errors, cards == [], "R02 currently has no same-revision verified Evidence Cards; do not populate them from older evidence")
    _add(errors, handoff.get("valid_evidence_cards") == [card.get("id") for card in cards if card.get("validation_status") == "VALIDATED"], "handoff Evidence Card IDs do not resolve from this package")
    _add(errors, handoff.get("evidence_cards_status") == "BLOCKED_SOURCE_RESULT_ALIGNMENT", "handoff does not preserve blocked Evidence Card status")
    _add(errors, handoff.get("source_package_revision") == EXPECTED_SOURCE_REVISION, "handoff source revision mismatch")

    def require_parent(package_path: str, expected: str) -> None:
        if package_path.startswith(package_prefix + "/"):
            package_path = package_path[len(package_prefix) + 1 :]
        entry = listed.get(package_path)
        _add(
            errors,
            isinstance(entry, dict) and expected in entry.get("parent_paths", []),
            f"required provenance parent is not declared: {package_path} -> {expected}",
        )

    package_prefix = PACKAGE_RELATIVE_PATH.as_posix()
    source_manifest_rel = str(source.get("spatial_r01_manifest_path", ""))
    active_artifact_rel = str(package.get("authority", {}).get("study_area_artifact_path", ""))
    normalized_source_rel = ""
    if source_manifest_rel and source_artifacts:
        normalized_source_rel = (
            Path(source_manifest_rel).parent / str(source_artifacts[0].get("uri", ""))
        ).as_posix()
        package_manifest_rel = (Path(source_manifest_rel).parent / "package-manifest.json").as_posix()
        require_parent(f"{package_prefix}/syntax/source-manifest.json", source_manifest_rel)
        require_parent(f"{package_prefix}/syntax/source-manifest.json", package_manifest_rel)
        require_parent(f"{package_prefix}/syntax/source-manifest.json", normalized_source_rel)
        require_parent(f"{package_prefix}/syntax/context.geojson", normalized_source_rel)
    if active_artifact_rel:
        require_parent(f"{package_prefix}/syntax/study-area.geojson", active_artifact_rel)
        require_parent(f"{package_prefix}/syntax/context.geojson", active_artifact_rel)
    for child, parents in {
        "syntax/syntax-result.json": ["syntax/source-manifest.json", "syntax/context.geojson", "syntax/study-area.geojson"],
        "syntax/figure-review-report.json": ["syntax/source-manifest.json", "syntax/context.geojson", "syntax/study-area.geojson", "syntax/syntax-result.json"],
        "syntax/syntax-local-800m-integration-r02.png": ["syntax/source-manifest.json", "syntax/context.geojson", "syntax/study-area.geojson", "syntax/syntax-result.json"],
        "syntax/syntax-local-800m-integration-r02.svg": ["syntax/source-manifest.json", "syntax/context.geojson", "syntax/study-area.geojson", "syntax/syntax-result.json"],
        "evidence-cards.json": ["syntax/source-manifest.json", "syntax/syntax-result.json"],
        "handoff.json": ["package-record.json", "evidence-cards.json", "syntax/syntax-result.json", "browser/report.json"],
    }.items():
        for parent in parents:
            require_parent(f"{package_prefix}/{child}", f"{package_prefix}/{parent}")

    expected_zero = {
        "candidate_or_geodata_requests": 0,
        "weather_requests": 0,
        "pdok_requests": 0,
        "osm_requests": 0,
        "model_requests": 0,
        "qgis_calls": 0,
        "dataset_snapshots_published": 0,
    }
    counts = request_log.get("counts", {})
    for key, expected in expected_zero.items():
        _add(errors, counts.get(key) == expected, f"request log counter must remain {expected}: {key}")
    _add(errors, request_log.get("external_requests_made") == [], "R02 package must not record new external requests")

    try:
        semantic_state = _verify_live_database(project_root, runtime, errors)
    except (OSError, ValueError, TypeError) as exc:
        errors.append(f"authoritative SQLite verification failed: {exc}")

    return {
        "status": "PASS" if not errors else "BLOCKED",
        "package_id": manifest.get("package_id"),
        "checked_files": checked_files,
        "checked_parents": checked_parents,
        "semantic_state": semantic_state,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_root", nargs="?", type=Path, default=Path("artifacts/week4-repair-r02"))
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None, help="write JSON report outside the package")
    args = parser.parse_args(argv)
    result = verify_package(args.package_root, project_root=args.project_root)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
