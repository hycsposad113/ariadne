"""Deterministic G2 road and public-space skeleton generation.

The geometry input object is the local resolver boundary: the caller supplies
resolved, hash-linked geometries from G0/A2 contracts. Generation itself is
pure and does not load sources, write project state, or infer approvals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from heapq import heappop, heappush
from itertools import combinations
import math
from typing import Iterable, Literal

import shapely
from shapely import affinity
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, Polygon, mapping, shape
from shapely.ops import nearest_points, polygonize, unary_union

from urban_design.generation.contracts import (
    AccessPolicy,
    AccessStatus,
    AreaGeometryValue,
    ConnectionRecord,
    FrozenRef,
    GenerationContext,
    LinearGeometryValue,
    OpenSpaceArtifact,
    PointGeometryValue,
    SkeletonArtifact,
    SkeletonEdge,
    SkeletonNode,
    StageStatus,
    StrategySpec,
    ValidationCheck,
    ValidationReport,
)
from urban_design.generation.hashing import generation_context_digest, semantic_digest
from urban_design.morphology.contracts import RoadSegment
from urban_design.morphology.streets import count_road_components


_TOLERANCE_M = 1e-6
_SUPPORTED_FAMILIES = frozenset({"CONNECTED_GRID", "CENTRAL_COMMON", "LINEAR_SPINE"})


class SkeletonBuildError(ValueError):
    """A strategy could not produce a valid skeleton; failure stays inspectable."""

    status = "BLOCKED"

    def __init__(self, message: str, *, strategy_id: str, failure_geometry=None):
        super().__init__(message)
        self.strategy_id = strategy_id
        self.failure_geometry = failure_geometry


@dataclass(frozen=True)
class SkeletonEntry:
    """A source-derived external contact; unknown levels never connect at grade."""

    id: str
    point: Point
    level: int | None
    source_refs: tuple[FrozenRef, ...]
    bridge: bool = False
    tunnel: bool = False
    access_status: AccessStatus = AccessStatus.UNKNOWN

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("entry contact id must be non-empty")
        if not isinstance(self.point, Point) or self.point.is_empty or not self.point.is_valid:
            raise ValueError("entry contact geometry must be a valid point")
        if self.level is not None and (isinstance(self.level, bool) or not isinstance(self.level, int)):
            raise ValueError("entry contact level must be an integer or unknown")
        if not isinstance(self.bridge, bool) or not isinstance(self.tunnel, bool):
            raise ValueError("entry bridge and tunnel flags must be boolean")
        if not self.source_refs:
            raise ValueError("entry contacts require source references")


@dataclass(frozen=True)
class SkeletonInputs:
    """Resolved A2/G0 geometry and frozen references for one exploration run."""

    site_geometry: object
    entry_contacts: tuple[SkeletonEntry, ...]
    water_geometries: tuple = ()
    retained_geometries: tuple = ()
    no_build_geometries: tuple = ()
    collector_exclusion_geometries: tuple = ()
    source_refs: tuple[FrozenRef, ...] = ()
    retained_geometry_refs: tuple[FrozenRef, ...] = ()
    spine_entry_id: str | None = None
    spine_target: Point | None = None
    spine_target_ref: FrozenRef | None = None
    crs: str = "EPSG:28992"

    def __post_init__(self) -> None:
        if self.crs != "EPSG:28992":
            raise ValueError("G2 skeleton geometry requires EPSG:28992 metres")
        if (
            self.site_geometry.geom_type not in {"Polygon", "MultiPolygon"}
            or self.site_geometry.is_empty
            or not self.site_geometry.is_valid
            or not math.isfinite(float(self.site_geometry.area))
            or self.site_geometry.area <= 0
        ):
            raise ValueError("site geometry must be a valid positive-area polygon or multipolygon")
        if not all(math.isfinite(float(value)) for row in shapely.get_coordinates(self.site_geometry) for value in row):
            raise ValueError("site geometry coordinates must be finite")
        contact_ids = [entry.id for entry in self.entry_contacts]
        if len(contact_ids) != len(set(contact_ids)):
            raise ValueError("entry contact IDs must be unique")
        for entry in self.entry_contacts:
            if self.site_geometry.boundary.distance(entry.point) > _TOLERANCE_M:
                raise ValueError(f"entry contact {entry.id!r} is not on the site exterior")
        for label, collection in (
            ("water", self.water_geometries),
            ("retained", self.retained_geometries),
            ("no-build", self.no_build_geometries),
            ("collector-exclusion", self.collector_exclusion_geometries),
        ):
            for geometry in collection:
                if (
                    geometry.geom_type not in {"Polygon", "MultiPolygon"}
                    or geometry.is_empty
                    or not geometry.is_valid
                    or not math.isfinite(float(geometry.area))
                    or geometry.area <= 0
                ):
                    raise ValueError(f"{label} obstacles must be valid positive-area polygons")
        if (self.spine_target is None) != (self.spine_target_ref is None):
            raise ValueError("spine target geometry and its frozen reference must be supplied together")
        if self.spine_target is not None:
            if self.spine_target.is_empty or not self.spine_target.is_valid:
                raise ValueError("spine target must be a valid point")
            if not self.site_geometry.buffer(_TOLERANCE_M).covers(self.spine_target):
                raise ValueError("spine target must be inside the study area")
            if self.spine_entry_id is None:
                raise ValueError("spine target requires an explicit entry contact id")
        if self.spine_entry_id is not None and self.spine_entry_id not in set(contact_ids):
            raise ValueError("spine entry contact id must resolve to an input contact")
        if not self.source_refs:
            raise ValueError("skeleton inputs require frozen source references")
        if self.retained_geometries and not self.retained_geometry_refs:
            raise ValueError("retained obstacle geometries require frozen retained references")
        if len(self.retained_geometries) != len(self.retained_geometry_refs):
            raise ValueError("retained geometries and their frozen references must align")


@dataclass(frozen=True)
class SkeletonBuildResult:
    status: Literal["READY"]
    artifact: SkeletonArtifact
    connected_components: int


@dataclass(frozen=True)
class _RoadPath:
    geometry: LineString
    road_class: str
    width_parameter: str


def _polygon_parts(geometry) -> tuple[Polygon, ...]:
    if geometry.is_empty:
        return ()
    if geometry.geom_type == "Polygon":
        return (geometry,)
    if geometry.geom_type == "MultiPolygon":
        return tuple(geometry.geoms)
    if geometry.geom_type == "GeometryCollection":
        return tuple(part for item in geometry.geoms for part in _polygon_parts(item))
    return ()


def _line_parts(geometry) -> tuple[LineString, ...]:
    if geometry.is_empty:
        return ()
    if geometry.geom_type == "LineString":
        return (geometry,) if geometry.length > _TOLERANCE_M else ()
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        return tuple(part for item in geometry.geoms for part in _line_parts(item))
    return ()


def _method_parameter(context: GenerationContext, parameter_id: str, *, allow_zero: bool = False) -> float:
    if parameter_id not in context.method_parameters:
        raise ValueError(f"required G2 method parameter {parameter_id!r} is missing")
    value = context.method_parameters[parameter_id]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"G2 method parameter {parameter_id!r} must be finite numeric metres")
    result = float(value)
    if result < 0 or (result == 0 and not allow_zero):
        raise ValueError(f"G2 method parameter {parameter_id!r} must be positive")
    if parameter_id.endswith("_m") and context.coordinate_unit != "m":
        raise ValueError(f"G2 method parameter {parameter_id!r} requires metre units")
    return result


def _parameter_reference(parameter_id: str, value: float) -> FrozenRef:
    digest = semantic_digest({"parameter_id": parameter_id, "value": value})
    return FrozenRef(id=f"method-parameter:{parameter_id}", sha256=digest, kind="METHOD_PARAMETER")


def _all_input_refs(context: GenerationContext, inputs: SkeletonInputs) -> tuple[FrozenRef, ...]:
    refs = (
        context.workspace_ref,
        context.analysis_ref,
        context.brief_ref,
        *context.source_refs,
        *context.constraint_refs,
        *inputs.source_refs,
        *inputs.retained_geometry_refs,
        *(ref for contact in inputs.entry_contacts for ref in contact.source_refs),
        *((inputs.spine_target_ref,) if inputs.spine_target_ref else ()),
    )
    unique = {(ref.id, ref.sha256, ref.kind): ref for ref in refs}
    return tuple(unique[key] for key in sorted(unique))


def _obstacles(inputs: SkeletonInputs):
    parts = []
    for geometry in (*inputs.water_geometries, *inputs.retained_geometries, *inputs.no_build_geometries):
        clipped = geometry.intersection(inputs.site_geometry)
        if not clipped.is_empty:
            parts.append(clipped)
    return unary_union(parts) if parts else GeometryCollection()


def _eligible_entries(inputs: SkeletonInputs, strategy_id: str) -> tuple[SkeletonEntry, ...]:
    eligible = tuple(
        entry
        for entry in inputs.entry_contacts
        if entry.level == 0 and not entry.bridge and not entry.tunnel
    )
    if not eligible:
        details = "no eligible at-grade entry contact"
        if any(entry.level is None for entry in inputs.entry_contacts):
            details += "; source level is unknown and is not treated as connected"
        elif inputs.entry_contacts:
            details += "; grade-separated contacts have no generated vertical transition"
        raise SkeletonBuildError(
            details,
            strategy_id=strategy_id,
            failure_geometry=inputs.site_geometry.boundary,
        )
    for component in _polygon_parts(inputs.site_geometry):
        if not any(component.boundary.distance(entry.point) <= _TOLERANCE_M for entry in eligible):
            raise SkeletonBuildError(
                "each disconnected land component requires an eligible source contact",
                strategy_id=strategy_id,
                failure_geometry=component,
            )
    return tuple(sorted(eligible, key=lambda entry: entry.id))


def _segment_clear(line: LineString, *, site, obstacles, minimum_clearance_m: float) -> bool:
    if line.is_empty or line.length <= _TOLERANCE_M or not site.covers(line):
        return False
    if not obstacles.is_empty and line.distance(obstacles) < minimum_clearance_m - _TOLERANCE_M:
        return False
    return True


def _snap_boundary_point(point: Point, site) -> Point:
    if site.covers(point):
        return point
    snapped = nearest_points(site.boundary, point)[0]
    return snapped if snapped.distance(point) <= _TOLERANCE_M else point


def _ring_vertices(geometry) -> Iterable[Point]:
    if geometry.is_empty:
        return ()
    result: list[Point] = []
    for polygon in _polygon_parts(geometry):
        rings = (polygon.exterior, *polygon.interiors)
        for ring in rings:
            result.extend(Point(x, y) for x, y, *_ in ring.coords[:-1])
    return tuple(result)


def _route(start: Point, goal: Point, *, site, obstacles, minimum_clearance_m: float, strategy_id: str) -> tuple[LineString, ...]:
    start = _snap_boundary_point(start, site)
    goal = _snap_boundary_point(goal, site)
    if start.distance(goal) <= _TOLERANCE_M:
        return ()
    direct = LineString((start, goal))
    if _segment_clear(direct, site=site, obstacles=obstacles, minimum_clearance_m=minimum_clearance_m):
        return (direct,)

    nodes_by_key: dict[tuple[int, int], Point] = {}

    def add(point: Point) -> None:
        key = (round(point.x * 1_000_000), round(point.y * 1_000_000))
        if site.buffer(_TOLERANCE_M).covers(point):
            nodes_by_key.setdefault(key, point)

    add(start)
    add(goal)
    for point in _ring_vertices(site.buffer(-minimum_clearance_m, join_style="mitre")):
        add(point)
    if not obstacles.is_empty:
        safe_obstacle = obstacles.buffer(minimum_clearance_m, join_style="mitre")
        for point in _ring_vertices(safe_obstacle):
            if obstacles.distance(point) >= minimum_clearance_m - _TOLERANCE_M:
                add(point)

    nodes = tuple(nodes_by_key[key] for key in sorted(nodes_by_key))
    try:
        start_index = nodes.index(start)
        goal_index = nodes.index(goal)
    except ValueError:
        start_index = min(range(len(nodes)), key=lambda index: nodes[index].distance(start))
        goal_index = min(range(len(nodes)), key=lambda index: nodes[index].distance(goal))
    graph: list[list[tuple[float, int, LineString]]] = [[] for _ in nodes]
    for first_index, second_index in combinations(range(len(nodes)), 2):
        segment = LineString((nodes[first_index], nodes[second_index]))
        if not _segment_clear(segment, site=site, obstacles=obstacles, minimum_clearance_m=minimum_clearance_m):
            continue
        distance = float(segment.length)
        graph[first_index].append((distance, second_index, segment))
        graph[second_index].append((distance, first_index, LineString(tuple(segment.coords)[::-1])))

    queue: list[tuple[float, int]] = [(0.0, start_index)]
    distances = {start_index: 0.0}
    previous: dict[int, tuple[int, LineString]] = {}
    while queue:
        distance, current = heappop(queue)
        if distance != distances.get(current):
            continue
        if current == goal_index:
            break
        for edge_cost, neighbor, segment in graph[current]:
            candidate = distance + edge_cost
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                previous[neighbor] = (current, segment)
                heappush(queue, (candidate, neighbor))
    if goal_index not in distances:
        failure = unary_union([start, goal, obstacles]) if not obstacles.is_empty else unary_union([start, goal])
        raise SkeletonBuildError(
            "no width-clear visibility route connects the requested skeleton points",
            strategy_id=strategy_id,
            failure_geometry=failure,
        )
    segments: list[LineString] = []
    cursor = goal_index
    while cursor != start_index:
        prior, segment = previous[cursor]
        segments.append(segment)
        cursor = prior
    return tuple(reversed(segments))


def _route_to_geometry(source: Point, target_geometry, *, site, obstacles, width_m, clearance_m, road_class, width_parameter, strategy_id):
    target = nearest_points(source, target_geometry)[1]
    if road_class == "COMMON_APPROACH":
        # A 0.1 mm interface overlap survives the registered micrometre noding.
        center = target_geometry.centroid
        distance = target.distance(center)
        if distance > 0:
            target = Point(target.x + (center.x-target.x)*1e-4/distance,
                           target.y + (center.y-target.y)*1e-4/distance)
    segments = _route(
        source,
        target,
        site=site,
        obstacles=obstacles,
        minimum_clearance_m=width_m / 2.0 + clearance_m,
        strategy_id=strategy_id,
    )
    return [_RoadPath(segment, road_class, width_parameter) for segment in segments]


def _connect_components(paths: list[_RoadPath], *, site, obstacles, width_m, clearance_m, strategy_id) -> list[_RoadPath]:
    # Group connected linework, rather than atomic noded segments. Adjacent
    # atomic segments have distance zero and used to terminate this loop early.
    for _ in range(len(paths)):
        groups = []
        for path in paths:
            touching = [g for g in groups if any(line.intersects(path.geometry) for line in g)]
            merged = [path.geometry]
            for group in touching:
                merged.extend(group)
                groups.remove(group)
            groups.append(merged)
        if len(groups) <= 1:
            return paths
        first, second = min(combinations([unary_union(g) for g in groups], 2),
                            key=lambda pair: (pair[0].distance(pair[1]), pair[0].wkb_hex, pair[1].wkb_hex))
        start, goal = nearest_points(first, second)
        routes = _route(start, goal, site=site, obstacles=obstacles,
                        minimum_clearance_m=width_m / 2.0 + clearance_m, strategy_id=strategy_id)
        if not routes:
            raise SkeletonBuildError('disconnected grid cannot be joined', strategy_id=strategy_id,
                                     failure_geometry=unary_union([first, second]))
        paths.extend(_RoadPath(route, "LOCAL_CONNECTOR", "road_local_width_m") for route in routes)
    return paths


def _local_site_and_inputs(inputs: SkeletonInputs, angle: float):
    origin = inputs.site_geometry.centroid
    site = affinity.rotate(inputs.site_geometry, -angle, origin=origin)
    obstacles = _obstacles(inputs)
    obstacles = affinity.rotate(obstacles, -angle, origin=origin) if not obstacles.is_empty else obstacles
    entries = tuple(
        (entry, affinity.rotate(entry.point, -angle, origin=origin))
        for entry in inputs.entry_contacts
    )
    water = tuple(affinity.rotate(item.intersection(inputs.site_geometry), -angle, origin=origin) for item in inputs.water_geometries)
    return site, obstacles, entries, water


def _principal_angle(site) -> float:
    candidates = []
    for polygon in sorted(_polygon_parts(site), key=lambda item: (-item.area, item.wkb_hex)):
        coordinates = tuple(polygon.exterior.coords)
        for first, second in zip(coordinates, coordinates[1:]):
            dx, dy = second[0] - first[0], second[1] - first[1]
            length = math.hypot(dx, dy)
            if length > _TOLERANCE_M:
                angle = math.degrees(math.atan2(dy, dx))
                while angle >= 90.0:
                    angle -= 180.0
                while angle < -90.0:
                    angle += 180.0
                candidates.append((length, angle))
    if not candidates:
        return 0.0
    longest = max(length for length, _angle in candidates)
    return min(angle for length, angle in candidates if math.isclose(length, longest, rel_tol=0.0, abs_tol=_TOLERANCE_M))


def _rotate_paths(paths: Iterable[_RoadPath], *, origin, angle) -> list[_RoadPath]:
    return [
        _RoadPath(affinity.rotate(path.geometry, angle, origin=origin), path.road_class, path.width_parameter)
        for path in paths
    ]


def _grid_paths_in_local_coordinates(context, inputs, entries, *, spacing_m, local_width_m, collector_width_m, clearance_m, strategy_id, angle, origin):
    site, obstacles, local_contacts, _water = _local_site_and_inputs(inputs, angle)
    local_width = _method_parameter(context, "road_local_width_m")
    safe_site = site.buffer(-local_width / 2.0, join_style="mitre")
    if not obstacles.is_empty:
        safe_site = safe_site.difference(obstacles.buffer(local_width / 2.0 + clearance_m, join_style="mitre"))
    paths: list[_RoadPath] = []
    for component in _polygon_parts(site):
        domain = safe_site.intersection(component)
        if domain.is_empty:
            raise SkeletonBuildError(
                "road width and frozen obstacles leave no safe grid domain",
                strategy_id=strategy_id,
                failure_geometry=component,
            )
        minx, miny, maxx, maxy = component.bounds
        xs = [x for x in _positions(minx, maxx, spacing_m) if minx + _TOLERANCE_M < x < maxx - _TOLERANCE_M]
        ys = [y for y in _positions(miny, maxy, spacing_m) if miny + _TOLERANCE_M < y < maxy - _TOLERANCE_M]
        if not xs:
            xs = [(minx + maxx) / 2.0]
        if not ys:
            ys = [(miny + maxy) / 2.0]
        component_paths: list[_RoadPath] = []
        for x in xs:
            for segment in _line_parts(LineString([(x, miny - 1.0), (x, maxy + 1.0)]).intersection(domain)):
                component_paths.append(_RoadPath(segment, "LOCAL", "road_local_width_m"))
        for y in ys:
            for segment in _line_parts(LineString([(minx - 1.0, y), (maxx + 1.0, y)]).intersection(domain)):
                component_paths.append(_RoadPath(segment, "LOCAL", "road_local_width_m"))
        component_paths = _connect_components(
            component_paths,
            site=component,
            obstacles=obstacles,
            width_m=local_width_m,
            clearance_m=clearance_m,
            strategy_id=strategy_id,
        )
        paths.extend(component_paths)
    if not paths:
        raise SkeletonBuildError("registered grid spacing produced no viable road lines", strategy_id=strategy_id, failure_geometry=site)
    for entry, local_point in local_contacts:
        if entry.level != 0 or entry.bridge or entry.tunnel:
            continue
        network = unary_union([path.geometry for path in paths])
        paths.extend(
            _route_to_geometry(
                local_point,
                network,
                site=site,
                obstacles=obstacles,
                width_m=collector_width_m,
                clearance_m=clearance_m,
                road_class="CONNECTOR",
                width_parameter="road_collector_width_m",
                strategy_id=strategy_id,
            )
        )
    return _rotate_paths(paths, origin=origin, angle=angle)


def _grid_paths(context, inputs, entries, *, spacing_m, local_width_m, collector_width_m, clearance_m, strategy_id):
    angle = context.method_parameters.get('grid_alignment_deg', _principal_angle(inputs.site_geometry))
    if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(angle):
        raise ValueError('grid alignment requires finite degrees')
    origin = inputs.site_geometry.centroid
    try:
        return _grid_paths_in_local_coordinates(
            context,
            inputs,
            entries,
            spacing_m=spacing_m,
            local_width_m=local_width_m,
            collector_width_m=collector_width_m,
            clearance_m=clearance_m,
            strategy_id=strategy_id,
            angle=angle,
            origin=origin,
        )
    except SkeletonBuildError as error:
        failure = error.failure_geometry
        world_failure = affinity.rotate(failure, angle, origin=origin) if failure is not None else inputs.site_geometry
        raise SkeletonBuildError(str(error), strategy_id=strategy_id, failure_geometry=world_failure) from error


def _positions(lower: float, upper: float, step: float) -> tuple[float, ...]:
    first = math.floor(lower / step) * step + step
    values: list[float] = []
    cursor = first
    while cursor < upper:
        values.append(cursor)
        cursor += step
    return tuple(values)


def _grid_open_spaces(paths, *, site, obstacles, width_m, clearance_m, diameter_m, strategy_id):
    linework = unary_union([path.geometry for path in paths])
    faces = tuple(
        face
        for face in polygonize(unary_union([linework, site.boundary]))
        if face.area > diameter_m * diameter_m and site.buffer(_TOLERANCE_M).covers(face)
    )
    road_surfaces = unary_union(
        [path.geometry.buffer(width_m / 2.0, cap_style="flat", join_style="mitre").intersection(site) for path in paths]
    )
    candidates = []
    for face in faces:
        center = face.representative_point()
        space = center.buffer(diameter_m / 2.0)
        if not face.covers(space) or road_surfaces.intersects(space):
            continue
        if not obstacles.is_empty and space.distance(obstacles) < clearance_m - _TOLERANCE_M:
            continue
        candidates.append(space)
    candidates.sort(key=lambda item: (-item.area, item.centroid.distance(site.centroid), item.wkb_hex))
    if not candidates:
        raise SkeletonBuildError(
            "grid has no polygonized open-space cell large enough for a primary node",
            strategy_id=strategy_id,
            failure_geometry=site,
        )
    return tuple(candidates[:3])


def _central_open_spaces(site, obstacles, *, diameter_m, approach_width_m, clearance_m, strategy_id):
    radius = diameter_m / 2.0
    centers = site.buffer(-radius, join_style="mitre")
    if not obstacles.is_empty:
        centers = centers.difference(
            obstacles.buffer(radius + approach_width_m / 2.0 + clearance_m, join_style="mitre")
        )
    spaces: list[Polygon] = []
    for component in _polygon_parts(site):
        component_centers = centers.intersection(component)
        if component_centers.is_empty:
            raise SkeletonBuildError(
                "no continuous safe area can contain the required central common",
                strategy_id=strategy_id,
                failure_geometry=component,
            )
        candidate = nearest_points(component.centroid, component_centers)[1]
        space = candidate.buffer(radius)
        if not component.buffer(_TOLERANCE_M).covers(space) or (not obstacles.is_empty and space.intersection(obstacles).area > _TOLERANCE_M):
            candidate = component_centers.representative_point()
            space = candidate.buffer(radius)
        if not component.buffer(_TOLERANCE_M).covers(space) or (not obstacles.is_empty and space.intersection(obstacles).area > _TOLERANCE_M):
            raise SkeletonBuildError(
                "central common candidate fails site or obstacle containment",
                strategy_id=strategy_id,
                failure_geometry=space,
            )
        spaces.append(space)
    return tuple(spaces)


def _central_paths(context, inputs, entries, *, diameter_m, local_width_m, collector_width_m, clearance_m, strategy_id):
    spaces = _central_open_spaces(
        inputs.site_geometry,
        _obstacles(inputs),
        diameter_m=diameter_m,
        approach_width_m=collector_width_m,
        clearance_m=clearance_m,
        strategy_id=strategy_id,
    )
    obstacles = _obstacles(inputs)
    paths: list[_RoadPath] = []
    for entry in entries:
        component = next((part for part in _polygon_parts(inputs.site_geometry) if part.boundary.distance(entry.point) <= _TOLERANCE_M), None)
        if component is None:
            raise SkeletonBuildError("entry contact could not be assigned to a land component", strategy_id=strategy_id, failure_geometry=entry.point)
        space = next((item for item in spaces if component.buffer(_TOLERANCE_M).covers(item)), None)
        if space is None:
            raise SkeletonBuildError("central common does not cover the entry's land component", strategy_id=strategy_id, failure_geometry=component)
        paths.extend(
            _route_to_geometry(
                entry.point,
                space.boundary,
                site=component,
                obstacles=obstacles,
                width_m=collector_width_m,
                clearance_m=clearance_m,
                road_class="COMMON_APPROACH",
                width_parameter="road_collector_width_m",
                strategy_id=strategy_id,
            )
        )
    return paths, spaces


def _waterfront_target(entry: SkeletonEntry, inputs: SkeletonInputs, *, distance_m: float):
    water = _obstacles(SkeletonInputs(
        site_geometry=inputs.site_geometry,
        entry_contacts=inputs.entry_contacts,
        water_geometries=inputs.water_geometries,
        source_refs=inputs.source_refs,
    ))
    if water.is_empty:
        return None
    target_band = water.buffer(distance_m, join_style="mitre").boundary
    return nearest_points(entry.point, target_band)[1]


def _linear_paths(context, strategy, inputs, entries, *, local_width_m, collector_width_m, open_width_m, clearance_m):
    strategy_id = strategy.strategy_id
    entry_id = inputs.spine_entry_id
    entry = next((item for item in entries if item.id == entry_id), None)
    if entry is None:
        raise SkeletonBuildError(
            "LINEAR_SPINE requires an explicitly selected eligible spine entry contact",
            strategy_id=strategy_id,
            failure_geometry=inputs.site_geometry.boundary,
        )
    target = inputs.spine_target
    if strategy.program_policy.get("spine_target") == "WATERFRONT":
        target = _waterfront_target(entry, inputs, distance_m=collector_width_m / 2.0 + clearance_m)
        if target is None:
            raise SkeletonBuildError(
                "A2 waterfront preference has no frozen water geometry to target",
                strategy_id=strategy_id,
                failure_geometry=entry.point,
            )
    elif target is None:
        raise SkeletonBuildError(
            "LINEAR_SPINE requires an explicit user-selected entry-to-target axis",
            strategy_id=strategy_id,
            failure_geometry=entry.point,
        )
    obstacle = _obstacles(inputs)
    spine_parts = _route(
        entry.point,
        target,
        site=inputs.site_geometry,
        obstacles=obstacle,
        minimum_clearance_m=collector_width_m / 2.0 + clearance_m,
        strategy_id=strategy_id,
    )
    if not spine_parts:
        raise SkeletonBuildError("linear spine axis collapsed to zero length", strategy_id=strategy_id, failure_geometry=entry.point)
    paths = [_RoadPath(part, "SPINE", "road_collector_width_m") for part in spine_parts]
    spine = unary_union(spine_parts)
    if spine.geom_type != "LineString":
        spine = max(_line_parts(spine), key=lambda item: item.length)

    public_spaces = []
    offset_distance = collector_width_m / 2.0 + open_width_m / 2.0 + clearance_m
    for side in ("left", "right"):
        offset = spine.parallel_offset(offset_distance, side, join_style="mitre")
        offset_parts = _line_parts(offset)
        if not offset_parts:
            continue
        candidate = max(offset_parts, key=lambda item: item.length).buffer(open_width_m / 2.0, cap_style="flat", join_style="mitre")
        if not inputs.site_geometry.buffer(_TOLERANCE_M).covers(candidate):
            candidate = candidate.intersection(inputs.site_geometry)
        if candidate.is_empty or candidate.area <= _TOLERANCE_M:
            continue
        if not obstacle.is_empty and candidate.intersection(obstacle).area > _TOLERANCE_M:
            continue
        road_surface = unary_union([path.geometry.buffer(collector_width_m / 2.0, cap_style="flat", join_style="mitre") for path in paths])
        if road_surface.intersection(candidate).area > _TOLERANCE_M:
            continue
        public_spaces = [candidate]
        break
    if not public_spaces:
        raise SkeletonBuildError(
            "linear spine has no safe adjacent public-space corridor",
            strategy_id=strategy_id,
            failure_geometry=spine,
        )

    for other in entries:
        if other.id == entry.id:
            continue
        paths.extend(
            _route_to_geometry(
                other.point,
                spine,
                site=inputs.site_geometry,
                obstacles=obstacle,
                width_m=local_width_m,
                clearance_m=clearance_m,
                road_class="SPINE_BRANCH",
                width_parameter="road_local_width_m",
                strategy_id=strategy_id,
            )
        )
    return paths, tuple(public_spaces)


def _linear_geometry_value(geometry: LineString) -> LinearGeometryValue:
    payload = mapping(geometry)
    return LinearGeometryValue(type=payload["type"], coordinates=payload["coordinates"], crs="EPSG:28992")


def _south_strip_collector(context, strategy, inputs, paths, spaces, width_m, clearance_m):
    """Founder-authorised southern arm, sampled in the shared grid frame.

    Select the longest width-clear horizontal section in the southern half.
    Sampling is relative to the site bounds (translation invariant), at 4 m
    intervals. Equal-length sections prefer the centre of the southern half,
    leaving developable depth on both sides rather than hugging the boundary.
    Obstacle buffers include retained
    setback and waterfront protection before allowing for the road half-width.
    Both endpoints route to the original network, never to another new spur.
    """
    angle = context.method_parameters.get('grid_alignment_deg', _principal_angle(inputs.site_geometry))
    origin = inputs.site_geometry.centroid
    rotate = lambda g: affinity.rotate(g, -angle, origin=origin)
    site = rotate(inputs.site_geometry)
    protected = unary_union([
        *[g.buffer(3, join_style='mitre') for g in inputs.retained_geometries],
        *inputs.no_build_geometries, *inputs.water_geometries, *inputs.collector_exclusion_geometries, *spaces,
    ])
    protected = rotate(protected)
    half = width_m / 2 + clearance_m
    domain = site.buffer(-half, join_style='mitre').difference(protected.buffer(half, join_style='mitre'))
    minx, miny, maxx, maxy = site.bounds
    upper = (miny + maxy) / 2
    sections = []
    y = miny + half
    while y <= upper:
        sections.extend(_line_parts(LineString([(minx, y), (maxx, y)]).intersection(domain)))
        y += 4
    if not sections:
        raise SkeletonBuildError('no safe south-strip collector section', strategy_id=strategy.strategy_id, failure_geometry=domain)
    longest = max(g.length for g in sections)
    tied = [g for g in sections if abs(g.length - longest) <= _TOLERANCE_M]
    collector = min(tied, key=lambda g: (abs(g.bounds[1] - (miny + upper) / 2), g.bounds[1], g.wkb_hex))
    routing_site = site.buffer(-half, join_style='mitre')
    network = rotate(unary_union([p.geometry for p in paths])).intersection(routing_site).difference(protected.buffer(half, join_style='mitre'))
    if network.is_empty:
        raise SkeletonBuildError('south-strip collector has no safe network attachment', strategy_id=strategy.strategy_id, failure_geometry=collector)
    additions = [_RoadPath(collector, 'SOUTH_STRIP_COLLECTOR', 'road_collector_width_m')]
    for coordinate in (collector.coords[0], collector.coords[-1]):
        endpoint = Point(coordinate)
        # Try the nearest point on each original edge, in deterministic order.
        targets = sorted((nearest_points(endpoint, g)[1] for g in _line_parts(network)),
                         key=lambda p: (p.distance(endpoint), p.x, p.y))
        connected = False
        for target in targets:
            try:
                routes = _route(endpoint, target, site=routing_site, obstacles=protected,
                                minimum_clearance_m=half, strategy_id=strategy.strategy_id)
            except SkeletonBuildError:
                continue
            additions.extend(_RoadPath(g, 'SOUTH_STRIP_CONNECTOR', 'road_collector_width_m') for g in routes)
            connected = True
            break
        if not connected:
            raise SkeletonBuildError('south-strip collector endpoint cannot attach safely', strategy_id=strategy.strategy_id, failure_geometry=endpoint)
    return [*paths, *_rotate_paths(additions, origin=origin, angle=angle)]


def _area_geometry_value(geometry) -> AreaGeometryValue:
    payload = mapping(geometry)
    return AreaGeometryValue(type=payload["type"], coordinates=payload["coordinates"], crs="EPSG:28992")


def _noded_paths(paths: list[_RoadPath], *, site, obstacles, strategy_id: str, grid_size=0):
    linework = shapely.union_all([path.geometry for path in paths], grid_size=grid_size)
    atomic = _line_parts(linework)
    if not atomic:
        raise SkeletonBuildError("strategy produced no non-collapsed road edges", strategy_id=strategy_id, failure_geometry=site)
    atomic_paths: list[tuple[LineString, str, str]] = []
    for line in atomic:
        midpoint = line.interpolate(0.5, normalized=True)
        matches = [path for path in paths if path.geometry.distance(midpoint) <= _TOLERANCE_M]
        if not matches:
            raise SkeletonBuildError("noded edge lost its road-class provenance", strategy_id=strategy_id, failure_geometry=line)
        path = max(matches, key=lambda item: (item.width_parameter == "road_collector_width_m", item.road_class))
        atomic_paths.append((line, path.road_class, path.width_parameter))
    return tuple(sorted(atomic_paths, key=lambda item: (item[0].wkb_hex, item[1], item[2])))


def _effective_component_count(road_geometries, road_levels, open_geometries) -> int:
    """Count same-level roads connected by their shared public-space interface."""

    geometries = list(road_geometries)
    levels: list[int | None] = list(road_levels)
    for space in open_geometries:
        if any(space.intersects(road) for road in road_geometries):
            geometries.append(space)
            levels.append(None)
    parents = list(range(len(geometries)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    for first in range(len(geometries)):
        for second in range(first + 1, len(geometries)):
            if levels[first] is not None and levels[second] is not None and levels[first] != levels[second]:
                continue
            if geometries[first].intersects(geometries[second]):
                union(first, second)
    return len({find(index) for index in range(len(geometries)) if levels[index] is not None})


def _artifact(context, strategy, inputs, paths, open_geometries, *, timestamp, local_width_m, collector_width_m):
    strategy_id = strategy.strategy_id
    grid_size = context.method_parameters.get('noding_grid_m', 0)
    if grid_size not in (0, 1e-6):
        raise ValueError('only exact or registered 1 micrometre noding is supported')
    if grid_size:
        open_geometries = tuple(shapely.set_precision(g, grid_size) for g in open_geometries)
    atomic = _noded_paths(paths, site=inputs.site_geometry, obstacles=_obstacles(inputs), strategy_id=strategy_id, grid_size=grid_size)
    road_surfaces = []
    nodes_by_key: dict[tuple[int, int, int], SkeletonNode] = {}
    edge_payloads = []
    parameter_values = {
        "road_local_width_m": local_width_m,
        "road_collector_width_m": collector_width_m,
        "access_lane_width_m": context.method_parameters.get("access_lane_width_m", 4.5),
    }
    width_refs = {key: _parameter_reference(key, value) for key, value in parameter_values.items()}
    input_refs = _all_input_refs(context, inputs)
    for line, road_class, width_parameter in atomic:
        width = parameter_values[width_parameter]
        surface = line.buffer(width / 2.0, cap_style="flat", join_style="mitre").intersection(inputs.site_geometry)
        if not _obstacles(inputs).is_empty and surface.intersection(_obstacles(inputs)).area > _TOLERANCE_M:
            raise SkeletonBuildError("road half-width buffer intersects a frozen obstacle", strategy_id=strategy_id, failure_geometry=surface.intersection(_obstacles(inputs)))
        road_surfaces.append(surface)
        coordinates = tuple(line.coords)
        endpoints = (Point(coordinates[0]), Point(coordinates[-1]))
        node_ids = []
        for point in endpoints:
            key = (round(point.x * 1_000_000), round(point.y * 1_000_000), 0)
            if key not in nodes_by_key:
                source_refs = tuple(
                    ref
                    for entry in inputs.entry_contacts
                    if entry.point.distance(point) <= _TOLERANCE_M
                    for ref in entry.source_refs
                )
                node_payload = {"point": point, "level": 0}
                node_id = "node-" + semantic_digest(node_payload).split(":", 1)[1][:16]
                nodes_by_key[key] = SkeletonNode(
                    id=node_id,
                    geometry=PointGeometryValue(type="Point", coordinates=(point.x, point.y)),
                    level=0,
                    access=AccessStatus.UNKNOWN.value,
                    source_refs=source_refs,
                )
            node_ids.append(nodes_by_key[key].id)
        edge_hash = semantic_digest({"geometry": line, "road_class": road_class, "level": 0}).split(":", 1)[1][:16]
        edge_payloads.append(
            SkeletonEdge(
                id=f"road:{road_class.lower()}:{edge_hash}",
                from_node_id=node_ids[0],
                to_node_id=node_ids[1],
                geometry=_linear_geometry_value(line),
                level=0,
                access=AccessStatus.UNKNOWN.value,
                width_m=width,
                width_ref=width_refs[width_parameter],
                source_refs=input_refs,
            )
        )

    open_spaces = []
    for geometry in open_geometries:
        if geometry.is_empty or geometry.area <= 0 or not inputs.site_geometry.buffer(_TOLERANCE_M).covers(geometry):
            raise SkeletonBuildError("primary open space is empty or outside the site", strategy_id=strategy_id, failure_geometry=geometry)
        if not _obstacles(inputs).is_empty and geometry.intersection(_obstacles(inputs)).area > _TOLERANCE_M:
            raise SkeletonBuildError("primary open space intersects a frozen obstacle", strategy_id=strategy_id, failure_geometry=geometry.intersection(_obstacles(inputs)))
        open_spaces.append(
            OpenSpaceArtifact(
                id="open-space-" + semantic_digest(geometry).split(":", 1)[1][:16],
                geometry=_area_geometry_value(geometry),
                access_policy=AccessPolicy(
                    status=AccessStatus.UNKNOWN,
                    reason="public access has not been verified by the frozen source package",
                ),
            )
        )
    if not open_spaces:
        raise SkeletonBuildError("strategy produced no primary public-space geometry", strategy_id=strategy_id, failure_geometry=inputs.site_geometry)

    edge_geometries = tuple(shape(edge.geometry.model_dump(exclude={"crs"})) for edge in edge_payloads)
    network = unary_union(edge_geometries)
    road_segments = tuple(
        RoadSegment(f"{strategy_id}-{index}", geometry=line, layer=edge.level)
        for index, (edge, line) in enumerate(zip(edge_payloads, edge_geometries))
    )
    road_component_count = count_road_components(road_segments)
    component_count = _effective_component_count(
        edge_geometries,
        tuple(edge.level for edge in edge_payloads),
        tuple(open_geometries),
    )
    components = _polygon_parts(inputs.site_geometry)
    entry_linked = all(
        any(
            component.boundary.distance(entry.point) <= _TOLERANCE_M
            and any(line.distance(entry.point) <= _TOLERANCE_M for line in edge_geometries)
            for entry in inputs.entry_contacts
            if entry.level == 0 and not entry.bridge and not entry.tunnel
        )
        for component in components
    )
    if component_count != len(components) or not entry_linked:
        raise SkeletonBuildError(
            "generated skeleton does not retain one connected network per disconnected land component",
            strategy_id=strategy_id,
            failure_geometry=network,
        )

    connections = []
    network_nodes = tuple(nodes_by_key.values())
    for entry in inputs.entry_contacts:
        if entry.level != 0 or entry.bridge or entry.tunnel:
            continue
        nearest_node = min(network_nodes, key=lambda node: shape(node.geometry.model_dump(exclude={"crs"})).distance(entry.point))
        contact_id = "entry-contact-" + semantic_digest({"entry_id": entry.id, "point": entry.point}).split(":", 1)[1][:16]
        contact_node = SkeletonNode(
            id=contact_id,
            geometry=PointGeometryValue(type="Point", coordinates=(entry.point.x, entry.point.y)),
            level=0,
            access=AccessStatus.UNKNOWN.value,
            source_refs=entry.source_refs,
        )
        nodes_by_key[(round(entry.point.x * 1_000_000), round(entry.point.y * 1_000_000), 1)] = contact_node
        connections.append(
            ConnectionRecord(
                id=f"proposed-entry-{entry.id}",
                from_node_id=contact_node.id,
                to_node_id=nearest_node.id,
                level=0,
                status="PROPOSED_SOURCE_CONTACT_PUBLIC_ACCESS_UNKNOWN",
                source_refs=entry.source_refs,
            )
        )

    context_hash = generation_context_digest(context)
    artifact_seed = context.seed
    artifact_id = "skeleton-" + semantic_digest(
        {"context_hash": context_hash, "strategy_id": strategy_id, "algorithm_version": "g2-skeleton-v1"}
    ).split(":", 1)[1][:16]
    unknowns = [
        "No approved ConstraintSet is applied; geometry is an exploratory candidate.",
        "Source road contacts do not establish legal public access or right of way.",
    ]
    unknowns.extend(
        f"Entry contact {entry.id!r} has unknown level and was not connected."
        for entry in inputs.entry_contacts
        if entry.level is None
    )
    unknowns.extend(
        f"Entry contact {entry.id!r} is grade-separated and has no generated vertical transition."
        for entry in inputs.entry_contacts
        if entry.level != 0 or entry.bridge or entry.tunnel
    )
    validation = ValidationReport(
        geometry_status=StageStatus.PASS,
        topology_status=StageStatus.PASS,
        constraint_status=StageStatus.UNKNOWN,
        checks=(
            ValidationCheck(check_id="valid-site-and-buffered-roads", status=StageStatus.PASS, detail="All emitted road surfaces are within the site and clear of supplied water/building/no-build masks."),
            ValidationCheck(check_id="same-level-connectivity", status=StageStatus.PASS, detail=f"{road_component_count} road component(s), joined by intersecting primary public spaces where present, form {component_count} same-level component(s) for {len(components)} disconnected land component(s)."),
            ValidationCheck(check_id="primary-open-space", status=StageStatus.PASS, detail=f"{len(open_spaces)} primary open-space geometry item(s) were checked against site and obstacle masks."),
            ValidationCheck(check_id="public-access", status=StageStatus.UNKNOWN, detail="Public access is not inferred from geometry or source-road contact."),
        ),
        unknowns=tuple(unknowns),
        failures=(),
    )
    artifact = SkeletonArtifact(
        artifact_id=artifact_id,
        context_hash=context_hash,
        input_refs=input_refs,
        seed=artifact_seed,
        algorithm_version="g2-skeleton-v1",
        method=strategy.registered_method,
        assumptions=context.assumptions,
        created_at=timestamp,
        nodes=tuple(sorted(nodes_by_key.values(), key=lambda node: node.id)),
        edges=tuple(sorted(edge_payloads, key=lambda edge: edge.id)),
        primary_open_spaces=tuple(open_spaces),
        retained_geometry_refs=inputs.retained_geometry_refs,
        connections=tuple(connections),
        validation=validation,
    )
    return SkeletonBuildResult(status="READY", artifact=artifact, connected_components=component_count)


def _build_geometry(context, strategy, inputs):
    strategy_id = strategy.strategy_id
    family = strategy.topology_family
    if family not in _SUPPORTED_FAMILIES:
        raise SkeletonBuildError(f"unsupported skeleton topology family {family!r}", strategy_id=strategy_id, failure_geometry=inputs.site_geometry)
    entries = _eligible_entries(inputs, strategy_id)
    local_width_m = _method_parameter(context, "road_local_width_m")
    collector_width_m = _method_parameter(context, "road_collector_width_m")
    clearance_m = _method_parameter(context, "road_clearance_m", allow_zero=True)
    open_spaces = ()
    if family == "CONNECTED_GRID":
        spacing_m = _method_parameter(context, "grid_spacing_m")
        paths = _grid_paths(
            context,
            inputs,
            entries,
            spacing_m=spacing_m,
            local_width_m=local_width_m,
            collector_width_m=collector_width_m,
            clearance_m=clearance_m,
            strategy_id=strategy_id,
        )
        diameter_m = _method_parameter(context, "grid_open_space_diameter_m")
        open_spaces = _grid_open_spaces(
            paths,
            site=inputs.site_geometry,
            obstacles=_obstacles(inputs),
            width_m=local_width_m,
            clearance_m=clearance_m,
            diameter_m=diameter_m,
            strategy_id=strategy_id,
        )
    elif family == "CENTRAL_COMMON":
        diameter_m = _method_parameter(context, "central_common_diameter_m")
        paths, open_spaces = _central_paths(
            context,
            inputs,
            entries,
            diameter_m=diameter_m,
            local_width_m=local_width_m,
            collector_width_m=collector_width_m,
            clearance_m=clearance_m,
            strategy_id=strategy_id,
        )
    else:
        open_width_m = _method_parameter(context, "linear_open_space_width_m")
        paths, open_spaces = _linear_paths(
            context,
            strategy,
            inputs,
            entries,
            local_width_m=local_width_m,
            collector_width_m=collector_width_m,
            open_width_m=open_width_m,
            clearance_m=clearance_m,
        )
    if family != 'CONNECTED_GRID' and context.method_parameters.get('south_strip_collector'):
        paths = _south_strip_collector(context, strategy, inputs, paths, open_spaces,
                                       collector_width_m, clearance_m)
    return _artifact(
        context,
        strategy,
        inputs,
        paths,
        open_spaces,
        timestamp=datetime.now(timezone.utc),
        local_width_m=local_width_m,
        collector_width_m=collector_width_m,
    )


def build_skeleton(context: GenerationContext, strategy: StrategySpec, inputs: SkeletonInputs) -> SkeletonBuildResult:
    """Build one replayable family candidate or raise a geometry-bearing BLOCKED error."""

    if context.crs != inputs.crs:
        raise ValueError("generation context CRS and resolved skeleton geometry CRS differ")
    if strategy.topology_family not in _SUPPORTED_FAMILIES:
        raise SkeletonBuildError(
            f"unregistered skeleton topology family {strategy.topology_family!r}",
            strategy_id=strategy.strategy_id,
            failure_geometry=inputs.site_geometry,
        )
    return _build_geometry(context, strategy, inputs)


def skeleton_geometry_digest(artifact: SkeletonArtifact) -> str:
    """Hash only road/open-space geometry semantics, excluding height and wall time."""

    roads = [
        {
            "geometry": shape(edge.geometry.model_dump(exclude={"crs"})),
            "level": edge.level,
            "width_m": edge.width_m,
            "width_ref": edge.width_ref,
        }
        for edge in artifact.edges
    ]
    spaces = [shape(item.geometry.model_dump(exclude={"crs"})) for item in artifact.primary_open_spaces]
    return semantic_digest({"algorithm_version": artifact.algorithm_version, "roads": roads, "primary_open_spaces": spaces})


__all__ = [
    "SkeletonBuildError",
    "SkeletonBuildResult",
    "SkeletonEntry",
    "SkeletonInputs",
    "build_skeleton",
    "skeleton_geometry_digest",
]
