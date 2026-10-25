from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest

import scripts.register_3dbag_snapshots as registration_module
from scripts.register_3dbag_snapshots import main as register_main
from urban_design.models import Project
from urban_design.store import ProjectStateStore
from urban_design.three_d_bag import (
    BuildingHeightTable,
    append_snapshot_registration_to_store,
    build_snapshot_registration_bundle,
)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_height_table(path: Path, tile_path: Path) -> dict[str, Any]:
    tile_url = "https://data.3dbag.nl/v20250903/tiles/9/304/512/9-304-512.gpkg.gz"
    tile_source = {
        "tile_id": "9/304/512",
        "url": tile_url,
        "path": str(tile_path.resolve()),
        "sha256": _sha256(tile_path),
        "size_bytes": tile_path.stat().st_size,
    }
    table = BuildingHeightTable(
        data_version="v2025.09.03",
        license="CC BY 4.0",
        attribution="© 3DBAG by tudelft3d and 3DGI",
        study_area_id="study-area-rotterdam-m4h-pilot-project-v5",
        study_area_version="v5",
        study_area_geometry_sha256="sha256:" + "a" * 64,
        study_area_artifact_sha256="sha256:" + "b" * 64,
        study_area_horizontal_crs="EPSG:28992",
        vertical_reference="NAP height (EPSG:5709); compound tile CRS EPSG:7415",
        buffer_distance_m=500.0,
        buffer_geometry_sha256="sha256:" + "c" * 64,
        buffer_bbox_m=(-500.0, -500.0, 510.0, 510.0),
        buffered_area_m2=1000.0,
        records={},
        source_tiles=(tile_source,),
    )
    path.write_text(json.dumps(table.to_dict(), ensure_ascii=False), encoding="utf-8")
    return {
        "data_version": table.data_version,
        "license": table.license,
        "attribution": table.attribution,
        "study_area_id": table.study_area_id,
        "study_area_version": table.study_area_version,
        "study_area_geometry_sha256": table.study_area_geometry_sha256,
        "study_area_artifact_sha256": table.study_area_artifact_sha256,
        "study_area_horizontal_crs": table.study_area_horizontal_crs,
        "buffer_distance_m": table.buffer_distance_m,
        "buffer_geometry_sha256": table.buffer_geometry_sha256,
        "record_count": 0,
        "available_count": 0,
        "unavailable_count": 0,
        "tile_url": tile_url,
        "tile_source": tile_source,
    }


def test_registration_bundle_validates_raw_and_derived_artifacts_without_database_write(
    tmp_path: Path,
) -> None:
    tile_path = tmp_path / "tile.gpkg.gz"
    tile_path.write_bytes(b"fixture raw tile bytes")
    table_path = tmp_path / "height-table.json"
    table_provenance = _write_height_table(table_path, tile_path)
    manifest = {
        "schema_version": "3dbag-height-source-manifest-v1",
        "project_id": "rotterdam-m4h-pilot-project",
        "dataset": {
            "version": table_provenance["data_version"],
            "publisher": "3D geoinformation research group, TU Delft and 3DGI",
            "license": table_provenance["license"],
            "license_url": "https://docs.3dbag.nl/en/copyright/",
            "attribution": table_provenance["attribution"],
        },
        "study_area": {
            "id": table_provenance["study_area_id"],
            "version": table_provenance["study_area_version"],
            "geometry_sha256": table_provenance["study_area_geometry_sha256"],
            "artifact_id": "study-area-artifact-existing-v5",
            "artifact_sha256": table_provenance["study_area_artifact_sha256"],
            "horizontal_crs": table_provenance["study_area_horizontal_crs"],
        },
        "scope": {
            "buffer_distance_m": table_provenance["buffer_distance_m"],
        },
        "height_table": {
            "artifact_id": "artifact-3dbag-height-table-fixture",
            "path": str(table_path),
            "sha256": _sha256(table_path),
            "size_bytes": table_path.stat().st_size,
            "created_at": "2026-09-27T14:00:00Z",
            "buffer_geometry_sha256": table_provenance["buffer_geometry_sha256"],
            "record_count": table_provenance["record_count"],
            "available_count": table_provenance["available_count"],
            "unavailable_count": table_provenance["unavailable_count"],
        },
        "tiles": [
            {
                "artifact_id": "artifact-3dbag-tile-9-304-512-fixture",
                "snapshot_id": "dataset-3dbag-v2025-09-03-tile-9-304-512-fixture",
                "tile_id": "9/304/512",
                "url": table_provenance["tile_url"],
                "path": str(tile_path),
                "sha256": _sha256(tile_path),
                "size_bytes": tile_path.stat().st_size,
                "retrieved_at": "2026-09-27T14:10:28Z",
                "query": "Official tile response selected by the StudyArea buffer query.",
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    bundle = build_snapshot_registration_bundle(manifest_path)

    assert len(bundle.artifacts) == 2
    raw_artifact = next(item for item in bundle.artifacts if item.id == manifest["tiles"][0]["artifact_id"])
    derived_artifact = next(item for item in bundle.artifacts if item.id == manifest["height_table"]["artifact_id"])
    assert raw_artifact.sha256 == _sha256(tile_path)
    assert derived_artifact.parent_artifact_ids == [
        manifest["tiles"][0]["artifact_id"],
        manifest["study_area"]["artifact_id"],
    ]
    assert len(bundle.dataset_snapshots) == 1
    snapshot = bundle.dataset_snapshots[0]
    assert snapshot.raw_artifact_id == raw_artifact.id
    assert snapshot.normalized_artifact_id == derived_artifact.id
    assert snapshot.version == "v2025.09.03"
    assert snapshot.license == "CC BY 4.0"
    assert snapshot.sha256 == raw_artifact.sha256


def test_3dbag_authority_writer_requires_live_database_hash_before_opening_database(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        register_main(["--database", "/does/not/exist.sqlite3", "--write-authority"])
    assert exc.value.code == 2
    assert "--write-authority requires --expected-sha256" in capsys.readouterr().err


def test_3dbag_write_copy_rechecks_database_hash_after_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3")
    database = tmp_path / "3dbag-test-copy.sqlite3"
    registration_module.backup_database_readonly(source, database)
    expected = _sha256(database).removeprefix("sha256:")
    monkeypatch.setattr(
        registration_module,
        "build_snapshot_registration_bundle",
        lambda _path: SimpleNamespace(
            manifest_sha256="sha256:" + "a" * 64,
            project_id="rotterdam-m4h-pilot-project",
            artifacts=(),
            dataset_snapshots=(),
        ),
    )
    original_backup = registration_module.backup_database_readonly

    def mutate_after_backup(source_path: Path, backup_path: Path) -> None:
        original_backup(source_path, backup_path)
        with sqlite3.connect(source_path) as connection:
            connection.execute("PRAGMA user_version = 92")

    monkeypatch.setattr(registration_module, "backup_database_readonly", mutate_after_backup)
    with pytest.raises(RuntimeError, match="changed after expected SHA-256 validation and backup"):
        register_main([
            "--database", str(database),
            "--manifest", str(tmp_path / "unused-manifest.json"),
            "--write-copy",
            "--expected-sha256", expected,
            "--backup-out", str(tmp_path / "3dbag-prewrite.sqlite3"),
        ])


def test_registration_bundle_rejects_changed_raw_bytes(tmp_path: Path) -> None:
    tile_path = tmp_path / "tile.gpkg.gz"
    tile_path.write_bytes(b"unreconciled raw bytes")
    table_path = tmp_path / "height-table.json"
    table_provenance = _write_height_table(table_path, tile_path)
    manifest = {
        "schema_version": "3dbag-height-source-manifest-v1",
        "project_id": "rotterdam-m4h-pilot-project",
        "dataset": {
            "version": table_provenance["data_version"],
            "publisher": "3D geoinformation research group, TU Delft and 3DGI",
            "license": table_provenance["license"],
            "license_url": "https://docs.3dbag.nl/en/copyright/",
            "attribution": table_provenance["attribution"],
        },
        "study_area": {
            "id": table_provenance["study_area_id"],
            "version": table_provenance["study_area_version"],
            "geometry_sha256": table_provenance["study_area_geometry_sha256"],
            "artifact_id": "study-area-artifact-existing-v5",
            "artifact_sha256": table_provenance["study_area_artifact_sha256"],
            "horizontal_crs": table_provenance["study_area_horizontal_crs"],
        },
        "scope": {
            "buffer_distance_m": table_provenance["buffer_distance_m"],
        },
        "height_table": {
            "artifact_id": "artifact-3dbag-height-table-fixture",
            "path": str(table_path),
            "sha256": _sha256(table_path),
            "size_bytes": table_path.stat().st_size,
            "created_at": "2026-09-27T14:00:00Z",
            "buffer_geometry_sha256": table_provenance["buffer_geometry_sha256"],
            "record_count": table_provenance["record_count"],
            "available_count": table_provenance["available_count"],
            "unavailable_count": table_provenance["unavailable_count"],
        },
        "tiles": [
            {
                "artifact_id": "artifact-3dbag-tile-fixture",
                "snapshot_id": "dataset-3dbag-tile-fixture",
                "tile_id": "9/304/512",
                "url": table_provenance["tile_url"],
                "path": str(tile_path),
                "sha256": "sha256:" + "0" * 64,
                "size_bytes": tile_path.stat().st_size,
                "retrieved_at": "2026-09-27T14:10:28Z",
                "query": "Official tile response selected by the StudyArea buffer query.",
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    try:
        build_snapshot_registration_bundle(manifest_path)
    except ValueError as exc:
        assert "SHA-256" in str(exc)
    else:
        raise AssertionError("changed source bytes must prevent registration")


def test_registration_writer_appends_only_fixture_artifacts_and_snapshots(tmp_path: Path) -> None:
    tile_path = tmp_path / "tile.gpkg.gz"
    tile_path.write_bytes(b"fixture raw tile bytes")
    table_path = tmp_path / "height-table.json"
    table_provenance = _write_height_table(table_path, tile_path)
    manifest = {
        "schema_version": "3dbag-height-source-manifest-v1",
        "project_id": "rotterdam-m4h-pilot-project",
        "dataset": {
            "version": table_provenance["data_version"],
            "publisher": "3D geoinformation research group, TU Delft and 3DGI",
            "license": table_provenance["license"],
            "license_url": "https://docs.3dbag.nl/en/copyright/",
            "attribution": table_provenance["attribution"],
        },
        "study_area": {
            "id": table_provenance["study_area_id"],
            "version": table_provenance["study_area_version"],
            "geometry_sha256": table_provenance["study_area_geometry_sha256"],
            "artifact_id": "artifact-study-area-fixture-v5",
            "artifact_sha256": table_provenance["study_area_artifact_sha256"],
            "horizontal_crs": table_provenance["study_area_horizontal_crs"],
        },
        "scope": {
            "buffer_distance_m": table_provenance["buffer_distance_m"],
        },
        "height_table": {
            "artifact_id": "artifact-3dbag-height-table-fixture",
            "path": str(table_path),
            "sha256": _sha256(table_path),
            "size_bytes": table_path.stat().st_size,
            "created_at": "2026-09-27T14:00:00Z",
            "buffer_geometry_sha256": table_provenance["buffer_geometry_sha256"],
            "record_count": table_provenance["record_count"],
            "available_count": table_provenance["available_count"],
            "unavailable_count": table_provenance["unavailable_count"],
        },
        "tiles": [
            {
                "artifact_id": "artifact-3dbag-tile-fixture",
                "snapshot_id": "dataset-3dbag-tile-fixture",
                "tile_id": "9/304/512",
                "url": table_provenance["tile_url"],
                "path": str(tile_path),
                "sha256": _sha256(tile_path),
                "size_bytes": tile_path.stat().st_size,
                "retrieved_at": "2026-09-27T14:10:28Z",
                "query": "Fixture query string.",
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    bundle = build_snapshot_registration_bundle(manifest_path)

    database_path = tmp_path / "fixture-project.sqlite3"
    backup_path = tmp_path / "fixture-project-backup.sqlite3"
    with ProjectStateStore(database_path) as store:
        store.create_typed(
            Project(id="rotterdam-m4h-pilot-project", name="fixture project"),
            actor="test",
            action="CreateProject",
            reason="fixture only",
        )
        backup_connection = sqlite3.connect(backup_path)
        try:
            store.connection.backup(backup_connection)
        finally:
            backup_connection.close()
        state_records, ledger_events = append_snapshot_registration_to_store(
            store,
            bundle,
            backup_path=backup_path,
            expected_backup_sha256=_sha256(backup_path),
        )
        assert len(state_records) == 3
        assert len(ledger_events) == 3
        assert sum(item.entity_type == "HumanDecision" for item in store.list_current(project_id="rotterdam-m4h-pilot-project")) == 0
        assert len(store.events(project_id="rotterdam-m4h-pilot-project")) == 4
