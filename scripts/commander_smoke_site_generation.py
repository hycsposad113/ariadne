"""Repeatable in-memory smoke run for W5-7 StudyArea v5 morphology.

The StudyArea and constraints are illustrative fixtures. This script does not
read or write the authority database, create decisions, call models, or use a
network connection.
"""

from __future__ import annotations

import argparse
import hashlib
from itertools import combinations
import json
from pathlib import Path
import time
from typing import Any

from shapely.geometry import shape

from urban_design.morphology.contracts import (
    ApprovedSiteConstraint,
    SiteGenerationInput,
    SiteRoadInput,
    SiteZoneInput,
    SITE_GEOMETRY_TOLERANCE_M,
)
from urban_design.morphology.strategies import generate_site_strategies
from urban_design.morphology.validation import is_within_site_geometry_tolerance
from urban_design.models import UnavailableValue


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STUDY_AREA = Path("artifacts/week4-repair-r02/syntax/study-area.geojson")
DEFAULT_SOURCE_ROOT = Path(
    "artifacts/milestone2-analysis-inputs-rotterdam-m4h/"
    "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01"
)
SCRIPT_VERSION = "commander-site-generation-smoke-v2"


def _path(value: str | Path) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else REPOSITORY_ROOT / candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _geometry_from_document(document: dict[str, Any]):
    if document.get("type") == "FeatureCollection":
        features = document.get("features") or []
        if not features:
            raise ValueError("StudyArea GeoJSON has no features")
        geometry_data = features[0].get("geometry")
    elif document.get("type") == "Feature":
        geometry_data = document.get("geometry")
    else:
        geometry_data = document
    if not isinstance(geometry_data, dict):
        raise ValueError("StudyArea GeoJSON has no geometry object")
    geometry = shape(geometry_data)
    if geometry.geom_type == "MultiPolygon":
        geometry = max(geometry.geoms, key=lambda item: item.area)
    if geometry.geom_type != "Polygon" or geometry.is_empty or not geometry.is_valid:
        raise ValueError("StudyArea source must resolve to one valid Polygon")
    return geometry


def _line_roads(osm_document: dict[str, Any]) -> tuple[SiteRoadInput, ...]:
    roads = []
    for feature in osm_document.get("features", []):
        geometry_data = feature.get("geometry") or {}
        if geometry_data.get("type") != "LineString":
            continue
        properties = feature.get("properties") or {}
        tags = properties.get("tags") or {}
        highway = tags.get("highway")
        if not isinstance(highway, str) or not highway.strip():
            continue
        layer_value = tags.get("layer", "0")
        try:
            layer = int(layer_value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"OSM road {feature.get('id')!r} has a non-integer layer tag") from error
        if isinstance(layer_value, str) and str(layer) != layer_value.strip():
            raise ValueError(f"OSM road {feature.get('id')!r} has a non-canonical layer tag")

        def flag(tag_name: str) -> bool:
            value = tags.get(tag_name)
            if value is None or value is False or value == 0:
                return False
            return not (isinstance(value, str) and value.strip().casefold() in {"", "no", "false", "0"})

        lifecycle_tags = ("construction", "proposed", "disused", "abandoned", "razed")
        inactive = highway.casefold() in lifecycle_tags or any(
            key == lifecycle or key.startswith(f"{lifecycle}:")
            for key, value in tags.items()
            for lifecycle in lifecycle_tags
            if value not in (None, False, 0, "", "no", "false")
        )
        road_id = feature.get("id") or properties.get("osm_id")
        if road_id is None:
            raise ValueError("OSM line road lacks a stable feature identifier")
        roads.append(SiteRoadInput(
            road_id=str(road_id),
            geometry=shape(geometry_data),
            layer=layer,
            bridge=flag("bridge"),
            tunnel=flag("tunnel"),
            source_artifact_id="artifact-osm-overpass-v5-normalized",
            source_snapshot_id="snapshot-osm-overpass-v5",
            road_width_scope=None,
            highway=highway,
            service=tags.get("service") if isinstance(tags.get("service"), str) else None,
            access=tags.get("access") if isinstance(tags.get("access"), str) else None,
            motor_vehicle=tags.get("motor_vehicle") if isinstance(tags.get("motor_vehicle"), str) else None,
            foot=tags.get("foot") if isinstance(tags.get("foot"), str) else None,
            inactive=inactive,
        ))
    if not roads:
        raise ValueError("OSM source contains no LineString highway features")
    return tuple(roads)


def _constraint(name: str, value: float, unit: str, *, scope: str = "whole_site") -> ApprovedSiteConstraint:
    return ApprovedSiteConstraint(
        id=f"fixture-{name}-{scope.replace(':', '-')}",
        name=name,
        value=value,
        unit=unit,
        scope=scope,
        enforcement="HARD",
        approval_decision_id="FIXTURE_ONLY",
    )


def _metric(value: Any) -> Any:
    if isinstance(value, UnavailableValue):
        return {"status": "UNAVAILABLE", "reason": value.reason}
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        return round(float(value), 6)
    return value


def _line_parts(geometry):
    if geometry.is_empty:
        return ()
    if geometry.geom_type == "LineString":
        return (geometry,)
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        return tuple(part for child in geometry.geoms for part in _line_parts(child))
    return ()


def _road_component_groups(roads, area) -> list[list[str]]:
    edges = []
    for road in roads:
        clipped = road.geometry.intersection(area)
        edges.extend(
            (f"{road.segment_id}#{index}", part, (road.layer, road.bridge, road.tunnel), road.segment_id)
            for index, part in enumerate(_line_parts(clipped))
        )
    parents = {edge[0]: edge[0] for edge in edges}

    def find(identifier: str) -> str:
        while parents[identifier] != identifier:
            parents[identifier] = parents[parents[identifier]]
            identifier = parents[identifier]
        return identifier

    for first, second in combinations(edges, 2):
        if first[2] != second[2]:
            continue
        if first[1].distance(second[1]) > SITE_GEOMETRY_TOLERANCE_M:
            continue
        left, right = find(first[0]), find(second[0])
        if left != right:
            parents[max(left, right)] = min(left, right)
    groups: dict[str, list[str]] = {}
    for identifier, _geometry, _topology, segment_id in edges:
        groups.setdefault(find(identifier), []).append(segment_id)
    return [sorted(items) for _key, items in sorted(groups.items())]


def run_smoke(
    *,
    study_area_path: Path,
    source_root: Path,
    seed: int,
    inset_m: float,
    simplify_tolerance_m: float,
) -> dict[str, Any]:
    area_document = json.loads(study_area_path.read_text(encoding="utf-8"))
    area = _geometry_from_document(area_document).buffer(-inset_m)
    if area.geom_type == "MultiPolygon":
        area = max(area.geoms, key=lambda item: item.area)
    area = area.simplify(simplify_tolerance_m, preserve_topology=True)
    if area.geom_type != "Polygon" or area.is_empty or not area.is_valid:
        raise ValueError("StudyArea inset/simplification did not produce one valid Polygon")

    osm_path = source_root / "sources/normalized/osm-overpass-v5-epsg28992.geojson"
    osm_document = json.loads(osm_path.read_text(encoding="utf-8"))
    roads = _line_roads(osm_document)
    constraints = (
        _constraint("far_upper_limit", 2.0, "ratio"),
        _constraint("coverage_upper_limit", 0.5, "ratio"),
        _constraint("height_upper_limit", 40.0, "m"),
        _constraint("first_floor_height", 4.5, "m"),
        _constraint("standard_floor_height", 3.5, "m"),
        _constraint("road_width", 14.0, "m", scope="road:primary"),
        _constraint("road_width", 10.0, "m", scope="road:secondary"),
    )
    zone = SiteZoneInput(
        zone_id="fixture-whole-site",
        geometry=area,
        crs="EPSG:28992",
        target_use="mixed",
        use_enforcement="PREFERENCE",
    )
    inputs = SiteGenerationInput(
        design_area=area,
        crs="EPSG:28992",
        seed=seed,
        source_network_roads=roads,
        preserved_roads=(),
        preserved_buildings=(),
        zones=(zone,),
        approved_constraints=constraints,
        minimum_fragment_area_m2=400.0,
        minimum_fragment_width_m=12.0,
        fragment_rule_version="illustrative-site-fragment-v1",
        allocation_policy=None,
        provenance="FIXTURE_ONLY",
    )
    generation_started = time.perf_counter()
    generated = generate_site_strategies(inputs)
    generation_seconds = time.perf_counter() - generation_started
    strategy_seconds = generated.metadata["strategy_runtime_seconds"]
    rows = []
    for candidate in generated.candidates:
        major_total = sum(item.priority == "major" for item in candidate.external_contacts)
        minor_total = sum(item.priority == "minor" for item in candidate.external_contacts)
        major_unconnected = sum(item.priority == "major" for item in candidate.unconnected_contacts)
        minor_unconnected = sum(item.priority == "minor" for item in candidate.unconnected_contacts)
        outside_roads = [
            {
                "segment_id": road.segment_id,
                "outside_length_m": round(float(road.geometry.difference(area).length), 9),
                "invalid": not road.geometry.is_valid,
            }
            for road in candidate.roads
            if not is_within_site_geometry_tolerance(area, road.geometry) or not road.geometry.is_valid
        ]
        outside_surfaces = [
            {
                "index": index,
                "outside_area_m2": round(float(surface.difference(area).area), 9),
                "invalid": not surface.is_valid,
            }
            for index, surface in enumerate(candidate.road_surfaces, start=1)
            if not is_within_site_geometry_tolerance(area, surface) or not surface.is_valid
        ]
        outside_parcels = [
            {
                "index": index,
                "outside_area_m2": round(float(parcel.difference(area).area), 9),
                "invalid": not parcel.is_valid,
            }
            for index, parcel in enumerate(candidate.parcels, start=1)
            if not is_within_site_geometry_tolerance(area, parcel) or not parcel.is_valid
        ]
        rows.append({
            "strategy_id": candidate.strategy_id,
            "valid": candidate.valid,
            "buildings": len(candidate.buildings),
            "far": _metric(candidate.metrics.far),
            "coverage_ratio": _metric(candidate.metrics.coverage_ratio),
            "height_m": _metric(candidate.metrics.height_m),
            "road_components": candidate.road_component_count,
            "road_component_groups": _road_component_groups(candidate.roads, area),
            "road_segments": [
                {
                    "segment_id": road.segment_id,
                    "layer": road.layer,
                    "bridge": road.bridge,
                    "tunnel": road.tunnel,
                    "source_length_m": round(float(road.geometry.length), 6),
                    "in_area_line_lengths_m": [round(float(part.length), 6) for part in _line_parts(road.geometry.intersection(area))],
                }
                for road in candidate.roads
            ],
            "contacts": {
                "connected": candidate.external_connection_count,
                "total": len(candidate.external_contacts),
                "major_total": major_total,
                "major_connected": major_total - major_unconnected,
                "minor_total": minor_total,
                "minor_connected": minor_total - minor_unconnected,
            },
            "unconnected_contacts": [
                {
                    "contact_id": item.contact_id,
                    "source_road_id": item.source_road_id,
                    "highway": item.highway,
                    "source_mode": item.source_mode,
                    "priority": item.priority,
                    "reason": item.reason,
                    "layer": item.layer,
                    "bridge": item.bridge,
                    "tunnel": item.tunnel,
                }
                for item in candidate.unconnected_contacts
            ],
            "geometry_audit": {
                "open_space_strictly_covered": area.covers(candidate.open_space),
                "open_space_within_precision_tolerance": is_within_site_geometry_tolerance(area, candidate.open_space),
                "open_space_valid": candidate.open_space.is_valid,
                "outside_roads": outside_roads,
                "outside_road_surfaces": outside_surfaces,
                "outside_building_sites": outside_parcels,
            },
            "failure_reasons": list(candidate.failure_reasons),
            "geometry_hash": candidate.geometry_hash,
            "elapsed_seconds": strategy_seconds[candidate.strategy_id],
        })

    return {
        "script_version": SCRIPT_VERSION,
        "evidence_class": "ILLUSTRATIVE",
        "provenance": "FIXTURE_ONLY",
        "persistence": "NONE",
        "study_area": {
            "label": "StudyArea v5; inward inset; simplified for this fixture run",
            "source_path": study_area_path.relative_to(REPOSITORY_ROOT).as_posix(),
            "source_sha256": _sha256(study_area_path),
            "inset_m": inset_m,
            "simplify_tolerance_m": simplify_tolerance_m,
            "area_m2": round(float(area.area), 3),
            "crs": "EPSG:28992",
        },
        "source_network": {
            "source_path": osm_path.relative_to(REPOSITORY_ROOT).as_posix(),
            "source_sha256": _sha256(osm_path),
            "source_road_count": len(roads),
            "contact_policy": "PD-20 car classes excluding motorway plus pedestrian streets",
        },
        "constraints_status": "FIXTURE_ONLY",
        "generation_rules_version": generated.rules_version,
        "metadata": generated.metadata,
        "generation_elapsed_seconds": round(generation_seconds, 6),
        "candidate_count": len(rows),
        "valid_candidate_count": sum(bool(row["valid"]) for row in rows),
        "strategies": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-area", default=str(DEFAULT_STUDY_AREA), help="StudyArea GeoJSON, relative to this worktree by default")
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT), help="StudyArea v5 source directory, relative to this worktree by default")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--inset-m", type=float, default=5.0)
    parser.add_argument("--simplify-tolerance-m", type=float, default=1.0)
    args = parser.parse_args()
    if args.inset_m < 0 or args.simplify_tolerance_m < 0:
        parser.error("inset and simplify tolerance must be nonnegative")
    report = run_smoke(
        study_area_path=_path(args.study_area),
        source_root=_path(args.source_root),
        seed=args.seed,
        inset_m=args.inset_m,
        simplify_tolerance_m=args.simplify_tolerance_m,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
