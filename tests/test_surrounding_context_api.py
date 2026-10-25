from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
from shapely.geometry import box, mapping

from urban_design.api import create_workspace_app
from urban_design.store import ProjectStateStore
from urban_design.geometry import canonical_geometry_hash


PROJECT_ID = "rotterdam-m4h-pilot-project"


def test_context_endpoint_is_read_only_typed_and_exposes_osm_attribution(tmp_path: Path):
    data_root, manifest_path, database = _make_context_package(tmp_path)
    store = ProjectStateStore(database)
    app = create_workspace_app(
        store,
        context_data_dir=data_root,
        context_manifest_path=manifest_path,
    )
    client = TestClient(app)
    before = _ledger_count(database)

    response = client.get(f"/api/v1/projects/{PROJECT_ID}/surrounding-context?tolerance_m=0")

    assert response.status_code == 200
    body = response.json()
    assert body["metadata"]["source"] == "OpenStreetMap"
    assert body["metadata"]["license"] == "ODbL 1.0"
    assert body["metadata"]["attribution"] == "© OpenStreetMap contributors"
    assert body["metadata"]["3dbag"] is None
    assert body["layers"]["buildings"]["features"][0]["id"] == "way/1"
    assert set(body["layers"]) == {"buildings", "water", "green", "roads"}
    assert _ledger_count(database) == before
    assert client.get("/api/v1/projects/unknown/surrounding-context").status_code == 404


def test_design_area_preview_endpoint_returns_intersection_without_persisting(tmp_path: Path):
    data_root, manifest_path, database = _make_context_package(tmp_path)
    store = ProjectStateStore(database)
    client = TestClient(create_workspace_app(
        store,
        context_data_dir=data_root,
        context_manifest_path=manifest_path,
    ))
    before = _ledger_count(database)
    candidate = {
        "type": "Polygon",
        "coordinates": [[[-5, 2], [5, 2], [5, 8], [-5, 8], [-5, 2]]],
    }

    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/design-area/preview",
        json={"geometry": candidate, "horizontal_crs": "EPSG:28992"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CLIPPED"
    assert body["clipped"] is True
    assert body["area_m2"] == 30.0
    assert body["geometry"]["type"] == "Polygon"
    assert _ledger_count(database) == before


def _make_context_package(tmp_path: Path) -> tuple[Path, Path, Path]:
    data_root = tmp_path / "context-data"
    run_dir = data_root / "run-fixture"
    run_dir.mkdir(parents=True)
    study_area = box(0, 0, 10, 10)
    boundary = {"type": "Feature", "properties": {}, "geometry": mapping(study_area)}
    (run_dir / "study-area-v5.geojson").write_text(json.dumps(boundary), encoding="utf-8")
    feature = {
        "type": "Feature",
        "id": "way/1",
        "properties": {"osm_type": "way", "osm_id": "1", "building": "yes"},
        "geometry": {"type": "Polygon", "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]]},
    }
    layer_files = {}
    for layer in ("buildings", "water", "green", "roads"):
        collection = {"type": "FeatureCollection", "features": [feature] if layer == "buildings" else []}
        filename = f"{layer}.geojson"
        path = run_dir / filename
        path.write_text(json.dumps(collection), encoding="utf-8")
        layer_files[layer] = {
            "file": filename,
            "sha256": _sha256(path),
            "feature_count": len(collection["features"]),
        }
    manifest = {
        "schema_version": "osm-surrounding-context-v1",
        "extraction_id": "fixture-run",
        "project_id": PROJECT_ID,
        "study_area_id": "study-area-fixture-v5",
        "study_area_version": "v5",
        "study_area_geometry_sha256": canonical_geometry_hash(mapping(study_area)),
        "study_area_artifact_sha256": _sha256(run_dir / "study-area-v5.geojson"),
        "crs": "EPSG:28992",
        "units": "m",
        "context_distance_m": 2000.0,
        "attribution": "© OpenStreetMap contributors",
        "license": "ODbL 1.0",
        "source": "OpenStreetMap",
        "source_data_version": "fixture-v1",
        "source_pbf_sha256": "fixture-hash",
        "run_directory": "run-fixture",
        "layer_files": layer_files,
    }
    encoded = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
    (data_root / "manifest.json").write_bytes(encoded)
    manifest_path = tmp_path / "reference-manifest.json"
    manifest_path.write_bytes(encoded)
    return data_root, manifest_path, tmp_path / "state.sqlite3"


def _ledger_count(database: Path) -> int:
    import sqlite3

    with sqlite3.connect(database) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
