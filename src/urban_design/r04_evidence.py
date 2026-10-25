"""R04 same-version observational cards with explicit unique-road semantics."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from pydantic import ValidationError
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .r03_evidence import (
    EvidenceAlignmentError,
    EvidenceBundleRecord,
    EvidenceCardRecord,
    SOURCE_ALIGNED_COVERAGE_LIMITED,
    _bundle_with_legacy_status_normalized,
    _canonical_bytes,
    _parents_for_normalized_artifacts,
    _sha256_bytes,
    _water_features,
    build_observational_evidence_bundle,
)
from .store import ProjectStateStore
from .workspace_sources import WorkspaceSourceCatalog


ROAD_METHOD = "r04-deduplicated-osm-centerline-union-v1"
ROAD_METRIC_KEY = "osm_highway_unique_centerline_length"
SITE_SUMMARY_METHOD = "r04-source-scoped-site-summary-v1"


def _make_source_observation_card(
    *,
    metric_key: str,
    metric_name: str,
    value: float | int,
    unit: str,
    source: str,
    feature_ids: Sequence[str],
    artifacts: Sequence[dict[str, Any]],
    snapshots: Sequence[dict[str, Any]],
    query_bounds: Sequence[dict[str, Any]],
    scope: Mapping[str, Any],
    input_material: Mapping[str, Any],
    limitations: Sequence[str],
    method_diagnostics: Mapping[str, float],
) -> dict[str, Any]:
    input_sha = _sha256_bytes(_canonical_bytes(input_material))
    diagnostics = {str(key): float(item) for key, item in sorted(method_diagnostics.items())}
    output_sha = _sha256_bytes(_canonical_bytes({
        "metric_key": metric_key,
        "value": value,
        "unit": unit,
        "algorithm_version": SITE_SUMMARY_METHOD,
        "input_sha256": input_sha,
        "method_diagnostics": diagnostics,
    }))
    parent_artifact_ids = sorted(
        str(parent["id"]) for parent in artifacts if parent.get("entity_type") == "Artifact"
    )
    snapshot_ids = sorted(str(parent["id"]) for parent in snapshots)
    retrieved = [str(parent.get("retrieved_at")) for parent in snapshots if parent.get("retrieved_at")]
    record = {
        "card_id": "card-r04-" + metric_key + "-" + hashlib.sha256(
            (input_sha + output_sha).encode("ascii")
        ).hexdigest()[:16],
        "metric_key": metric_key,
        "metric_name": metric_name,
        "value": value,
        "unit": unit,
        "status": SOURCE_ALIGNED_COVERAGE_LIMITED,
        "confidence": "OBSERVATIONAL_ONLY",
        "source": source,
        "timestamp": max(retrieved) if retrieved else "UNKNOWN_SOURCE_TIME",
        "crs": "EPSG:28992",
        "query_bounds": list(query_bounds),
        "algorithm_version": SITE_SUMMARY_METHOD,
        "input_sha256": input_sha,
        "output_sha256": output_sha,
        "source_package_id": scope["source_package_id"],
        "source_package_revision": scope["source_package_revision"],
        "study_area_id": scope["study_area_id"],
        "study_area_revision": scope["study_area_revision"],
        "study_area_geometry_sha256": scope["study_area_geometry_sha256"],
        "source_feature_ids": sorted(set(str(item) for item in feature_ids)),
        "source_artifact_ids": parent_artifact_ids,
        "dataset_snapshot_ids": snapshot_ids,
        "parents": [*artifacts, *snapshots],
        "limitations": list(limitations),
        "method_definition": SITE_SUMMARY_METHOD,
        "method_diagnostics": diagnostics,
    }
    return EvidenceCardRecord.model_validate(record).model_dump(mode="json", exclude_none=True)


def calculate_clipped_road_length_metrics(
    geometries: Sequence[BaseGeometry], study_area: BaseGeometry
) -> dict[str, float]:
    """Measure summed clipped ways and their unique linework union in metres."""
    clipped: list[BaseGeometry] = []
    for geometry in geometries:
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError("road geometry must be non-empty and valid")
        intersection = geometry.intersection(study_area)
        if not intersection.is_empty:
            clipped.append(intersection)
    summed = sum(float(geometry.length) for geometry in clipped)
    unique = float(unary_union(clipped).length) if clipped else 0.0
    return {
        "clipped_way_length_sum_m": round(summed, 6),
        "deduplicated_centerline_length_m": round(unique, 6),
        "overlap_multiplicity_excess_m": round(summed - unique, 6),
    }


def build_r04_observational_evidence_bundle(
    catalog: WorkspaceSourceCatalog, store: ProjectStateStore
) -> dict[str, Any]:
    """Keep verified R03 observations while replacing its double-countable road card."""
    bundle = build_observational_evidence_bundle(catalog, store)
    prior = next(
        (card for card in bundle["cards"] if card["metric_key"] == "osm_highway_centerline_length"),
        None,
    )
    if prior is None:
        raise EvidenceAlignmentError("R03 parent bundle has no verified OSM road observation")

    metrics = calculate_clipped_road_length_metrics(
        [shape(item.geometry) for item in catalog.roads],
        catalog.study_area_shape,
    )
    value = metrics["deduplicated_centerline_length_m"]
    inputs = {
        "method_definition": ROAD_METHOD,
        "scope": bundle["scope"],
        "features": [
            {"id": item.feature_id, "artifact_id": item.source_artifact_id, "geometry": item.geometry}
            for item in catalog.roads
        ],
        "parents": prior["parents"],
        "study_area_geometry": catalog.study_area_geometry,
    }
    input_sha = _sha256_bytes(_canonical_bytes(inputs))
    output_sha = _sha256_bytes(_canonical_bytes({
        "metric_key": ROAD_METRIC_KEY,
        "value": value,
        "unit": "m",
        "algorithm_version": ROAD_METHOD,
        "input_sha256": input_sha,
        "method_diagnostics": metrics,
    }))
    road = {
        **prior,
        "card_id": "card-r04-" + ROAD_METRIC_KEY + "-" + hashlib.sha256(
            (input_sha + output_sha).encode("ascii")
        ).hexdigest()[:16],
        "metric_key": ROAD_METRIC_KEY,
        "metric_name": "OSM unique highway centerline length inside StudyArea",
        "value": value,
        "algorithm_version": ROAD_METHOD,
        "input_sha256": input_sha,
        "output_sha256": output_sha,
        "method_definition": ROAD_METHOD,
        "method_diagnostics": metrics,
        "limitations": [
            "This is the length of the union of clipped OSM centerline geometries; coincident linework is counted once.",
            "This is not a connected pedestrian graph, public right of way, access permission, passability, safety, or travel time.",
            "The retained OSM acquisition is bounded; no regional completeness or radius-stability claim is made.",
            "Road classification is the retained OSM highway tagging and does not establish a transport-mode policy.",
        ],
    }
    cards = [road if card is prior else card for card in bundle["cards"]]

    bag_artifact_ids = sorted({
        artifact_id for artifact_id, record in catalog.normalized_artifacts.items()
        if "/pdok-bag-pand-" in str(record.get("uri", ""))
    })
    if not bag_artifact_ids:
        raise EvidenceAlignmentError("verified spatial-r01 has no BAG pand source Artifact")
    bag_artifacts, bag_snapshots, bag_bounds = _parents_for_normalized_artifacts(catalog, bag_artifact_ids)
    raw_usages = [item.properties.get("gebruiksdoel") for item in catalog.buildings]
    usage_counts: dict[str, int] = {}
    null_usage_count = sum(usage is None for usage in raw_usages)
    blank_usage_count = sum(usage is not None and not str(usage).strip() for usage in raw_usages)
    for usage in raw_usages:
        if usage is None or not str(usage).strip():
            continue
        label = str(usage)
        usage_counts[label] = usage_counts.get(label, 0) + 1
    missing_usage_count = len(raw_usages) - sum(usage_counts.values())
    usage_diagnostics = {
        "features_with_null_gebruiksdoel": float(null_usage_count),
        "features_with_blank_gebruiksdoel": float(blank_usage_count),
        "features_with_null_or_blank_gebruiksdoel": float(missing_usage_count),
        **{f"gebruiksdoel::{label}": float(count) for label, count in sorted(usage_counts.items())},
    }
    scope = bundle["scope"]
    bag_features = [
        {
            "id": item.feature_id,
            "artifact_id": item.source_artifact_id,
            "gebruiksdoel": item.properties.get("gebruiksdoel"),
        }
        for item in catalog.buildings
    ]
    cards.append(_make_source_observation_card(
        metric_key="bag_registered_gebruiksdoel_features",
        metric_name="BAG features with a registered gebruiksdoel value",
        value=sum(usage_counts.values()),
        unit="features",
        source="PDOK / Kadaster BAG pand normalized attributes in spatial-r01",
        feature_ids=[item.feature_id for item in catalog.buildings],
        artifacts=bag_artifacts,
        snapshots=bag_snapshots,
        query_bounds=bag_bounds,
        scope=scope,
        input_material={
            "scope": scope,
            "method": SITE_SUMMARY_METHOD,
            "features": bag_features,
            "parents": [*bag_artifacts, *bag_snapshots],
        },
        limitations=[
            "Counts nonblank BAG gebruiksdoel attributes only among retained valid BAG polygon features intersecting the active StudyArea.",
            "This is not a complete land-use inventory, actual occupancy, ownership, permitted use, or a finding about features absent from the retained bounded acquisition.",
            "Blank values are counted explicitly and are not imputed.",
        ],
        method_diagnostics=usage_diagnostics,
    ))

    water_geometries, water_feature_ids, water_artifact_ids = _water_features(catalog)
    water_artifacts, water_snapshots, water_bounds = _parents_for_normalized_artifacts(catalog, water_artifact_ids)
    combined_artifacts = sorted(
        [*bag_artifacts, *water_artifacts], key=lambda parent: (parent.get("entity_type", ""), parent.get("id", ""))
    )
    combined_snapshots = sorted(
        [*bag_snapshots, *water_snapshots], key=lambda parent: str(parent.get("id", ""))
    )
    building_geometries = [
        shape(item.geometry).intersection(catalog.study_area_shape)
        for item in catalog.buildings
    ]
    building_union = unary_union([geometry for geometry in building_geometries if not geometry.is_empty])
    water_union = unary_union(water_geometries) if water_geometries else None
    occupied_parts = [geometry for geometry in (building_union, water_union) if geometry is not None]
    occupied_union = unary_union(occupied_parts) if occupied_parts else None
    site_area = float(catalog.study_area_shape.area)
    occupied_area = float(occupied_union.area) if occupied_union is not None else 0.0
    residual_area = round(max(0.0, site_area - occupied_area), 6)
    building_area = float(building_union.area)
    water_area = float(water_union.area) if water_union is not None else 0.0
    overlap_area = max(0.0, building_area + water_area - occupied_area)
    residual_ids = sorted([item.feature_id for item in catalog.buildings] + water_feature_ids)
    residual_cards_bounds = [*bag_bounds, *water_bounds]
    cards.append(_make_source_observation_card(
        metric_key="unclassified_surface_residual_area",
        metric_name="StudyArea surface outside retained BAG footprints and BGT waterdeel polygons",
        value=residual_area,
        unit="m²",
        source="Derived from retained PDOK / Kadaster BAG and BGT spatial-r01 normalized geometry",
        feature_ids=residual_ids,
        artifacts=combined_artifacts,
        snapshots=combined_snapshots,
        query_bounds=residual_cards_bounds,
        scope=scope,
        input_material={
            "scope": scope,
            "method": SITE_SUMMARY_METHOD,
            "study_area_geometry": catalog.study_area_geometry,
            "building_geometries": [item.geometry for item in catalog.buildings],
            "water_geometries": [mapping(geometry) for geometry in water_geometries],
            "parents": [*combined_artifacts, *combined_snapshots],
        },
        limitations=[
            "This is only the geometric remainder after subtracting retained BAG building footprints and retained BGT waterdeel geometries inside the StudyArea.",
            "It is not open space or green space, and it does not establish public access, private access, ownership, vacancy, availability, legal buildability, or a complete surface classification.",
            "Both source acquisitions are bounded and do not establish absence outside their recorded retained observations.",
        ],
        method_diagnostics={
            "study_area_area_m2": site_area,
            "bag_building_footprint_union_area_m2": building_area,
            "bgt_waterdeel_union_area_m2": water_area,
            "building_water_overlap_area_m2": overlap_area,
            "occupied_union_area_m2": occupied_area,
            "unclassified_surface_residual_area_m2": residual_area,
        },
    ))
    bundle["cards"] = sorted(cards, key=lambda card: card["metric_key"])
    bundle["schema_version"] = "week4-r04-evidence-bundle-v1"
    return EvidenceBundleRecord.model_validate(bundle).model_dump(mode="json", exclude_none=True)


def validate_r04_observational_evidence_bundle(
    candidate: Mapping[str, Any],
    catalog: WorkspaceSourceCatalog,
    store: ProjectStateStore,
) -> list[dict[str, Any]]:
    """Recompute and compare every R04 result, method field, and source parent."""
    expected = build_r04_observational_evidence_bundle(catalog, store)
    if not isinstance(candidate, Mapping):
        raise EvidenceAlignmentError("R04 Evidence Card bundle is invalid")
    try:
        EvidenceBundleRecord.model_validate(candidate)
    except ValidationError as exc:
        raise EvidenceAlignmentError("R04 Evidence Card typed contract validation failed") from exc
    if _bundle_with_legacy_status_normalized(candidate) != expected:
        raise EvidenceAlignmentError("R04 Evidence Card result, method, revision, or parent lineage differs from deterministic recomputation")
    if candidate.get("schema_version") != "week4-r04-evidence-bundle-v1":
        raise EvidenceAlignmentError("R04 Evidence Card bundle schema is invalid")
    return [dict(item) for item in candidate["cards"]]
