"""Context street network extraction, cleaning, and exploratory angular layers (CP4-6).

Extracts and validates street segments from OSM Overpass:
- Breaks linestrings at vertices into 2-point segment features.
- Offers an explicitly experimental shared-OSM-node segmentation candidate that retains shape vertices.
- Uses shared OSM node IDs for source-way connectivity; XY-only crossings do not create junctions.
- Keeps absent or invalid grade tags unknown and audits unresolved crossings/overlaps.
- Geometrically nodes synthetic fixtures only when both grades are explicit and equal.
- Computes 6 mandatory layers across local (800m), mid (2,000m), and regional (10,000m) scales.
- Explicitly flags boundary and extent sufficiency to prevent reporting edge-clipped data as validated.

No segmentation or measure method in this module is approved for Rotterdam analysis until it is
compared with a pinned independent Space Syntax engine and accepted in a method manifest.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Mapping, Sequence
from shapely.geometry import LineString, Point, MultiPoint, GeometryCollection, shape
from shapely.strtree import STRtree

from .space_syntax import (
    SegmentFeature,
    SegmentNetwork,
    calculate_segment_angular_measures,
)


def _aligned_osm_node_ids(
    normalized_geometry: Mapping[str, Any],
    raw_way: Mapping[str, Any],
    *,
    transform: Callable[[float, float], tuple[float, float]],
) -> list[str]:
    """Return OSM node IDs only when the raw way vertices match normalized XY."""
    if raw_way.get("type") != "way":
        raise ValueError("OSM topology parent is not a way")
    raw_node_ids = raw_way.get("nodes")
    raw_geometry = raw_way.get("geometry")
    if (
        not isinstance(raw_node_ids, list)
        or not isinstance(raw_geometry, list)
        or len(raw_node_ids) < 2
        or len(raw_node_ids) != len(raw_geometry)
        or any(not isinstance(node_id, (str, int)) or isinstance(node_id, bool) for node_id in raw_node_ids)
    ):
        raise ValueError(f"OSM way {raw_way.get('id')!r} has missing or unaligned source node IDs")

    normalized = shape(normalized_geometry)
    if not isinstance(normalized, LineString) or normalized.is_empty:
        raise ValueError(f"OSM way {raw_way.get('id')!r} normalized geometry is not a LineString")
    normalized_coords = list(normalized.coords)
    if len(normalized_coords) != len(raw_geometry):
        raise ValueError(f"OSM way {raw_way.get('id')!r} geometry does not align with its source node IDs")

    for raw_point, projected_point in zip(raw_geometry, normalized_coords):
        if not isinstance(raw_point, Mapping):
            raise ValueError(f"OSM way {raw_way.get('id')!r} has a malformed source geometry point")
        try:
            expected_x, expected_y = transform(float(raw_point["lon"]), float(raw_point["lat"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"OSM way {raw_way.get('id')!r} has a malformed source geometry point") from exc
        if math.dist((expected_x, expected_y), (projected_point[0], projected_point[1])) > 0.01:
            raise ValueError(f"OSM way {raw_way.get('id')!r} geometry does not align with its source node IDs")
    return [str(node_id) for node_id in raw_node_ids]


def clean_osm_segments(
    features: Sequence[Mapping[str, Any]],
    *,
    topology_policy: str = "source_safe",
    segmentation_policy: str = "source_way_vertices_v1",
) -> list[SegmentFeature]:
    """Build analysis segments while preserving defensible junction identity.

    OSM ways use their source node IDs as the only junction evidence. Synthetic
    inputs may use geometric noding, but only when both intersecting features
    have an explicit, matching grade layer. ``legacy_r02_replay`` exists solely
    to re-derive the immutable historic R02 segment map and must not be used for
    new source analysis. ``osm_shared_nodes_candidate_v1`` is an experimental
    segmentation candidate: it retains shape vertices inside a polyline and
    splits an OSM way only at endpoints or nodes shared by distinct ways. It is
    not an approved project Space Syntax method.
    """
    if topology_policy not in {"source_safe", "legacy_r02_replay"}:
        raise ValueError(f"unsupported topology policy: {topology_policy}")
    if segmentation_policy not in {"source_way_vertices_v1", "osm_shared_nodes_candidate_v1"}:
        raise ValueError(f"unsupported segmentation policy: {segmentation_policy}")
    legacy_r02_replay = topology_policy == "legacy_r02_replay"
    if segmentation_policy == "osm_shared_nodes_candidate_v1" and legacy_r02_replay:
        raise ValueError("osm_shared_nodes_candidate_v1 cannot be combined with legacy_r02_replay")
    base_segments: list[SegmentFeature] = []

    source_ways_by_node: dict[str, set[str]] = {}
    candidate_way_ids: dict[int, str] = {}
    if segmentation_policy == "osm_shared_nodes_candidate_v1":
        seen_way_ids: set[str] = set()
        for idx, feat in enumerate(features):
            if not isinstance(feat, Mapping):
                raise ValueError("osm_shared_nodes_candidate_v1 requires feature mappings")
            geom_raw = feat.get("geometry")
            if geom_raw is None:
                raise ValueError("osm_shared_nodes_candidate_v1 features must include a non-empty LineString geometry")
            try:
                geom = shape(geom_raw) if isinstance(geom_raw, dict) else geom_raw
            except Exception as exc:
                raise ValueError("osm_shared_nodes_candidate_v1 features must include a non-empty LineString geometry") from exc
            if not isinstance(geom, LineString) or geom.is_empty or len(geom.coords) < 2:
                raise ValueError("osm_shared_nodes_candidate_v1 features must include a non-empty LineString geometry")
            if any(
                not math.isfinite(float(value))
                for coordinate in geom.coords
                for value in coordinate[:2]
            ):
                raise ValueError("osm_shared_nodes_candidate_v1 requires finite XY coordinates")
            coordinates = list(geom.coords)
            total_length = 0.0
            for start, end in zip(coordinates, coordinates[1:]):
                dx = float(end[0]) - float(start[0])
                dy = float(end[1]) - float(start[1])
                if not math.isfinite(dx) or not math.isfinite(dy):
                    raise ValueError("osm_shared_nodes_candidate_v1 requires finite segment lengths")
                total_length += math.hypot(dx, dy)
                if not math.isfinite(total_length):
                    raise ValueError("osm_shared_nodes_candidate_v1 requires finite segment lengths")
            if total_length <= 0:
                raise ValueError("osm_shared_nodes_candidate_v1 requires positive finite segment lengths")
            props = feat.get("properties", {})
            if not isinstance(props, Mapping):
                raise ValueError("osm_shared_nodes_candidate_v1 requires OSM way properties")
            if props.get("osm_type") != "way":
                raise ValueError("osm_shared_nodes_candidate_v1 requires OSM ways with aligned source node IDs")
            coords = list(geom.coords)
            raw_node_ids = props.get("osm_node_ids")
            if (
                not isinstance(raw_node_ids, list)
                or len(raw_node_ids) != len(coords)
                or any(not isinstance(node_id, (str, int)) or isinstance(node_id, bool) for node_id in raw_node_ids)
            ):
                raise ValueError("osm_shared_nodes_candidate_v1 requires OSM ways with aligned source node IDs")
            if any(not str(node_id).strip() for node_id in raw_node_ids):
                raise ValueError("osm_shared_nodes_candidate_v1 source node IDs must be non-empty")
            raw_way_id = props.get("osm_id", feat.get("id"))
            if (
                raw_way_id is None
                or isinstance(raw_way_id, bool)
                or not isinstance(raw_way_id, (str, int))
                or not str(raw_way_id).strip()
            ):
                raise ValueError("osm_shared_nodes_candidate_v1 requires a non-empty OSM way ID")
            way_id = str(raw_way_id)
            if way_id in seen_way_ids:
                raise ValueError(f"osm_shared_nodes_candidate_v1 requires unique OSM way IDs; duplicate {way_id!r}")
            seen_way_ids.add(way_id)
            candidate_way_ids[idx] = way_id
            for node_id in set(str(value) for value in raw_node_ids):
                source_ways_by_node.setdefault(node_id, set()).add(way_id)

    for idx, feat in enumerate(features):
        geom_raw = feat.get("geometry")
        if geom_raw is None:
            if segmentation_policy == "osm_shared_nodes_candidate_v1":
                raise ValueError("osm_shared_nodes_candidate_v1 features must include a non-empty LineString geometry")
            continue
        try:
            geom = shape(geom_raw) if isinstance(geom_raw, dict) else geom_raw
        except Exception as exc:
            if segmentation_policy == "osm_shared_nodes_candidate_v1":
                raise ValueError("osm_shared_nodes_candidate_v1 features must include a non-empty LineString geometry") from exc
            raise
        if not isinstance(geom, LineString) or geom.is_empty:
            if segmentation_policy == "osm_shared_nodes_candidate_v1":
                raise ValueError("osm_shared_nodes_candidate_v1 features must include a non-empty LineString geometry")
            continue

        props = feat.get("properties", {})
        raw_tags = props.get("tags", {})
        tags = raw_tags if isinstance(raw_tags, Mapping) else {}

        # Missing or malformed grade metadata remains unknown; it is never
        # silently converted to ground level.
        layer_tag = tags.get("layer") if "layer" in tags else props.get("layer")
        layer: int | None = None
        if layer_tag is not None:
            try:
                layer = int(str(layer_tag).strip())
            except ValueError:
                layer = 0 if legacy_r02_replay else None
        elif tags.get("bridge") == "yes":
            layer = 1
        elif tags.get("tunnel") == "yes":
            layer = -1
        elif legacy_r02_replay:
            layer = 0

        highway = tags.get("highway") or props.get("highway")
        oneway = tags.get("oneway") == "yes"

        coords = list(geom.coords)
        if len(coords) < 2:
            continue

        is_osm_way = props.get("osm_type") == "way" or isinstance(props.get("osm_node_ids"), list)
        node_ids: list[str] | None = None
        if segmentation_policy == "osm_shared_nodes_candidate_v1" and not is_osm_way:
            raise ValueError("osm_shared_nodes_candidate_v1 requires OSM ways with aligned source node IDs")
        if is_osm_way and not legacy_r02_replay:
            raw_node_ids = props.get("osm_node_ids")
            if (
                not isinstance(raw_node_ids, list)
                or len(raw_node_ids) != len(coords)
                or any(not isinstance(node_id, (str, int)) or isinstance(node_id, bool) for node_id in raw_node_ids)
            ):
                raise ValueError(f"OSM way {feat.get('id', idx)!r} must carry aligned source OSM node IDs")
            node_ids = [str(node_id) for node_id in raw_node_ids]

        if segmentation_policy == "osm_shared_nodes_candidate_v1":
            assert node_ids is not None
            way_id = candidate_way_ids[idx]
            if node_ids[0] == node_ids[-1]:
                split_indices = [
                    node_idx
                    for node_idx, node_id in enumerate(node_ids[:-1])
                    if len(source_ways_by_node.get(node_id, set())) > 1
                ]
                if len(split_indices) < 2 or len({node_ids[node_idx] for node_idx in split_indices}) < 2:
                    raise ValueError(
                        f"closed OSM way {way_id!r} requires at least two distinct shared source junctions"
                    )
                ranges: list[tuple[int, int, list[tuple[float, ...]]]] = []
                for range_idx, start_idx in enumerate(split_indices):
                    end_idx = split_indices[(range_idx + 1) % len(split_indices)]
                    if start_idx < end_idx:
                        part_coords = coords[start_idx : end_idx + 1]
                    elif end_idx == 0:
                        part_coords = coords[start_idx:]
                    else:
                        part_coords = coords[start_idx:] + coords[1 : end_idx + 1]
                    ranges.append((start_idx, end_idx, part_coords))
            else:
                split_indices = [0]
                split_indices.extend(
                    node_idx
                    for node_idx in range(1, len(node_ids) - 1)
                    if len(source_ways_by_node.get(node_ids[node_idx], set())) > 1
                )
                split_indices.append(len(node_ids) - 1)
                ranges = [
                    (start_idx, end_idx, coords[start_idx : end_idx + 1])
                    for start_idx, end_idx in zip(split_indices, split_indices[1:])
                ]
        else:
            # Historical default: split each source-way vertex for replay compatibility.
            ranges = [
                (seg_idx, seg_idx + 1, coords[seg_idx : seg_idx + 2])
                for seg_idx in range(len(coords) - 1)
            ]

        for seg_start, seg_end, part_coords in ranges:
            seg_geom = LineString(part_coords)
            length = round(seg_geom.length, 2)
            if length < 0.5:
                continue  # Skip microscopic slivers

            if segmentation_policy == "osm_shared_nodes_candidate_v1":
                fid = f"osm_{way_id}_seg_{seg_start}_{seg_end}"
            else:
                fid = f"osm_{feat.get('id', idx)}_seg_{seg_start}"
            base_segments.append(
                SegmentFeature(
                    id=fid,
                    geometry=seg_geom,
                    length_m=length,
                    layer=layer,
                    oneway=oneway,
                    highway=highway,
                    start_node_id=node_ids[seg_start] if node_ids is not None else None,
                    end_node_id=node_ids[seg_end] if node_ids is not None else None,
                )
            )

    if len(base_segments) < 2:
        return base_segments

    geometries = [segment.geometry for segment in base_segments]
    tree = STRtree(geometries)
    split_distances: list[list[float]] = [[0.0, geom.length] for geom in geometries]

    for left_idx, left_geom in enumerate(geometries):
        candidate_indices = tree.query(left_geom)
        for raw_right_idx in candidate_indices:
            right_idx = int(raw_right_idx)
            left_segment = base_segments[left_idx]
            right_segment = base_segments[right_idx]
            if right_idx <= left_idx:
                continue
            # Explicit OSM topology is authoritative. A coincident XY crossing
            # without a shared source node is not a junction. Unknown grade is
            # likewise insufficient evidence for geometric noding.
            if (
                left_segment.start_node_id is not None
                or left_segment.end_node_id is not None
                or right_segment.start_node_id is not None
                or right_segment.end_node_id is not None
                or left_segment.layer is None
                or right_segment.layer is None
                or left_segment.layer != right_segment.layer
            ):
                continue
            intersection = left_geom.intersection(geometries[right_idx])
            if isinstance(intersection, Point):
                points = [intersection]
            elif isinstance(intersection, MultiPoint):
                points = list(intersection.geoms)
            elif isinstance(intersection, GeometryCollection):
                points = [part for part in intersection.geoms if isinstance(part, Point)]
            else:
                # Collinear overlaps are not unambiguous junctions and are left
                # intact for source-level duplicate/overlap review.
                points = []
            for point in points:
                left_distance = left_geom.project(point)
                right_geom = geometries[right_idx]
                right_distance = right_geom.project(point)
                if 1e-6 < left_distance < left_geom.length - 1e-6:
                    split_distances[left_idx].append(left_distance)
                if 1e-6 < right_distance < right_geom.length - 1e-6:
                    split_distances[right_idx].append(right_distance)

    noded: list[SegmentFeature] = []
    for idx, segment in enumerate(base_segments):
        geom = geometries[idx]
        distances = sorted(split_distances[idx])
        unique_distances: list[float] = []
        for distance in distances:
            if not unique_distances or distance - unique_distances[-1] > 1e-6:
                unique_distances.append(distance)
        part_count = len(unique_distances) - 1
        for part_idx, (start, end) in enumerate(zip(unique_distances, unique_distances[1:])):
            start_point = geom.interpolate(start)
            end_point = geom.interpolate(end)
            part = geom if part_count == 1 else LineString([start_point, end_point])
            length = round(part.length, 2)
            if length < 0.5:
                continue
            segment_id = segment.id if part_count == 1 else f"{segment.id}_node_{part_idx}"
            noded.append(
                SegmentFeature(
                    id=segment_id,
                    geometry=part,
                    length_m=length,
                    layer=segment.layer,
                    oneway=segment.oneway,
                    highway=segment.highway,
                    start_node_id=(
                        segment.start_node_id if start <= 1e-6 else None
                    ),
                    end_node_id=(
                        segment.end_node_id if end >= geom.length - 1e-6 else None
                    ),
                )
            )

    return noded


def audit_source_topology(segments: Sequence[SegmentFeature]) -> dict[str, Any]:
    """Audit coincident geometries without converting them into connections."""
    if not segments:
        return {
            "readiness": "BLOCKED_EMPTY_NETWORK",
            "segment_count": 0,
            "unknown_grade_segment_count": 0,
            "shared_source_node_intersection_count": 0,
            "known_grade_separated_intersection_count": 0,
            "unresolved_intersection_count": 0,
            "overlap_count": 0,
            "overlapping_pairs": [],
            "unresolved_intersections": [],
        }

    geometries = [segment.geometry for segment in segments]
    tree = STRtree(geometries)
    unknown_grade_segment_count = sum(segment.layer is None for segment in segments)
    shared_node_intersection_count = 0
    grade_separated_intersection_count = 0
    overlap_count = 0
    overlapping_pairs: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    def points_from_intersection(geometry: Any) -> list[Point]:
        if isinstance(geometry, Point):
            return [geometry]
        if isinstance(geometry, (MultiPoint, GeometryCollection)):
            points: list[Point] = []
            for part in geometry.geoms:
                points.extend(points_from_intersection(part))
            return points
        if geometry.geom_type in {"LineString", "MultiLineString"} and not geometry.is_empty:
            return []
        return []

    def node_id_at(segment: SegmentFeature, point: Point) -> str | None:
        if segment.start_node_id is not None and math.dist(segment.start_coord, (point.x, point.y)) <= 0.01:
            return segment.start_node_id
        if segment.end_node_id is not None and math.dist(segment.end_coord, (point.x, point.y)) <= 0.01:
            return segment.end_node_id
        return None

    for left_index, left in enumerate(segments):
        for raw_right_index in tree.query(left.geometry):
            right_index = int(raw_right_index)
            if right_index <= left_index:
                continue
            right = segments[right_index]
            intersection = left.geometry.intersection(right.geometry)
            if intersection.is_empty:
                continue
            if intersection.geom_type in {"LineString", "MultiLineString"}:
                overlap_count += 1
                overlapping_pairs.append(
                    {
                        "left_segment_id": left.id,
                        "right_segment_id": right.id,
                        "overlap_length_m": round(float(intersection.length), 2),
                    }
                )
                continue
            for point in points_from_intersection(intersection):
                left_node = node_id_at(left, point)
                right_node = node_id_at(right, point)
                if left_node is not None and left_node == right_node:
                    shared_node_intersection_count += 1
                elif left.layer is not None and right.layer is not None and left.layer != right.layer:
                    grade_separated_intersection_count += 1
                else:
                    unresolved.append(
                        {
                            "left_segment_id": left.id,
                            "right_segment_id": right.id,
                            "point_epsg28992": [round(point.x, 4), round(point.y, 4)],
                            "left_node_id": left_node,
                            "right_node_id": right_node,
                            "left_layer": left.layer,
                            "right_layer": right.layer,
                        }
                    )

    if unresolved:
        readiness = "BLOCKED_UNRESOLVED_GRADE_OR_TOPOLOGY_CROSSINGS"
    elif overlap_count:
        readiness = "BLOCKED_OVERLAPPING_SEGMENT_REVIEW"
    else:
        readiness = "SOURCE_NODE_TOPOLOGY_CHECKED"
    return {
        "readiness": readiness,
        "segment_count": len(segments),
        "unknown_grade_segment_count": unknown_grade_segment_count,
        "shared_source_node_intersection_count": shared_node_intersection_count,
        "known_grade_separated_intersection_count": grade_separated_intersection_count,
        "unresolved_intersection_count": len(unresolved),
        "overlap_count": overlap_count,
        "overlapping_pairs": overlapping_pairs,
        "unresolved_intersections": unresolved,
    }


def compute_six_syntax_layers(
    segments: Sequence[SegmentFeature],
    *,
    calculate_radii_m: Sequence[float] | None = None,
    study_area_geometry: Any | None = None,
    acquisition_envelope_geometry: Any | None = None,
    extract_covers_envelope: bool | None = None,
    stability_validated_radii_m: Sequence[float] = (),
) -> dict[str, Any]:
    """Compute six layers while separating metric values from coverage readiness.

    The geometric envelope and radius-stability checks are reported only when
    the caller provides the StudyArea, the actual acquisition envelope, a
    retained extract-boundary containment check, and a boundary-stability
    assessment for the relevant radius. These checks do not establish OSM
    feature, semantic, or network completeness.
    """
    if extract_covers_envelope is not None and not isinstance(extract_covers_envelope, bool):
        raise ValueError("extract_covers_envelope must be true, false, or None")

    net = SegmentNetwork.from_features(segments)
    all_radii = [800.0, 2000.0, 10000.0]
    calculation_radii = all_radii if calculate_radii_m is None else [float(radius) for radius in calculate_radii_m]
    if not set(calculation_radii).issubset(set(all_radii)):
        raise ValueError("calculate_radii_m may contain only the configured 800m, 2000m, and 10000m radii")
    raw_results = calculate_segment_angular_measures(
        net,
        radii_m=calculation_radii,
    )

    layers_def = [
        ("syntax_local_800m_integration", 800.0, "nain", "Local Scale (800m) Angular Integration", "NAIN (normalized)"),
        ("syntax_local_800m_choice", 800.0, "nach", "Local Scale (800m) Angular Choice", "NACH (normalized)"),
        ("syntax_mid_2000m_integration", 2000.0, "nain", "Mid Scale (2000m) Angular Integration", "NAIN (normalized)"),
        ("syntax_mid_2000m_choice", 2000.0, "nach", "Mid Scale (2000m) Angular Choice", "NACH (normalized)"),
        ("syntax_regional_10000m_integration", 10000.0, "nain", "Regional Scale (10000m) Angular Integration", "NAIN (normalized)"),
        ("syntax_regional_10000m_choice", 10000.0, "nach", "Regional Scale (10000m) Angular Choice", "NACH (normalized)"),
    ]

    layers_output = []
    study_area = study_area_geometry
    acquisition_envelope = acquisition_envelope_geometry
    study_area_in_envelope = bool(
        study_area is not None
        and acquisition_envelope is not None
        and not study_area.is_empty
        and not acquisition_envelope.is_empty
        and acquisition_envelope.covers(study_area)
    )
    coverage_buffer_m = (
        float(study_area.distance(acquisition_envelope.boundary))
        if study_area_in_envelope
        else None
    )
    stability_radii = {float(radius) for radius in stability_validated_radii_m}
    analysis_segment_ids = {
        segment.id
        for segment in segments
        if study_area is None or segment.geometry.intersects(study_area)
    }

    for layer_id, radius, metric_key, title, unit in layers_def:
        was_calculated = radius in raw_results
        data_by_seg = raw_results.get(radius, {})
        scoped_data = {
            sid: result
            for sid, result in data_by_seg.items()
            if sid in analysis_segment_ids
        }
        values = [d.get(metric_key, 0.0) for d in scoped_data.values()]
        values_clean = [v for v in values if not math.isnan(v) and not math.isinf(v)]

        if values_clean:
            v_min = round(min(values_clean), 4)
            v_max = round(max(values_clean), 4)
            v_mean = round(sum(values_clean) / len(values_clean), 4)
            sorted_v = sorted(values_clean)
            q20 = round(sorted_v[int(len(sorted_v) * 0.2)], 4)
            q40 = round(sorted_v[int(len(sorted_v) * 0.4)], 4)
            q60 = round(sorted_v[int(len(sorted_v) * 0.6)], 4)
            q80 = round(sorted_v[int(len(sorted_v) * 0.8)], 4)
        else:
            v_min = v_max = v_mean = q20 = q40 = q60 = q80 = 0.0

        if not study_area_in_envelope:
            readiness = "BLOCKED_COVERAGE_EVIDENCE_ABSENT"
            limitations = "A verified StudyArea contained by an explicit acquisition envelope is required."
        elif extract_covers_envelope is None:
            readiness = "BLOCKED_EXTRACT_ENVELOPE_STATUS_UNKNOWN"
            limitations = "No retained extract-boundary test verifies containment of the requested analysis envelope."
        elif not extract_covers_envelope:
            readiness = "BLOCKED_EXTRACT_ENVELOPE_NOT_COVERED"
            limitations = "The retained extract boundary does not contain the requested analysis envelope."
        elif coverage_buffer_m is None or coverage_buffer_m + 1e-6 < radius:
            readiness = "EDGE_AFFECTED_INSUFFICIENT_ACQUISITION_BUFFER"
            limitations = (
                f"StudyArea-to-acquisition-boundary clearance is {coverage_buffer_m or 0.0:.1f}m, "
                f"below the {radius:.0f}m metric radius."
            )
        elif radius not in stability_radii:
            readiness = "BLOCKED_BOUNDARY_STABILITY_UNASSESSED"
            limitations = "Boundary stability has not been demonstrated for this metric radius."
        else:
            readiness = "BLOCKED_SOURCE_COMPLETENESS_UNVERIFIED"
            limitations = (
                "The extract boundary contains the requested envelope and radius stability was checked, "
                "but this does not establish OSM feature, semantic, or network completeness."
            )

        segment_values = {sid: d.get(metric_key, 0.0) for sid, d in scoped_data.items()}

        layers_output.append(
            {
                "layer_id": layer_id,
                "title": title,
                "scale": "local" if radius == 800.0 else ("mid" if radius == 2000.0 else "regional"),
                "radius_m": radius,
                "metric_key": metric_key,
                "unit": unit,
                "calculation_status": "COMPUTED" if was_calculated else "NOT_COMPUTED_COVERAGE_BLOCKED",
                "data_readiness": readiness,
                "limitations": limitations,
                "coverage_buffer_m": coverage_buffer_m,
                "coverage_scope": "study_area_segments" if study_area is not None else "all_source_segments",
                "formula_version": "turner-2007-angular-segment-v1",
                "legend_breaks": [v_min, q20, q40, q60, q80, v_max],
                "statistics": {
                    "min": v_min,
                    "max": v_max,
                    "mean": v_mean,
                    "count": len(segment_values),
                },
                "segment_values": segment_values,
            }
        )

    return {
        "network_segment_count": len(segments),
        "analysis_segment_count": len(analysis_segment_ids),
        "coverage_buffer_m": coverage_buffer_m,
        "extract_covers_envelope": extract_covers_envelope,
        "stability_validated_radii_m": sorted(stability_radii),
        "layers": layers_output,
    }
