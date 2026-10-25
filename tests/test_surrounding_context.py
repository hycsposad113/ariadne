from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import box, mapping, shape

from urban_design.geometry import canonical_geometry_hash
from urban_design.surrounding_context import (
    ContextRepository,
    extract_osm_context,
    preview_design_area_intersection,
)


ROOT = Path(__file__).resolve().parents[1]
OSM_FIXTURE = ROOT / "tests" / "fixtures" / "osm-surrounding-context.osm"
BAG_ID = "NL.IMBAG.Pand.0599100000018261"


def _write_study_area(path: Path, geometry) -> dict:
    geojson = {"type": "Feature", "properties": {}, "geometry": mapping(geometry)}
    path.write_text(json.dumps(geojson), encoding="utf-8")
    return geojson


def test_extracts_and_clips_osm_context_layers_with_source_height_priority(tmp_path: Path):
    study_area = box(89150, 435700, 89200, 435760)
    study_area_path = tmp_path / "study-area-v5.geojson"
    study_area_geojson = _write_study_area(study_area_path, study_area)
    study_area_hash = canonical_geometry_hash(study_area_geojson["geometry"])
    height_table_path = tmp_path / "3dbag-heights.json"
    height_table_path.write_text(
        json.dumps(
            {
                "schema_version": "3dbag-height-table-v1",
                "data_version": "fixture-v1",
                    "license": "CC BY 4.0",
                    "attribution": "© 3DBAG by tudelft3d and 3DGI",
                    "study_area_id": "study-area-fixture-v5",
                    "study_area_version": "v5",
                    "study_area_geometry_sha256": study_area_hash,
                    "study_area_artifact_sha256": _sha256(study_area_path),
                "buffer_distance_m": 500.0,
                "records": [
                    {
                        "bag_identificatie": BAG_ID,
                        "height_above_ground_m": 16.25,
                        "status": "AVAILABLE",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = extract_osm_context(
        pbf_path=OSM_FIXTURE,
        study_area_path=study_area_path,
        output_dir=tmp_path / "run-fixture",
        height_table_path=height_table_path,
        context_distance_m=30.0,
        study_area_id="study-area-fixture-v5",
        study_area_version="v5",
        extraction_id="fixture-run",
        source_data_version="fixture-v1",
    )

    assert manifest["study_area_geometry_sha256"] == study_area_hash
    assert manifest["context_distance_m"] == 30.0
    assert manifest["crs"] == "EPSG:28992"
    assert manifest["units"] == "m"
    assert manifest["selection_query"]["road_lines"] == "way with highway=* and area!=yes"
    assert "natural=water" in manifest["selection_query"]["polygon_layers"]
    assert any(item.startswith("waterway in ") for item in manifest["selection_query"]["polygon_layers"])
    assert manifest["feature_counts"] == {
        "buildings": 3,
        "water": 1,
        "green": 1,
        "roads": 1,
    }

    layers = {
        layer: json.loads((tmp_path / "run-fixture" / f"{layer}.geojson").read_text())
        for layer in ("buildings", "water", "green", "roads")
    }
    buildings = {feature["id"]: feature for feature in layers["buildings"]["features"]}
    bag_building = buildings["way/100"]
    assert bag_building["properties"]["height_m"] == 16.25
    assert bag_building["properties"]["height_source"] == "3DBAG"
    assert bag_building["properties"]["osm_height_m"] == 9.0
    assert bag_building["properties"]["osm_building_levels"] == 3.0

    clipped_building = shape(buildings["way/500"]["geometry"])
    assert clipped_building.bounds[2] == 89230.0
    assert buildings["way/500"]["properties"]["height_source"] == "OSM_BUILDING_LEVELS_DISPLAY_ASSUMPTION"
    assert buildings["way/500"]["properties"]["height_m"] == 6.0
    assert buildings["way/600"]["properties"]["height_source"] == "FOOTPRINT_ONLY"
    assert layers["water"]["features"][0]["properties"]["natural"] == "water"
    assert layers["green"]["features"][0]["properties"]["landuse"] == "grass"
    assert layers["roads"]["features"][0]["geometry"]["type"] == "LineString"


def test_context_repository_checks_hashes_and_simplifies_by_tolerance(tmp_path: Path):
    run_dir = tmp_path / "run-fixture"
    run_dir.mkdir()
    area = box(0, 0, 100, 100)
    boundary = {"type": "Feature", "properties": {}, "geometry": mapping(area)}
    (run_dir / "study-area-v5.geojson").write_text(json.dumps(boundary), encoding="utf-8")
    line = {
        "type": "Feature",
        "id": "way/1",
        "properties": {"osm_type": "way", "osm_id": "1"},
        "geometry": {
            "type": "LineString",
            "coordinates": [[0, 0], [20, 1], [40, 0], [60, 1], [80, 0], [100, 1]],
        },
    }
    layer_hashes = {}
    for layer in ("buildings", "water", "green", "roads"):
        collection = {"type": "FeatureCollection", "features": [line] if layer == "roads" else []}
        filename = f"{layer}.geojson"
        (run_dir / filename).write_text(json.dumps(collection), encoding="utf-8")
        layer_hashes[layer] = {"file": filename, "sha256": _sha256(run_dir / filename), "feature_count": len(collection["features"])}
    manifest = {
        "schema_version": "osm-surrounding-context-v1",
        "extraction_id": "fixture-run",
        "study_area_id": "study-area-fixture-v5",
        "study_area_version": "v5",
        "study_area_geometry_sha256": canonical_geometry_hash(mapping(area)),
        "study_area_artifact_sha256": _sha256(run_dir / "study-area-v5.geojson"),
        "crs": "EPSG:28992",
        "units": "m",
        "context_distance_m": 2000.0,
        "source": "OpenStreetMap",
        "source_data_version": "fixture-v1",
        "source_pbf_sha256": "fixture-hash",
        "attribution": "© OpenStreetMap contributors",
        "license": "ODbL 1.0",
        "run_directory": "run-fixture",
        "layer_files": layer_hashes,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    repository = ContextRepository(data_root=tmp_path, manifest_path=manifest_path)

    detailed = repository.get_context(tolerance_m=0.0)
    simplified = repository.get_context(tolerance_m=10.0)

    assert detailed["metadata"]["crs"] == "EPSG:28992"
    assert detailed["metadata"]["license"] == "ODbL 1.0"
    assert len(detailed["layers"]["roads"]["features"][0]["geometry"]["coordinates"]) == 6
    assert len(simplified["layers"]["roads"]["features"][0]["geometry"]["coordinates"]) < 6


def test_preview_intersection_reports_clipped_empty_and_multiple_components():
    study_area = box(0, 0, 10, 10)
    clipped = preview_design_area_intersection(
        {"type": "Polygon", "coordinates": [[[-5, 2], [5, 2], [5, 8], [-5, 8], [-5, 2]]]},
        mapping(study_area),
    )
    empty = preview_design_area_intersection(
        {"type": "Polygon", "coordinates": [[[20, 20], [30, 20], [30, 30], [20, 30], [20, 20]]]},
        mapping(study_area),
    )
    islands = {
        "type": "MultiPolygon",
        "coordinates": [
            mapping(box(0, 0, 10, 10))["coordinates"],
            mapping(box(20, 0, 30, 10))["coordinates"],
        ],
    }
    multiple = preview_design_area_intersection(
        {"type": "Polygon", "coordinates": [[[-5, -5], [35, -5], [35, 15], [-5, 15], [-5, -5]]]},
        islands,
    )

    assert clipped["status"] == "CLIPPED"
    assert clipped["area_m2"] == 30.0
    assert shape(clipped["geometry"]).bounds == (0.0, 2.0, 5.0, 8.0)
    assert empty["status"] == "EMPTY"
    assert multiple["status"] == "MULTIPLE_COMPONENTS"
    assert multiple["component_count"] == 2


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
