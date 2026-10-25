"""Fixture road geometry, connectivity, and boundary-node helpers."""

from __future__ import annotations

from itertools import combinations
import hashlib

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, Point
from shapely.ops import unary_union

from urban_design.morphology.contracts import (
    ExternalRoadContact,
    MASK_GEOMETRY_CLEARANCE_M,
    MorphologyGenerationError,
    RoadSegment,
    SITE_GEOMETRY_TOLERANCE_M,
    SiteRoadInput,
)


_CAR_CONTACT_HIGHWAYS = frozenset({
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
    "tertiary", "tertiary_link",
    "unclassified", "residential", "living_street", "service",
})
_MAJOR_CONTACT_HIGHWAYS = frozenset({
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
    "tertiary", "tertiary_link",
})
_FOOT_PERMISSIONS = frozenset({"yes", "designated", "permissive"})
_EXCLUDED_SERVICE_TYPES = frozenset({"driveway", "parking_aisle", "drive-through", "drive_through"})


def _contact_source(road: SiteRoadInput) -> tuple[str, str] | None:
    """Return PD-20 mode and priority for a road that may define a site contact."""
    if road.inactive:
        return None
    highway = (road.highway or "").strip().casefold()
    access = (road.access or "").strip().casefold()
    foot = (road.foot or "").strip().casefold()
    if highway == "pedestrian":
        if foot == "no" or (access in {"no", "private"} and foot not in _FOOT_PERMISSIONS):
            return None
        return "pedestrian", "major"
    if highway not in _CAR_CONTACT_HIGHWAYS:
        return None
    if access in {"no", "private"} or (road.motor_vehicle or "").strip().casefold() == "no":
        return None
    if highway == "service" and (road.service or "").strip().casefold() in _EXCLUDED_SERVICE_TYPES:
        return None
    priority = "major" if highway in _MAJOR_CONTACT_HIGHWAYS else "minor"
    return "motor_vehicle", priority


def _connected_parts(geometry):
    if geometry.is_empty:
        return ()
    if geometry.geom_type in {"MultiLineString", "MultiPolygon", "GeometryCollection"}:
        return tuple(part for child in geometry.geoms for part in _connected_parts(child))
    if geometry.geom_type not in {"LineString", "Polygon"}:
        return ()
    return (geometry,)


def count_road_components(roads: tuple[RoadSegment, ...] | list[RoadSegment]) -> int:
    """Count intersections as connections only when layer/bridge/tunnel match."""
    if not roads:
        return 0
    edges = []
    for road in roads:
        parts = list(road.geometry.geoms) if road.geometry.geom_type == "MultiLineString" else [road.geometry]
        edges.extend(
            (f"{road.segment_id}#{index}", part, road.layer, road.bridge, road.tunnel)
            for index, part in enumerate(parts)
        )
    parents = {edge[0]: edge[0] for edge in edges}

    def find(item: str) -> str:
        while parents[item] != item:
            parents[item] = parents[parents[item]]
            item = parents[item]
        return item

    def union(first: str, second: str) -> None:
        a, b = find(first), find(second)
        if a != b:
            parents[max(a, b)] = min(a, b)

    for first, second in combinations(edges, 2):
        if first[2:] != second[2:]:
            continue
        if first[1].intersects(second[1]):
            union(first[0], second[0])
    return len({find(edge[0]) for edge in edges})


def external_connection_count(roads: tuple[RoadSegment, ...] | list[RoadSegment], design_area) -> int:
    """Count distinct road endpoints that reach the fixture boundary."""
    boundary = design_area.boundary
    endpoints: set[tuple[float, float]] = set()
    for road in roads:
        components = list(road.geometry.geoms) if road.geometry.geom_type == "MultiLineString" else [road.geometry]
        for line in components:
            coordinates = list(line.coords)
            for coordinate in (coordinates[0], coordinates[-1]):
                point = Point(coordinate[:2])
                if boundary.distance(point) <= 1e-6:
                    endpoints.add((float(point.x), float(point.y)))
    return len(endpoints)


def build_road_surfaces(roads: tuple[RoadSegment, ...], *, design_area, road_width_m: float):
    if road_width_m <= 0:
        raise MorphologyGenerationError("road width must be positive")
    surfaces = []
    for road in roads:
        if not design_area.covers(road.geometry):
            raise MorphologyGenerationError(f"road centerline {road.segment_id} extends outside the design area")
        surface = road.geometry.buffer(road_width_m / 2.0, cap_style="flat", join_style="mitre").intersection(design_area)
        if surface.is_empty or not surface.is_valid:
            raise MorphologyGenerationError(f"road surface {road.segment_id} is empty or invalid")
        surfaces.append(surface)
    return tuple(surfaces)


def derive_external_road_contacts(source_roads: tuple[SiteRoadInput, ...], *, design_area) -> tuple[ExternalRoadContact, ...]:
    """Derive PD-20 car/pedestrian boundary contacts without joining different layers."""
    return _derive_contacts(source_roads, boundary=design_area.exterior)


def derive_land_block_contacts(
    source_roads: tuple[SiteRoadInput, ...],
    *,
    land_block,
    design_area,
) -> tuple[ExternalRoadContact, ...]:
    """Derive OSM road contacts only where a land block meets the site exterior."""
    external_boundary = land_block.boundary.intersection(design_area.exterior)
    if external_boundary.is_empty:
        return ()
    return _derive_contacts(source_roads, boundary=external_boundary)


def external_contact_boundary_side(contact: ExternalRoadContact, *, design_area) -> str:
    """Return the cardinal side of the nearest exterior segment for stable routing preference."""
    coordinates = list(design_area.exterior.coords)
    segments = [
        (index, LineString((coordinates[index], coordinates[index + 1])))
        for index in range(len(coordinates) - 1)
    ]
    if not segments:
        return "unknown"
    _index, segment = min(
        segments,
        key=lambda item: (float(item[1].distance(contact.point)), item[0]),
    )
    (x1, y1), (x2, y2) = segment.coords
    center = design_area.centroid
    if abs(x2 - x1) >= abs(y2 - y1):
        return "north" if (y1 + y2) / 2.0 >= center.y else "south"
    return "east" if (x1 + x2) / 2.0 >= center.x else "west"


def _derive_contacts(source_roads: tuple[SiteRoadInput, ...], *, boundary) -> tuple[ExternalRoadContact, ...]:
    contacts: list[ExternalRoadContact] = []
    for road in sorted(source_roads, key=lambda item: item.road_id):
        source = _contact_source(road)
        if source is None:
            continue
        source_mode, priority = source
        highway = (road.highway or "").strip().casefold()
        crossing = road.geometry.intersection(boundary)
        points: list[Point] = []

        def collect(geometry) -> None:
            if geometry.is_empty:
                return
            if geometry.geom_type == "Point":
                points.append(geometry)
            elif geometry.geom_type in {"MultiPoint", "GeometryCollection"}:
                for part in geometry.geoms:
                    collect(part)
            elif geometry.geom_type in {"LineString", "MultiLineString"}:
                lines = list(geometry.geoms) if geometry.geom_type == "MultiLineString" else [geometry]
                for line in lines:
                    coordinates = list(line.coords)
                    if coordinates:
                        points.append(Point(coordinates[0][:2]))
                        if len(coordinates) > 1:
                            points.append(Point(coordinates[-1][:2]))

        collect(crossing)
        unique: dict[tuple[int, int], Point] = {}
        for point in points:
            if not boundary.distance(point) <= 1e-6:
                continue
            unique.setdefault((round(point.x * 1_000_000), round(point.y * 1_000_000)), point)
        for ordinal, (_coordinate, point) in enumerate(sorted(unique.items()), start=1):
            stable = f"{road.road_id}:{point.x:.6f}:{point.y:.6f}:{road.layer}:{road.bridge}:{road.tunnel}:{highway}:{source_mode}:{priority}"
            contact_id = "contact-" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
            contacts.append(ExternalRoadContact(
                contact_id=contact_id,
                source_road_id=road.road_id,
                point=point,
                layer=road.layer,
                bridge=road.bridge,
                tunnel=road.tunnel,
                source_artifact_id=road.source_artifact_id,
                source_snapshot_id=road.source_snapshot_id,
                highway=highway,
                source_mode=source_mode,
                priority=priority,
            ))
    return tuple(sorted(contacts, key=lambda item: (item.source_road_id, item.point.x, item.point.y, item.layer)))


def unconnected_contact_reason(contact: ExternalRoadContact, roads: tuple[RoadSegment, ...] | list[RoadSegment]) -> str | None:
    """Describe whether a contact reaches generated geometry at its exact vertical layer."""
    connected = any(
        (road.layer, road.bridge, road.tunnel) == (contact.layer, contact.bridge, contact.tunnel)
        and road.geometry.distance(contact.point) <= SITE_GEOMETRY_TOLERANCE_M
        for road in roads
    )
    if connected:
        return None
    if contact.layer != 0 or contact.bridge or contact.tunnel:
        return (
            "grade-separated source cannot connect to the at-grade strategy graph "
            f"(layer={contact.layer}, bridge={str(contact.bridge).lower()}, tunnel={str(contact.tunnel).lower()}); "
            "no vertical transition is inferred"
        )
    return "no matching at-grade strategy road reaches the contact point"


def build_site_road_surfaces(
    roads: tuple[RoadSegment, ...],
    preserved_roads: tuple[SiteRoadInput, ...],
    *,
    design_area,
    road_widths_by_scope: dict[str, float],
    non_buildable_area=None,
    bridgeable_area=None,
) -> tuple[tuple[object, ...], tuple[object, ...]]:
    """Buffer generated/preserved centerlines at approved widths and clip to site."""
    generated_surfaces = []
    exclusion_area = (
        non_buildable_area.buffer(MASK_GEOMETRY_CLEARANCE_M)
        if non_buildable_area is not None and not non_buildable_area.is_empty
        else non_buildable_area
    )
    for road in roads:
        width_scope = road.road_width_scope
        if width_scope is None or width_scope not in road_widths_by_scope:
            raise MorphologyGenerationError(f"generated road {road.segment_id!r} lacks an approved width constraint")
        width = road_widths_by_scope[width_scope]
        surface = road.geometry.buffer(width / 2.0, cap_style="flat", join_style="mitre").intersection(design_area)
        if exclusion_area is not None and not exclusion_area.is_empty:
            surface = surface.difference(exclusion_area)
        if surface.is_empty or not surface.is_valid:
            raise MorphologyGenerationError(f"generated road surface {road.segment_id!r} is empty or invalid")
        generated_surfaces.append(surface)

    preserved_surfaces = []
    for road in preserved_roads:
        clipped = road.geometry.intersection(design_area)
        if clipped.is_empty:
            continue
        if road.geometry.geom_type in {"Polygon", "MultiPolygon"}:
            surface = clipped
        else:
            width_scope = road.road_width_scope
            if width_scope is None:
                # Retain the observed centerline without fabricating an
                # unprovided carriageway width for this hierarchy.
                surface = clipped
            else:
                if width_scope not in road_widths_by_scope:
                    raise MorphologyGenerationError(f"preserved road {road.road_id!r} lacks an approved width constraint")
                width = road_widths_by_scope[width_scope]
                surface = road.geometry.buffer(width / 2.0, cap_style="flat", join_style="mitre").intersection(design_area)
        if exclusion_area is not None and not exclusion_area.is_empty:
            excluded = exclusion_area
            if road.bridge and bridgeable_area is not None and not bridgeable_area.is_empty:
                non_water_masks = non_buildable_area.difference(bridgeable_area)
                excluded = non_water_masks.buffer(MASK_GEOMETRY_CLEARANCE_M)
            if not excluded.is_empty:
                surface = surface.difference(excluded)
        if surface.is_empty:
            continue
        if surface.is_empty or not surface.is_valid:
            raise MorphologyGenerationError(f"preserved road surface {road.road_id!r} is empty or invalid")
        preserved_surfaces.append(surface)
    return tuple(generated_surfaces), tuple(preserved_surfaces)


def count_site_road_components(
    roads: tuple[RoadSegment, ...],
    preserved_roads: tuple[SiteRoadInput, ...],
    *,
    design_area,
    non_buildable_area=None,
    bridgeable_area=None,
) -> int:
    """Count connected at-grade components while retaining layer/bridge/tunnel identity."""
    mask_interior = (
        non_buildable_area.buffer(-SITE_GEOMETRY_TOLERANCE_M)
        if non_buildable_area is not None and not non_buildable_area.is_empty
        else None
    )
    bridgeable_interior = (
        bridgeable_area.buffer(-SITE_GEOMETRY_TOLERANCE_M)
        if bridgeable_area is not None and not bridgeable_area.is_empty
        else None
    )
    edges = []
    for identifier, geometry, layer, bridge, tunnel in (
        (road.segment_id, road.geometry, road.layer, road.bridge, road.tunnel)
        for road in roads
    ):
        clipped = geometry.intersection(design_area)
        if mask_interior is not None and not mask_interior.is_empty:
            clipped = clipped.difference(mask_interior)
        edges.extend(
            (f"generated:{identifier}#{index}", part, layer, bridge, tunnel)
            for index, part in enumerate(_connected_parts(clipped))
        )
    for road in preserved_roads:
        clipped = road.geometry.intersection(design_area)
        if mask_interior is not None and not mask_interior.is_empty:
            excluded = mask_interior
            if road.bridge and bridgeable_interior is not None and not bridgeable_interior.is_empty:
                excluded = mask_interior.difference(bridgeable_interior)
            if not excluded.is_empty:
                clipped = clipped.difference(excluded)
        edges.extend(
            (f"preserved:{road.road_id}#{index}", part, road.layer, road.bridge, road.tunnel)
            for index, part in enumerate(_connected_parts(clipped))
        )
    edges = [edge for edge in edges if not edge[1].is_empty]
    if not edges:
        return 0
    parents = {edge[0]: edge[0] for edge in edges}

    def find(item: str) -> str:
        while parents[item] != item:
            parents[item] = parents[parents[item]]
            item = parents[item]
        return item

    for first, second in combinations(edges, 2):
        if first[0] == second[0] or first[2:] != second[2:]:
            continue
        if first[1].intersects(second[1]) or first[1].distance(second[1]) <= SITE_GEOMETRY_TOLERANCE_M:
            left, right = find(first[0]), find(second[0])
            if left != right:
                parents[max(left, right)] = min(left, right)
    return len({find(edge[0]) for edge in edges})


__all__ = [
    "build_road_surfaces",
    "build_site_road_surfaces",
    "count_road_components",
    "count_site_road_components",
    "derive_external_road_contacts",
    "derive_land_block_contacts",
    "external_connection_count",
    "unconnected_contact_reason",
]
