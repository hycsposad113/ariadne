"""Exploratory deterministic angular segment measures.

This project-specific implementation calculates angular depth, metric-radius
reachability, route choice, and candidate normalized measures. Its segment
construction, radius convention, route definition, and formulas have not been
verified against a selected Space Syntax engine or an approved method manifest;
the outputs must remain exploratory until that comparison is complete.

A segment s has endpoints J1, J2. Traversing s from J1 to J2 exits at J2, from which
transitions can only be made to other segments v != s meeting at J2, traversing v to
its other junction. This prevents spurious same-junction reversal loops.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Any, Hashable, Mapping, Sequence
from shapely.geometry import LineString


@dataclass(frozen=True)
class SegmentFeature:
    """A street segment with geometry, length, and elevation/layer attributes."""

    id: str
    geometry: LineString
    length_m: float
    layer: int | None = 0
    oneway: bool = False
    highway: str | None = None
    start_node_id: str | None = None
    end_node_id: str | None = None

    @property
    def start_coord(self) -> tuple[float, float]:
        coords = list(self.geometry.coords)
        return (round(coords[0][0], 4), round(coords[0][1], 4))

    @property
    def end_coord(self) -> tuple[float, float]:
        coords = list(self.geometry.coords)
        return (round(coords[-1][0], 4), round(coords[-1][1], 4))

    @property
    def midpoint(self) -> tuple[float, float]:
        pt = self.geometry.interpolate(0.5, normalized=True)
        return (round(pt.x, 4), round(pt.y, 4))


@dataclass
class SegmentNetwork:
    """Cleaned segment graph for angular depth analysis."""

    segments: dict[str, SegmentFeature]
    # junction -> list of (seg_id, 'start' | 'end')
    junctions: dict[Hashable, list[tuple[str, str]]]
    junction_coords: dict[Hashable, tuple[float, float]]
    endpoint_junctions: dict[tuple[str, str], Hashable]

    @classmethod
    def from_features(cls, features: Sequence[SegmentFeature]) -> SegmentNetwork:
        seen_ids: set[str] = set()
        for feat in features:
            if not isinstance(feat.id, str) or not feat.id.strip():
                raise ValueError("segment IDs must be non-empty strings")
            if feat.id in seen_ids:
                raise ValueError(f"segment IDs must be unique; duplicate {feat.id!r}")
            seen_ids.add(feat.id)
            if not isinstance(feat.geometry, LineString) or feat.geometry.is_empty:
                raise ValueError(f"segment {feat.id!r} must have a non-empty LineString geometry")
            coords = list(feat.geometry.coords)
            if len(coords) < 2 or any(
                len(coord) < 2
                or not math.isfinite(float(coord[0]))
                or not math.isfinite(float(coord[1]))
                for coord in coords
            ):
                raise ValueError(f"segment {feat.id!r} must have finite XY coordinates")
            if not math.isfinite(float(feat.length_m)) or float(feat.length_m) <= 0:
                raise ValueError(f"segment {feat.id!r} must have a finite positive length in metres")
            if not math.isfinite(float(feat.geometry.length)) or feat.geometry.length <= 0:
                raise ValueError(f"segment {feat.id!r} geometry must have positive finite XY length")

        segments = {feat.id: feat for feat in features}
        junctions: dict[Hashable, list[tuple[str, str]]] = {}
        junction_coords: dict[Hashable, tuple[float, float]] = {}
        endpoint_junctions: dict[tuple[str, str], Hashable] = {}

        for feat in features:
            for endpoint, coord, node_id in (
                ("start", feat.start_coord, feat.start_node_id),
                ("end", feat.end_coord, feat.end_node_id),
            ):
                if node_id is not None:
                    key: Hashable = ("osm-node", str(node_id))
                    prior_coord = junction_coords.get(key)
                    if prior_coord is not None and math.dist(prior_coord, coord) > 0.01:
                        raise ValueError(f"OSM node {node_id!r} has inconsistent projected coordinates")
                elif feat.layer is None:
                    # Unknown grade cannot be inferred from XY coincidence.
                    key = ("unresolved-endpoint", feat.id, endpoint)
                else:
                    key = (coord, feat.layer)
                junction_coords.setdefault(key, coord)
                endpoint_junctions[(feat.id, endpoint)] = key
                junctions.setdefault(key, []).append((feat.id, endpoint))

        return cls(
            segments=segments,
            junctions=junctions,
            junction_coords=junction_coords,
            endpoint_junctions=endpoint_junctions,
        )

    def get_turn_angle(self, seg1_id: str, seg2_id: str, junction: Hashable) -> float:
        """Calculate turn angle in radians between seg1 exiting at junction and seg2 entering at junction."""
        seg1 = self.segments[seg1_id]
        seg2 = self.segments[seg2_id]
        if junction not in self.junction_coords:
            raise ValueError(f"unknown junction {junction!r}")

        seg1_at_start = self.endpoint_junctions[(seg1_id, "start")] == junction
        seg1_at_end = self.endpoint_junctions[(seg1_id, "end")] == junction
        seg2_at_start = self.endpoint_junctions[(seg2_id, "start")] == junction
        seg2_at_end = self.endpoint_junctions[(seg2_id, "end")] == junction
        if seg1_at_start == seg1_at_end or seg2_at_start == seg2_at_end:
            raise ValueError("turn angle requires one unambiguous endpoint from each segment at the junction")

        def vector_to_endpoint(segment: SegmentFeature, endpoint: str) -> tuple[float, float]:
            coords = list(segment.geometry.coords)
            if endpoint == "start":
                anchor = coords[0]
                interior_coords = coords[1:]
            else:
                anchor = coords[-1]
                interior_coords = reversed(coords[:-1])
            for interior in interior_coords:
                dx = float(anchor[0]) - float(interior[0])
                dy = float(anchor[1]) - float(interior[1])
                if math.hypot(dx, dy) > 0.0:
                    return dx, dy
            return 0.0, 0.0

        # The turn is local to the junction: use the nearest nonduplicate
        # geometry vertex at each segment endpoint, not the full-line chord.
        first_endpoint = "start" if seg1_at_start else "end"
        second_endpoint = "start" if seg2_at_start else "end"
        dx1, dy1 = vector_to_endpoint(seg1, first_endpoint)
        dx2, dy2 = vector_to_endpoint(seg2, second_endpoint)
        # seg1 arrives at the junction; seg2 departs from it.
        dx2, dy2 = -dx2, -dy2

        len1 = math.hypot(dx1, dy1)
        len2 = math.hypot(dx2, dy2)
        if len1 == 0 or len2 == 0:
            return 0.0

        dot = (dx1 * dx2 + dy1 * dy2) / (len1 * len2)
        dot = max(-1.0, min(1.0, dot))
        return math.acos(dot)


def calculate_segment_angular_measures(
    network: SegmentNetwork,
    radii_m: Sequence[float] = (800.0, 2000.0, 10000.0),
    *,
    angle_cost_unit: str = "turns",  # 'turns' (90 deg = 1.0) or 'radians'
) -> dict[float, dict[str, dict[str, Any]]]:
    """Calculate angular measures with nondominated angle/distance route labels.

    Metric radius makes angular route search a constrained multiobjective problem:
    a lower-angle route cannot discard a higher-angle route if the latter is
    shorter and can reach additional segments before the radius boundary.
    """
    if angle_cost_unit not in {"turns", "radians"}:
        raise ValueError("angle_cost_unit must be 'turns' or 'radians'")
    try:
        radii = tuple(float(radius) for radius in radii_m)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("radii_m must contain finite non-negative metric radii") from exc
    if any(not math.isfinite(radius) or radius < 0 for radius in radii):
        raise ValueError("radii_m must contain finite non-negative metric radii")

    results: dict[float, dict[str, dict[str, Any]]] = {}
    seg_ids = sorted(network.segments.keys())

    # Directed segments: (seg_id, direction)
    # direction: +1 means traverse from start to end; -1 means traverse from end to start
    # Exit junction:
    # (+1) exits at end_coord
    # (-1) exits at start_coord
    def exit_junction(sid: str, d: int) -> Hashable:
        endpoint = "end" if d == 1 else "start"
        return network.endpoint_junctions[(sid, endpoint)]

    # Prebuild directed transitions: (u, d_u) -> list of (v, d_v, turn_cost, metric_step)
    directed_adj: dict[tuple[str, int], list[tuple[str, int, float, float]]] = {}
    for sid in seg_ids:
        for d in (1, -1):
            directed_adj[(sid, d)] = []
            j_exit = exit_junction(sid, d)
            for other_sid, end_type in network.junctions.get(j_exit, []):
                if other_sid == sid:
                    continue
                # If other segment connects at its start, traversal direction is +1 (from start to end)
                # If other segment connects at its end, traversal direction is -1 (from end to start)
                d_v = 1 if end_type == "start" else -1
                turn_rad = network.get_turn_angle(sid, other_sid, j_exit)
                turn_cost = turn_rad / (math.pi / 2.0) if angle_cost_unit == "turns" else turn_rad
                metric_step = (network.segments[sid].length_m + network.segments[other_sid].length_m) / 2.0
                directed_adj[(sid, d)].append((other_sid, d_v, turn_cost, metric_step))

    for radius in radii:
        radius_res: dict[str, dict[str, Any]] = {
            sid: {
                "total_depth": 0.0,
                "node_count": 0,
                "mean_depth": 0.0,
                "integration": 0.0,
                "nain": 0.0,
                "choice": 0.0,
                "nach": 0.0,
                "formula_version": "turner-2007-angular-segment-v1",
            }
            for sid in seg_ids
        }

        # Choice accumulator for intermediate segments
        choice_acc: dict[str, float] = {sid: 0.0 for sid in seg_ids}

        for src in seg_ids:
            # A label is one Pareto-optimal (angular cost, metric distance) route
            # to a directed segment state. Positive metric steps make predecessor
            # labels acyclic when ordered lexicographically by (angle, distance).
            labels: list[dict[str, Any]] = []
            frontiers: dict[tuple[str, int], list[int]] = {}
            pq: list[tuple[float, float, int]] = []

            def add_label(
                state: tuple[str, int],
                angular: float,
                metric: float,
                predecessor: int | None,
                ways: float,
            ) -> None:
                current = frontiers.setdefault(state, [])
                for label_id in current:
                    label = labels[label_id]
                    no_worse = label["angular"] <= angular + 1e-9 and label["metric"] <= metric + 1e-9
                    equal = math.isclose(label["angular"], angular, abs_tol=1e-9) and math.isclose(
                        label["metric"], metric, abs_tol=1e-9
                    )
                    if equal:
                        if predecessor is not None and predecessor not in label["predecessors"]:
                            label["predecessors"].append(predecessor)
                            label["sigma"] += ways
                        return
                    if no_worse:
                        return

                survivors: list[int] = []
                for label_id in current:
                    label = labels[label_id]
                    candidate_dominates = angular <= label["angular"] + 1e-9 and metric <= label["metric"] + 1e-9
                    strictly_better = (
                        angular < label["angular"] - 1e-9 or metric < label["metric"] - 1e-9
                    )
                    if candidate_dominates and strictly_better:
                        label["active"] = False
                    else:
                        survivors.append(label_id)

                label_id = len(labels)
                labels.append(
                    {
                        "state": state,
                        "angular": angular,
                        "metric": metric,
                        "sigma": ways,
                        "predecessors": [] if predecessor is None else [predecessor],
                        "active": True,
                    }
                )
                survivors.append(label_id)
                frontiers[state] = survivors
                heapq.heappush(pq, (angular, metric, label_id))

            for direction in (1, -1):
                add_label((src, direction), 0.0, 0.0, None, 1.0)

            while pq:
                _, _, label_id = heapq.heappop(pq)
                label = labels[label_id]
                if not label["active"]:
                    continue
                u_node = label["state"]
                for v, d_v, turn_cost, metric_step in directed_adj[u_node]:
                    cand_metric = label["metric"] + metric_step
                    if cand_metric > radius + 1e-9:
                        continue
                    add_label(
                        (v, d_v),
                        label["angular"] + turn_cost,
                        cand_metric,
                        label_id,
                        label["sigma"],
                    )

            active_ids = [idx for idx, label in enumerate(labels) if label["active"]]
            labels_by_segment: dict[str, list[int]] = {sid: [] for sid in seg_ids}
            for label_id in active_ids:
                sid, _ = labels[label_id]["state"]
                if sid != src:
                    labels_by_segment[sid].append(label_id)

            seg_min_depth: dict[str, float] = {}
            for sid, label_ids in labels_by_segment.items():
                if label_ids:
                    seg_min_depth[sid] = min(labels[idx]["angular"] for idx in label_ids)

            tot_depth = sum(seg_min_depth.values())
            k = len(seg_min_depth)
            radius_res[src]["total_depth"] = round(tot_depth, 6)
            radius_res[src]["node_count"] = k
            if k > 0:
                md = tot_depth / k
                radius_res[src]["mean_depth"] = round(md, 6)
                radius_res[src]["integration"] = round(1.0 / md if md > 1e-6 else 999.0, 6)
                nain = (k ** 1.2) / (tot_depth + 2.0)
                radius_res[src]["nain"] = round(nain, 6)
            else:
                radius_res[src]["mean_depth"] = 0.0
                radius_res[src]["integration"] = 0.0
                radius_res[src]["nain"] = 0.0

            # Seed one unit of expected path flow per target segment, split across
            # its equal shortest-angle route labels. A single reverse pass then
            # propagates all target flows through the predecessor DAG (Brandes
            # dependency accumulation), avoiding an O(targets * labels) replay.
            reverse_order = sorted(
                active_ids,
                key=lambda idx: (labels[idx]["angular"], labels[idx]["metric"], idx),
                reverse=True,
            )
            terminal_fraction: dict[int, float] = {}
            for target_sid, best_depth in seg_min_depth.items():
                terminal_ids = [
                    idx
                    for idx in labels_by_segment[target_sid]
                    if math.isclose(labels[idx]["angular"], best_depth, rel_tol=1e-7, abs_tol=1e-9)
                ]
                total_paths = sum(labels[idx]["sigma"] for idx in terminal_ids)
                if total_paths <= 0:
                    continue
                for label_id in terminal_ids:
                    terminal_fraction[label_id] = labels[label_id]["sigma"] / total_paths

            flow = dict(terminal_fraction)
            for label_id in reverse_order:
                amount = flow.get(label_id, 0.0)
                if amount <= 0.0:
                    continue
                sid, _ = labels[label_id]["state"]
                if sid != src:
                    # Exclude this label's own target endpoint mass, but retain
                    # any flow through it for farther target segments.
                    choice_acc[sid] += amount - terminal_fraction.get(label_id, 0.0)
                sigma_here = labels[label_id]["sigma"]
                if sigma_here <= 0:
                    continue
                for predecessor in labels[label_id]["predecessors"]:
                    pred_sigma = labels[predecessor]["sigma"]
                    flow[predecessor] = flow.get(predecessor, 0.0) + amount * pred_sigma / sigma_here

        # Finalize Choice and NACH for all segments
        # In undirected graphs where pairs (s, t) are evaluated with both directions,
        # divide accumulated choice by 2 (or keep directed pair sum). Standard depthmap reports total pass-throughs.
        for sid in seg_ids:
            # We normalize choice_acc (pair traversals)
            ch = choice_acc[sid] / 2.0  # undirected pair symmetry
            td = radius_res[sid]["total_depth"]
            nach = math.log(ch + 1.0) / math.log(td + 3.0) if td >= 0 else 0.0
            radius_res[sid]["choice"] = round(ch, 6)
            radius_res[sid]["nach"] = round(nach, 6)

        results[radius] = radius_res

    return results
