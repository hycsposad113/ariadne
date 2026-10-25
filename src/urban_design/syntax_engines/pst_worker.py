"""Child process entry point for PST's ctypes interface."""

from __future__ import annotations

import array
import json
import math
import sys
from typing import Any


def _finite_array(values: array.array, label: str) -> list[float]:
    result = [float(value) for value in values]
    if any(not math.isfinite(value) for value in result):
        raise ValueError(f"PST returned a non-finite {label} value")
    return result


def run(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema_version") != "pst-angular-request-v1":
        raise ValueError("unsupported PST request schema")
    lines = request.get("lines")
    unlinks = request.get("unlinks")
    if not isinstance(lines, list) or not lines or not isinstance(unlinks, list):
        raise ValueError("PST request requires lines and unlink arrays")
    poly_coords = array.array("d")
    poly_sections = array.array("i")
    source_ids: list[str] = []
    for line in lines:
        if not isinstance(line, dict):
            raise ValueError("PST line entry must be an object")
        line_id = line.get("id")
        coordinates = line.get("coordinates")
        if not isinstance(line_id, str) or not line_id.strip() or line_id in source_ids:
            raise ValueError("PST line IDs must be unique non-empty strings")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise ValueError(f"PST line {line_id!r} must contain at least two coordinates")
        for point in coordinates:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError(f"PST line {line_id!r} coordinates must be XY pairs")
            x, y = float(point[0]), float(point[1])
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError(f"PST line {line_id!r} coordinates must be finite")
            poly_coords.extend((x, y))
        poly_sections.append(len(coordinates))
        source_ids.append(line_id)
    unlink_coords = array.array("d")
    for point in unlinks:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError("PST unlink must be an XY pair")
        x, y = float(point[0]), float(point[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("PST unlink coordinates must be finite")
        unlink_coords.extend((x, y))

    settings = request.get("segment_map")
    if not isinstance(settings, dict) or set(settings) != {"snap_m", "min_tail_m", "colinear_deviation", "extrude_m"}:
        raise ValueError("PST request requires the complete segment_map settings")
    snap = float(settings["snap_m"])
    tail = float(settings["min_tail_m"])
    deviation = float(settings["colinear_deviation"])
    extrude = float(settings["extrude_m"])
    if any(not math.isfinite(value) or value < 0 for value in (snap, tail, deviation, extrude)):
        raise ValueError("PST segment_map settings must be finite and non-negative")

    import pstalgo

    segment_graph = None
    segment_map_algorithm = None
    try:
        segment_map, segment_map_algorithm = pstalgo.CreateSegmentMap(
            road_network_type=pstalgo.RoadNetworkType.AXIAL_OR_SEGMENT,
            poly_coords=poly_coords,
            poly_sections=poly_sections,
            unlinks=unlink_coords if unlink_coords else None,
            snap=snap,
            tail=tail,
            deviation=deviation,
            extrude=extrude,
        )
        segment_count = int(segment_map.m_SegmentCount)
        if segment_count <= 0:
            raise ValueError("PST CreateSegmentMap produced no segments")

        raw_segment_rows: list[tuple[int, int, int]] = []
        max_point_index = -1
        for index in range(segment_count):
            start_index = int(segment_map.m_Segments[index * 3])
            end_index = int(segment_map.m_Segments[index * 3 + 1])
            source_index = int(segment_map.m_Segments[index * 3 + 2])
            if start_index < 0 or end_index < 0 or source_index < 0 or source_index >= len(source_ids):
                raise ValueError("PST CreateSegmentMap returned invalid segment references")
            raw_segment_rows.append((start_index, end_index, source_index))
            max_point_index = max(max_point_index, start_index, end_index)

        segment_coords = array.array("d")
        for point_index in range(max_point_index + 1):
            segment_coords.extend((
                float(segment_map.m_SegmentCoords[point_index * 2]),
                float(segment_map.m_SegmentCoords[point_index * 2 + 1]),
            ))
        segment_indices = array.array("I")
        segment_records: list[dict[str, Any]] = []
        source_segment_counts: dict[int, int] = {}
        for start_index, end_index, source_index in raw_segment_rows:
            segment_indices.extend((start_index, end_index))
            source_id = source_ids[source_index]
            ordinal = source_segment_counts.get(source_index, 0) + 1
            source_segment_counts[source_index] = ordinal
            segment_records.append({
                "id": f"{source_id}::pst-segment-{ordinal:04d}",
                "source_line_id": source_id,
                "start": [segment_coords[start_index * 2], segment_coords[start_index * 2 + 1]],
                "end": [segment_coords[end_index * 2], segment_coords[end_index * 2 + 1]],
            })
        segment_graph = pstalgo.CreateSegmentGraph(segment_coords, segment_indices, None)

        radius_value = float(request["radius_m"])
        if not math.isfinite(radius_value) or radius_value <= 0:
            raise ValueError("radius_m must be finite and positive")
        radius_mode = request["radius_mode"]
        if radius_mode not in ("straight", "walking", "axmeter"):
            raise ValueError("unsupported metric radius mode")
        radius = pstalgo.Radii(**{radius_mode: radius_value})
        angle_threshold = float(request["angle_threshold"])
        angle_precision = int(request["angle_precision"])
        weigh_by_length = request["weigh_by_length"]
        if not math.isfinite(angle_threshold) or not 0 <= angle_threshold <= 180:
            raise ValueError("angle_threshold must be between 0 and 180 degrees")
        if angle_precision < 1 or not isinstance(weigh_by_length, bool):
            raise ValueError("angle_precision and weigh_by_length are invalid")

        metric_mode = request.get("metric_mode", "both")
        if metric_mode not in ("both", "integration", "choice"):
            raise ValueError("unsupported metric mode")

        count = segment_count
        radius_value = float(request["radius_m"])
        node_counts = array.array("I", [0] * count)
        total_depths = array.array("f", [0.0] * count)
        total_weights = array.array("f", [0.0] * count)
        total_depth_weights = array.array("f", [0.0] * count)
        if metric_mode in ("both", "integration"):
            pstalgo.AngularIntegration(
                graph_handle=segment_graph,
                radius=radius,
                weigh_by_length=weigh_by_length,
                angle_threshold=angle_threshold,
                angle_precision=angle_precision,
                out_node_counts=node_counts,
                out_total_depths=total_depths,
                out_total_weights=total_weights,
                out_total_depth_weights=total_depth_weights,
            )

        choices = array.array("f", [0.0] * count)
        choice_node_counts = array.array("I", [0] * count)
        choice_total_depths = array.array("f", [0.0] * count)
        choice_total_depth_weights = array.array("f", [0.0] * count)
        if metric_mode in ("both", "choice"):
            pstalgo.AngularChoice(
                graph_handle=segment_graph,
                radius=radius,
                weigh_by_length=weigh_by_length,
                angle_threshold=angle_threshold,
                angle_precision=angle_precision,
                out_choice=choices,
                out_node_count=choice_node_counts,
                out_total_depth=choice_total_depths,
                out_total_depth_weight=choice_total_depth_weights,
            )
            if metric_mode == "choice":
                node_counts = choice_node_counts
                total_depths = choice_total_depths
                total_depth_weights = choice_total_depth_weights
        return {
            "schema_version": "pst-angular-result-v1",
            "segments": segment_records,
            "source_line_count": len(source_ids),
            "explicit_unlink_count": len(unlinks),
            "segment_map_generated_unlink_count": int(segment_map.m_UnlinkCount),
            "segment_map_settings": settings,
            "node_counts": list(node_counts),
            "total_depths": _finite_array(total_depths, "total_depths"),
            "total_depth_weights": _finite_array(total_depth_weights, "total_depth_weights"),
            "choices": _finite_array(choices, "choices"),
            "choice_node_counts": list(choice_node_counts),
            "choice_total_depths": _finite_array(choice_total_depths, "choice_total_depths"),
            "choice_total_depth_weights": _finite_array(
                choice_total_depth_weights, "choice_total_depth_weights"
            ),
        }
    finally:
        if segment_graph is not None:
            pstalgo.FreeSegmentGraph(segment_graph)
        if segment_map_algorithm is not None:
            pstalgo.Free(segment_map_algorithm)


def main() -> int:
    try:
        request = json.load(sys.stdin)
        result = run(request)
        json.dump(result, sys.stdout, allow_nan=False, separators=(",", ":"))
        sys.stdout.write("\n")
        return 0
    except Exception as exc:  # child process must report failures without parent ctypes load
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
