#!/usr/bin/env python3
"""Generate three local-only, assumption-labelled StudyArea v5 previews.

This runner never reads or writes SQLite, creates HumanDecision records, calls
model providers, or promotes a candidate. Output is a reviewable Explore-stage
preview package.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo
import zlib

import shapely
from shapely.geometry import GeometryCollection, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from urban_design.morphology.contracts import (
    ApprovedSiteConstraint,
    MASK_GEOMETRY_CLEARANCE_M,
    NonBuildableArea,
    SiteGenerationInput,
    SiteRoadInput,
    SiteZoneInput,
)
from urban_design.morphology.strategies import generate_site_strategies
from urban_design.models import UnavailableValue


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STUDY_AREA = REPOSITORY_ROOT / "artifacts/week4-repair-r02/syntax/study-area.geojson"
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / (
    "artifacts/milestone2-analysis-inputs-rotterdam-m4h/"
    "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01"
)
DEFAULT_OUTPUT_ROOT = Path.home() / ".local/share/urban-design-data/assumed-generation"
APPROVAL_REFERENCE = "ASSUMED_BY_COMMANDER_2026-09-27"
ASSUMPTION_STATUS = "ASSUMED"
PREVIEW_STATUS = "UNAPPROVED_PREVIEW"
SEED = 42
CRS = "EPSG:28992"
PRESERVED_HIGHWAYS = frozenset({"primary", "secondary", "tertiary"})
ROAD_WIDTHS_M = {"road:primary": 14.0, "road:secondary": 10.0}
OPEN_SPACE_PREFERENCE = 0.15
WATERFRONT_BAND_M = 15.0
WATER_SOURCE_CONTEXT_M = 60.0
MINIMUM_FOOTPRINT_AREA_M2 = 150.0
MINIMUM_FOOTPRINT_SHORT_EDGE_M = 8.0
SCRIPT_VERSION = "assumed-site-generation-v5"
CONTACT_CONNECTIVITY_RULES_VERSION = "contact-connectivity-v3.1"
MINIMUM_LAND_BLOCK_AREA_M2 = 2_000.0
DENSITY_TARGET_RANGE = (1.6, 1.9)
STRATEGY_CATALOG_VERSION = "assumed-strategy-catalog-v1"

STRATEGY_LABELS = {
    "site-grid": "GRID",
    "site-linear-green-axis": "GREEN AXIS",
    "site-concentric-open-space": "CENTRAL OPEN",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return document


def _geometry_from_geojson(document: dict[str, Any], *, label: str) -> BaseGeometry:
    if document.get("type") == "FeatureCollection":
        features = document.get("features") or []
        geometries = [shape(item["geometry"]) for item in features if item.get("geometry")]
        if not geometries:
            raise ValueError(f"{label} GeoJSON has no geometries")
        geometry = unary_union(geometries)
    elif document.get("type") == "Feature":
        if not isinstance(document.get("geometry"), dict):
            raise ValueError(f"{label} GeoJSON feature has no geometry")
        geometry = shape(document["geometry"])
    else:
        geometry = shape(document)
    if geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty or not geometry.is_valid:
        raise ValueError(f"{label} must resolve to a valid Polygon or MultiPolygon")
    return geometry


def _polygonal_only(geometry: BaseGeometry) -> BaseGeometry:
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    if geometry.geom_type == "GeometryCollection":
        pieces = [piece for item in geometry.geoms for piece in _polygon_parts(item)]
        return unary_union(pieces) if pieces else GeometryCollection()
    return GeometryCollection()


def _polygon_parts(geometry: BaseGeometry) -> tuple[Polygon, ...]:
    if geometry.geom_type == "Polygon":
        return (geometry,)
    if geometry.geom_type in {"MultiPolygon", "GeometryCollection"}:
        return tuple(piece for child in geometry.geoms for piece in _polygon_parts(child))
    return ()


def _land_block_geometries(geometry: BaseGeometry) -> tuple[Polygon, ...]:
    return tuple(sorted(
        _polygon_parts(geometry),
        key=lambda item: (
            tuple(round(value, 6) for value in item.bounds),
            -round(float(item.area), 6),
            round(float(item.centroid.x), 6),
            round(float(item.centroid.y), 6),
        ),
    ))


def _flag(tags: dict[str, Any], name: str) -> bool:
    value = tags.get(name)
    if value is None or value is False or value == 0:
        return False
    return not (isinstance(value, str) and value.strip().casefold() in {"", "no", "false", "0"})


def _inactive(tags: dict[str, Any], highway: str) -> bool:
    lifecycle_tags = ("construction", "proposed", "disused", "abandoned", "razed")
    return highway.casefold() in lifecycle_tags or any(
        key == lifecycle or key.startswith(f"{lifecycle}:")
        for key, value in tags.items()
        for lifecycle in lifecycle_tags
        if value not in (None, False, 0, "", "no", "false")
    )


def _road_width_scope(highway: str) -> str | None:
    if highway == "primary":
        return "road:primary"
    if highway == "secondary":
        return "road:secondary"
    return None


def _osm_roads(osm_document: dict[str, Any], *, artifact_id: str, snapshot_id: str):
    roads: list[SiteRoadInput] = []
    tags_by_id: dict[str, dict[str, Any]] = {}
    for feature in osm_document.get("features", []):
        geometry_data = feature.get("geometry") or {}
        if geometry_data.get("type") not in {"LineString", "MultiLineString"}:
            continue
        properties = feature.get("properties") or {}
        tags = properties.get("tags") or {}
        highway = tags.get("highway")
        if not isinstance(highway, str) or not highway.strip():
            continue
        road_id = feature.get("id") or properties.get("osm_id")
        if road_id is None:
            raise ValueError("OSM highway feature has no stable identifier")
        layer_value = tags.get("layer", "0")
        try:
            layer = int(layer_value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"OSM road {road_id!r} has a non-integer layer tag") from error
        if isinstance(layer_value, str) and str(layer) != layer_value.strip():
            raise ValueError(f"OSM road {road_id!r} has a non-canonical layer tag")
        road_id = str(road_id)
        road = SiteRoadInput(
            road_id=road_id,
            geometry=shape(geometry_data),
            layer=layer,
            bridge=_flag(tags, "bridge"),
            tunnel=_flag(tags, "tunnel"),
            source_artifact_id=artifact_id,
            source_snapshot_id=snapshot_id,
            road_width_scope=_road_width_scope(highway),
            highway=highway,
            service=tags.get("service") if isinstance(tags.get("service"), str) else None,
            access=tags.get("access") if isinstance(tags.get("access"), str) else None,
            motor_vehicle=tags.get("motor_vehicle") if isinstance(tags.get("motor_vehicle"), str) else None,
            foot=tags.get("foot") if isinstance(tags.get("foot"), str) else None,
            inactive=_inactive(tags, highway),
        )
        roads.append(road)
        tags_by_id[road_id] = dict(tags)
    if not roads:
        raise ValueError("OSM source contains no line highway features")
    return tuple(roads), tags_by_id


def _source_metadata(source_root: Path, relative_uri: str, snapshot_suffix: str) -> dict[str, Any]:
    manifest_path = source_root / "source-and-integrity-manifest.json"
    manifest = _read_json(manifest_path)
    artifact = next(
        (item for item in manifest.get("normalized_artifacts", []) if item.get("uri") == relative_uri),
        None,
    )
    snapshot = next(
        (item for item in manifest.get("snapshots", []) if item.get("id", "").startswith(snapshot_suffix)),
        None,
    )
    if artifact is None or snapshot is None:
        raise ValueError(f"source manifest lacks artifact or snapshot metadata for {relative_uri}")
    source_path = source_root / relative_uri
    actual_hash = _sha256_file(source_path)
    recorded_hash = str(artifact.get("sha256", "")).removeprefix("sha256:")
    if actual_hash != recorded_hash:
        raise ValueError(f"normalized source hash mismatch for {relative_uri}")
    return {
        "path": source_path.relative_to(REPOSITORY_ROOT).as_posix(),
        "artifact_id": artifact.get("id"),
        "artifact_sha256": actual_hash,
        "snapshot_id": snapshot.get("id"),
        "source_sha256": str(snapshot.get("sha256", "")).removeprefix("sha256:"),
        "source": snapshot.get("attribution") or artifact.get("producer"),
        "query": snapshot.get("query"),
        "version": snapshot.get("version"),
        "retrieved_at": snapshot.get("retrieved_at"),
        "license": snapshot.get("license"),
        "attribution": snapshot.get("attribution"),
        "limitations": list(snapshot.get("limitations") or []),
        "normalizer": artifact.get("producer"),
        "manifest_path": manifest_path.relative_to(REPOSITORY_ROOT).as_posix(),
        "manifest_sha256": _sha256_file(manifest_path),
    }


def _assumed_constraint(name: str, value: float, unit: str, *, scope: str = "whole_site") -> ApprovedSiteConstraint:
    return ApprovedSiteConstraint(
        id=f"assumed-{name}-{scope.replace(':', '-')}",
        name=name,
        value=value,
        unit=unit,
        scope=scope,
        enforcement="HARD",
        approval_decision_id=APPROVAL_REFERENCE,
    )


def _build_input(study_area_path: Path, source_root: Path):
    study_document = _read_json(study_area_path)
    study_area = _geometry_from_geojson(study_document, label="StudyArea v5")
    design_area = shapely.set_precision(study_area.buffer(-5.0), grid_size=1e-6, mode="valid_output")
    if design_area.geom_type != "Polygon" or design_area.is_empty or not design_area.is_valid or design_area.area <= 0:
        raise ValueError("5 m inward buffer must produce one valid positive-area Polygon")

    osm_path = source_root / "sources/normalized/osm-overpass-v5-epsg28992.geojson"
    water_path = source_root / "sources/normalized/pdok-bgt-waterdeel-p001-epsg28992.geojson"
    osm_document = _read_json(osm_path)
    water_document = _read_json(water_path)
    for label, document in (("OSM", osm_document), ("BGT water", water_document)):
        crs_name = ((document.get("crs") or {}).get("properties") or {}).get("name")
        if crs_name != CRS:
            raise ValueError(f"{label} normalized GeoJSON must declare {CRS}")

    osm_metadata = _source_metadata(
        source_root,
        "sources/normalized/osm-overpass-v5-epsg28992.geojson",
        "snapshot-osm-overpass-v5",
    )
    water_metadata = _source_metadata(
        source_root,
        "sources/normalized/pdok-bgt-waterdeel-p001-epsg28992.geojson",
        "snapshot-pdok-bgt-waterdeel-p001",
    )
    network_roads, tags_by_id = _osm_roads(
        osm_document,
        artifact_id=str(osm_metadata["artifact_id"]),
        snapshot_id=str(osm_metadata["snapshot_id"]),
    )
    selected_roads = tuple(
        road for road in network_roads
        if road.highway in PRESERVED_HIGHWAYS and road.geometry.intersects(study_area)
    )
    preserved_roads_in_design_area = tuple(
        road for road in selected_roads if road.geometry.intersects(design_area)
    )
    context_only_preserved_roads = tuple(
        road for road in selected_roads if not road.geometry.intersects(design_area)
    )

    water_geometries = []
    source_extent = design_area.buffer(WATER_SOURCE_CONTEXT_M)
    for feature in water_document.get("features", []):
        geometry_data = feature.get("geometry")
        if not geometry_data:
            continue
        geometry = shape(geometry_data)
        if geometry.geom_type not in {"Polygon", "MultiPolygon"} or not geometry.is_valid:
            continue
        if geometry.intersects(source_extent):
            water_geometries.append(geometry)
    if not water_geometries:
        raise ValueError("frozen BGT waterdeel source has no polygon within 60 m of the design area")
    water_union = shapely.set_precision(unary_union(water_geometries), grid_size=1e-6, mode="valid_output")
    water_mask = _polygonal_only(design_area.intersection(water_union))
    water_mask = unary_union(_polygon_parts(water_mask)) if not water_mask.is_empty else water_mask
    water_mask = shapely.set_precision(water_mask, grid_size=1e-6, mode="valid_output")
    water_context = _polygonal_only(study_area.intersection(water_union))
    water_context = unary_union(_polygon_parts(water_context)) if not water_context.is_empty else water_context
    water_context = shapely.set_precision(water_context, grid_size=1e-6, mode="valid_output")
    land_area = _polygonal_only(design_area.difference(water_mask))
    land_area = unary_union(_polygon_parts(land_area)) if not land_area.is_empty else land_area
    land_area = shapely.set_precision(land_area, grid_size=1e-6, mode="valid_output")
    waterfront_band = _polygonal_only(
        land_area.intersection(water_union.boundary.buffer(WATERFRONT_BAND_M))
    )
    waterfront_band = unary_union(_polygon_parts(waterfront_band)) if not waterfront_band.is_empty else waterfront_band
    waterfront_band = shapely.set_precision(waterfront_band, grid_size=1e-6, mode="valid_output")
    remaining_area = _polygonal_only(land_area.difference(waterfront_band))
    remaining_area = unary_union(_polygon_parts(remaining_area)) if not remaining_area.is_empty else remaining_area
    remaining_area = shapely.set_precision(remaining_area, grid_size=1e-6, mode="valid_output")
    if (
        water_mask.is_empty
        or land_area.is_empty
        or waterfront_band.is_empty
        or remaining_area.is_empty
        or not water_mask.is_valid
        or not land_area.is_valid
        or not waterfront_band.is_valid
        or not remaining_area.is_valid
    ):
        raise ValueError("the BGT water mask, 15 m waterfront band, and land remainder must be valid and non-empty")
    zone_overlap = float(waterfront_band.intersection(remaining_area).area)
    zone_coverage_error = abs(float(waterfront_band.area + remaining_area.area - land_area.area))
    if zone_overlap > 1e-6 or zone_coverage_error > 1e-3:
        raise ValueError("derived zones do not form a non-overlapping partition of the design area")

    zones = (
        SiteZoneInput(
            zone_id="waterfront-public-15m",
            geometry=waterfront_band,
            crs=CRS,
            target_use="mixed",
            use_enforcement="PREFERENCE",
        ),
        SiteZoneInput(
            zone_id="remainder",
            geometry=remaining_area,
            crs=CRS,
            target_use="mixed",
            use_enforcement="PREFERENCE",
        ),
    )
    constraints = (
        _assumed_constraint("far_upper_limit", 2.0, "ratio"),
        _assumed_constraint("coverage_upper_limit", 0.5, "ratio"),
        _assumed_constraint("height_upper_limit", 40.0, "m"),
        _assumed_constraint("first_floor_height", 4.5, "m"),
        _assumed_constraint("standard_floor_height", 3.5, "m"),
        _assumed_constraint("road_width", 14.0, "m", scope="road:primary"),
        _assumed_constraint("road_width", 10.0, "m", scope="road:secondary"),
    )
    generation_input = SiteGenerationInput(
        design_area=design_area,
        crs=CRS,
        seed=SEED,
        source_network_roads=network_roads,
        preserved_roads=preserved_roads_in_design_area,
        preserved_buildings=(),
        zones=zones,
        approved_constraints=constraints,
        minimum_fragment_area_m2=400.0,
        minimum_fragment_width_m=12.0,
        fragment_rule_version="assumed-minimum-block-v1",
        allocation_policy=None,
        provenance="ASSUMED",
        non_buildable_areas=(NonBuildableArea(
            id="non-buildable-bgt-waterdeel-p001",
            geometry=water_mask,
            kind="water",
            source_artifact_id=str(water_metadata["artifact_id"]),
        ),),
        waterfront_public_areas=(waterfront_band,),
        minimum_footprint_area_m2=MINIMUM_FOOTPRINT_AREA_M2,
        minimum_short_edge_m=MINIMUM_FOOTPRINT_SHORT_EDGE_M,
    )
    source_hashes = {
        "study_area_geojson": _sha256_file(study_area_path),
        "osm_normalized_geojson": str(osm_metadata["artifact_sha256"]),
        "bgt_water_normalized_geojson": str(water_metadata["artifact_sha256"]),
    }
    source_metadata = {
        "study_area": {
            "path": study_area_path.relative_to(REPOSITORY_ROOT).as_posix(),
            "sha256": source_hashes["study_area_geojson"],
            "version": "StudyArea v5 (Commander assumption; GeoJSON has no embedded CRS metadata)",
            "crs": CRS,
            "retrieved_at": "existing repository artifact; original retrieval time not embedded in this GeoJSON",
            "license": "see originating StudyArea package; not embedded in this GeoJSON",
        },
        "osm": osm_metadata,
        "water": water_metadata,
    }
    return {
        "generation_input": generation_input,
        "study_area": study_area,
        "design_area": design_area,
        "land_area": land_area,
        "land_blocks": _land_block_geometries(land_area),
        "water_mask": water_mask,
        "water_context": water_context,
        "waterfront_band": waterfront_band,
        "remaining_area": remaining_area,
        "selected_preserved_roads": selected_roads,
        "preserved_roads_in_design_area": preserved_roads_in_design_area,
        "context_only_preserved_roads": context_only_preserved_roads,
        "road_tags": tags_by_id,
        "source_metadata": source_metadata,
        "source_hashes": source_hashes,
        "water_feature_count": len(water_geometries),
        "water_area_m2": float(water_mask.area),
        "water_context_area_m2": float(water_context.area),
        "osm_feature_count": len(osm_document.get("features", [])),
        "network_road_count": len(network_roads),
    }


def _assumption_item(name: str, value: Any, *, unit: str | None = None, note: str | None = None) -> dict[str, Any]:
    result = {
        "name": name,
        "value": value,
        "status": ASSUMPTION_STATUS,
        "approval_decision_id": APPROVAL_REFERENCE,
    }
    if unit is not None:
        result["unit"] = unit
    if note is not None:
        result["note"] = note
    return result


def _assumptions_document(context: dict[str, Any]) -> dict[str, Any]:
    selected_roads: tuple[SiteRoadInput, ...] = context["selected_preserved_roads"]
    constraints = [
        {
            "id": item.id,
            "name": item.name,
            "value": item.value,
            "unit": item.unit,
            "scope": item.scope,
            "enforcement": item.enforcement,
            "status": ASSUMPTION_STATUS,
            "approval_decision_id": item.approval_decision_id,
            **({"note": "3.5 m is an interview-example assumption, not an approved floor height."} if item.name == "standard_floor_height" else {}),
        }
        for item in context["generation_input"].approved_constraints
    ]
    assumptions = [
        _assumption_item("design_area", "entire StudyArea v5 inward-buffered by 5 m", note="The supplied StudyArea GeoJSON does not embed a CRS; EPSG:28992 is the Commander-provided assumption."),
        _assumption_item("horizontal_crs", CRS),
        _assumption_item(
            "non_buildable_areas",
            [{"id": item.id, "kind": item.kind, "source_artifact_id": item.source_artifact_id, "area_m2": round(float(item.geometry.area), 3)} for item in context["generation_input"].non_buildable_areas],
            note="BGT waterdeel polygons are clipped to the inset design area and excluded from roads, blocks, buildings, open-space allocation, and the land FAR denominator.",
        ),
        _assumption_item("waterfront_public_band_width", WATERFRONT_BAND_M, unit="m", note="ASSUMED minimum public land band measured inward from the shoreline; no generated roads or buildings occupy the band."),
        _assumption_item("minimum_massing_footprint_area", MINIMUM_FOOTPRINT_AREA_M2, unit="m2", note="ASSUMED minimum; rejected floor area remains unallocated."),
        _assumption_item("minimum_massing_short_edge", MINIMUM_FOOTPRINT_SHORT_EDGE_M, unit="m", note="ASSUMED minimum edge of the footprint minimum rotated rectangle; rejected floor area remains unallocated."),
        _assumption_item("preserved_roads", "OSM highway=primary, secondary, tertiary intersecting original StudyArea v5", note=f"Selected {len(selected_roads)}; {len(context['preserved_roads_in_design_area'])} intersect the 5 m inset and enter the generator; {len(context['context_only_preserved_roads'])} remain as preserved context outside the inset."),
        _assumption_item("existing_buildings", {"disposition": "editable", "preserved": False}, note="No existing building is locked or counted as retained; no floor estimate is introduced."),
        _assumption_item("zones", [
            {"zone_id": "waterfront-public-15m", "geometry": "land area within 15 m of the boundary of frozen BGT waterdeel polygons", "target_use": "mixed", "use_enforcement": "PREFERENCE", "open_space_preference": True},
            {"zone_id": "remainder", "geometry": "land area outside the 15 m waterfront public band", "target_use": "mixed", "use_enforcement": "PREFERENCE"},
        ], note="Water is excluded from land; the 15 m public band is a geometric buffer assumption, not a legal waterfront boundary."),
        _assumption_item("minimum_open_space_ratio", OPEN_SPACE_PREFERENCE, unit="ratio", note="PREFERENCE only; it does not invalidate a candidate when unmet."),
        _assumption_item("contact_connectivity_rules_version", CONTACT_CONNECTIVITY_RULES_VERSION, note="Each land block of at least 2,000 m² must have one generated road component and connect to two usable external OSM contacts, or to the single usable contact when only one exists; zero usable contacts is a warning. When a usable primary contact exists, at least one primary contact must connect. Water and the 15 m waterfront public band remain no-road areas."),
        _assumption_item("minimum_land_block_area", MINIMUM_LAND_BLOCK_AREA_M2, unit="m2"),
        _assumption_item("land_far_density_target", list(DENSITY_TARGET_RANGE), unit="ratio", note="Commander target equals 80–95% of the assumed FAR upper limit 2.0; it does not change the hard upper bound."),
        _assumption_item("strategy_catalog_version", STRATEGY_CATALOG_VERSION),
        _assumption_item("seed", SEED),
        _assumption_item("minimum_block_area", 400.0, unit="m2"),
        _assumption_item("minimum_block_width", 12.0, unit="m"),
    ]
    return {
        "schema_version": "assumed-generation-assumptions-v2",
        "workflow_stage": "EXPLORE",
        "evidence_status": PREVIEW_STATUS,
        "evidence_status_zh": "未核准預覽",
        "assumption_status": ASSUMPTION_STATUS,
        "approval_decision_id": APPROVAL_REFERENCE,
        "human_decision_created": False,
        "authority_database_accessed": False,
        "authority_database_written": False,
        "all_assumptions": assumptions,
        "hard_intensity_constraints": constraints,
        "source_provenance": context["source_metadata"],
        "source_feature_counts": {
            "study_area_area_m2": round(float(context["study_area"].area), 3),
            "design_area_after_5m_inset_m2": round(float(context["design_area"].area), 3),
            "land_area_after_water_exclusion_m2": round(float(context["land_area"].area), 3),
            "land_block_count": len(context["land_blocks"]),
            "land_block_areas_m2": [round(float(item.area), 3) for item in context["land_blocks"]],
            "bgt_water_mask_area_m2": round(float(context["water_mask"].area), 3),
            "waterfront_public_band_area_m2": round(float(context["waterfront_band"].area), 3),
            "osm_features": context["osm_feature_count"],
            "osm_line_highways": context["network_road_count"],
            "preserved_highways_intersecting_study_area": len(selected_roads),
            "preserved_highways_intersecting_inset_design_area": len(context["preserved_roads_in_design_area"]),
            "preserved_highways_outside_inset_context_only": len(context["context_only_preserved_roads"]),
            "bgt_water_polygons_within_60m": context["water_feature_count"],
        },
        "scope_note": "All Commander-specified settings are assumed, are not human-approved project decisions, and remain local preview inputs.",
    }


def _metric_value(value: Any) -> Any:
    if isinstance(value, UnavailableValue):
        return {"status": "UNAVAILABLE", "reason": value.reason}
    if isinstance(value, tuple):
        return [_metric_value(item) for item in value]
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        return round(float(value), 8)
    return value


def _building_height(building, *, first_floor_m: float, standard_floor_m: float) -> float:
    if building.floor_blocks:
        return max(float(block.top_height_m) for block in building.floor_blocks)
    return first_floor_m + max(0, int(building.floor_count) - 1) * standard_floor_m


def _feature(geometry: BaseGeometry, properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "geometry": mapping(geometry), "properties": properties}


def _preserved_road_context_geometry(road: SiteRoadInput, context: dict[str, Any]) -> BaseGeometry:
    geometry = road.geometry.intersection(context["study_area"])
    if not road.bridge:
        geometry = geometry.difference(context["water_context"])
    return geometry


def _scenario_geojson(candidate, context: dict[str, Any], *, height_settings: tuple[float, float]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    common = {
        "evidence_status": PREVIEW_STATUS,
        "assumption_status": ASSUMPTION_STATUS,
        "approval_decision_id": APPROVAL_REFERENCE,
        "strategy_id": candidate.strategy_id,
    }
    for mask in context["generation_input"].non_buildable_areas:
        features.append(_feature(mask.geometry, {
            **common,
            "feature_kind": "non_buildable_area",
            "mask_id": mask.id,
            "mask_kind": mask.kind,
            "source_artifact_id": mask.source_artifact_id,
            "area_m2": round(float(mask.geometry.area), 3),
        }))
    for index, geometry in enumerate(context["generation_input"].waterfront_public_areas, start=1):
        features.append(_feature(geometry, {
            **common,
            "feature_kind": "waterfront_public_band",
            "band_index": index,
            "width_m": WATERFRONT_BAND_M,
            "area_m2": round(float(geometry.area), 3),
        }))
    block_connectivity = candidate.diff_report.get("land_block_connectivity", [])
    contact_details_by_id = {
        item["contact_id"]: {**item, "land_block_id": block["land_block_id"]}
        for block in block_connectivity
        for item in block.get("external_contacts", [])
    }
    for index, geometry in enumerate(context["land_blocks"], start=1):
        block_metrics = block_connectivity[index - 1] if index <= len(block_connectivity) else {}
        features.append(_feature(geometry.boundary, {
            **common,
            "feature_kind": "land_block_boundary",
            "land_block_id": block_metrics.get("land_block_id", f"land-block-{index:03d}"),
            "area_m2": round(float(geometry.area), 3),
            "connectivity_required": bool(block_metrics.get("required", geometry.area >= MINIMUM_LAND_BLOCK_AREA_M2)),
        }))
    unconnected_ids = {item.contact_id for item in candidate.unconnected_contacts}
    for contact in candidate.external_contacts:
        details = contact_details_by_id.get(contact.contact_id, {})
        features.append(_feature(contact.point, {
            **common,
            "feature_kind": "external_road_contact",
            "contact_id": contact.contact_id,
            "source_road_id": contact.source_road_id,
            "highway": contact.highway,
            "source_mode": contact.source_mode,
            "priority": contact.priority,
            "connected": contact.contact_id not in unconnected_ids,
            "available": details.get("available"),
            "unavailable_reason": details.get("unavailable_reason"),
            "boundary_side": details.get("boundary_side"),
            "land_block_id": details.get("land_block_id"),
        }))
    for zone in context["generation_input"].zones:
        features.append(_feature(zone.geometry, {
            **common,
            "feature_kind": "zone",
            "zone_id": zone.zone_id,
            "target_use": zone.target_use,
            "use_enforcement": zone.use_enforcement,
            "open_space_preference": zone.zone_id == "waterfront-public-15m",
        }))
    features.append(_feature(candidate.open_space, {**common, "feature_kind": "open_space", "area_m2": round(float(candidate.open_space.area), 3)}))
    for index, parcel in enumerate(candidate.parcels, start=1):
        features.append(_feature(parcel, {**common, "feature_kind": "block", "block_id": f"{candidate.strategy_id}-block-{index:04d}", "area_m2": round(float(parcel.area), 3)}))
    first_floor_m, standard_floor_m = height_settings
    for building in candidate.buildings:
        height_m = _building_height(building, first_floor_m=first_floor_m, standard_floor_m=standard_floor_m)
        features.append(_feature(building.footprint, {
            **common,
            "feature_kind": "building_mass",
            "building_id": building.building_id,
            "floors": int(building.floor_count),
            "height_m": round(height_m, 4),
            "base_height_m": 0.0,
            "use_label": building.use_label,
            "zone_id": building.zone_id,
            "area_m2": round(float(building.footprint.area), 3),
        }))
    for road in candidate.roads:
        features.append(_feature(road.geometry, {
            **common,
            "feature_kind": "road_centerline",
            "road_id": road.segment_id,
            "road_status": "generated",
            "road_width_scope": road.road_width_scope,
            "layer": road.layer,
            "bridge": road.bridge,
            "tunnel": road.tunnel,
        }))
    for road in context["selected_preserved_roads"]:
        display_geometry = _preserved_road_context_geometry(road, context)
        if display_geometry.is_empty:
            continue
        source_tags = context["road_tags"].get(road.road_id, {})
        inside_inset = road.geometry.intersects(context["design_area"])
        features.append(_feature(display_geometry, {
            **common,
            "feature_kind": "road_centerline",
            "road_id": road.road_id,
            "road_status": "preserved_by_assumption",
            "disposition": "preserved",
            "inside_inset_generation_area": inside_inset,
            "road_width_scope": road.road_width_scope,
            "width_status": "assumed_constraint" if road.road_width_scope else "not_supplied_centerline_only",
            "source": "OpenStreetMap",
            "source_tags": source_tags,
            "layer": road.layer,
            "bridge": road.bridge,
            "tunnel": road.tunnel,
        }))
    for index, surface in enumerate(candidate.road_surfaces, start=1):
        features.append(_feature(surface, {**common, "feature_kind": "road_surface", "road_status": "generated", "surface_index": index}))
    return {
        "type": "FeatureCollection",
        "name": f"{candidate.strategy_id}-{PREVIEW_STATUS}",
        "crs": {"type": "name", "properties": {"name": CRS}},
        "properties": {
            "evidence_status": PREVIEW_STATUS,
            "assumption_status": ASSUMPTION_STATUS,
            "approval_decision_id": APPROVAL_REFERENCE,
            "human_decision_created": False,
        },
        "features": features,
    }


def _candidate_metrics(candidate, context: dict[str, Any]) -> dict[str, Any]:
    generation_input: SiteGenerationInput = context["generation_input"]
    constraint_values = {(item.name, item.scope): item for item in generation_input.approved_constraints}
    land_far = candidate.metrics.far
    gfa = candidate.metrics.gfa_m2
    full_design_far = (
        gfa if isinstance(gfa, UnavailableValue)
        else float(gfa) / float(generation_input.design_area.area)
    )
    height = candidate.metrics.height_m
    max_height = height[1] if isinstance(height, tuple) else height
    open_space_ratio = float(candidate.open_space.area) / float(generation_input.land_area.area)
    waterfront_public = unary_union(generation_input.waterfront_public_areas) if generation_input.waterfront_public_areas else GeometryCollection()
    strategy_open_space = candidate.open_space.difference(waterfront_public) if not waterfront_public.is_empty else candidate.open_space
    strategy_open_space_ratio = float(strategy_open_space.area) / float(generation_input.land_area.area)
    massing_filter = candidate.diff_report["massing_filter"]
    far_number = None if isinstance(land_far, UnavailableValue) else float(land_far)
    if far_number is None:
        density_status = "UNAVAILABLE"
        density_exception = "FAR is unavailable under the retained-building floor-count evidence."
    elif far_number < DENSITY_TARGET_RANGE[0]:
        density_status = "BELOW_TARGET"
        if candidate.strategy_id == "site-concentric-open-space" and open_space_ratio >= OPEN_SPACE_PREFERENCE:
            density_exception = "The concentric strategy reserves its central open-space pattern and the waterfront public band; open-space ratio and FAR are reported separately."
        else:
            density_exception = "Street-block geometry and minimum viable massing dimensions limited additional floor area; sub-minimum footprints were not emitted."
    elif far_number > DENSITY_TARGET_RANGE[1]:
        density_status = "ABOVE_TARGET_WITHIN_HARD_LIMIT"
        density_exception = None
    else:
        density_status = "MET"
        density_exception = None
    hard_checks = {
        "far_upper_limit": {
            "limit": 2.0,
            "observed": _metric_value(land_far),
            "denominator": "land area (design area minus non-buildable masks)",
            "unit": "ratio",
            "status": "PASS" if not isinstance(land_far, UnavailableValue) and float(land_far) <= 2.0 + 1e-9 else "FAIL_OR_UNAVAILABLE",
        },
        "coverage_upper_limit": {
            "limit": 0.5,
            "observed": _metric_value(candidate.metrics.coverage_ratio),
            "unit": "ratio",
            "status": "PASS" if float(candidate.metrics.coverage_ratio) <= 0.5 + 1e-9 else "FAIL",
        },
        "height_upper_limit": {
            "limit": 40.0,
            "observed": _metric_value(max_height),
            "unit": "m",
            "status": "PASS" if not isinstance(max_height, UnavailableValue) and float(max_height) <= 40.0 + 1e-9 else "FAIL_OR_UNAVAILABLE",
        },
    }
    selected_ids = [item.road_id for item in context["selected_preserved_roads"]]
    candidate_ids = [item.road_id for item in candidate.preserved_roads]
    preserved_ids_stable = set(candidate_ids).issubset(set(selected_ids))
    contact_block_metrics = candidate.diff_report.get("land_block_connectivity", [])
    available_contact_ids = {
        contact["contact_id"]
        for block in contact_block_metrics
        for contact in block.get("external_contacts", [])
        if contact.get("available")
    }
    unconnected_contact_ids = {contact.contact_id for contact in candidate.unconnected_contacts}
    connected_contact_ids = list(dict.fromkeys(
        item.contact_id for item in candidate.external_contacts
        if item.contact_id not in unconnected_contact_ids
    ))
    return {
        "schema_version": "assumed-generation-metrics-v2",
        "strategy_id": candidate.strategy_id,
        "strategy_label": candidate.strategy_label,
        "scenario_status": PREVIEW_STATUS,
        "scenario_status_zh": "未核准預覽",
        "assumption_status": ASSUMPTION_STATUS,
        "approval_decision_id": APPROVAL_REFERENCE,
        "human_decision_created": False,
        "metrics": {
            "far_land_area": {"value": _metric_value(land_far), "unit": "ratio", "denominator_area_m2": round(float(generation_input.land_area.area), 3), "definition": "generated plus retained gross floor area divided by inset design area minus non-buildable mask area"},
            "far_full_design_area": {"value": _metric_value(full_design_far), "unit": "ratio", "denominator_area_m2": round(float(generation_input.design_area.area), 3), "definition": "generated plus retained gross floor area divided by the complete inset design area, including water"},
            "coverage_ratio": {"value": _metric_value(candidate.metrics.coverage_ratio), "unit": "ratio"},
            "maximum_height_m": {"value": _metric_value(max_height), "unit": "m"},
            "open_space_ratio": {"value": round(open_space_ratio, 8), "unit": "ratio", "preference_limit": OPEN_SPACE_PREFERENCE, "preference_status": "MET" if open_space_ratio + 1e-9 >= OPEN_SPACE_PREFERENCE else "NOT_MET_PREFERENCE_ONLY"},
            "strategy_open_space_ratio": {"value": round(strategy_open_space_ratio, 8), "unit": "ratio", "definition": "strategy-created open space excluding the reserved waterfront public band"},
            "density_target": {"target_range": list(DENSITY_TARGET_RANGE), "unit": "ratio", "status": density_status, "exception_reason": density_exception},
            "road_connectivity": {"component_count": candidate.road_component_count, "unit": "components", "method": CONTACT_CONNECTIVITY_RULES_VERSION},
            "land_block_connectivity": {"rules_version": CONTACT_CONNECTIVITY_RULES_VERSION, "minimum_required_area_m2": MINIMUM_LAND_BLOCK_AREA_M2, "blocks": candidate.diff_report.get("land_block_connectivity", [])},
            "external_connection_count": {
                "value": candidate.external_connection_count,
                "unit": "connections",
                "total_contacts": len(candidate.external_contacts),
                "available_contacts": len(available_contact_ids),
                "connected_contact_ids": connected_contact_ids,
                "unconnected_contacts": len(candidate.unconnected_contacts),
            },
            "building_count": len(candidate.buildings),
            "discarded_massing_count": int(massing_filter["discarded_massing_count"]),
            "discarded_gfa_m2": round(float(massing_filter["discarded_gfa_m2"]), 3),
            "block_count": len(candidate.parcels),
            "preserved_road_ids": selected_ids,
            "preserved_road_count": len(selected_ids),
        },
        "hard_constraint_validation": hard_checks,
        "preserved_road_validation": {
            "status": "PASS" if preserved_ids_stable else "FAIL",
            "selected_ids": selected_ids,
            "generator_input_ids": candidate_ids,
            "all_selected_preserved_features_written": True,
            "note": "Roads outside the 5 m inset are retained as source context; roads inside the inset are passed unchanged to the generator.",
        },
        "validation": {
            "valid": bool(candidate.valid and preserved_ids_stable),
            "result": "VALID" if candidate.valid and preserved_ids_stable else "INVALID",
            "result_zh": "有效" if candidate.valid and preserved_ids_stable else "無效",
            "failure_reasons": list(candidate.failure_reasons) + ([] if preserved_ids_stable else ["preserved road input identity changed"]),
            "geometry_hash": candidate.geometry_hash,
            "metrics_provenance": candidate.metrics.provenance,
        },
        "generator": {
            "rules_version": "site-generation-v4",
            "strategy_catalog_version": STRATEGY_CATALOG_VERSION,
            "contact_connectivity_rules_version": CONTACT_CONNECTIVITY_RULES_VERSION,
            "seed": SEED,
            "hard_constraints": [
                {"name": key[0], "scope": key[1], "value": value.value, "unit": value.unit, "enforcement": value.enforcement, "approval_decision_id": value.approval_decision_id}
                for key, value in constraint_values.items()
            ],
        },
        "limitations": [
            "Assumption-only run; not accepted, human-approved, or written to authoritative project state.",
            "The 3.5 m standard floor height is an interview-example assumption, not an approved floor height.",
            "OSM primary/secondary/tertiary preservation is limited to the frozen source coverage and observed tags.",
            "Water masks and the 15 m waterfront public band are geometric assumptions; they are not legal access or waterfront-boundary determinations.",
        ],
    }


_FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    ":": ("00000", "00110", "00110", "00000", "00110", "00110", "00000"),
    "%": ("11001", "11010", "00100", "01000", "10110", "00110", "00000"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
}


class _Raster:
    def __init__(self, width: int, height: int, background: tuple[int, int, int] = (250, 250, 247)):
        self.width = width
        self.height = height
        self.background = background
        self.rows = [bytearray(background * width) for _ in range(height)]

    def pixel(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = x * 3
            self.rows[y][offset:offset + 3] = bytes(color)

    def fill_rect(self, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        left = max(0, min(self.width, min(x0, x1)))
        right = max(0, min(self.width, max(x0, x1)))
        top = max(0, min(self.height, min(y0, y1)))
        bottom = max(0, min(self.height, max(y0, y1)))
        if left >= right or top >= bottom:
            return
        span = bytes(color) * (right - left)
        for y in range(top, bottom):
            start = left * 3
            self.rows[y][start:start + len(span)] = span

    def line(self, start: tuple[float, float], end: tuple[float, float], color: tuple[int, int, int], thickness: int = 1) -> None:
        x0, y0 = start
        x1, y1 = end
        steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0))))
        radius = max(0, thickness // 2)
        for index in range(steps + 1):
            fraction = index / steps
            x = round(x0 + (x1 - x0) * fraction)
            y = round(y0 + (y1 - y0) * fraction)
            if radius == 0:
                self.pixel(x, y, color)
            else:
                self.fill_rect(x - radius, y - radius, x + radius + 1, y + radius + 1, color)

    def polyline(self, points: Sequence[tuple[float, float]], color: tuple[int, int, int], thickness: int = 1) -> None:
        for start, end in zip(points, points[1:]):
            self.line(start, end, color, thickness)

    def fill_polygon(self, points: Sequence[tuple[float, float]], color: tuple[int, int, int]) -> None:
        if len(points) < 3:
            return
        minimum_y = max(0, math.floor(min(point[1] for point in points)))
        maximum_y = min(self.height - 1, math.ceil(max(point[1] for point in points)))
        for y in range(minimum_y, maximum_y + 1):
            scan_y = y + 0.5
            intersections = []
            for first, second in zip(points, (*points[1:], points[0])):
                x0, y0 = first
                x1, y1 = second
                if (y0 <= scan_y < y1) or (y1 <= scan_y < y0):
                    intersections.append(x0 + (scan_y - y0) * (x1 - x0) / (y1 - y0))
            intersections.sort()
            row = self.rows[y]
            fill = bytes(color)
            for left_x, right_x in zip(intersections[::2], intersections[1::2]):
                left = max(0, math.ceil(left_x))
                right = min(self.width, math.ceil(right_x))
                if left < right:
                    start = left * 3
                    row[start:right * 3] = fill * (right - left)

    def text(self, x: int, y: int, value: str, color: tuple[int, int, int], scale: int = 2) -> None:
        cursor_x = x
        for character in value.upper():
            glyph = _FONT.get(character)
            if glyph is None:
                cursor_x += 6 * scale
                continue
            for row_index, row in enumerate(glyph):
                for column_index, enabled in enumerate(row):
                    if enabled == "1":
                        self.fill_rect(
                            cursor_x + column_index * scale,
                            y + row_index * scale,
                            cursor_x + (column_index + 1) * scale,
                            y + (row_index + 1) * scale,
                            color,
                        )
            cursor_x += 6 * scale

    def write_png(self, path: Path) -> None:
        raw = b"".join(b"\x00" + bytes(row) for row in self.rows)

        def chunk(kind: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        payload = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 7)) + chunk(b"IEND", b"")
        path.write_bytes(payload)


def _draw_geometry(canvas: _Raster, geometry: BaseGeometry, transform: Callable[[float, float], tuple[float, float]], *, fill=None, outline=None, thickness: int = 1) -> None:
    if geometry.is_empty:
        return
    if geometry.geom_type == "Polygon":
        exterior = [transform(float(x), float(y)) for x, y, *_ in geometry.exterior.coords]
        if fill is not None:
            canvas.fill_polygon(exterior, fill)
        if outline is not None:
            canvas.polyline((*exterior, exterior[0]), outline, thickness)
        for ring in geometry.interiors:
            points = [transform(float(x), float(y)) for x, y, *_ in ring.coords]
            if fill is not None:
                canvas.fill_polygon(points, canvas.background)
            if outline is not None:
                canvas.polyline((*points, points[0]), outline, thickness)
        return
    if geometry.geom_type in {"MultiPolygon", "MultiLineString", "GeometryCollection"}:
        for part in geometry.geoms:
            _draw_geometry(canvas, part, transform, fill=fill, outline=outline, thickness=thickness)
        return
    if geometry.geom_type == "LineString":
        points = [transform(float(x), float(y)) for x, y, *_ in geometry.coords]
        if fill is not None or outline is not None:
            canvas.polyline(points, outline or fill, thickness)


def _plan_transform(area: BaseGeometry, width: int, height: int, margin: int = 62) -> Callable[[float, float], tuple[float, float]]:
    min_x, min_y, max_x, max_y = area.bounds
    span_x, span_y = max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)
    scale = min((width - 2 * margin) / span_x, (height - 2 * margin) / span_y)
    offset_x = (width - span_x * scale) / 2.0
    offset_y = (height - span_y * scale) / 2.0

    def transform(x: float, y: float) -> tuple[float, float]:
        return offset_x + (x - min_x) * scale, height - offset_y - (y - min_y) * scale

    return transform


def _render_plan(path: Path, candidate, context: dict[str, Any]) -> None:
    width, height = 1200, 920
    canvas = _Raster(width, height)
    area = context["design_area"]
    transform = _plan_transform(area, width, height)
    _draw_geometry(canvas, area, transform, fill=(239, 240, 233), outline=(70, 78, 79), thickness=2)
    for zone in context["generation_input"].zones:
        color = (221, 234, 233) if zone.zone_id == "waterfront-public-15m" else (239, 240, 233)
        _draw_geometry(canvas, zone.geometry, transform, fill=color, outline=None)
    _draw_geometry(canvas, candidate.open_space, transform, fill=(159, 196, 155), outline=(84, 128, 83), thickness=1)
    for geometry in context["generation_input"].waterfront_public_areas:
        _draw_geometry(canvas, geometry, transform, fill=(102, 195, 182), outline=(36, 118, 111), thickness=1)
    _draw_geometry(canvas, context["water_mask"], transform, fill=(76, 157, 207), outline=(35, 100, 145), thickness=1)
    for index, land_block in enumerate(context["land_blocks"], start=1):
        _draw_geometry(canvas, land_block.boundary, transform, outline=(151, 63, 111), thickness=2)
        representative = land_block.representative_point()
        label_x, label_y = transform(float(representative.x), float(representative.y))
        canvas.text(int(label_x + 5), int(label_y + 5), f"L{index}", (119, 43, 91), 2)
    for parcel in candidate.parcels:
        _draw_geometry(canvas, parcel, transform, outline=(192, 171, 130), thickness=1)
    for surface in candidate.road_surfaces:
        _draw_geometry(canvas, surface, transform, fill=(177, 183, 183), outline=None)
    for road in context["selected_preserved_roads"]:
        display_geometry = _preserved_road_context_geometry(road, context)
        if not display_geometry.is_empty:
            _draw_geometry(canvas, display_geometry, transform, outline=(45, 88, 128), thickness=3)
    for road in candidate.roads:
        _draw_geometry(canvas, road.geometry, transform, outline=(81, 88, 93), thickness=2)
    for building in candidate.buildings:
        _draw_geometry(canvas, building.footprint, transform, fill=(202, 126, 91), outline=(115, 65, 51), thickness=1)
    unconnected_ids = {item.contact_id for item in candidate.unconnected_contacts}
    contact_label_offsets = ((-30, -27), (0, -35), (30, -26), (-30, 20), (0, 31), (30, 20))
    for index, contact in enumerate(candidate.external_contacts, start=1):
        point_x, point_y = transform(float(contact.point.x), float(contact.point.y))
        center_x, center_y = int(point_x), int(point_y)
        if contact.contact_id not in unconnected_ids:
            marker = ((center_x, center_y - 8), (center_x + 8, center_y), (center_x, center_y + 8), (center_x - 8, center_y))
            canvas.fill_polygon(marker, (22, 132, 91))
            canvas.polyline((*marker, marker[0]), (17, 71, 51), 2)
            label_color = (17, 91, 63)
        else:
            canvas.line((center_x - 7, center_y), (center_x + 7, center_y), (133, 43, 141), 3)
            canvas.line((center_x, center_y - 7), (center_x, center_y + 7), (133, 43, 141), 3)
            label_color = (105, 31, 115)
        offset_x, offset_y = contact_label_offsets[(index - 1) % len(contact_label_offsets)]
        label_x = center_x + offset_x
        label_y = center_y + offset_y
        canvas.line((center_x, center_y), (label_x, label_y), label_color, 1)
        canvas.text(label_x, label_y, f"C{index}", label_color, 2)
    canvas.text(32, 22, f"PLAN - {STRATEGY_LABELS.get(candidate.strategy_id, candidate.strategy_id)}", (36, 45, 48), 3)
    canvas.text(32, 48, "ASSUMED - UNAPPROVED PREVIEW", (112, 84, 39), 2)
    canvas.fill_rect(32, 82, 52, 98, (76, 157, 207))
    canvas.text(60, 83, "WATER", (36, 45, 48), 2)
    canvas.fill_rect(150, 82, 170, 98, (102, 195, 182))
    canvas.text(178, 83, "15M PUBLIC BAND", (36, 45, 48), 2)
    canvas.line((32, 119), (54, 119), (151, 63, 111), 3)
    canvas.text(62, 110, "BLOCK EDGE", (36, 45, 48), 2)
    canvas.line((190, 119), (204, 119), (133, 43, 141), 3)
    canvas.line((197, 112), (197, 126), (133, 43, 141), 3)
    canvas.text(212, 110, "OSM CONTACT", (36, 45, 48), 2)
    connected_marker = ((430, 119 - 8), (438, 119), (430, 119 + 8), (422, 119))
    canvas.fill_polygon(connected_marker, (22, 132, 91))
    canvas.polyline((*connected_marker, connected_marker[0]), (17, 71, 51), 2)
    canvas.text(448, 110, "CONNECTED OSM CONTACT", (36, 45, 48), 2)
    canvas.write_png(path)


def _axonometric_transform(area: BaseGeometry, width: int, height: int, max_height: float, margin: int = 70):
    min_x, min_y, max_x, max_y = area.bounds
    z_exaggeration = 4.0

    def raw(x: float, y: float, z: float) -> tuple[float, float]:
        local_x, local_y = x - min_x, y - min_y
        return local_x - local_y, 0.5 * (local_x + local_y) - z * z_exaggeration

    corners = [raw(x, y, z) for x in (min_x, max_x) for y in (min_y, max_y) for z in (0.0, max_height)]
    lo_x = min(item[0] for item in corners)
    hi_x = max(item[0] for item in corners)
    lo_y = min(item[1] for item in corners)
    hi_y = max(item[1] for item in corners)
    span_x, span_y = max(hi_x - lo_x, 1.0), max(hi_y - lo_y, 1.0)
    scale = min((width - 2 * margin) / span_x, (height - 2 * margin) / span_y)
    offset_x = (width - span_x * scale) / 2.0
    offset_y = (height - span_y * scale) / 2.0

    def transform(x: float, y: float, z: float = 0.0) -> tuple[float, float]:
        px, py = raw(x, y, z)
        return offset_x + (px - lo_x) * scale, offset_y + (py - lo_y) * scale

    return transform, z_exaggeration


def _darken(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(channel * factor))) for channel in color)


def _draw_extruded_polygon(canvas: _Raster, polygon: Polygon, height_m: float, transform, color: tuple[int, int, int]) -> None:
    coordinates = [(float(x), float(y)) for x, y, *_ in polygon.exterior.coords]
    if coordinates and coordinates[0] == coordinates[-1]:
        coordinates = coordinates[:-1]
    base = [transform(x, y, 0.0) for x, y in coordinates]
    top = [transform(x, y, height_m) for x, y in coordinates]
    for index in range(len(coordinates)):
        next_index = (index + 1) % len(coordinates)
        wall = [base[index], base[next_index], top[next_index], top[index]]
        wall_color = _darken(color, 0.62 if index % 2 else 0.78)
        canvas.fill_polygon(wall, wall_color)
        canvas.polyline((*wall, wall[0]), (112, 67, 54), 1)
    canvas.fill_polygon(top, color)
    canvas.polyline((*top, top[0]), (112, 67, 54), 1)


def _render_axonometric(path: Path, candidate, context: dict[str, Any], *, first_floor_m: float, standard_floor_m: float) -> None:
    width, height = 1200, 920
    canvas = _Raster(width, height)
    area = context["design_area"]
    max_height = max(
        (_building_height(item, first_floor_m=first_floor_m, standard_floor_m=standard_floor_m) for item in candidate.buildings),
        default=40.0,
    )
    transform, z_exaggeration = _axonometric_transform(area, width, height, max_height)
    project = lambda x, y: transform(x, y, 0.0)
    _draw_geometry(canvas, area, project, fill=(238, 239, 232), outline=(70, 78, 79), thickness=2)
    for zone in context["generation_input"].zones:
        color = (221, 234, 233) if zone.zone_id == "waterfront-public-15m" else (238, 239, 232)
        _draw_geometry(canvas, zone.geometry, project, fill=color)
    _draw_geometry(canvas, candidate.open_space, project, fill=(159, 196, 155), outline=(84, 128, 83), thickness=1)
    for geometry in context["generation_input"].waterfront_public_areas:
        _draw_geometry(canvas, geometry, project, fill=(102, 195, 182), outline=(36, 118, 111), thickness=1)
    _draw_geometry(canvas, context["water_mask"], project, fill=(76, 157, 207), outline=(35, 100, 145), thickness=1)
    for surface in candidate.road_surfaces:
        _draw_geometry(canvas, surface, project, fill=(177, 183, 183))
    for road in context["selected_preserved_roads"]:
        display_geometry = _preserved_road_context_geometry(road, context)
        if not display_geometry.is_empty:
            _draw_geometry(canvas, display_geometry, project, outline=(45, 88, 128), thickness=3)
    for road in candidate.roads:
        _draw_geometry(canvas, road.geometry, project, outline=(81, 88, 93), thickness=2)
    sorted_buildings = sorted(candidate.buildings, key=lambda item: item.footprint.centroid.x + item.footprint.centroid.y)
    for building in sorted_buildings:
        roof_height = _building_height(building, first_floor_m=first_floor_m, standard_floor_m=standard_floor_m)
        for polygon in _polygon_parts(building.footprint):
            _draw_extruded_polygon(canvas, polygon, roof_height, transform, (202, 126, 91))
    canvas.text(32, 22, f"AXONOMETRIC - {STRATEGY_LABELS.get(candidate.strategy_id, candidate.strategy_id)}", (36, 45, 48), 2)
    canvas.text(32, 48, f"ASSUMED PREVIEW - Z VISUAL SCALE X{int(z_exaggeration)}", (112, 84, 39), 2)
    canvas.write_png(path)


def _short(value: Any, digits: int = 2) -> str:
    if isinstance(value, UnavailableValue) or value is None:
        return "NA"
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _render_comparison(path: Path, rows: list[dict[str, Any]]) -> None:
    width, row_height = 2050, 112
    height = 190 + row_height * len(rows)
    canvas = _Raster(width, height, (250, 250, 247))
    canvas.text(36, 24, "ASSUMED STRATEGY COMPARISON", (36, 45, 48), 3)
    canvas.text(36, 54, "UNAPPROVED PREVIEW - NO OVERALL WINNER", (112, 84, 39), 2)
    columns = [
        (40, "STRATEGY"), (340, "FAR LAND"), (485, "FAR FULL"), (630, "COVER"),
        (760, "H MAX M"), (895, "OPEN"), (1020, "DROP"), (1140, "ROAD COMP"),
        (1340, "EXT CONN"), (1510, "BLOCK CONN/REQ"), (1800, "VALID"),
    ]
    for x, label in columns:
        canvas.text(x, 119, label, (60, 70, 72), 2)
    canvas.line((32, 148), (width - 32, 148), (172, 177, 174), 2)
    for index, row in enumerate(rows):
        y = 166 + index * row_height
        metrics = row["document"]["metrics"]
        block_summary = ";".join(
            f"{block['connected_external_contact_count']}/{block['required_external_connection_count']}"
            for block in metrics["land_block_connectivity"]["blocks"]
            if block["required"]
        ) or "none"
        values = [
            (40, STRATEGY_LABELS.get(row["strategy_id"], row["strategy_id"])),
            (340, _short(metrics["far_land_area"]["value"])),
            (485, _short(metrics["far_full_design_area"]["value"])),
            (630, _short(metrics["coverage_ratio"]["value"])),
            (760, _short(metrics["maximum_height_m"]["value"])),
            (895, _short(metrics["open_space_ratio"]["value"])),
            (1020, str(metrics["discarded_massing_count"])),
            (1140, str(metrics["road_connectivity"]["component_count"])),
            (1340, str(metrics["external_connection_count"]["value"])),
            (1510, block_summary),
            (1800, "YES" if row["document"]["validation"]["valid"] else "NO"),
        ]
        valid = row["document"]["validation"]["valid"]
        canvas.fill_rect(30, y - 10, width - 30, y + 70, (240, 246, 237) if valid else (250, 235, 229))
        for x, value in values:
            canvas.text(x, y + 12, value, (44, 59, 55) if valid else (121, 67, 52), 2)
        canvas.line((32, y + 83), (width - 32, y + 83), (220, 222, 218), 1)
    canvas.text(36, height - 38, "OPEN SPACE IS A PREFERENCE - NUMBERS ARE DETERMINISTIC PREVIEW MEASUREMENTS", (74, 83, 81), 2)
    canvas.write_png(path)


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _git_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def _all_file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "run-manifest.json"
    }


def run_assumed_generation(
    *,
    study_area_path: Path = DEFAULT_STUDY_AREA,
    source_root: Path = DEFAULT_SOURCE_ROOT,
    output_dir: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    study_area_path = study_area_path.resolve()
    source_root = source_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite assumed-generation run directory: {output_dir}")
    context = _build_input(study_area_path, source_root)
    assumptions = _assumptions_document(context)
    input_payload = {
        "assumptions": assumptions["all_assumptions"],
        "hard_constraints": assumptions["hard_intensity_constraints"],
        "source_metadata": context["source_metadata"],
        "source_hashes": context["source_hashes"],
        "design_area_wkb_sha256": _sha256_bytes(context["design_area"].wkb),
        "land_area_wkb_sha256": _sha256_bytes(context["land_area"].wkb),
        "water_mask_wkb_sha256": _sha256_bytes(context["water_mask"].wkb),
        "waterfront_band_wkb_sha256": _sha256_bytes(context["waterfront_band"].wkb),
        "generation_rules_version": "site-generation-v4",
        "mask_geometry_clearance_m": MASK_GEOMETRY_CLEARANCE_M,
        "contact_connectivity_rules_version": CONTACT_CONNECTIVITY_RULES_VERSION,
        "minimum_land_block_area_m2": MINIMUM_LAND_BLOCK_AREA_M2,
        "density_target_range": DENSITY_TARGET_RANGE,
        "strategy_catalog_version": STRATEGY_CATALOG_VERSION,
    }
    input_hash = _sha256_bytes(json.dumps(input_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    generated = generate_site_strategies(context["generation_input"])
    if len(generated.candidates) < 3:
        raise RuntimeError(f"morphology catalog returned only {len(generated.candidates)} strategies")

    output_dir.mkdir(parents=True, exist_ok=False)
    _write_json(output_dir / "assumptions.json", assumptions)
    first_floor_m, standard_floor_m = 4.5, 3.5
    rows = []
    for candidate in generated.candidates:
        strategy_dir = output_dir / candidate.strategy_id
        strategy_dir.mkdir()
        scenario = _scenario_geojson(candidate, context, height_settings=(first_floor_m, standard_floor_m))
        metrics = _candidate_metrics(candidate, context)
        _write_json(strategy_dir / "scenario.geojson", scenario)
        _write_json(strategy_dir / "metrics.json", metrics)
        _render_plan(strategy_dir / "plan.png", candidate, context)
        _render_axonometric(
            strategy_dir / "axonometric.png",
            candidate,
            context,
            first_floor_m=first_floor_m,
            standard_floor_m=standard_floor_m,
        )
        rows.append({"strategy_id": candidate.strategy_id, "document": metrics})
    _render_comparison(output_dir / "comparison.png", rows)

    elapsed = time.perf_counter() - started
    manifest = {
        "schema_version": "assumed-generation-run-manifest-v2",
        "run_id": output_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workflow_stage": "EXPLORE",
        "evidence_status": PREVIEW_STATUS,
        "evidence_status_zh": "未核准預覽",
        "assumption_status": ASSUMPTION_STATUS,
        "approval_decision_id": APPROVAL_REFERENCE,
        "script_version": SCRIPT_VERSION,
        "mask_geometry_clearance_m": MASK_GEOMETRY_CLEARANCE_M,
        "human_decision_created": False,
        "authority_database_accessed": False,
        "authority_database_written": False,
        "input_hash": input_hash,
        "input_source_hashes": context["source_hashes"],
        "program_git_revision": _git_revision(),
        "program_git_revision_is_uncommitted_source_aware": "git revision points to HEAD; program_source_sha256 additionally binds this runner file",
        "program_source_sha256": _sha256_file(Path(__file__).resolve()),
        "morphology_source_sha256": {
            "contracts.py": _sha256_file(REPOSITORY_ROOT / "src/urban_design/morphology/contracts.py"),
            "strategies.py": _sha256_file(REPOSITORY_ROOT / "src/urban_design/morphology/strategies.py"),
            "validation.py": _sha256_file(REPOSITORY_ROOT / "src/urban_design/morphology/validation.py"),
            "streets.py": _sha256_file(REPOSITORY_ROOT / "src/urban_design/morphology/streets.py"),
            "massing.py": _sha256_file(REPOSITORY_ROOT / "src/urban_design/morphology/massing.py"),
            "parcels.py": _sha256_file(REPOSITORY_ROOT / "src/urban_design/morphology/parcels.py"),
            "metrics.py": _sha256_file(REPOSITORY_ROOT / "src/urban_design/morphology/metrics.py"),
        },
        "generator_rules_version": generated.rules_version,
        "contact_connectivity_rules_version": CONTACT_CONNECTIVITY_RULES_VERSION,
        "candidate_count": len(rows),
        "valid_candidate_count": sum(bool(row["document"]["validation"]["valid"]) for row in rows),
        "elapsed_seconds": round(elapsed, 6),
        "output_files_sha256": _all_file_hashes(output_dir),
    }
    _write_json(output_dir / "run-manifest.json", manifest)
    return {
        "output_dir": output_dir,
        "input_hash": input_hash,
        "manifest": manifest,
        "assumptions": assumptions,
        "strategies": rows,
    }


def _timestamp_name() -> str:
    return datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("%Y%m%dT%H%M%S.%f%z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-area", type=Path, default=DEFAULT_STUDY_AREA)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="Parent for a timestamp-named run directory")
    parser.add_argument("--output-dir", type=Path, help="Write one run to this exact directory")
    args = parser.parse_args(argv)
    output_dir = args.output_dir.expanduser() if args.output_dir else args.output_root.expanduser() / _timestamp_name()
    result = run_assumed_generation(study_area_path=args.study_area, source_root=args.source_root, output_dir=output_dir)
    summary = {
        "output_dir": str(result["output_dir"]),
        "input_hash": result["input_hash"],
        "program_git_revision": result["manifest"]["program_git_revision"],
        "elapsed_seconds": result["manifest"]["elapsed_seconds"],
        "strategies": [
            {
                "strategy_id": row["strategy_id"],
                "far_land_area": row["document"]["metrics"]["far_land_area"]["value"],
                "far_full_design_area": row["document"]["metrics"]["far_full_design_area"]["value"],
                "coverage_ratio": row["document"]["metrics"]["coverage_ratio"]["value"],
                "maximum_height_m": row["document"]["metrics"]["maximum_height_m"]["value"],
                "open_space_ratio": row["document"]["metrics"]["open_space_ratio"]["value"],
                "land_block_connectivity": row["document"]["metrics"]["land_block_connectivity"]["blocks"],
                "density_target": row["document"]["metrics"]["density_target"],
                "discarded_massing_count": row["document"]["metrics"]["discarded_massing_count"],
                "road_components": row["document"]["metrics"]["road_connectivity"]["component_count"],
                "external_connection_count": row["document"]["metrics"]["external_connection_count"]["value"],
                "valid": row["document"]["validation"]["valid"],
                "failure_reasons": row["document"]["validation"]["failure_reasons"],
            }
            for row in result["strategies"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
