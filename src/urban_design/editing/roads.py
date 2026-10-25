"""Deterministic road-node editing primitives for synthetic fixtures.

This module does not persist a workspace or recompute Syntax results. A move
returns a new immutable graph and marks supplied dependent result IDs stale.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Iterable, Literal

from shapely.geometry import LineString, Point


class RoadEditError(ValueError):
    """Raised when a road graph edit cannot be applied without ambiguity."""


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RoadEditError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise RoadEditError(f"{field} must be a finite number")
    return number


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RoadEditError(f"{field} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class RoadNode:
    node_id: str
    x_m: float
    y_m: float
    layer: int | None = None
    bridge: bool = False
    tunnel: bool = False
    lineage_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.node_id, "node id")
        object.__setattr__(self, "x_m", _finite(self.x_m, "node x coordinate"))
        object.__setattr__(self, "y_m", _finite(self.y_m, "node y coordinate"))
        if self.layer is not None and (isinstance(self.layer, bool) or not isinstance(self.layer, int)):
            raise RoadEditError("node layer must be an integer or None")
        if not isinstance(self.bridge, bool) or not isinstance(self.tunnel, bool):
            raise RoadEditError("bridge and tunnel flags must be booleans")
        if not isinstance(self.lineage_ids, tuple) or any(not isinstance(item, str) or not item.strip() for item in self.lineage_ids):
            raise RoadEditError("node lineage IDs must be a tuple of non-empty strings")


@dataclass(frozen=True)
class RoadEdge:
    edge_id: str
    start_node_id: str
    end_node_id: str
    layer: int | None = None
    bridge: bool = False
    tunnel: bool = False
    locked: bool = False
    lineage_ids: tuple[str, ...] = ()
    access_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.access_refs, tuple) or any(not isinstance(item, str) or not item.strip() for item in self.access_refs):
            raise RoadEditError("edge access refs must be a tuple of non-empty strings")
        _identifier(self.edge_id, "edge id")
        _identifier(self.start_node_id, "edge start node id")
        _identifier(self.end_node_id, "edge end node id")
        if self.start_node_id == self.end_node_id:
            raise RoadEditError("road edge cannot have the same start and end node")
        if self.layer is not None and (isinstance(self.layer, bool) or not isinstance(self.layer, int)):
            raise RoadEditError("edge layer must be an integer or None")
        if not all(isinstance(flag, bool) for flag in (self.bridge, self.tunnel, self.locked)):
            raise RoadEditError("edge bridge, tunnel, and locked flags must be booleans")
        if not isinstance(self.lineage_ids, tuple) or any(not isinstance(item, str) or not item.strip() for item in self.lineage_ids):
            raise RoadEditError("edge lineage IDs must be a tuple of non-empty strings")


def _topology(item: RoadNode | RoadEdge) -> tuple[int | None, bool, bool]:
    return item.layer, item.bridge, item.tunnel


def _line(edge: RoadEdge, nodes: dict[str, RoadNode]) -> LineString:
    start = nodes[edge.start_node_id]
    end = nodes[edge.end_node_id]
    line = LineString([(start.x_m, start.y_m), (end.x_m, end.y_m)])
    if line.length <= 1e-9:
        raise RoadEditError(f"road edge {edge.edge_id} is zero-length")
    return line


@dataclass(frozen=True)
class RoadGraph:
    nodes: tuple[RoadNode, ...]
    edges: tuple[RoadEdge, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.nodes, tuple) or any(not isinstance(node, RoadNode) for node in self.nodes):
            raise RoadEditError("road graph nodes must be a tuple of RoadNode values")
        if not isinstance(self.edges, tuple) or any(not isinstance(edge, RoadEdge) for edge in self.edges):
            raise RoadEditError("road graph edges must be a tuple of RoadEdge values")
        node_ids = [node.node_id for node in self.nodes]
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(node_ids) != len(set(node_ids)):
            raise RoadEditError("road node IDs must be unique")
        if len(edge_ids) != len(set(edge_ids)):
            raise RoadEditError("road edge IDs must be unique")
        by_id = {node.node_id: node for node in self.nodes}
        occupied_pairs: set[tuple[str, str]] = set()
        occupied_geometry: set[tuple[object, ...]] = set()
        for edge in self.edges:
            pair = tuple(sorted((edge.start_node_id, edge.end_node_id)))
            if pair in occupied_pairs:
                raise RoadEditError("duplicate road edge endpoints")
            occupied_pairs.add(pair)
            if edge.start_node_id not in by_id or edge.end_node_id not in by_id:
                raise RoadEditError(f"road edge {edge.edge_id} references a missing node")
            if _topology(by_id[edge.start_node_id]) != _topology(edge) or _topology(by_id[edge.end_node_id]) != _topology(edge):
                raise RoadEditError(f"road edge {edge.edge_id} endpoint layer/bridge/tunnel values must match")
            _line(edge, by_id)
            coordinates = tuple(sorted(((by_id[edge.start_node_id].x_m, by_id[edge.start_node_id].y_m),
                                        (by_id[edge.end_node_id].x_m, by_id[edge.end_node_id].y_m))))
            geometry_key = (_topology(edge), coordinates)
            if geometry_key in occupied_geometry:
                raise RoadEditError("duplicate road edge geometry")
            occupied_geometry.add(geometry_key)

    def node(self, node_id: str) -> RoadNode:
        for item in self.nodes:
            if item.node_id == node_id:
                return item
        raise RoadEditError(f"unknown road node {node_id!r}")

    @property
    def graph_hash(self) -> str:
        payload = {
            "nodes": [
                {
                    "id": node.node_id,
                    "x_m": node.x_m,
                    "y_m": node.y_m,
                    "layer": node.layer,
                    "bridge": node.bridge,
                    "tunnel": node.tunnel,
                    "lineage_ids": list(node.lineage_ids),
                }
                for node in sorted(self.nodes, key=lambda item: item.node_id)
            ],
            "edges": [
                {
                    "id": edge.edge_id,
                    "start": edge.start_node_id,
                    "end": edge.end_node_id,
                    "layer": edge.layer,
                    "bridge": edge.bridge,
                    "tunnel": edge.tunnel,
                    "locked": edge.locked,
                    "access_refs": list(edge.access_refs),
                    "lineage_ids": list(edge.lineage_ids),
                }
                for edge in sorted(self.edges, key=lambda item: item.edge_id)
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def connected_component_count(self) -> int:
        """Count edge components using shared node IDs, never geometric crossings."""
        if not self.edges:
            return 0
        parents = {edge.edge_id: edge.edge_id for edge in self.edges}

        def root(edge_id: str) -> str:
            while parents[edge_id] != edge_id:
                parents[edge_id] = parents[parents[edge_id]]
                edge_id = parents[edge_id]
            return edge_id

        def union(first: str, second: str) -> None:
            first_root, second_root = root(first), root(second)
            if first_root != second_root:
                parents[max(first_root, second_root)] = min(first_root, second_root)

        for index, first in enumerate(self.edges):
            for second in self.edges[index + 1 :]:
                if _topology(first) != _topology(second):
                    continue
                if {first.start_node_id, first.end_node_id} & {second.start_node_id, second.end_node_id}:
                    union(first.edge_id, second.edge_id)
        return len({root(edge.edge_id) for edge in self.edges})


@dataclass(frozen=True)
class RoadEditResult:
    graph: RoadGraph
    moved_node_id: str
    requested_x_m: float
    requested_y_m: float
    actual_x_m: float
    actual_y_m: float
    snapped_to_node_id: str | None
    snapped_to_edge_id: str | None
    stale_syntax_result_ids: tuple[str, ...]
    graph_hash: str
    snap_kind: str = "NONE"


def _unique_strings(values: Iterable[str]) -> tuple[str, ...]:
    result = tuple(sorted({_identifier(value, "Syntax result id") for value in values}))
    return result


SnapKind = Literal["ENDPOINT", "NEAREST_POINT", "MIDPOINT", "INTERSECTION", "PERPENDICULAR", "QUARTER", "THREE_QUARTER"]
SNAP_KINDS = ("ENDPOINT", "NEAREST_POINT", "MIDPOINT", "INTERSECTION", "PERPENDICULAR", "QUARTER", "THREE_QUARTER")


@dataclass(frozen=True)
class RoadSnapCandidate:
    snap_kind: SnapKind
    x_m: float
    y_m: float
    distance_m: float
    target_node_id: str | None
    target_edge_ids: tuple[str, ...]
    position_semantics: str
    target_length_m: float | None = None
    distance_along_m: float | None = None
    target_fraction: float | None = None


def _compatible(first: RoadNode | RoadEdge, second: RoadNode | RoadEdge) -> bool:
    return first.layer is not None and second.layer is not None and _topology(first) == _topology(second)


def road_snap_candidates(
    graph: RoadGraph, node_id: str, *, x_m: float, y_m: float,
    snap_tolerance_m: float, perpendicular_anchor_node_id: str | None = None,
) -> tuple[RoadSnapCandidate, ...]:
    """Seven ground-metre snaps on straight endpoint-defined edges.

    Midpoint/quarter positions measure length from the edge's start node.
    Perpendicular projects the explicit anchor (or original moving node) onto
    the finite target segment; unlike nearest it never clamps beyond endpoints.
    Unknown levels produce no candidates.
    """
    x, y = _finite(x_m, "target x coordinate"), _finite(y_m, "target y coordinate")
    tolerance = _finite(snap_tolerance_m, "snap tolerance")
    if tolerance <= 0:
        raise RoadEditError("snap tolerance must be positive")
    moving = graph.node(node_id)
    incident = [e for e in graph.edges if node_id in (e.start_node_id, e.end_node_id)]
    if not incident:
        raise RoadEditError("cannot move a road node without incident edges")
    if any(e.locked for e in incident):
        raise RoadEditError("node is incident to a locked road and cannot be dragged")
    anchor = graph.node(perpendicular_anchor_node_id) if perpendicular_anchor_node_id else moving
    if not _compatible(moving, anchor):
        if perpendicular_anchor_node_id:
            raise RoadEditError("perpendicular anchor topology is unknown or incompatible")
    nodes = {n.node_id: n for n in graph.nodes}
    target = Point(x, y)
    candidates: list[RoadSnapCandidate] = []
    edges = [e for e in graph.edges if node_id not in (e.start_node_id, e.end_node_id) and _compatible(moving, e)]
    used = {i for e in graph.edges for i in (e.start_node_id, e.end_node_id)}

    def add(kind: SnapKind, point: Point, node: str | None, ids: tuple[str, ...], semantics: str) -> None:
        distance = float(target.distance(point))
        if distance <= tolerance:
            line = _line(next(e for e in edges if e.edge_id == ids[0]), nodes) if len(ids) == 1 else None
            length = float(line.length) if line is not None else None
            along = float(line.project(point)) if line is not None else None
            candidates.append(RoadSnapCandidate(kind, float(point.x), float(point.y), distance, node, ids, semantics, length, along, along / length if length else None))

    for n in graph.nodes:
        if n.node_id != node_id and n.node_id in used and _compatible(moving, n):
            add("ENDPOINT", Point(n.x_m, n.y_m), n.node_id, (), "existing graph node")
    for e in edges:
        if e.locked:
            continue
        line = _line(e, nodes)
        add("NEAREST_POINT", line.interpolate(line.project(target)), None, (e.edge_id,), "closest point on finite straight segment")
        for kind, fraction in (("MIDPOINT", .5), ("QUARTER", .25), ("THREE_QUARTER", .75)):
            add(kind, line.interpolate(fraction, normalized=True), None, (e.edge_id,), f"straight edge along-length fraction {fraction} from start")
        a, b = nodes[e.start_node_id], nodes[e.end_node_id]
        dx, dy = b.x_m-a.x_m, b.y_m-a.y_m
        fraction = ((anchor.x_m-a.x_m)*dx+(anchor.y_m-a.y_m)*dy)/(dx*dx+dy*dy)
        if 0 <= fraction <= 1:
            add("PERPENDICULAR", line.interpolate(fraction, normalized=True), None, (e.edge_id,), f"perpendicular from node {anchor.node_id} onto finite straight segment")
    for index, first in enumerate(edges):
        for second in edges[index+1:]:
            if first.locked or second.locked:
                continue
            crossing = _line(first, nodes).intersection(_line(second, nodes))
            if crossing.geom_type == "Point":
                add("INTERSECTION", crossing, None, tuple(sorted((first.edge_id, second.edge_id))), "finite straight edge intersection")
    for fraction, point, edge_id, along, length in _polyline_fraction_points(edges, nodes):
        distance = float(target.distance(point))
        if distance <= tolerance:
            kind = {0.25: "QUARTER", 0.5: "MIDPOINT", 0.75: "THREE_QUARTER"}[fraction]
            candidates.append(RoadSnapCandidate(
                kind, float(point.x), float(point.y), distance, None, (edge_id,),
                f"connected polyline along-length fraction {fraction} from the geometric start",
                length, along, fraction,
            ))
    return tuple(sorted(candidates, key=lambda c: (c.distance_m, SNAP_KINDS.index(c.snap_kind), c.target_node_id or "", c.target_edge_ids, c.x_m, c.y_m)))


def _polyline_fraction_points(edges: list[RoadEdge], nodes: dict[str, RoadNode]) -> list[tuple[float, Point, str, float, float]]:
    """Quarter, midpoint, and three-quarter points of each connected path of two or more edges.

    Single edges stay on their own start-to-end fractions. A path is measured from
    the geometric start, so a bend is not replaced by the bounding-box centre.
    """
    if len(edges) < 2:
        return []
    incident: dict[str, list[RoadEdge]] = {}
    for edge in edges:
        incident.setdefault(edge.start_node_id, []).append(edge)
        incident.setdefault(edge.end_node_id, []).append(edge)
    degree = {node_id: len(items) for node_id, items in incident.items()}
    endpoints = [node_id for node_id, count in degree.items() if count != 2]
    seen: set[str] = set()
    paths: list[list[tuple[RoadEdge, str]]] = []
    for start in sorted(endpoints):
        for edge in incident[start]:
            if edge.edge_id in seen:
                continue
            path: list[tuple[RoadEdge, str]] = []
            node_id = start
            current: RoadEdge | None = edge
            while current is not None and current.edge_id not in seen:
                seen.add(current.edge_id)
                path.append((current, node_id))
                node_id = current.end_node_id if current.start_node_id == node_id else current.start_node_id
                nxt = [item for item in incident.get(node_id, []) if item.edge_id not in seen]
                current = nxt[0] if len(nxt) == 1 and degree.get(node_id) == 2 else None
            if len(path) >= 2:
                paths.append(path)
    points: list[tuple[float, Point, str, float, float]] = []
    for path in paths:
        start_id = path[0][1]
        end_id = path[-1][0].end_node_id if path[-1][0].start_node_id == path[-1][1] else path[-1][0].start_node_id
        start_node, end_node = nodes[start_id], nodes[end_id]
        if (end_node.x_m, end_node.y_m, end_node.node_id) < (start_node.x_m, start_node.y_m, start_node.node_id):
            reversed_path: list[tuple[RoadEdge, str]] = []
            node_id = end_id
            for edge, _from in reversed(path):
                reversed_path.append((edge, node_id))
                node_id = edge.end_node_id if edge.start_node_id == node_id else edge.start_node_id
            path = reversed_path
        located: list[tuple[RoadEdge, float, float]] = []
        cursor = 0.0
        for edge, from_id in path:
            other = edge.end_node_id if edge.start_node_id == from_id else edge.start_node_id
            length = float(_line(edge, nodes).length)
            located.append((edge, cursor, length))
            cursor += length
        total = cursor
        if total <= 1e-9:
            continue
        for fraction in (0.25, 0.5, 0.75):
            distance = fraction * total
            for edge, start_distance, length in located:
                if distance <= start_distance + length + 1e-9:
                    from_id = next(node for item, node in path if item.edge_id == edge.edge_id)
                    other = edge.end_node_id if edge.start_node_id == from_id else edge.start_node_id
                    line = LineString([(nodes[from_id].x_m, nodes[from_id].y_m), (nodes[other].x_m, nodes[other].y_m)])
                    points.append((fraction, line.interpolate(distance - start_distance), edge.edge_id, distance, total))
                    break
    return points


def move_road_node(
    graph: RoadGraph, node_id: str, *, x_m: float, y_m: float,
    snap_tolerance_m: float, syntax_result_ids: Iterable[str] = (),
    snap_kind: SnapKind | None = None, perpendicular_anchor_node_id: str | None = None,
    target_id: str | None = None,
) -> RoadEditResult:
    """Move a node and materialize a selected snap as shared-node topology."""
    if snap_kind is not None and snap_kind not in SNAP_KINDS:
        raise RoadEditError("unknown snap kind")
    candidates = road_snap_candidates(graph, node_id, x_m=x_m, y_m=y_m,
        snap_tolerance_m=snap_tolerance_m, perpendicular_anchor_node_id=perpendicular_anchor_node_id)
    moving = graph.node(node_id)
    incident = [e for e in graph.edges if node_id in (e.start_node_id, e.end_node_id)]
    if not incident:
        raise RoadEditError("cannot move a road node without incident edges")
    if any(e.locked for e in incident):
        raise RoadEditError("node is incident to a locked road and cannot be dragged")
    available = [c for c in candidates if c.snap_kind == snap_kind] if snap_kind else [c for c in candidates if c.snap_kind in ("ENDPOINT", "NEAREST_POINT")]
    if target_id is not None:
        available = [c for c in available if c.target_node_id == target_id or target_id in c.target_edge_ids]
        if not available:
            raise RoadEditError("selected snap target is unavailable within tolerance")
    if snap_kind is not None and not available:
        raise RoadEditError("NOT_READY: selected snap kind has no candidate within tolerance")
    selected = available[0] if available else None
    x, y = (selected.x_m, selected.y_m) if selected else (float(x_m), float(y_m))
    nodes = {n.node_id: n for n in graph.nodes}
    # A candidate at an existing endpoint must truly merge, even for fractions/intersections.
    coincident = sorted(n.node_id for n in graph.nodes if n.node_id != node_id and _compatible(moving, n) and math.hypot(n.x_m-x, n.y_m-y) <= 1e-9)
    if selected and len(coincident) > 1:
        raise RoadEditError("ambiguous coincident endpoint topology")
    destination = coincident[0] if selected and coincident else node_id
    snap_node = destination if destination != node_id else None
    replacement = RoadNode(destination, x, y, moving.layer, moving.bridge, moving.tunnel,
        tuple(sorted(set(moving.lineage_ids) | (set(nodes[destination].lineage_ids) if snap_node else set()))))
    nodes[destination] = replacement
    if snap_node:
        nodes.pop(node_id)
    edges: list[RoadEdge] = []
    occupied = {e.edge_id for e in graph.edges}
    for e in graph.edges:
        start = destination if e.start_node_id == node_id else e.start_node_id
        end = destination if e.end_node_id == node_id else e.end_node_id
        if start == end:
            raise RoadEditError("snapping would create a zero-length road edge")
        is_target = selected and node_id not in (e.start_node_id, e.end_node_id) and _compatible(moving, e)
        line = _line(e, {n.node_id:n for n in graph.nodes})
        point = Point(x, y)
        if is_target and line.distance(point) <= 1e-9 and destination not in (start, end):
            if e.locked:
                raise RoadEditError("snap would alter a locked target road")
            if line.project(point) <= 1e-9 or line.length-line.project(point) <= 1e-9:
                raise RoadEditError("ambiguous coincident endpoint topology")
            ids = (f"{e.edge_id}:1", f"{e.edge_id}:2")
            if any(i in occupied for i in ids):
                raise RoadEditError("split edge ID collision")
            occupied.update(ids)
            lineage = tuple(sorted(set(e.lineage_ids) | {e.edge_id}))
            edges.extend((RoadEdge(ids[0], start, destination, e.layer, e.bridge, e.tunnel, False, lineage, e.access_refs),
                          RoadEdge(ids[1], destination, end, e.layer, e.bridge, e.tunnel, False, lineage, e.access_refs)))
        else:
            if e.locked and (start != e.start_node_id or end != e.end_node_id):
                raise RoadEditError("snap would alter a locked target road")
            edges.append(RoadEdge(e.edge_id, start, end, e.layer, e.bridge, e.tunnel, e.locked, e.lineage_ids, e.access_refs))
    result = RoadGraph(tuple(nodes[k] for k in sorted(nodes)), tuple(sorted(edges, key=lambda e:e.edge_id)))
    changed = result.graph_hash != graph.graph_hash
    return RoadEditResult(result, node_id, float(x_m), float(y_m), x, y, snap_node,
        selected.target_edge_ids[0] if selected and selected.target_edge_ids and not snap_node else None,
        _unique_strings(syntax_result_ids) if changed else (), result.graph_hash, selected.snap_kind if selected else "NONE")
