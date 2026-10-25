"""Fail-closed fixture strategy checks and canonical geometry hashing."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import shapely
from shapely.geometry import GeometryCollection
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from urban_design.morphology.contracts import (
    ExternalRoadContact,
    FixtureGenerationInput,
    GeneratedBuilding,
    ROAD_CENTERLINE_CLEARANCE_MARGIN_M,
    RoadSegment,
    SITE_GEOMETRY_TOLERANCE_M,
    SiteGenerationInput,
    SiteRoadInput,
    UnconnectedRoadContact,
)
from urban_design.morphology.metrics import FloorPlate, MorphologyMetrics, RetainedBuilding, Zone, calculate_morphology_metrics
from urban_design.models import UnavailableValue
from urban_design.far import FarSiteContext, resolve_far_denominator
from urban_design.morphology.streets import (
    count_road_components,
    count_site_road_components,
    external_connection_count,
    external_contact_boundary_side,
    unconnected_contact_reason,
)


def _polygon_parts(geometry: BaseGeometry) -> tuple[BaseGeometry, ...]:
    if geometry.is_empty:
        return ()
    if geometry.geom_type == "Polygon":
        return (geometry,)
    if geometry.geom_type in {"MultiPolygon", "GeometryCollection"}:
        return tuple(part for item in geometry.geoms for part in _polygon_parts(item))
    return ()


def _canonical_wkb(geometry: BaseGeometry) -> str:
    snapped = shapely.set_precision(geometry, grid_size=1e-6, mode="valid_output")
    normalized = shapely.normalize(snapped)
    return normalized.wkb_hex


def is_within_site_geometry_tolerance(area: BaseGeometry, geometry: BaseGeometry) -> bool:
    """Accept only overlay roundoff up to the declared one-micrometre tolerance."""
    return area.covers(geometry) or area.buffer(SITE_GEOMETRY_TOLERANCE_M).covers(geometry)


def _contact_unavailable_reason(contact: ExternalRoadContact, *, no_road_area: BaseGeometry) -> str | None:
    if contact.layer != 0 or contact.bridge or contact.tunnel:
        return "grade-separated contact has no generated vertical transition"
    if not no_road_area.is_empty and no_road_area.distance(contact.point) <= SITE_GEOMETRY_TOLERANCE_M:
        return "contact lies in water or the waterfront no-road clearance area"
    return None


def canonical_geometry_hash(
    *,
    roads: tuple[RoadSegment, ...],
    road_surfaces: tuple[BaseGeometry, ...],
    open_space: BaseGeometry,
    parcels: tuple[BaseGeometry, ...],
    buildings: tuple[GeneratedBuilding, ...],
    retained_footprints: tuple[BaseGeometry, ...],
    preserved_roads: tuple[SiteRoadInput, ...] = (),
    preserved_road_surfaces: tuple[BaseGeometry, ...] = (),
    external_contacts: tuple[ExternalRoadContact, ...] = (),
    excluded_fragments: tuple[Any, ...] = (),
) -> str:
    payload = {
        "coordinate_precision_m": 1e-6,
        "roads": [[item.segment_id, _canonical_wkb(item.geometry), item.layer, item.bridge, item.tunnel, item.road_width_scope] for item in sorted(roads, key=lambda item: item.segment_id)],
        "road_surfaces": [_canonical_wkb(item) for item in road_surfaces],
        "preserved_road_surfaces": [_canonical_wkb(item) for item in preserved_road_surfaces],
        "excluded_fragments": [
            [item.fragment_id, item.reason, _canonical_wkb(item.geometry)]
            for item in sorted(excluded_fragments, key=lambda value: value.fragment_id)
            if item.geometry is not None
        ],
        "open_space": _canonical_wkb(open_space),
        "parcels": [_canonical_wkb(item) for item in parcels],
        "buildings": [[
            item.building_id,
            _canonical_wkb(item.footprint),
            item.floor_count,
            item.use_label,
            item.strategy_parameter,
            item.zone_id,
            [[block.floor_number, _canonical_wkb(block.footprint), block.base_height_m, block.top_height_m, block.use_label] for block in item.floor_blocks],
        ] for item in buildings],
        "retained_footprints": [_canonical_wkb(item) for item in retained_footprints],
        "preserved_roads": [[item.road_id, _canonical_wkb(item.geometry), item.layer, item.bridge, item.tunnel, item.road_width_scope] for item in sorted(preserved_roads, key=lambda item: item.road_id)],
        "external_contacts": [[item.contact_id, item.source_road_id, _canonical_wkb(item.point), item.layer, item.bridge, item.tunnel] for item in sorted(external_contacts, key=lambda item: item.contact_id)],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_candidate_geometry(
    inputs: FixtureGenerationInput,
    *,
    roads: tuple[RoadSegment, ...],
    road_surfaces: tuple[BaseGeometry, ...],
    open_space: BaseGeometry,
    parcels: tuple[BaseGeometry, ...],
    buildings: tuple[GeneratedBuilding, ...],
    retained_footprints: tuple[BaseGeometry, ...],
) -> tuple[tuple[str, ...], MorphologyMetrics, int, int, dict[str, Any]]:
    reasons: list[str] = []
    area = inputs.design_area
    if not open_space.is_valid or open_space.is_empty or not area.covers(open_space):
        reasons.append("open space geometry is invalid or outside the design area")
    for road in roads:
        if not area.covers(road.geometry):
            reasons.append(f"road {road.segment_id} leaves the design area")
    for surface in road_surfaces:
        if not surface.is_valid or not area.covers(surface):
            reasons.append("road surface is invalid or outside the design area")
        if any(surface.intersection(retained).area > 1e-9 for retained in retained_footprints):
            reasons.append("road surface overlaps a retained footprint")
    for parcel in parcels:
        if not parcel.is_valid or not area.covers(parcel):
            reasons.append("parcel geometry is invalid or outside the design area")
    for building in buildings:
        if not building.footprint.is_valid or not area.covers(building.footprint):
            reasons.append(f"building {building.building_id} is invalid or outside the design area")
        if not any(parcel.covers(building.footprint) for parcel in parcels):
            reasons.append(f"building {building.building_id} is outside its generated parcels")
        if any(building.footprint.intersection(retained).area > 1e-9 for retained in retained_footprints):
            reasons.append(f"building {building.building_id} overlaps a retained footprint")
        if any(building.footprint.intersection(surface).area > 1e-9 for surface in road_surfaces):
            reasons.append(f"building {building.building_id} overlaps a road")
        if building.footprint.intersection(open_space).area > 1e-9:
            reasons.append(f"building {building.building_id} overlaps open space")
    if not buildings:
        reasons.append("no massing footprint fits a generated parcel")
    if any(road.geometry.intersects(open_space) and road.geometry.intersection(open_space).length > 1e-9 for road in roads):
        reasons.append("road centerline overlaps open space")
    if any(open_space.intersection(retained).area > 1e-9 for retained in retained_footprints):
        reasons.append("open space overlaps a retained footprint")
    if retained_footprints != inputs.retained_footprints:
        reasons.append("retained footprints changed during generation")

    road_components = count_road_components(roads)
    external_connections = external_connection_count(roads, area)
    if road_components != 1:
        reasons.append(f"road graph has {road_components} disconnected components")
    if external_connections == 0:
        reasons.append("road graph does not connect to an external boundary node")

    floor_plates = tuple(
        FloorPlate(
            id=f"{building.building_id}-floor-{level + 1}",
            geometry=building.footprint,
            level=level,
            building_id=building.building_id,
        )
        for building in buildings
        for level in range(building.floor_count)
    )
    retained_buildings = tuple(
        RetainedBuilding(
            id=f"retained-{index + 1}",
            footprint=footprint,
            floor_count=(
                UnavailableValue(reason="retained building floor count is not available in the fixture")
                if inputs.retained_floor_counts[index] is None
                else inputs.retained_floor_counts[index]
            ),
        )
        for index, footprint in enumerate(retained_footprints)
    )
    metrics = calculate_morphology_metrics(
        area,
        floor_plates,
        first_floor_height_m=inputs.first_floor_height_m,
        standard_floor_height_m=inputs.standard_floor_height_m,
        retained_buildings=retained_buildings,
        far_upper_bound=inputs.far_upper_bound,
        floor_count=max(
            [item.floor_count for item in buildings]
            + [count for count in inputs.retained_floor_counts if count is not None],
            default=1,
        ),
    )
    if isinstance(metrics.far, UnavailableValue):
        reasons.append("FAR is unavailable because retained floor count is unknown")
    elif metrics.far_bound_check is not None and not metrics.far_bound_check.acceptable:
        reasons.append("FAR exceeds upper bound")
    if inputs.max_height_m is not None and not isinstance(metrics.height_m, UnavailableValue):
        height_high = metrics.height_m[1] if isinstance(metrics.height_m, tuple) else metrics.height_m
        if height_high > inputs.max_height_m:
            reasons.append("height exceeds upper bound")
    if inputs.max_coverage_ratio is not None and metrics.coverage_ratio > inputs.max_coverage_ratio:
        reasons.append("coverage ratio exceeds upper bound")

    areas = sorted(float(parcel.area) for parcel in parcels)
    if not areas:
        median_area = None
    elif len(areas) % 2:
        median_area = areas[len(areas) // 2]
    else:
        median_area = (areas[len(areas) // 2 - 1] + areas[len(areas) // 2]) / 2
    open_ratio = float(open_space.area / area.area)

    def metric_record(value, unit: str) -> dict[str, Any]:
        if isinstance(value, UnavailableValue):
            return {"status": "UNAVAILABLE", "reason": value.reason, "unit": unit}
        if isinstance(value, tuple):
            return {"status": "ESTIMATE_RANGE", "range": [float(value[0]), float(value[1])], "unit": unit}
        return {"status": "AVAILABLE", "value": float(value), "unit": unit}

    diff_report = {
        "road_centerline_total_m": math.fsum(float(road.geometry.length) for road in roads),
        "road_segment_count": len(roads),
        "road_surface_area_m2": math.fsum(float(surface.area) for surface in road_surfaces),
        "open_space_area_m2": float(open_space.area),
        "open_space_ratio": open_ratio,
        "parcel_area_distribution_m2": {
            "count": len(areas),
            "minimum": areas[0] if areas else None,
            "median": median_area,
            "maximum": areas[-1] if areas else None,
        },
        "building_count": len(buildings),
        "building_footprint_area_m2": math.fsum(float(item.footprint.area) for item in buildings),
        "strategy_floor_count": sorted({item.floor_count for item in buildings}),
        "gfa": metric_record(metrics.gfa_m2, "m²"),
        "far": metric_record(metrics.far, "ratio"),
        "coverage_area": metric_record(metrics.coverage_m2, "m²"),
        "coverage_ratio": metric_record(metrics.coverage_ratio, "ratio"),
        "height": metric_record(metrics.height_m, "m"),
        "metrics_provenance": metrics.provenance,
        "retained_floor_count_status": ["KNOWN" if count is not None else "UNAVAILABLE" for count in inputs.retained_floor_counts],
    }
    return tuple(dict.fromkeys(reasons)), metrics, road_components, external_connections, diff_report


def validate_site_candidate(
    inputs: SiteGenerationInput,
    *,
    roads: tuple[RoadSegment, ...],
    road_surfaces: tuple[BaseGeometry, ...],
    preserved_road_surfaces: tuple[BaseGeometry, ...],
    open_space: BaseGeometry,
    parcels: tuple[BaseGeometry, ...],
    buildings: tuple[GeneratedBuilding, ...],
    retained_footprints: tuple[BaseGeometry, ...],
    preserved_roads: tuple[SiteRoadInput, ...],
    external_contacts: tuple[ExternalRoadContact, ...],
    excluded_fragments: tuple[Any, ...],
    contact_connectivity_rules_version: str = "contact-connectivity-v2",
) -> tuple[tuple[str, ...], MorphologyMetrics, int, int, dict[str, Any], tuple[UnconnectedRoadContact, ...]]:
    """Validate site geometry, immutable inputs, topology, uses, and hard limits."""
    area = inputs.land_area
    assumed_contact_rules = contact_connectivity_rules_version in {
        "contact-connectivity-v3",
        "contact-connectivity-v3.1",
    }
    has_non_buildable = not inputs.non_buildable_geometry.is_empty
    reasons: list[str] = []
    if not open_space.is_valid or open_space.is_empty or not is_within_site_geometry_tolerance(area, open_space):
        reasons.append("open-space geometry is invalid or outside the design area")
    if has_non_buildable and open_space.intersection(inputs.non_buildable_geometry).area > 1e-9:
        reasons.append("open-space geometry overlaps a non-buildable area")
    all_surfaces = (*road_surfaces, *preserved_road_surfaces)
    for surface in road_surfaces:
        if not surface.is_valid or not is_within_site_geometry_tolerance(area, surface):
            reasons.append("road surface is invalid or outside the design area")
        if has_non_buildable and surface.intersection(inputs.non_buildable_geometry).area > 1e-9:
            reasons.append("generated road surface overlaps a non-buildable area")
        if any(surface.intersection(footprint).area > 1e-9 for footprint in retained_footprints):
            reasons.append("road surface overlaps a preserved building footprint")
        if assumed_contact_rules and inputs.waterfront_public_areas:
            waterfront_band = unary_union(inputs.waterfront_public_areas)
            if surface.intersection(waterfront_band).area > 1e-9:
                reasons.append("generated road surface overlaps the waterfront public band")
    bridgeable = unary_union(tuple(
        road.geometry.buffer(
            next((float(item.value) for item in inputs.approved_constraints if item.name == "road_width" and item.scope == road.road_width_scope), 0.0) / 2.0,
            cap_style="flat",
        ) if road.road_width_scope else road.geometry
        for road in inputs.preserved_roads if road.bridge
    )) if any(road.bridge for road in inputs.preserved_roads) else None
    non_water_masks = inputs.non_buildable_geometry.difference(inputs.water_geometry)
    for surface in preserved_road_surfaces:
        if not surface.is_valid or not is_within_site_geometry_tolerance(inputs.design_area, surface):
            reasons.append("preserved road surface is invalid or outside the design area")
        if has_non_buildable:
            if not non_water_masks.is_empty and surface.intersection(non_water_masks).area > 1e-9:
                reasons.append("preserved road surface overlaps a non-water non-buildable area")
            water_overlap = surface.intersection(inputs.water_geometry)
            if not water_overlap.is_empty and (
                bridgeable is None or not bridgeable.buffer(SITE_GEOMETRY_TOLERANCE_M).covers(water_overlap)
            ):
                reasons.append("preserved road surface overlaps water outside an existing bridge")
        if any(surface.intersection(footprint).area > 1e-9 for footprint in retained_footprints):
            reasons.append("road surface overlaps a preserved building footprint")
    for road in roads:
        if not road.geometry.is_valid or not is_within_site_geometry_tolerance(area, road.geometry):
            reasons.append(f"road centerline {road.segment_id!r} is invalid or outside the design area")
        if not inputs.non_buildable_geometry.is_empty:
            masked_overlap = road.geometry.intersection(inputs.non_buildable_geometry)
            masked_interior_overlap = masked_overlap.difference(inputs.non_buildable_geometry.boundary)
            if masked_interior_overlap.length > 1e-8:
                reasons.append(f"road centerline {road.segment_id!r} crosses a non-buildable area")
        if assumed_contact_rules and inputs.waterfront_public_areas:
            waterfront_band = unary_union(inputs.waterfront_public_areas)
            if road.geometry.intersection(waterfront_band).length > 1e-8:
                reasons.append(f"road centerline {road.segment_id!r} enters the waterfront public band")
    for parcel in parcels:
        if not parcel.is_valid or parcel.is_empty or not is_within_site_geometry_tolerance(area, parcel):
            reasons.append("parcel geometry is invalid or outside the design area")
        if has_non_buildable and parcel.intersection(inputs.non_buildable_geometry).area > 1e-9:
            reasons.append("parcel geometry overlaps a non-buildable area")
    for building in buildings:
        if not building.footprint.is_valid or not is_within_site_geometry_tolerance(area, building.footprint):
            reasons.append(f"building {building.building_id!r} is invalid or outside the design area")
        if not any(parcel.covers(building.footprint) for parcel in parcels):
            reasons.append(f"building {building.building_id!r} is outside its generated parcel")
        if any(building.footprint.intersection(footprint).area > 1e-9 for footprint in retained_footprints):
            reasons.append(f"building {building.building_id!r} overlaps a preserved building")
        if any(building.footprint.intersection(surface).area > 1e-9 for surface in all_surfaces):
            reasons.append(f"building {building.building_id!r} overlaps a road")
        if building.footprint.intersection(open_space).area > 1e-9:
            reasons.append(f"building {building.building_id!r} overlaps open space")
        if has_non_buildable and building.footprint.intersection(inputs.non_buildable_geometry).area > 1e-9:
            reasons.append(f"building {building.building_id!r} overlaps a non-buildable area")
        if any(building.footprint.intersection(geometry).area > 1e-9 for geometry in inputs.waterfront_public_areas):
            reasons.append(f"building {building.building_id!r} overlaps the waterfront public band")
        zone = next((item for item in inputs.zones if item.zone_id == building.zone_id), None)
        if zone is None or not zone.geometry.covers(building.footprint):
            reasons.append(f"building {building.building_id!r} is outside its assigned zone")
        elif building.use_label != zone.target_use:
            reasons.append(f"building {building.building_id!r} use does not match its assigned zone")
        if len(building.floor_blocks) != building.floor_count:
            reasons.append(f"building {building.building_id!r} lacks floor-by-floor blocks")
        for expected_floor, block in enumerate(building.floor_blocks, start=1):
            if (
                block.floor_number != expected_floor
                or not block.footprint.equals(building.footprint)
                or block.top_height_m <= block.base_height_m
            ):
                reasons.append(f"building {building.building_id!r} has invalid floor block geometry or height")
    if not buildings:
        reasons.append("no new massing fits the generated parcels and approved limits")
    if retained_footprints != tuple(item.footprint for item in inputs.preserved_buildings):
        reasons.append("preserved building footprints changed during generation")
    if preserved_roads != inputs.preserved_roads:
        reasons.append("preserved road geometries or layer metadata changed during generation")
    land_blocks = sorted(_polygon_parts(inputs.land_area), key=lambda item: (
        tuple(round(value, 6) for value in item.bounds),
        -round(float(item.area), 6),
        round(float(item.centroid.x), 6),
        round(float(item.centroid.y), 6),
    ))
    for contact in external_contacts:
        if assumed_contact_rules:
            on_external_land_block_boundary = any(
                contact.point.distance(block.boundary.intersection(inputs.design_area.exterior)) <= 1e-6
                for block in land_blocks
            )
            if not on_external_land_block_boundary:
                reasons.append(
                    f"external road contact {contact.contact_id!r} is not on a land-block/site exterior boundary"
                )
        elif contact.point.distance(inputs.design_area.exterior) > 1e-6:
            reasons.append(f"external road contact {contact.contact_id!r} is not on the design-area exterior")

    if assumed_contact_rules:
        road_components = count_road_components(roads)
    else:
        road_components = count_site_road_components(
            roads,
            preserved_roads,
            design_area=inputs.design_area,
            non_buildable_area=inputs.non_buildable_geometry,
            bridgeable_area=inputs.water_geometry,
        )
        if road_components != 1:
            reasons.append(f"road graph has {road_components} disconnected at-grade components")
    external_connections = 0
    unconnected_contacts: list[UnconnectedRoadContact] = []
    for contact in external_contacts:
        reason = unconnected_contact_reason(contact, roads)
        if reason is None:
            external_connections += 1
        else:
            unconnected_contacts.append(UnconnectedRoadContact(
                contact_id=contact.contact_id,
                source_road_id=contact.source_road_id,
                highway=contact.highway,
                source_mode=contact.source_mode,
                priority=contact.priority,
                reason=reason,
                layer=contact.layer,
                bridge=contact.bridge,
                tunnel=contact.tunnel,
            ))
            if contact_connectivity_rules_version == "contact-connectivity-v2" and contact.priority == "major":
                reasons.append(f"major external contact {contact.contact_id!r} remains unconnected: {reason}")
    if not external_contacts and contact_connectivity_rules_version == "contact-connectivity-v2":
        reasons.append("no eligible PD-20 external road contacts were derived from the source network")
    land_block_connectivity = []
    if contact_connectivity_rules_version == "contact-connectivity-v3.1":
        road_widths = [
            float(item.value)
            for item in inputs.approved_constraints
            if item.name == "road_width"
        ]
        no_road_areas = [
            inputs.non_buildable_clearance_geometry
        ] if not inputs.non_buildable_clearance_geometry.is_empty else []
        if inputs.waterfront_public_areas and road_widths:
            no_road_areas.append(
                unary_union(inputs.waterfront_public_areas).buffer(
                    max(road_widths) / 2.0 + ROAD_CENTERLINE_CLEARANCE_MARGIN_M
                )
            )
        no_road_area = unary_union(no_road_areas) if no_road_areas else GeometryCollection()
        for index, land_block in enumerate(land_blocks, start=1):
            block_id = f"land-block-{index:03d}"
            local_roads = tuple(
                road for road in roads
                if land_block.buffer(SITE_GEOMETRY_TOLERANCE_M).covers(road.geometry)
            )
            component_count = count_road_components(local_roads)
            block_contacts = tuple(
                contact for contact in external_contacts
                if contact.point.distance(
                    land_block.boundary.intersection(inputs.design_area.exterior)
                ) <= 1e-6
            )
            unavailable_by_id = {
                contact.contact_id: _contact_unavailable_reason(contact, no_road_area=no_road_area)
                for contact in block_contacts
            }
            available_contacts = tuple(
                contact for contact in block_contacts
                if unavailable_by_id[contact.contact_id] is None
            )
            observed_primary_contacts = tuple(
                contact for contact in block_contacts if contact.priority == "major"
            )
            available_primary_contacts = tuple(
                contact for contact in available_contacts if contact.priority == "major"
            )
            connected_by_id = {
                contact.contact_id: unconnected_contact_reason(contact, roads) is None
                for contact in block_contacts
            }
            connected_primary = sum(
                connected_by_id[contact.contact_id]
                for contact in available_primary_contacts
            )
            connected_external = sum(
                connected_by_id[contact.contact_id]
                for contact in available_contacts
            )
            required = float(land_block.area) >= 2_000.0
            required_external_connections = min(2, len(available_contacts)) if required else 0
            block_warnings = []
            if required and component_count != 1:
                reasons.append(f"{block_id} has {component_count} generated road components; expected exactly one")
            if required and not available_contacts:
                block_warnings.append(
                    "no usable external OSM contact on this land-block boundary; external-connection minimum is not enforced"
                )
            elif required and connected_external < required_external_connections:
                reasons.append(
                    f"{block_id} requires {required_external_connections} connected external OSM contacts "
                    f"but only {connected_external} of {len(available_contacts)} usable boundary contacts "
                    "connect to its generated road network"
                )
            if required and available_primary_contacts and connected_primary == 0:
                reasons.append(
                    f"{block_id} has usable primary OSM contacts but none connects to its generated road network"
                )
            if required and not available_primary_contacts:
                block_warnings.append("no usable external primary OSM contact on this land-block boundary")
            unavailable_count = len(block_contacts) - len(available_contacts)
            if required and unavailable_count:
                block_warnings.append(
                    f"{unavailable_count} observed external OSM contacts are unavailable because they are grade-separated or overlap a no-road mask"
                )
            contact_details = []
            for contact in block_contacts:
                unavailable_reason = unavailable_by_id[contact.contact_id]
                contact_details.append({
                    "contact_id": contact.contact_id,
                    "source_road_id": contact.source_road_id,
                    "highway": contact.highway,
                    "source_mode": contact.source_mode,
                    "priority": contact.priority,
                    "boundary_side": external_contact_boundary_side(contact, design_area=inputs.design_area),
                    "available": unavailable_reason is None,
                    "unavailable_reason": unavailable_reason,
                    "connected": connected_by_id[contact.contact_id],
                })
            land_block_connectivity.append({
                "land_block_id": block_id,
                "area_m2": round(float(land_block.area), 3),
                "required": required,
                "road_component_count": component_count,
                "observed_primary_contact_count": len(observed_primary_contacts),
                "primary_contact_count": len(available_primary_contacts),
                "available_primary_contact_count": len(available_primary_contacts),
                "unusable_primary_contact_count": len(observed_primary_contacts) - len(available_primary_contacts),
                "connected_primary_contact_count": int(connected_primary),
                "total_external_contact_count": len(block_contacts),
                "available_external_contact_count": len(available_contacts),
                "required_external_connection_count": required_external_connections,
                "connected_external_contact_count": int(connected_external),
                "external_contacts": contact_details,
                "warnings": block_warnings,
            })
    elif contact_connectivity_rules_version == "contact-connectivity-v3":
        road_widths = [
            float(item.value)
            for item in inputs.approved_constraints
            if item.name == "road_width"
        ]
        waterfront_no_road_area = (
            unary_union(inputs.waterfront_public_areas).buffer(max(road_widths) / 2.0 + 0.01)
            if inputs.waterfront_public_areas and road_widths
            else None
        )
        for index, land_block in enumerate(land_blocks, start=1):
            block_id = f"land-block-{index:03d}"
            local_roads = tuple(
                road for road in roads
                if land_block.buffer(SITE_GEOMETRY_TOLERANCE_M).covers(road.geometry)
            )
            component_count = count_road_components(local_roads)
            block_contacts = tuple(
                contact for contact in external_contacts
                if contact.point.distance(
                    land_block.boundary.intersection(inputs.design_area.exterior)
                ) <= 1e-6
            )
            observed_primary_contacts = tuple(contact for contact in block_contacts if contact.priority == "major")
            primary_contacts = tuple(
                contact for contact in observed_primary_contacts
                if waterfront_no_road_area is None or waterfront_no_road_area.distance(contact.point) > 1e-6
            )
            unusable_primary_count = len(observed_primary_contacts) - len(primary_contacts)
            connected_primary = sum(
                unconnected_contact_reason(contact, roads) is None
                for contact in primary_contacts
            )
            connected_external = sum(
                unconnected_contact_reason(contact, roads) is None
                for contact in block_contacts
            )
            required = float(land_block.area) >= 2_000.0
            block_warnings = []
            if required and component_count != 1:
                reasons.append(f"{block_id} has {component_count} generated road components; expected exactly one")
            if required and primary_contacts and connected_primary == 0:
                reasons.append(f"{block_id} has primary OSM contacts but none connects to its generated road network")
            if required and unusable_primary_count:
                block_warnings.append(
                    "observed primary OSM contacts lie within the waterfront public band road-clearance area; "
                    "they cannot be connected without violating the no-road rule"
                )
            if required and unusable_primary_count and not primary_contacts:
                reasons.append(
                    f"{block_id} has {unusable_primary_count} observed primary OSM contacts inside the "
                    "waterfront public band road-clearance area; none can connect without violating the no-road rule"
                )
            elif required and not observed_primary_contacts:
                block_warnings.append("no external primary OSM contact on this land-block boundary")
            land_block_connectivity.append({
                "land_block_id": block_id,
                "area_m2": round(float(land_block.area), 3),
                "required": required,
                "road_component_count": component_count,
                "observed_primary_contact_count": len(observed_primary_contacts),
                "primary_contact_count": len(primary_contacts),
                "unusable_primary_contact_count": unusable_primary_count,
                "connected_primary_contact_count": int(connected_primary),
                "total_external_contact_count": len(block_contacts),
                "connected_external_contact_count": int(connected_external),
                "warnings": block_warnings,
            })

    floor_plates = tuple(
        FloorPlate(
            id=f"{building.building_id}-floor-{block.floor_number}",
            geometry=block.footprint,
            level=block.floor_number - 1,
            building_id=building.building_id,
        )
        for building in buildings
        for block in building.floor_blocks
    )
    retained_metrics = tuple(
        RetainedBuilding(
            id=item.building_id,
            footprint=item.footprint,
            floor_count=(
                item.floor_count
                if item.floor_count is not None
                else UnavailableValue(reason="preserved building floor count is unavailable")
            ),
        )
        for item in inputs.preserved_buildings
    )
    far_constraint = next(item for item in inputs.approved_constraints if item.name == "far_upper_limit" and item.scope == "whole_site")
    far_area, far_label = resolve_far_denominator(
        far_constraint, FarSiteContext(inputs.design_area, inputs.water_geometry), legacy_basis="land_area",
    )
    if far_constraint.denominator is None:
        far_area = float(area.area)
    coverage_constraint = next(item for item in inputs.approved_constraints if item.name == "coverage_upper_limit" and item.scope == "whole_site")
    height_constraint = next(item for item in inputs.approved_constraints if item.name == "height_upper_limit" and item.scope == "whole_site")
    first_floor = next(item.value for item in inputs.approved_constraints if item.name == "first_floor_height" and item.scope == "whole_site")
    standard_floor = next(item.value for item in inputs.approved_constraints if item.name == "standard_floor_height" and item.scope == "whole_site")
    zone_metrics = tuple(
        Zone(id=item.zone_id, geometry=item.geometry.intersection(area))
        for item in inputs.zones
        if not item.geometry.intersection(area).is_empty
    )
    height_count = max(
        [item.floor_count for item in buildings]
        + [item.floor_count for item in inputs.preserved_buildings if item.floor_count is not None],
        default=1,
    )
    metrics = calculate_morphology_metrics(
        area,
        floor_plates,
        first_floor_height_m=float(first_floor),
        standard_floor_height_m=float(standard_floor),
        retained_buildings=retained_metrics,
        zones=zone_metrics,
        allocation_policy=inputs.allocation_policy,
        far_upper_bound=float(far_constraint.value),
        floor_count=height_count,
        provenance=inputs.provenance,
        far_denominator_area_m2=far_area,
    )
    if far_constraint.enforcement == "HARD":
        if isinstance(metrics.far, UnavailableValue):
            reasons.append("FAR is unavailable because preserved building floors are unknown")
        elif float(metrics.far) > float(far_constraint.value) + 1e-9:
            reasons.append("FAR exceeds approved whole-site upper bound")
    if coverage_constraint.enforcement == "HARD" and metrics.coverage_ratio > float(coverage_constraint.value) + 1e-9:
        reasons.append("coverage ratio exceeds approved whole-site upper bound")
    if height_constraint.enforcement == "HARD" and not isinstance(metrics.height_m, UnavailableValue):
        observed_height = metrics.height_m[1] if isinstance(metrics.height_m, tuple) else metrics.height_m
        if observed_height > float(height_constraint.value) + 1e-9:
            reasons.append("generated building height exceeds approved whole-site upper bound")

    zone_far_values: dict[str, float | None] = {}
    zone_far_denominators: dict[str, dict[str, Any]] = {}
    for constraint in inputs.approved_constraints:
        if constraint.name != "zone_far_upper_limit":
            continue
        zone_id = constraint.scope.removeprefix("zone:")
        zone = next(item for item in inputs.zones if item.zone_id == zone_id)
        allocated = metrics.zone_floor_area_m2.get(zone_id, 0.0)
        if isinstance(allocated, UnavailableValue):
            zone_far_values[zone_id] = None
            if constraint.enforcement == "HARD":
                reasons.append(f"zone FAR is unavailable for {zone_id!r}")
            continue
        zone_land_area, zone_label = resolve_far_denominator(
            constraint,
            FarSiteContext(zone.geometry.intersection(inputs.design_area if constraint.denominator else area), inputs.water_geometry),
            legacy_basis="exploration_design_area",
        )
        zone_far_denominators[zone_id] = {"label": zone_label, "area_m2": zone_land_area}
        zone_far = float(allocated) / zone_land_area if zone_land_area > 0 else math.inf
        zone_far_values[zone_id] = zone_far
        if constraint.enforcement == "HARD" and zone_far > float(constraint.value) + 1e-9:
            reasons.append(f"zone FAR exceeds approved upper bound for {zone_id!r}")

    excluded_records = [
        {
            "fragment_id": item.fragment_id,
            "area_m2": item.area_m2,
            "minimum_width_m": item.minimum_width_m,
            "reason": item.reason,
        }
        for item in excluded_fragments
    ]
    parcel_areas = sorted(float(item.area) for item in parcels)
    middle = len(parcel_areas) // 2
    median_area = None if not parcel_areas else (
        parcel_areas[middle] if len(parcel_areas) % 2 else (parcel_areas[middle - 1] + parcel_areas[middle]) / 2
    )
    road_union_area = float(unary_union(all_surfaces).area) if all_surfaces else 0.0
    diff_report = {
        "road_centerline_total_m": math.fsum(float(road.geometry.length) for road in roads),
        "road_segment_count": len(roads),
        "road_surface_area_m2": road_union_area,
        "open_space_area_m2": float(open_space.area),
        "open_space_ratio": float(open_space.area / area.area),
        "parcel_area_distribution_m2": {
            "count": len(parcel_areas),
            "minimum": parcel_areas[0] if parcel_areas else None,
            "median": median_area,
            "maximum": parcel_areas[-1] if parcel_areas else None,
        },
        "building_count": len(buildings),
        "building_footprint_area_m2": math.fsum(float(item.footprint.area) for item in buildings),
        "strategy_floor_count": sorted({item.floor_count for item in buildings}),
        "far": _site_metric_record(metrics.far, "ratio"),
        "coverage_ratio": float(metrics.coverage_ratio),
        "height_m": _site_metric_record(metrics.height_m, "m"),
        "zone_far_ratio": zone_far_values,
        "far_denominator": {"label": far_label, "area_m2": far_area},
        "zone_far_denominators": zone_far_denominators,
        "excluded_fragment_count": len(excluded_records),
        "excluded_fragments": excluded_records,
        "external_contact_count": len(external_contacts),
        "external_connected_count": external_connections,
        "land_block_connectivity": land_block_connectivity,
        "preserved_road_count": len(preserved_roads),
        "preserved_building_count": len(retained_footprints),
        "constraint_enforcement": {
            f"{item.name}:{item.scope}": item.enforcement for item in inputs.approved_constraints
        },
        "metrics_provenance": metrics.provenance,
        "geometry_precision_tolerance_m": SITE_GEOMETRY_TOLERANCE_M,
    }
    return (
        tuple(dict.fromkeys(reasons)),
        metrics,
        road_components,
        external_connections,
        diff_report,
        tuple(unconnected_contacts),
    )


def _site_metric_record(value: Any, unit: str) -> dict[str, Any]:
    if isinstance(value, UnavailableValue):
        return {"status": "UNAVAILABLE", "reason": value.reason, "unit": unit}
    if isinstance(value, tuple):
        return {"status": "ESTIMATE_RANGE", "range": [float(value[0]), float(value[1])], "unit": unit}
    return {"status": "AVAILABLE", "value": float(value), "unit": unit}


__all__ = ["canonical_geometry_hash", "validate_candidate_geometry", "validate_site_candidate"]
