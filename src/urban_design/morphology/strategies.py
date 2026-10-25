"""Deterministic D2 fixture strategy catalogue and runner.

The catalogue is explicitly a set of system-proposed patterns, not approved
typologies or a proposal for the Rotterdam study area.
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
import time

from shapely.geometry import GeometryCollection, LineString, Point, box
from shapely.ops import nearest_points, unary_union

from urban_design.morphology.contracts import (
    GeneratedBuilding,
    FixtureGenerationInput,
    ROAD_CENTERLINE_CLEARANCE_MARGIN_M,
    RoadSegment,
    SITE_GEOMETRY_TOLERANCE_M,
    SiteGenerationInput,
    SiteStrategyGenerationResult,
    StrategyCandidate,
    StrategyGenerationResult,
    UnconnectedRoadContact,
)
from urban_design.morphology.massing import (
    place_fixture_buildings,
    place_site_buildings,
    subdivide_building_sites,
)
from urban_design.morphology.parcels import parcelize
from urban_design.morphology.streets import (
    build_road_surfaces,
    build_site_road_surfaces,
    count_road_components,
    derive_external_road_contacts,
    derive_land_block_contacts,
    external_contact_boundary_side,
    unconnected_contact_reason,
)
from urban_design.morphology.validation import (
    canonical_geometry_hash,
    validate_candidate_geometry,
    validate_site_candidate,
)

LAND_BLOCK_MIN_AREA_M2 = 2_000.0


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    label: str
    vertical_axis_fraction: float | None
    horizontal_axis_fraction: float | None
    open_space_bounds_fraction: tuple[float, float, float, float]


def strategy_catalog_v1() -> tuple[StrategyDefinition, ...]:
    """Return versioned examples labelled as proposed system patterns."""
    return (
        StrategyDefinition(
            "grid",
            "System-proposed pattern: connected grid with a distributed open-space pocket",
            0.5,
            0.5,
            (0.68, 0.60, 0.88, 0.84),
        ),
        StrategyDefinition(
            "linear-green-axis",
            "System-proposed pattern: linear green axis with a parallel street spine",
            0.34,
            None,
            (0.60, 0.08, 0.76, 0.92),
        ),
        StrategyDefinition(
            "offset-courtyard",
            "System-proposed pattern: offset streets around a central open-space court",
            0.72,
            0.72,
            (0.42, 0.39, 0.60, 0.59),
        ),
    )


def _roads(definition: StrategyDefinition, bounds: tuple[float, float, float, float]) -> tuple[RoadSegment, ...]:
    min_x, min_y, max_x, max_y = bounds
    width, height = max_x - min_x, max_y - min_y
    roads: list[RoadSegment] = []
    if definition.vertical_axis_fraction is not None:
        x = min_x + width * definition.vertical_axis_fraction
        roads.append(RoadSegment(
            f"{definition.strategy_id}-street-v",
            LineString([(x, min_y), (x, max_y)]),
        ))
    if definition.horizontal_axis_fraction is not None:
        y = min_y + height * definition.horizontal_axis_fraction
        roads.append(RoadSegment(
            f"{definition.strategy_id}-street-h",
            LineString([(min_x, y), (max_x, y)]),
        ))
    return tuple(roads)


def _open_space(definition: StrategyDefinition, area_bounds: tuple[float, float, float, float]):
    min_x, min_y, max_x, max_y = area_bounds
    width, height = max_x - min_x, max_y - min_y
    left, bottom, right, top = definition.open_space_bounds_fraction
    return box(min_x + left * width, min_y + bottom * height, min_x + right * width, min_y + top * height)


def _generate_candidate(inputs: FixtureGenerationInput, definition: StrategyDefinition) -> StrategyCandidate:
    area = inputs.design_area
    roads = _roads(definition, area.bounds)
    road_surfaces = build_road_surfaces(roads, design_area=area, road_width_m=inputs.road_width_m)
    raw_open_space = _open_space(definition, area.bounds)
    removed_from_open_space = (*road_surfaces, *inputs.retained_footprints)
    open_space = raw_open_space.difference(unary_union(removed_from_open_space))
    cutouts = (*road_surfaces, open_space, *inputs.retained_footprints)
    parcel_result = parcelize(
        area,
        cutouts,
        minimum_area_m2=inputs.min_parcel_area_m2,
        minimum_width_m=inputs.min_parcel_width_m,
    )
    buildings = place_fixture_buildings(
        parcel_result.parcels,
        floor_count=inputs.strategy_floor_count,
        maximum_footprint_width_m=inputs.max_footprint_width_m,
        maximum_footprint_depth_m=inputs.max_footprint_depth_m,
        use_label="UNASSIGNED_FIXTURE_USE",
    )
    failure_reasons, metrics, road_components, external_connections, diff_report = validate_candidate_geometry(
        inputs,
        roads=roads,
        road_surfaces=road_surfaces,
        open_space=open_space,
        parcels=parcel_result.parcels,
        buildings=buildings,
        retained_footprints=inputs.retained_footprints,
    )
    if parcel_result.excluded_fragments:
        diff_report["excluded_fragment_count"] = len(parcel_result.excluded_fragments)
        diff_report["excluded_fragment_reasons"] = [item.reason for item in parcel_result.excluded_fragments]
    geometry_hash = canonical_geometry_hash(
        roads=roads,
        road_surfaces=road_surfaces,
        open_space=open_space,
        parcels=parcel_result.parcels,
        buildings=buildings,
        retained_footprints=inputs.retained_footprints,
    )
    return StrategyCandidate(
        candidate_id=f"scenario-fixture-{definition.strategy_id}-{inputs.seed}",
        strategy_id=definition.strategy_id,
        strategy_label=definition.label,
        seed=inputs.seed,
        scenario_status="PROPOSED_FIXTURE_ONLY",
        provenance="FIXTURE_ONLY",
        geometry_hash=geometry_hash,
        roads=roads,
        road_surfaces=road_surfaces,
        open_space=open_space,
        parcels=parcel_result.parcels,
        buildings=buildings,
        retained_footprints=inputs.retained_footprints,
        metrics=metrics,
        valid=not failure_reasons,
        failure_reasons=failure_reasons,
        diff_report=diff_report,
        road_component_count=road_components,
        external_connection_count=external_connections,
    )


def generate_fixture_strategies(inputs: FixtureGenerationInput) -> StrategyGenerationResult:
    """Generate three fixed D2 candidates without reading or persisting project state."""
    return StrategyGenerationResult(
        fixture_parameter_version=inputs.fixture_parameter_version,
        candidates=tuple(_generate_candidate(inputs, definition) for definition in strategy_catalog_v1()),
    )


__all__ = [
    "SiteStrategyDefinition",
    "StrategyDefinition",
    "generate_fixture_strategies",
    "generate_site_strategies",
    "site_strategy_catalog_assumed_v1",
    "site_strategy_catalog_v1",
    "strategy_catalog_v1",
]


@dataclass(frozen=True)
class SiteStrategyDefinition:
    strategy_id: str
    label: str
    street_pattern: str
    open_space_pattern: str
    gfa_utilization: float
    footprint_fraction: float
    floor_utilization: float
    building_plot_size_m: float


def site_strategy_catalog_v1() -> tuple[SiteStrategyDefinition, ...]:
    """Versioned system templates; these are not designer-approved typologies."""
    return (
        SiteStrategyDefinition("site-grid", "System-proposed template: connected grid with distributed open-space pockets", "grid", "distributed", 0.72, 0.42, 0.62, 68.0),
        SiteStrategyDefinition("site-linear-green-axis", "System-proposed template: linear green axis with crossing local streets", "linear", "linear", 0.84, 0.45, 0.72, 56.0),
        SiteStrategyDefinition("site-concentric-open-space", "System-proposed template: central open space with a connected surrounding street", "concentric", "central", 0.68, 0.40, 0.58, 62.0),
    )


def site_strategy_catalog_assumed_v1() -> tuple[SiteStrategyDefinition, ...]:
    """Higher-intensity assumed alternatives; these never alter approved-data runs."""
    return (
        SiteStrategyDefinition("site-grid", "System-proposed template: connected grid with distributed open-space pockets", "grid", "distributed", 0.93, 0.45, 0.91, 52.0),
        SiteStrategyDefinition("site-linear-green-axis", "System-proposed template: linear green axis with crossing local streets", "linear", "linear", 0.95, 0.48, 1.0, 48.0),
        SiteStrategyDefinition("site-concentric-open-space", "System-proposed template: central open space with a connected surrounding street", "concentric", "central", 0.80, 0.38, 0.73, 62.0),
    )


def _linear_parts(geometry) -> tuple[LineString, ...]:
    if geometry.is_empty:
        return ()
    if geometry.geom_type == "LineString":
        return (geometry,) if geometry.length > 1e-6 else ()
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        return tuple(line for part in geometry.geoms for line in _linear_parts(part))
    return ()


def _connected_geometry_parts(geometry) -> tuple:
    if geometry.is_empty:
        return ()
    if geometry.geom_type in {"MultiLineString", "MultiPolygon", "GeometryCollection"}:
        return tuple(part for child in geometry.geoms for part in _connected_geometry_parts(child))
    return (geometry,)


def _boundary_lines(definition: SiteStrategyDefinition, area) -> tuple[tuple[LineString, str], ...]:
    min_x, min_y, max_x, max_y = area.bounds
    width, height = max_x - min_x, max_y - min_y
    center_x, center_y = min_x + width / 2, min_y + height / 2
    raw: list[tuple[LineString, str]] = []
    if definition.street_pattern == "grid":
        raw.extend(((LineString([(center_x, min_y - height), (center_x, max_y + height)]), "primary"),
                    (LineString([(min_x - width, center_y), (max_x + width, center_y)]), "primary")))
    elif definition.street_pattern == "linear":
        raw.extend(((LineString([(center_x, min_y - height), (center_x, max_y + height)]), "primary"),
                    (LineString([(min_x - width, min_y + height * 0.33), (max_x + width, min_y + height * 0.33)]), "secondary"),
                    (LineString([(min_x - width, min_y + height * 0.67), (max_x + width, min_y + height * 0.67)]), "secondary")))
    else:
        radius = min(width, height) * 0.28
        center = area.representative_point()
        raw.extend((part, "primary") for part in _linear_parts(center.buffer(radius, quad_segs=20).boundary.intersection(area)))
        raw.extend(((LineString([(min_x - width, center_y), (max_x + width, center_y)]), "secondary"),
                    (LineString([(center_x, min_y - height), (center_x, max_y + height)]), "secondary")))
    clipped = [
        (part, hierarchy)
        for line, hierarchy in raw
        for part in _linear_parts(line.intersection(area))
    ]
    return tuple(sorted(clipped, key=lambda item: (
        item[1], tuple(round(value, 6) for value in item[0].bounds), round(float(item[0].length), 6)
    )))


def _route_inside_area(
    area,
    obstacles: tuple,
    start: Point,
    end: Point,
    *,
    allow_boundary_roundoff: bool = False,
) -> LineString | None:
    routeable_area = area.buffer(SITE_GEOMETRY_TOLERANCE_M) if allow_boundary_roundoff else area
    if allow_boundary_roundoff and not area.covers(start) and area.distance(start) <= SITE_GEOMETRY_TOLERANCE_M:
        start = nearest_points(routeable_area, start)[0]
    if allow_boundary_roundoff and not area.covers(end) and area.distance(end) <= SITE_GEOMETRY_TOLERANCE_M:
        end = nearest_points(routeable_area, end)[0]
    direct = LineString([(start.x, start.y), (end.x, end.y)])
    if direct.length <= 1e-8:
        return None
    if routeable_area.covers(direct) and not any(direct.crosses(obstacle) or direct.within(obstacle) for obstacle in obstacles):
        return direct
    coordinates = {
        (float(start.x), float(start.y)),
        (float(end.x), float(end.y)),
    }
    for polygon in (area, *obstacles):
        parts = list(polygon.geoms) if polygon.geom_type == "MultiPolygon" else [polygon]
        for part in parts:
            if part.geom_type == "Polygon":
                for ring in (part.exterior, *part.interiors):
                    coordinates.update((float(x), float(y)) for x, y, *_ in ring.coords)
    nodes = sorted(coordinates)
    source, target = (float(start.x), float(start.y)), (float(end.x), float(end.y))
    adjacency = {node: [] for node in nodes}
    for index, first in enumerate(nodes):
        for second in nodes[index + 1:]:
            segment = LineString([first, second])
            if segment.length <= 1e-8 or not routeable_area.covers(segment):
                continue
            if any(segment.crosses(obstacle) or segment.within(obstacle) for obstacle in obstacles):
                continue
            adjacency[first].append((second, float(segment.length)))
            adjacency[second].append((first, float(segment.length)))
    distances = {node: math.inf for node in nodes}
    previous = {node: None for node in nodes}
    distances[source] = 0.0
    queue = [(0.0, source)]
    while queue:
        cost, node = heapq.heappop(queue)
        if cost != distances[node]:
            continue
        if node == target:
            break
        for neighbor, distance in sorted(adjacency[node]):
            candidate = cost + distance
            if candidate + 1e-9 < distances[neighbor]:
                distances[neighbor] = candidate
                previous[neighbor] = node
                heapq.heappush(queue, (candidate, neighbor))
    if not math.isfinite(distances[target]):
        return None
    path = [target]
    while path[-1] != source:
        parent = previous[path[-1]]
        if parent is None:
            return None
        path.append(parent)
    return LineString(list(reversed(path)))


def _connect_to_target(
    roads: list[RoadSegment],
    *,
    target_geometry,
    layer: int,
    bridge: bool,
    tunnel: bool,
    area,
    obstacles: tuple,
    road_width_scope: str,
    segment_id: str,
    allow_boundary_roundoff: bool = False,
) -> bool:
    matching = [road for road in roads if (road.layer, road.bridge, road.tunnel) == (layer, bridge, tunnel)]
    if not matching:
        return False
    network = unary_union([road.geometry for road in matching])
    if target_geometry.distance(network) <= 1e-6:
        return True
    start, end = nearest_points(target_geometry, network)
    route = _route_inside_area(area, obstacles, start, end, allow_boundary_roundoff=allow_boundary_roundoff)
    if route is None:
        return False
    roads.append(RoadSegment(segment_id, route, layer, bridge, tunnel, road_width_scope))
    return True


def _road_components(roads: list[RoadSegment]) -> list[list[RoadSegment]]:
    parents = {road.segment_id: road.segment_id for road in roads}

    def find(item: str) -> str:
        while parents[item] != item:
            parents[item] = parents[parents[item]]
            item = parents[item]
        return item

    for index, first in enumerate(roads):
        for second in roads[index + 1:]:
            if (first.layer, first.bridge, first.tunnel) != (second.layer, second.bridge, second.tunnel):
                continue
            if first.geometry.intersects(second.geometry) or first.geometry.distance(second.geometry) <= SITE_GEOMETRY_TOLERANCE_M:
                left, right = find(first.segment_id), find(second.segment_id)
                if left != right:
                    parents[max(left, right)] = min(left, right)
    groups: dict[str, list[RoadSegment]] = {}
    for road in roads:
        groups.setdefault(find(road.segment_id), []).append(road)
    return [groups[key] for key in sorted(groups)]


def _connect_core_components(
    roads: list[RoadSegment],
    *,
    area,
    obstacles: tuple,
    width_scope: str,
    allow_boundary_roundoff: bool = False,
) -> list[str]:
    """Join compatible at-grade components one verified route at a time."""
    failures: list[str] = []
    if not roads:
        return ["strategy produced no internal road centerlines"]
    link_index = 0
    while True:
        components = _road_components(roads)
        if len(components) <= 1:
            return failures
        choices = []
        for first_index, first in enumerate(components):
            first_topology = (first[0].layer, first[0].bridge, first[0].tunnel)
            first_geometry = unary_union([item.geometry for item in first])
            for second in components[first_index + 1:]:
                if (second[0].layer, second[0].bridge, second[0].tunnel) != first_topology:
                    continue
                second_geometry = unary_union([item.geometry for item in second])
                start, end = nearest_points(first_geometry, second_geometry)
                route = _route_inside_area(
                    area,
                    obstacles,
                    start,
                    end,
                    allow_boundary_roundoff=allow_boundary_roundoff,
                )
                if route is None:
                    continue
                tie_key = tuple(sorted(item.segment_id for item in (*first, *second)))
                choices.append((float(route.length), tie_key, route, first_topology))
        if not choices:
            failures.append(f"road graph remains disconnected with {len(components)} components")
            return failures
        _length, _tie_key, route, (layer, bridge, tunnel) = min(choices, key=lambda item: (item[0], item[1]))
        link_index += 1
        roads.append(RoadSegment(
            f"site-link-core-{link_index}", route, layer, bridge, tunnel, width_scope
        ))


def _site_open_space(
    definition: SiteStrategyDefinition,
    area,
    road_cutouts: tuple,
    preserved_buildings: tuple,
    *,
    per_land_component: bool = False,
):
    components = _polygon_parts(area) if per_land_component else (area,)
    raw_spaces = []
    for component in components:
        min_x, min_y, max_x, max_y = component.bounds
        width, height = max_x - min_x, max_y - min_y
        center = component.representative_point()
        if definition.open_space_pattern == "distributed":
            raw = unary_union((
                box(min_x + width * 0.18, min_y + height * 0.18, min_x + width * 0.34, min_y + height * 0.36),
                box(min_x + width * 0.66, min_y + height * 0.60, min_x + width * 0.82, min_y + height * 0.78),
            ))
        elif definition.open_space_pattern == "linear":
            axis = LineString([(center.x, min_y - height), (center.x, max_y + height)])
            raw = axis.buffer(min(width, height) * 0.07, cap_style="flat")
        else:
            radius_fraction = 0.30 if per_land_component else 0.17
            raw = center.buffer(min(width, height) * radius_fraction)
        raw_spaces.append(raw.intersection(component))
    raw = unary_union(raw_spaces) if raw_spaces else area.intersection(GeometryCollection())
    cutouts = (*road_cutouts, *preserved_buildings)
    return raw.difference(unary_union(cutouts)) if cutouts else raw


def _polygon_parts(geometry) -> tuple:
    if geometry.is_empty:
        return ()
    if geometry.geom_type == "Polygon":
        return (geometry,)
    if geometry.geom_type in {"MultiPolygon", "GeometryCollection"}:
        return tuple(part for item in geometry.geoms for part in _polygon_parts(item))
    return ()


def _land_block_sort_key(geometry) -> tuple:
    return (
        tuple(round(value, 6) for value in geometry.bounds),
        -round(float(geometry.area), 6),
        round(float(geometry.centroid.x), 6),
        round(float(geometry.centroid.y), 6),
    )


def _assumed_road_centerline_area(inputs: SiteGenerationInput, land_block, road_widths: dict[str, float]):
    area = land_block
    if not inputs.non_buildable_clearance_geometry.is_empty:
        area = area.difference(inputs.non_buildable_clearance_geometry)
    if inputs.waterfront_public_areas:
        road_clearance = max(road_widths.values()) / 2.0 + ROAD_CENTERLINE_CLEARANCE_MARGIN_M
        no_road_area = unary_union(inputs.waterfront_public_areas).buffer(road_clearance)
        area = area.difference(no_road_area)
    return area


def _available_assumed_contacts(contacts: tuple, *, road_area) -> tuple:
    return tuple(
        contact for contact in contacts
        if contact.layer == 0
        and not contact.bridge
        and not contact.tunnel
        and (
            road_area.covers(contact.point)
            or road_area.distance(contact.point) <= SITE_GEOMETRY_TOLERANCE_M
        )
    )


def _select_assumed_contacts(
    contacts: tuple,
    *,
    road_area,
    land_block,
    design_area,
) -> tuple:
    available = _available_assumed_contacts(contacts, road_area=road_area)
    if float(land_block.area) < LAND_BLOCK_MIN_AREA_M2:
        return tuple(contact for contact in available if contact.priority == "major")

    required_count = min(2, len(available))
    if required_count == 0:
        return ()
    side_by_id = {
        contact.contact_id: external_contact_boundary_side(contact, design_area=design_area)
        for contact in available
    }
    selected = []
    primary = sorted(
        (contact for contact in available if contact.priority == "major"),
        key=lambda contact: (side_by_id[contact.contact_id], contact.source_road_id, contact.contact_id),
    )
    if primary:
        selected.append(primary[0])
    while len(selected) < required_count:
        used_sides = {side_by_id[contact.contact_id] for contact in selected}
        remaining = [contact for contact in available if contact not in selected]
        next_contact = min(
            remaining,
            key=lambda contact: (
                side_by_id[contact.contact_id] in used_sides,
                side_by_id[contact.contact_id],
                contact.source_road_id,
                contact.contact_id,
            ),
        )
        selected.append(next_contact)
    return tuple(selected)


def _generate_assumed_block_roads(
    inputs: SiteGenerationInput,
    definition: SiteStrategyDefinition,
    *,
    width_scopes: dict[str, float],
    primary_scope: str,
    secondary_scope: str,
    retained_footprints: tuple,
) -> tuple[tuple[RoadSegment, ...], tuple, tuple[str, ...]]:
    roads: list[RoadSegment] = []
    contacts = []
    failures: list[str] = []
    land_blocks = sorted(_polygon_parts(inputs.land_area), key=_land_block_sort_key)
    obstacles = tuple(item.footprint for item in inputs.preserved_buildings) + tuple(
        footprint.buffer(
            max(width_scopes.values()) / 2.0 + ROAD_CENTERLINE_CLEARANCE_MARGIN_M,
            quad_segs=16,
        )
        for footprint in retained_footprints
    )
    for block_index, land_block in enumerate(land_blocks, start=1):
        block_id = f"land-block-{block_index:03d}"
        road_area = _assumed_road_centerline_area(inputs, land_block, width_scopes)
        block_contacts = derive_land_block_contacts(
            inputs.source_network_roads,
            land_block=land_block,
            design_area=inputs.design_area,
        )
        contacts.extend(block_contacts)
        if road_area.is_empty or not road_area.is_valid:
            if land_block.area >= LAND_BLOCK_MIN_AREA_M2:
                failures.append(f"{block_id} has no valid road area outside water and the waterfront public band")
            continue

        core: list[RoadSegment] = []
        for line_index, (line, hierarchy) in enumerate(_boundary_lines(definition, road_area), start=1):
            width_scope = primary_scope if hierarchy == "primary" else secondary_scope
            clearance = tuple(
                footprint.buffer(
                    width_scopes[width_scope] / 2.0 + ROAD_CENTERLINE_CLEARANCE_MARGIN_M,
                    quad_segs=16,
                )
                for footprint in retained_footprints
            )
            clipped = line.difference(unary_union(clearance)) if clearance else line
            for part_index, part in enumerate(_linear_parts(clipped), start=1):
                if part.length > 1e-6:
                    core.append(RoadSegment(
                        segment_id=f"{definition.strategy_id}-{block_id}-{hierarchy}-{line_index}-{part_index}",
                        geometry=part,
                        layer=0,
                        bridge=False,
                        tunnel=False,
                        road_width_scope=width_scope,
                    ))
        network_failures = _connect_core_components(
            core,
            area=road_area,
            obstacles=obstacles,
            width_scope=primary_scope,
            allow_boundary_roundoff=True,
        )
        selected_contacts = _select_assumed_contacts(
            block_contacts,
            road_area=road_area,
            land_block=land_block,
            design_area=inputs.design_area,
        )
        for contact in selected_contacts:
            _connect_to_target(
                core,
                target_geometry=contact.point,
                layer=contact.layer,
                bridge=contact.bridge,
                tunnel=contact.tunnel,
                area=road_area,
                obstacles=obstacles,
                road_width_scope=primary_scope,
                segment_id=f"{definition.strategy_id}-{block_id}-external-{contact.contact_id}",
                allow_boundary_roundoff=True,
            )
        if land_block.area >= LAND_BLOCK_MIN_AREA_M2:
            failures.extend(f"{block_id}: {reason}" for reason in network_failures)
        roads.extend(core)
    return (
        tuple(sorted({road.segment_id: road for road in roads}.values(), key=lambda item: item.segment_id)),
        tuple(contacts),
        tuple(failures),
    )


def _zone_parcels(inputs: SiteGenerationInput, parcels: tuple):
    effective_zones = []
    covered = None
    for zone in inputs.zones:
        geometry = zone.geometry
        if inputs.allocation_policy == "priority" and covered is not None:
            geometry = geometry.difference(covered)
        covered = geometry if covered is None else unary_union((covered, geometry))
        effective_zones.append((zone, geometry))
    zoned: list[tuple[object, str, str]] = []
    excluded = []
    for parcel in parcels:
        for zone, zone_geometry in effective_zones:
            parts = _polygon_parts(parcel.intersection(zone_geometry))
            if not parts:
                continue
            split = parcelize(
                unary_union(parts),
                (),
                minimum_area_m2=inputs.minimum_fragment_area_m2,
                minimum_width_m=inputs.minimum_fragment_width_m,
            )
            zoned.extend((item, zone.zone_id, zone.target_use) for item in split.parcels)
            excluded.extend(split.excluded_fragments)
    return tuple(zoned), tuple(excluded)


def _retained_gfa_by_zone(inputs: SiteGenerationInput) -> dict[str, float | None]:
    result = {}
    for zone in inputs.zones:
        total = 0.0
        unknown = False
        for building in inputs.preserved_buildings:
            overlap = building.footprint.intersection(zone.geometry).area
            if overlap <= 1e-9:
                continue
            if building.floor_count is None:
                unknown = True
            else:
                total += float(overlap) * building.floor_count
        result[zone.zone_id] = None if unknown else total
    return result


def _generate_site_v2_roads(
    inputs: SiteGenerationInput,
    definition: SiteStrategyDefinition,
    contacts,
    *,
    area,
    width_scopes: dict[str, float],
    primary_scope: str,
    secondary_scope: str,
    retained_footprints: tuple,
) -> tuple[tuple[RoadSegment, ...], tuple[str, ...]]:
    core = []
    for index, (line, hierarchy) in enumerate(_boundary_lines(definition, area), start=1):
        width_scope = primary_scope if hierarchy == "primary" else secondary_scope
        clearance = tuple(
            footprint.buffer(
                width_scopes[width_scope] / 2.0 + ROAD_CENTERLINE_CLEARANCE_MARGIN_M,
                quad_segs=16,
            )
            for footprint in retained_footprints
        )
        clipped = line.difference(unary_union(clearance)) if clearance else line
        for part_index, part in enumerate(_linear_parts(clipped), start=1):
            if part.length > 1e-6:
                core.append(RoadSegment(
                    segment_id=f"{definition.strategy_id}-{hierarchy}-{index}-{part_index}",
                    geometry=part,
                    layer=0,
                    bridge=False,
                    tunnel=False,
                    road_width_scope=width_scope,
                ))
    obstacles = tuple(item.footprint for item in inputs.preserved_buildings) + tuple(
        footprint.buffer(
            max(width_scopes.values()) / 2.0 + ROAD_CENTERLINE_CLEARANCE_MARGIN_M,
            quad_segs=16,
        )
        for footprint in retained_footprints
    )
    network_failures = _connect_core_components(
        core, area=area, obstacles=obstacles, width_scope=primary_scope
    )
    for contact in contacts:
        if not _connect_to_target(
            core,
            target_geometry=contact.point,
            layer=contact.layer,
            bridge=contact.bridge,
            tunnel=contact.tunnel,
            area=area,
            obstacles=obstacles,
            road_width_scope=primary_scope,
            segment_id=f"{definition.strategy_id}-external-{contact.contact_id}",
        ):
            reason = unconnected_contact_reason(contact, core)
            if contact.priority == "major":
                network_failures.append(f"major external contact {contact.contact_id!r} remains unconnected: {reason}")
    for road in inputs.preserved_roads:
        clipped = road.geometry.intersection(area)
        for part_index, part in enumerate(_connected_geometry_parts(clipped), start=1):
            if not _connect_to_target(
                core,
                target_geometry=part,
                layer=road.layer,
                bridge=road.bridge,
                tunnel=road.tunnel,
                area=area,
                obstacles=obstacles,
                road_width_scope=road.road_width_scope or primary_scope,
                segment_id=f"{definition.strategy_id}-preserved-road-link-{road.road_id}-{part_index}",
            ):
                network_failures.append(
                    f"preserved road {road.road_id!r} component {part_index} cannot reach the strategy graph at its source layer"
                )
    return tuple(sorted({road.segment_id: road for road in core}.values(), key=lambda item: item.segment_id)), tuple(network_failures)


def _generate_site_candidate(
    inputs: SiteGenerationInput,
    definition: SiteStrategyDefinition,
    contacts,
    *,
    width_scopes: dict[str, float],
    contact_connectivity_rules_version: str,
    strategy_catalog_version: str,
) -> StrategyCandidate:
    area = inputs.land_area
    development_area = inputs.development_area
    if "road:primary" in width_scopes:
        primary_scope = "road:primary"
    elif "road:local" in width_scopes:
        primary_scope = "road:local"
    elif len(width_scopes) == 1:
        primary_scope = next(iter(width_scopes))
    else:
        raise ValueError("approved road width scopes do not identify a system-template primary road width")
    secondary_scope = "road:secondary" if "road:secondary" in width_scopes else (
        "road:local" if "road:local" in width_scopes else primary_scope
    )
    retained_footprints = tuple(item.footprint for item in inputs.preserved_buildings)
    assumed_connectivity_rules = contact_connectivity_rules_version in {
        "contact-connectivity-v3",
        "contact-connectivity-v3.1",
    }
    if assumed_connectivity_rules:
        roads, contacts, network_failures = _generate_assumed_block_roads(
            inputs,
            definition,
            width_scopes=width_scopes,
            primary_scope=primary_scope,
            secondary_scope=secondary_scope,
            retained_footprints=retained_footprints,
        )
    else:
        roads, network_failures = _generate_site_v2_roads(
            inputs,
            definition,
            contacts,
            area=area,
            width_scopes=width_scopes,
            primary_scope=primary_scope,
            secondary_scope=secondary_scope,
            retained_footprints=retained_footprints,
        )
    road_surfaces, preserved_surfaces = build_site_road_surfaces(
        roads,
        inputs.preserved_roads,
        design_area=inputs.design_area,
        road_widths_by_scope=width_scopes,
        non_buildable_area=inputs.non_buildable_geometry,
        bridgeable_area=inputs.water_geometry,
    )
    open_space = _site_open_space(
        definition,
        area,
        (*road_surfaces, *preserved_surfaces),
        retained_footprints,
        per_land_component=assumed_connectivity_rules,
    )
    waterfront_public = tuple(
        geometry.intersection(area)
        for geometry in inputs.waterfront_public_areas
        if not geometry.intersection(area).is_empty
    )
    if waterfront_public:
        reserved_open_space = unary_union(waterfront_public)
        road_and_building_cutouts = (*road_surfaces, *preserved_surfaces, *retained_footprints)
        if road_and_building_cutouts:
            reserved_open_space = reserved_open_space.difference(unary_union(road_and_building_cutouts))
        if not reserved_open_space.is_empty:
            open_space = unary_union((open_space, reserved_open_space))
    if not inputs.non_buildable_geometry.is_empty:
        open_space = open_space.difference(inputs.non_buildable_clearance_geometry)
    cutouts = (*road_surfaces, *preserved_surfaces, open_space, *retained_footprints)
    parcel_result = parcelize(
        development_area,
        cutouts,
        minimum_area_m2=inputs.minimum_fragment_area_m2,
        minimum_width_m=inputs.minimum_fragment_width_m,
    )
    zoned_parcels, zone_excluded = _zone_parcels(inputs, parcel_result.parcels)
    excluded_fragments = (*parcel_result.excluded_fragments, *zone_excluded)

    from urban_design.far import FarSiteContext, resolve_far_denominator
    far_constraint = next(item for item in inputs.approved_constraints if item.name == "far_upper_limit" and item.scope == "whole_site")
    far_limit = far_constraint.value
    water = unary_union([item.geometry for item in inputs.non_buildable_areas if item.kind == "water"])
    far_area, far_label = resolve_far_denominator(far_constraint, FarSiteContext(inputs.design_area, water), legacy_basis="land_area")
    if far_constraint.denominator is None:
        # Preserve historical budgets, which subtract all non-buildable masks.
        far_area = float(area.area)
    coverage_limit = next(item.value for item in inputs.approved_constraints if item.name == "coverage_upper_limit" and item.scope == "whole_site")
    height_limits = [item.value for item in inputs.approved_constraints if item.name == "height_upper_limit"]
    first_floor = next(item.value for item in inputs.approved_constraints if item.name == "first_floor_height" and item.scope == "whole_site")
    standard_floor = next(item.value for item in inputs.approved_constraints if item.name == "standard_floor_height" and item.scope == "whole_site")
    maximum_height = min(height_limits)
    maximum_floor_count = max(1, int(math.floor((maximum_height - first_floor) / standard_floor)) + 1)
    floor_count = max(1, min(maximum_floor_count, int(math.floor(maximum_floor_count * definition.floor_utilization))))
    known_retained_gfa = sum(
        float(item.footprint.area) * item.floor_count
        for item in inputs.preserved_buildings
        if item.floor_count is not None
    )
    maximum_new_gfa = max(
        0.0, far_area * float(far_limit) * definition.gfa_utilization - known_retained_gfa
    )
    retained_coverage = float(unary_union(retained_footprints).area) if retained_footprints else 0.0
    maximum_new_coverage = max(0.0, float(area.area) * float(coverage_limit) - retained_coverage)
    retained_by_zone = _retained_gfa_by_zone(inputs)
    zone_gfa_limits = {}
    for zone in inputs.zones:
        constraint = next(
            (item for item in inputs.approved_constraints if item.name == "zone_far_upper_limit" and item.scope == f"zone:{zone.zone_id}"),
            None,
        )
        if constraint is not None:
            retained = retained_by_zone[zone.zone_id]
            zone_gfa_limits[zone.zone_id] = max(
                0.0,
                resolve_far_denominator(constraint, FarSiteContext(zone.geometry.intersection(inputs.design_area), water), legacy_basis="exploration_design_area")[0] * float(constraint.value) * definition.gfa_utilization - (retained or 0.0),
            )
    building_sites = subdivide_building_sites(
        zoned_parcels,
        building_plot_size_m=definition.building_plot_size_m,
    )
    massing_result = place_site_buildings(
        building_sites,
        strategy_id=definition.strategy_id,
        seed=inputs.seed,
        floor_count=floor_count,
        first_floor_height_m=float(first_floor),
        standard_floor_height_m=float(standard_floor),
        maximum_new_gfa_m2=maximum_new_gfa,
        maximum_new_coverage_m2=maximum_new_coverage,
        zone_gfa_limits_m2=zone_gfa_limits,
        footprint_fraction=definition.footprint_fraction,
        minimum_footprint_area_m2=inputs.minimum_footprint_area_m2,
        minimum_short_edge_m=inputs.minimum_short_edge_m,
        footprint_mode=("shape-aware" if assumed_connectivity_rules else "square"),
        preserve_capacity_after_discard=assumed_connectivity_rules,
    )
    buildings = massing_result.buildings
    failure_reasons, metrics, road_components, external_count, diff_report, unconnected_contacts = validate_site_candidate(
        inputs,
        roads=roads,
        road_surfaces=road_surfaces,
        preserved_road_surfaces=preserved_surfaces,
        open_space=open_space,
        parcels=tuple(site for site, _zone_id, _use_label in building_sites),
        buildings=buildings,
        retained_footprints=retained_footprints,
        preserved_roads=inputs.preserved_roads,
        external_contacts=contacts,
        excluded_fragments=excluded_fragments,
        contact_connectivity_rules_version=contact_connectivity_rules_version,
    )
    failure_reasons = tuple(dict.fromkeys((*network_failures, *failure_reasons)))
    diff_report.update({
        "strategy_parameters": {
            "gfa_utilization": definition.gfa_utilization,
            "footprint_fraction": definition.footprint_fraction,
            "floor_utilization": definition.floor_utilization,
            "building_plot_size_m": definition.building_plot_size_m,
            "building_site_count": len(building_sites),
            "street_block_count": len(parcel_result.parcels),
            "minimum_footprint_area_m2": inputs.minimum_footprint_area_m2,
            "minimum_short_edge_m": inputs.minimum_short_edge_m,
            "primary_road_width_scope": primary_scope,
            "secondary_road_width_scope": secondary_scope,
            "fragment_rule_version": inputs.fragment_rule_version,
            "strategy_catalog_version": strategy_catalog_version,
        },
        "contact_connectivity": {
            "rules_version": contact_connectivity_rules_version,
            "land_blocks": diff_report.get("land_block_connectivity", []),
            "major_contact_count": sum(contact.priority == "major" for contact in contacts),
            "minor_contact_count": sum(contact.priority == "minor" for contact in contacts),
            "connected_contact_count": external_count,
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
                for item in unconnected_contacts
            ],
        },
        "road_hierarchy_lengths_m": {
            scope: math.fsum(road.geometry.length for road in roads if road.road_width_scope == scope)
            for scope in sorted(width_scopes)
        },
        "geometry_precision_tolerance_m": SITE_GEOMETRY_TOLERANCE_M,
        "road_centerline_building_clearance_margin_m": ROAD_CENTERLINE_CLEARANCE_MARGIN_M,
        "massing_filter": {
            "discarded_massing_count": massing_result.discarded_massing_count,
            "discarded_gfa_m2": round(massing_result.discarded_gfa_m2, 6),
            "minimum_footprint_area_m2": inputs.minimum_footprint_area_m2,
            "minimum_short_edge_m": inputs.minimum_short_edge_m,
        },
    })
    geometry_hash = canonical_geometry_hash(
        roads=roads,
        road_surfaces=road_surfaces,
        open_space=open_space,
        parcels=tuple(site for site, _zone_id, _use_label in building_sites),
        buildings=buildings,
        retained_footprints=retained_footprints,
        preserved_roads=inputs.preserved_roads,
        preserved_road_surfaces=preserved_surfaces,
        external_contacts=contacts,
        excluded_fragments=excluded_fragments,
    )
    return StrategyCandidate(
        candidate_id=f"scenario-site-{definition.strategy_id}-{inputs.seed}",
        strategy_id=definition.strategy_id,
        strategy_label=definition.label,
        seed=inputs.seed,
        scenario_status="UNAPPROVED_PREVIEW" if inputs.provenance == "ASSUMED" else "PROPOSED",
        provenance=inputs.provenance,
        geometry_hash=geometry_hash,
        roads=roads,
        road_surfaces=road_surfaces,
        open_space=open_space,
        parcels=tuple(site for site, _zone_id, _use_label in building_sites),
        buildings=buildings,
        retained_footprints=retained_footprints,
        preserved_roads=inputs.preserved_roads,
        preserved_road_surfaces=preserved_surfaces,
        external_contacts=contacts,
        unconnected_contacts=unconnected_contacts,
        excluded_fragments=excluded_fragments,
        metrics=metrics,
        valid=not failure_reasons,
        failure_reasons=failure_reasons,
        diff_report=diff_report,
        road_component_count=road_components,
        external_connection_count=external_count,
    )


def generate_site_strategies(inputs: SiteGenerationInput) -> SiteStrategyGenerationResult:
    """Generate deterministic site alternatives from explicitly typed inputs."""
    contact_connectivity_rules_version = (
        "contact-connectivity-v3.1" if inputs.provenance == "ASSUMED" else "contact-connectivity-v2"
    )
    strategy_catalog_version = (
        "assumed-strategy-catalog-v1" if inputs.provenance == "ASSUMED" else "strategy-catalog-v2"
    )
    generation_rules_version = (
        "site-generation-v4" if inputs.provenance == "ASSUMED" else "site-generation-v3"
    )
    width_scopes = {
        item.scope: float(item.value)
        for item in inputs.approved_constraints
        if item.name == "road_width"
    }
    contacts = (
        () if contact_connectivity_rules_version in {"contact-connectivity-v3", "contact-connectivity-v3.1"}
        else derive_external_road_contacts(inputs.source_network_roads, design_area=inputs.design_area)
    )
    candidates = []
    strategy_runtime_seconds = {}
    catalog = site_strategy_catalog_assumed_v1() if inputs.provenance == "ASSUMED" else site_strategy_catalog_v1()
    for definition in catalog:
        started = time.perf_counter()
        candidates.append(_generate_site_candidate(
            inputs,
            definition,
            contacts,
            width_scopes=width_scopes,
            contact_connectivity_rules_version=contact_connectivity_rules_version,
            strategy_catalog_version=strategy_catalog_version,
        ))
        strategy_runtime_seconds[definition.strategy_id] = round(time.perf_counter() - started, 6)
    from urban_design.far import FarSiteContext, resolve_far_denominator
    far_constraint = next(item for item in inputs.approved_constraints if item.name == "far_upper_limit" and item.scope == "whole_site")
    water = unary_union([item.geometry for item in inputs.non_buildable_areas if item.kind == "water"])
    far_area, far_label = resolve_far_denominator(far_constraint, FarSiteContext(inputs.design_area, water), legacy_basis="land_area")
    if far_constraint.denominator is None:
        far_area = float(inputs.land_area.area)
    far_limit = far_constraint.value
    return SiteStrategyGenerationResult(
        rules_version=generation_rules_version,
        candidates=tuple(candidates),
        provenance=inputs.provenance,
        metadata={
            "provenance": inputs.provenance,
            "evidence_class": {
                "FIXTURE_ONLY": "ILLUSTRATIVE",
                "ASSUMED": "UNAPPROVED_PREVIEW",
                "APPROVED_PROJECT_DATA": "PROPOSED",
            }[inputs.provenance],
            "contact_connectivity_rules_version": contact_connectivity_rules_version,
            "strategy_catalog_version": strategy_catalog_version,
            "minimum_land_block_area_m2": LAND_BLOCK_MIN_AREA_M2 if contact_connectivity_rules_version == "contact-connectivity-v3.1" else None,
            "non_buildable_area_count": len(inputs.non_buildable_areas),
            "non_buildable_kinds": sorted({item.kind for item in inputs.non_buildable_areas}),
            "land_area_m2": round(float(inputs.land_area.area), 6),
            "far_denominator": {"label": far_label, "area_m2": far_area},
            "far_gfa_upper_limit_m2": far_area * float(far_limit),
            "development_area_m2": round(float(inputs.development_area.area), 6),
            "geometry_precision_tolerance_m": SITE_GEOMETRY_TOLERANCE_M,
            "contact_connectivity": {
                "major_classes": ["trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link", "pedestrian"],
                "minor_classes": ["unclassified", "residential", "living_street", "service"],
                "external_contact_minimum_policy": (
                    "two_if_two_or_more_usable_contacts; one_if_exactly_one; warning_if_zero"
                    if contact_connectivity_rules_version == "contact-connectivity-v3.1" else None
                ),
                "primary_contact_policy": (
                    "at_least_one_connected_when_a_usable_primary_contact_exists"
                    if contact_connectivity_rules_version == "contact-connectivity-v3.1" else None
                ),
                "grade_separation": "layer_bridge_tunnel_must_match; no at-grade inference",
            },
            "strategy_runtime_seconds": strategy_runtime_seconds,
        },
    )
