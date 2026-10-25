"""Deterministic site calculations from caller-provided geometry and properties.

This standalone helper does not independently verify source provenance, package
completeness, hashes, or CRS. Its calculations and cards must not be treated as
accepted platform Evidence Cards without a separate source-bound validator.

Calculates:
- Source coverage & ground footprint coverage.
- Water and unclassified surface distribution.
- Clipped road length sums and hierarchy.
- Explicit data-gap accounting (missing heights/floors never become zero or fake FAR).
- Controlled gating of grocery accessibility behind human spatial policy approval.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import Polygon
from shapely.ops import unary_union


DECLARED_COMPLETE = "DECLARED_COMPLETE_WITHIN_SCOPE"


class SourceCoverageEvidence(BaseModel):
    """Caller declaration used for calculation gating, not provenance verification."""

    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["DECLARED_COMPLETE_WITHIN_SCOPE", "INCOMPLETE", "UNKNOWN"]
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_evidence_for_complete_scope(self) -> "SourceCoverageEvidence":
        if self.status == DECLARED_COMPLETE and not any(ref.strip() for ref in self.evidence_refs):
            raise ValueError("declared complete coverage requires at least one evidence reference")
        return self


def calculate_site_metrics(
    study_area_geom: Polygon,
    study_area_id: str,
    building_features: Sequence[Mapping[str, Any]],
    water_features: Sequence[Mapping[str, Any]],
    road_features: Sequence[Mapping[str, Any]],
    source_coverage: Mapping[str, SourceCoverageEvidence | Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Calculate deterministic site metrics within a validated study area geometry."""
    study_area_area = round(study_area_geom.area, 2)
    if study_area_area <= 0:
        raise ValueError("Study area has zero or negative area")

    accepted_sources = {"buildings", "water", "roads"}
    unexpected_sources = set(source_coverage or {}) - accepted_sources
    if unexpected_sources:
        raise ValueError(f"unknown source coverage entries: {', '.join(sorted(unexpected_sources))}")
    coverage: dict[str, SourceCoverageEvidence] = {}
    for name in ("buildings", "water", "roads"):
        raw = (source_coverage or {}).get(name)
        coverage[name] = (
            raw if isinstance(raw, SourceCoverageEvidence)
            else SourceCoverageEvidence.model_validate(raw) if raw is not None
            else SourceCoverageEvidence(status="UNKNOWN")
        )
    source_data_status = {name: item.status for name, item in coverage.items()}
    buildings_declared_complete = coverage["buildings"].status == DECLARED_COMPLETE
    water_declared_complete = coverage["water"].status == DECLARED_COMPLETE
    roads_declared_complete = coverage["roads"].status == DECLARED_COMPLETE

    # 1. Building footprint & usage analysis
    intersecting_buildings = []
    clipped_buildings = []
    usage_counts: dict[str, int] = {}
    construction_years: list[int] = []

    for feat in building_features:
        geom = feat.get("geometry")
        if geom is None:
            continue
        if geom.intersects(study_area_geom):
            clipped = geom.intersection(study_area_geom)
            if clipped.area > 1e-3:
                intersecting_buildings.append(feat)
                clipped_buildings.append(clipped)
                props = feat.get("properties", {})
                usage = props.get("gebruiksdoel") or "onbekend"
                usage_counts[usage] = usage_counts.get(usage, 0) + 1
                yr = props.get("bouwjaar")
                if isinstance(yr, int) and 1000 <= yr <= 2030:
                    construction_years.append(yr)

    building_union = unary_union(clipped_buildings) if clipped_buildings else None
    total_footprint_m2 = round(building_union.area if building_union is not None else 0.0, 2)
    coverage_ratio = round(total_footprint_m2 / study_area_area, 4)

    # 2. Water features
    clipped_water = []
    for feat in water_features:
        geom = feat.get("geometry")
        if geom is None:
            continue
        if geom.intersects(study_area_geom):
            clipped = geom.intersection(study_area_geom)
            if clipped.area > 1e-3:
                clipped_water.append(clipped)

    water_union = unary_union(clipped_water) if clipped_water else None
    total_water_m2 = round(water_union.area if water_union is not None else 0.0, 2)
    water_ratio = round(total_water_m2 / study_area_area, 4)

    # 3. Unclassified remainder; this is not evidence of open/public space.
    occupied_parts = [part for part in (building_union, water_union) if part is not None]
    occupied_union_area = unary_union(occupied_parts).area if occupied_parts else 0.0
    unclassified_residual_m2 = max(0.0, round(study_area_area - occupied_union_area, 2))
    unclassified_residual_ratio = round(unclassified_residual_m2 / study_area_area, 4)

    # 4. Road network within study area
    road_lengths_by_type: dict[str, float] = {}
    total_road_length_m = 0.0
    road_segment_count = 0

    for feat in road_features:
        geom = feat.get("geometry")
        if geom is None:
            continue
        if geom.intersects(study_area_geom):
            clipped = geom.intersection(study_area_geom)
            if clipped.length > 1e-3:
                road_segment_count += 1
                length = clipped.length
                total_road_length_m += length
                hwy = feat.get("properties", {}).get("tags", {}).get("highway") or "unclassified"
                road_lengths_by_type[hwy] = round(road_lengths_by_type.get(hwy, 0.0) + length, 2)

    total_road_length_m = round(total_road_length_m, 2)

    # 5. Explicit Data Gaps Register
    data_gaps = [
        {
            "field": "building_height (pand.hoogte)",
            "status": "UNAVAILABLE",
            "impact": "FAR cannot be deterministically computed without building height or storey counts",
            "source": "PDOK BAG ogc/v2",
        },
        {
            "field": "floor_area_ratio (far)",
            "status": "UNAVAILABLE",
            "impact": "FAR is strictly reported as UNAVAILABLE instead of substituting zero or estimated defaults",
            "source": "Derived metric",
        },
        {
            "field": "cadastral_ownership",
            "status": "NOT_APPLICABLE_IN_STUDY_AREA_SCOPE",
            "impact": "Exploration StudyArea does not confer legal parcel or cadastral title conclusions",
            "source": "Kadaster BRK",
        },
        {
            "field": "local_microclimate_wind",
            "status": "UNVERIFIED_E5",
            "impact": "Wind comfort requires boundary conditions and CFD mesh, not wind rose alone",
            "source": "E5 Simulation",
        },
    ]

    return {
        "study_area_id": study_area_id,
        "study_area_area_m2": study_area_area,
        "source_data_status": source_data_status,
        "source_evidence_refs": {
            name: list(item.evidence_refs) for name, item in coverage.items()
        },
        "building_count": len(intersecting_buildings) if buildings_declared_complete else None,
        "building_footprint_area_m2": total_footprint_m2 if buildings_declared_complete else None,
        "ground_coverage_ratio": coverage_ratio if buildings_declared_complete else None,
        "usage_distribution": usage_counts if buildings_declared_complete else None,
        "construction_year_range": {
            "min": min(construction_years) if construction_years else None,
            "max": max(construction_years) if construction_years else None,
        } if buildings_declared_complete else None,
        "height_status": "UNAVAILABLE",
        "far_status": "UNAVAILABLE",
        "calculated_far": None,
        "water_area_m2": total_water_m2 if water_declared_complete else None,
        "water_coverage_ratio": water_ratio if water_declared_complete else None,
        "unclassified_surface_residual_area_m2": (
            unclassified_residual_m2 if buildings_declared_complete and water_declared_complete else None
        ),
        "unclassified_surface_residual_ratio": (
            unclassified_residual_ratio if buildings_declared_complete and water_declared_complete else None
        ),
        "road_segment_count": road_segment_count if roads_declared_complete else None,
        "total_road_length_m": total_road_length_m if roads_declared_complete else None,
        "road_lengths_by_type": road_lengths_by_type if roads_declared_complete else None,
        "data_gaps": data_gaps,
        "formula_version": "site-analysis-m4h-v1",
    }


def evaluate_grocery_accessibility(
    policies_approved: bool = False,
    origin_denominator: str | None = None,
    destination_taxonomy: str | None = None,
    network_policy: str | None = None,
) -> dict[str, Any]:
    """Evaluate grocery accessibility under explicit human approval gating."""
    if not policies_approved or not (origin_denominator and destination_taxonomy and network_policy):
        return {
            "status": "BLOCKED",
            "reason": (
                "Grocery accessibility evaluation requires prior human approval of "
                "origin denominator, destination taxonomy, and pedestrian network spatial policies."
            ),
            "metric_value": None,
            "validation_status": "BLOCKED",
        }

    return {
        "status": "BLOCKED",
        "reason": (
            "The approved policy labels alone do not provide validated origin, destination, and pedestrian graph route inputs; "
            "no accessibility calculation is implemented for this call, so no metric value can be reported."
        ),
        "metric_value": None,
        "validation_status": "BLOCKED",
    }


def _card_calculation_status(value: Any) -> str:
    return "UNAVAILABLE" if value is None else "CALCULATED_INPUT_PROVENANCE_UNVERIFIED"


def generate_site_evidence_cards(
    study_area_geom: Polygon,
    study_area_id: str,
    building_features: Sequence[Mapping[str, Any]],
    water_features: Sequence[Mapping[str, Any]],
    road_features: Sequence[Mapping[str, Any]],
    policies_approved: bool = False,
    source_coverage: Mapping[str, SourceCoverageEvidence | Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Generate provisional calculation cards without claiming verified provenance."""
    metrics = calculate_site_metrics(
        study_area_geom=study_area_geom,
        study_area_id=study_area_id,
        building_features=building_features,
        water_features=water_features,
        road_features=road_features,
        source_coverage=source_coverage,
    )
    acc = evaluate_grocery_accessibility(policies_approved=policies_approved)

    cards = [
        {
            "card_id": f"card-{study_area_id}-footprint-coverage",
            "title": "Building Footprint & Coverage",
            "category": "Built Form",
            "metric": "ground_coverage_ratio",
            "value": metrics["ground_coverage_ratio"],
            "unit": "ratio (0..1)",
            "details": {
                "building_count": metrics["building_count"],
                "footprint_area_m2": metrics["building_footprint_area_m2"],
                "study_area_area_m2": metrics["study_area_area_m2"],
                "usages": metrics["usage_distribution"],
            },
            "source_ref": "PDOK BAG pand items",
            "formula_version": "sum(footprints)/study_area_area-v1",
            "limitations": "Height and FAR unavailable in current PDOK snapshot; missing heights not treated as zero.",
            "validation_status": _card_calculation_status(metrics["ground_coverage_ratio"]),
        },
        {
            "card_id": f"card-{study_area_id}-water-unclassified-residual",
            "title": "Observed Building/Water Footprint Residual",
            "category": "Landscape & Surface",
            "metric": "unclassified_surface_residual_ratio",
            "value": metrics["unclassified_surface_residual_ratio"],
            "unit": "ratio (0..1)",
            "details": {
                "water_area_m2": metrics["water_area_m2"],
                "unclassified_surface_residual_area_m2": metrics["unclassified_surface_residual_area_m2"],
            },
            "source_ref": "PDOK BAG footprints and BGT waterdeel polygons",
            "formula_version": "unclassified_surface_residual-v1",
            "limitations": "Residual of observed building and BGT water geometries only; not open space, public access, ownership, availability, or buildability.",
            "validation_status": _card_calculation_status(metrics["unclassified_surface_residual_ratio"]),
        },
        {
            "card_id": f"card-{study_area_id}-clipped-road-length-sum",
            "title": "Clipped Road Length Sum",
            "category": "Mobility",
            "metric": "total_road_length_m",
            "value": metrics["total_road_length_m"],
            "unit": "metres",
            "details": {
                "segment_count": metrics["road_segment_count"],
                "hierarchy": metrics["road_lengths_by_type"],
            },
            "source_ref": "OpenStreetMap Overpass ways",
            "formula_version": "clipped_linestring_length_sum-v1",
            "limitations": "This is a sum of clipped line lengths, not a graph or a connectivity measure. It does not establish public access, passability, safety, or travel time; OSM tags may omit access restrictions on port-facility roads.",
            "validation_status": _card_calculation_status(metrics["total_road_length_m"]),
        },
        {
            "card_id": f"card-{study_area_id}-data-gaps",
            "title": "Declared Data Gaps & Limitations",
            "category": "Uncertainty & Gaps",
            "metric": "data_gap_count",
            "value": len(metrics["data_gaps"]),
            "unit": "count",
            "details": {"gaps": metrics["data_gaps"]},
            "source_ref": "PDOK / OSM schema audit",
            "formula_version": "gap_inventory-v1",
            "limitations": "Missing values are explicitly recorded as UNAVAILABLE; model is prohibited from guessing.",
            "validation_status": "CALCULATED_INPUT_PROVENANCE_UNVERIFIED",
        },
        {
            "card_id": f"card-{study_area_id}-grocery-accessibility",
            "title": "Grocery Accessibility (Gated)",
            "category": "Accessibility",
            "metric": "walking_accessibility_score",
            "value": None,
            "unit": "score (0..1)",
            "details": acc,
            "source_ref": "OSM grocery candidates & PDOK addresses",
            "formula_version": "spatial_policy_gated_routing-v1",
            "limitations": "Blocked pending explicit human spatial policy decisions.",
            "validation_status": "BLOCKED",
        },
    ]

    return cards
