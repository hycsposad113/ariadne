#!/usr/bin/env python3
"""Build a source-linked, explicitly coverage-blocked R02 Syntax package.

The authoritative SQLite file is opened read-only and backed up to a disposable
database before ProjectStateStore is used for source-artifact verification.
Only the output directory is written; no network or QGIS calls are made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, mapping, shape

from urban_design.context_network import (
    _aligned_osm_node_ids,
    audit_source_topology,
    clean_osm_segments,
    compute_six_syntax_layers,
)
from urban_design.store import ProjectStateStore
from urban_design.workspace_sources import DEFAULT_SPATIAL_R01_ROOT, WorkspaceSourceCatalog
from render_syntax_figure import render_formal_syntax_figure


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / ".urban_design_runtime/state.sqlite3"
DEFAULT_OUTPUT = ROOT / "artifacts/week4-repair-r02/syntax"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: Any) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def _line_parts(geometry: Any) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if not part.is_empty]
    return []


def _load_osm_way_lookup(catalog: WorkspaceSourceCatalog) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    normalized_records = [
        record
        for record in catalog.normalized_artifacts.values()
        if str(record.get("uri", "")).endswith("/osm-overpass-v5-epsg28992.geojson")
    ]
    if len(normalized_records) != 1:
        raise ValueError("spatial-r01 must identify exactly one normalized OSM way artifact")
    raw_parent_id = str(normalized_records[0].get("raw_parent_artifact_id") or "")
    raw_record = catalog.raw_artifacts.get(raw_parent_id)
    if raw_record is None:
        raise ValueError("normalized OSM artifact has no retained raw response parent")
    raw_relative_path = Path(str(raw_record.get("uri", "")))
    if raw_relative_path.is_absolute() or ".." in raw_relative_path.parts:
        raise ValueError("retained OSM raw artifact URI is unsafe")
    raw_path = catalog.package_root / raw_relative_path
    raw_bytes = raw_path.read_bytes()
    if len(raw_bytes) != int(raw_record.get("size_bytes", -1)) or _sha256(raw_bytes) != str(raw_record.get("sha256", "")).removeprefix("sha256:"):
        raise ValueError("retained OSM raw artifact does not match its catalog size/hash")
    raw_payload = json.loads(raw_bytes)
    elements = raw_payload.get("elements")
    if not isinstance(elements, list):
        raise ValueError("retained OSM raw response has no elements list")
    ways: dict[str, dict[str, Any]] = {}
    for element in elements:
        if not isinstance(element, dict) or element.get("type") != "way" or not element.get("tags", {}).get("highway"):
            continue
        key = f"way/{element.get('id')}"
        if key in ways:
            raise ValueError(f"retained OSM response duplicates {key}")
        ways[key] = element
    raw_reference = {
        "artifact_id": raw_parent_id,
        "path": str(raw_relative_path),
        "size_bytes": len(raw_bytes),
        "sha256": _sha256(raw_bytes),
    }
    return ways, raw_reference


def build(output_dir: Path, database: Path, package_root: Path) -> dict[str, Any]:
    output_dir = Path(output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"R02 syntax output is append-only; refusing non-empty path: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    before_live_hash = _sha256(Path(database).read_bytes())

    with tempfile.TemporaryDirectory(prefix="week4-r02-syntax-state-", dir="/private/tmp") as temp_dir:
        disposable_db = Path(temp_dir) / "state.sqlite3"
        source = sqlite3.connect(f"file:{Path(database).resolve()}?mode=ro", uri=True)
        target = sqlite3.connect(disposable_db)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

        with ProjectStateStore(disposable_db) as store:
            catalog = WorkspaceSourceCatalog.load(store, package_root)
            if catalog.study_area_id != "study-area-rotterdam-m4h-pilot-project-v5":
                raise ValueError("active source catalog is not the confirmed Rotterdam M4H v5 StudyArea")
            osm_ways, osm_raw_parent = _load_osm_way_lookup(catalog)
            transformer = Transformer.from_crs("OGC:CRS84", "EPSG:28992", always_xy=True)

            study_path = output_dir / "study-area.geojson"
            study_doc = {
                "type": "Feature",
                "id": catalog.study_area_id,
                "geometry": dict(catalog.study_area_geometry),
                "properties": {
                    "project_id": catalog.project_id,
                    "crs": "EPSG:28992",
                    "study_area_geometry_sha256": catalog.study_area_geometry_sha256,
                },
            }
            study_bytes = _write_json(study_path, study_doc)

            raw_features: list[dict[str, Any]] = []
            source_by_clean_id: dict[str, Any] = {}
            for road in catalog.roads:
                geometry = shape(road.geometry)
                raw_way = osm_ways.get(road.source_feature_id)
                if raw_way is None:
                    raise ValueError(f"retained raw OSM response is missing {road.source_feature_id}")
                osm_node_ids = _aligned_osm_node_ids(road.geometry, raw_way, transform=transformer.transform)
                for part_idx, line in enumerate(_line_parts(geometry)):
                    if len(_line_parts(geometry)) != 1:
                        raise ValueError(f"OSM source way {road.source_feature_id} unexpectedly normalized to multiple lines")
                    clean_id = road.source_feature_id if len(_line_parts(geometry)) == 1 else f"{road.source_feature_id}__part_{part_idx}"
                    feature = {
                        "type": "Feature",
                        "id": clean_id,
                        "geometry": mapping(line),
                        "properties": {
                            **dict(road.properties),
                            "source_feature_id": road.source_feature_id,
                            "source_artifact_id": road.source_artifact_id,
                            "source_snapshot_id": road.source_snapshot_id,
                            "tags": dict(road.properties.get("tags") or {}),
                            "osm_node_ids": osm_node_ids,
                        },
                    }
                    raw_features.append(feature)
                    source_by_clean_id[clean_id] = road

            context_doc = {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
                "features": raw_features,
            }
            context_path = output_dir / "context.geojson"
            context_bytes = _write_json(context_path, context_doc)
            cleaned_segments = clean_osm_segments(raw_features)
            topology_audit = audit_source_topology(cleaned_segments)
            segment_mapping: dict[str, dict[str, str]] = {}
            for segment in cleaned_segments:
                clean_id = segment.id.removeprefix("osm_").split("_seg_", 1)[0]
                road = source_by_clean_id.get(clean_id)
                if road is None:
                    raise ValueError(f"noded segment lost its source feature mapping: {segment.id}")
                segment_mapping[segment.id] = {
                    "source_feature_id": road.source_feature_id,
                    "source_artifact_id": road.source_artifact_id,
                    "source_snapshot_id": road.source_snapshot_id,
                }

            used_snapshot_ids = sorted({road.source_snapshot_id for road in catalog.roads})
            used_artifact_ids = sorted({road.source_artifact_id for road in catalog.roads})
            topology_blockers = []
            if topology_audit["unresolved_intersection_count"]:
                topology_blockers.append("BLOCKED_UNRESOLVED_GRADE_OR_TOPOLOGY_CROSSINGS")
            if topology_audit["overlap_count"]:
                topology_blockers.append("BLOCKED_OVERLAPPING_SEGMENT_REVIEW")
            source_manifest = {
                "schema_version": "week4-syntax-source-v2",
                "package_id": catalog.package_id,
                "package_revision": catalog.package_revision,
                "project_id": catalog.project_id,
                "study_area_id": catalog.study_area_id,
                "study_area_geometry_sha256": catalog.study_area_geometry_sha256,
                "crs": "EPSG:28992",
                "study_area_geojson_sha256": _sha256(study_bytes),
                "context_geojson_sha256": _sha256(context_bytes),
                "spatial_r01_manifest_path": str(
                    (Path(package_root) / "source-and-integrity-manifest.json").relative_to(ROOT)
                ),
                "spatial_r01_manifest_sha256": _sha256(
                    (Path(package_root) / "source-and-integrity-manifest.json").read_bytes()
                ),
                "source_artifacts": [catalog.normalized_artifacts[item] for item in used_artifact_ids],
                "source_snapshots": [catalog.snapshots[item] for item in used_snapshot_ids],
                "segment_mapping": segment_mapping,
                "source_node_topology": {
                    "status": (
                        "SOURCE_NODE_IDS_ALIGNED"
                        if topology_audit["readiness"] == "SOURCE_NODE_TOPOLOGY_CHECKED"
                        else "SOURCE_NODE_IDS_ALIGNED_BUT_REVIEW_REQUIRED"
                    ),
                    "connectivity_rule": "OSM ways connect only at shared source node IDs; XY-only crossings are not connected.",
                    "raw_parent": osm_raw_parent,
                    "mapped_way_count": len(catalog.roads),
                    "geometry_alignment_tolerance_m": 0.01,
                    "grade_layer_missing_is_unknown": True,
                    "audit": topology_audit,
                },
                "source_scope": "only spatial-r01 highway ways intersecting active StudyArea; not a regional network",
                "extract_covers_envelope": None,
                "coverage_basis": "No regional extract boundary is declared for this StudyArea-intersection-only source subset.",
                "source_completeness_evidence": None,
                "boundary_stability_evidence_by_radius_m": {},
                "limitations": [
                "The chosen feature subset omits roads that do not intersect the StudyArea.",
                "This subset has no declared complete acquisition envelope for the route graph.",
                "No radius-specific boundary stability analysis is attached.",
                "All three radii may be calculated over this same truncated graph for comparison only; all values remain coverage-blocked.",
                ],
            }
            manifest_path = output_dir / "source-manifest.json"
            manifest_bytes = _write_json(manifest_path, source_manifest)

            layer_result = compute_six_syntax_layers(
                cleaned_segments,
                study_area_geometry=catalog.study_area_shape,
                acquisition_envelope_geometry=None,
                stability_validated_radii_m=(),
            )
            syntax_result = {
                "schema_version": "week4-syntax-result-v2",
                "package_id": catalog.package_id,
                "package_revision": catalog.package_revision,
                "project_id": catalog.project_id,
                "study_area_id": catalog.study_area_id,
                "crs": "EPSG:28992",
                "source_manifest_sha256": _sha256(manifest_bytes),
                "study_area_geojson_sha256": _sha256(study_bytes),
                "context_geojson_sha256": _sha256(context_bytes),
                "formula_version": "turner-2007-angular-segment-v1",
                "source_node_topology": topology_audit,
                "network_segment_count": layer_result["network_segment_count"],
                "analysis_segment_count": layer_result["analysis_segment_count"],
                "coverage_buffer_m": None,
                "extract_covers_envelope": layer_result["extract_covers_envelope"],
                "stability_validated_radii_m": [],
                "layers": layer_result["layers"],
                "status": "BLOCKED_SOURCE_COVERAGE_UNVERIFIED",
                "blocking_conditions": sorted({"SOURCE_COVERAGE_UNVERIFIED", *topology_blockers}),
            }
            for layer in syntax_result["layers"]:
                layer["blocking_conditions"] = [layer["data_readiness"]]
                if topology_audit["readiness"] != "SOURCE_NODE_TOPOLOGY_CHECKED":
                    layer["blocking_conditions"].extend(topology_blockers)
                    layer["limitations"] += (
                        f" Source-node topology audit found {topology_audit['unresolved_intersection_count']} "
                        "geometric crossings without shared source-node evidence and "
                        f"{topology_audit['overlap_count']} overlapping feature pairs; "
                        "these were not converted to network junctions."
                    )
            result_path = output_dir / "syntax-result.json"
            _write_json(result_path, syntax_result)

    if _sha256(Path(database).read_bytes()) != before_live_hash:
        raise RuntimeError("authoritative SQLite bytes changed during disposable syntax build")

    figure_report = render_formal_syntax_figure(
        output_dir / "syntax-local-800m-integration.png",
        study_area_geojson_path=output_dir / "study-area.geojson",
        context_geojson_path=output_dir / "context.geojson",
        source_manifest_path=output_dir / "source-manifest.json",
        syntax_result_path=output_dir / "syntax-result.json",
    )
    report = {
        "status": "BUILT_WITH_BLOCKED_COVERAGE",
        "live_database_sha256_before": before_live_hash,
        "live_database_sha256_after": _sha256(Path(database).read_bytes()),
        "source_package_id": catalog.package_id,
        "source_package_revision": catalog.package_revision,
        "study_area_id": catalog.study_area_id,
        "source_feature_count": len(catalog.roads),
        "noded_segment_count": len(cleaned_segments),
        "source_node_topology": source_manifest["source_node_topology"],
        "segments_with_unknown_grade_layer": sum(segment.layer is None for segment in cleaned_segments),
        "analysis_segment_count": syntax_result["analysis_segment_count"],
        "layer_statuses": {layer["layer_id"]: layer["data_readiness"] for layer in syntax_result["layers"]},
        "figure": figure_report,
        "outbound_requests": 0,
        "qgis_calls": 0,
    }
    _write_json(output_dir / "build-report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--source-package", type=Path, default=DEFAULT_SPATIAL_R01_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output_dir, args.database, args.source_package), indent=2))


if __name__ == "__main__":
    main()
