"""PST-based Space Syntax calculation for 6 mandatory layers (WC-3, PD-15).

Implements authoritative Space Syntax calculations via pinned PST 3.3.1 runtime:
- Uses walking radius mode (shortest network distance in metres).
- Angular turn cost: degrees / 90.0.
- Normalization:
  - NAIN = NC^1.2 / (TD + 2.0)  [where NC = PST_node_count - 1]
  - NACH = ln(Choice/2 + 1) / ln(TD + 3.0)  [where Choice = PST_choice / 2]
- Splits closed loops (coords[0] == coords[-1]) to ensure strictly non-zero segment lengths.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence
from shapely.geometry import LineString, shape

from .syntax_engines.pst_adapter import (
    MetricMode,
    PSTAdapter,
    PSTLine,
    PSTRequest,
    PSTResult,
)

DEFAULT_PST_MANIFEST = Path(__file__).resolve().parents[2] / "config/runtimes/pstalgo-3.3.1.json"


def _clean_coordinates(coords: Sequence[tuple[float, float] | list[float]]) -> list[tuple[float, float]]:
    if not coords:
        return []
    clean: list[tuple[float, float]] = [(float(coords[0][0]), float(coords[0][1]))]
    for p in coords[1:]:
        pt = (float(p[0]), float(p[1]))
        if pt != clean[-1]:
            clean.append(pt)
    return clean


def prepare_pst_lines(
    features: Sequence[Mapping[str, Any]],
    *,
    return_excluded: bool = False,
) -> tuple[PSTLine, ...] | tuple[tuple[PSTLine, ...], list[dict[str, Any]]]:
    """Convert GeoJSON-like line features into PSTLine inputs, splitting closed loops and excluding redundant/degenerate lines."""
    candidate_lines: list[PSTLine] = []
    excluded_records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for idx, feat in enumerate(features):
        geom_raw = feat.get("geometry")
        if geom_raw is None:
            continue
        geom = shape(geom_raw) if isinstance(geom_raw, dict) else geom_raw
        if not isinstance(geom, LineString) or geom.is_empty or len(geom.coords) < 2:
            continue

        raw_coords = list(geom.coords)
        base_id = str(feat.get("id") or feat.get("properties", {}).get("osm_id") or f"feature_{idx}")
        way_id = base_id
        suffix_idx = 1
        while way_id in seen_ids:
            way_id = f"{base_id}_{suffix_idx}"
            suffix_idx += 1

        clean_coords = _clean_coordinates(raw_coords)
        if len(clean_coords) < 2:
            seen_ids.add(way_id)
            excluded_records.append({"id": way_id, "reason": "zero_length"})
            continue

        # If it's a closed ring:
        if clean_coords[0] == clean_coords[-1]:
            if len(clean_coords) < 4:
                # Degenerate loop (fewer than 4 vertices, cannot form valid polygon ring)
                seen_ids.add(way_id)
                excluded_records.append({"id": way_id, "reason": "degenerate_collapsed_loop"})
                continue
            mid = len(clean_coords) // 2
            id_a, id_b = f"{way_id}_a", f"{way_id}_b"
            seen_ids.add(id_a)
            seen_ids.add(id_b)
            coords_a = tuple(clean_coords[: mid + 1])
            coords_b = tuple(clean_coords[mid:])
            if coords_b == tuple(reversed(coords_a)):
                candidate_lines.append(PSTLine(id=id_a, coordinates=coords_a))
                excluded_records.append({"id": id_b, "reason": "degenerate_collapsed_loop"})
            else:
                candidate_lines.append(PSTLine(id=id_a, coordinates=coords_a))
                candidate_lines.append(PSTLine(id=id_b, coordinates=coords_b))
        else:
            seen_ids.add(way_id)
            candidate_lines.append(PSTLine(id=way_id, coordinates=tuple(clean_coords)))

    def get_segments(coords: Sequence[tuple[float, float]]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        segs = []
        for i in range(len(coords) - 1):
            p1 = (round(coords[i][0], 3), round(coords[i][1], 3))
            p2 = (round(coords[i + 1][0], 3), round(coords[i + 1][1], 3))
            if p1 != p2:
                segs.append(tuple(sorted([p1, p2])))
        return segs

    line_segs = {l.id: get_segments(l.coordinates) for l in candidate_lines}
    seg_counts: dict[tuple[tuple[float, float], tuple[float, float]], int] = {}
    for segs in line_segs.values():
        for s in segs:
            seg_counts[s] = seg_counts.get(s, 0) + 1

    def sort_key(item: tuple[int, PSTLine]):
        orig_idx, l = item
        segs = line_segs[l.id]
        unique_count = sum(1 for s in segs if seg_counts[s] == 1)
        is_split_half = l.id.endswith("_a") or l.id.endswith("_b")
        return (unique_count > 0, not is_split_half, len(segs), -orig_idx)

    indexed_candidates = list(enumerate(candidate_lines))
    sorted_candidates = [l for _, l in sorted(indexed_candidates, key=sort_key, reverse=True)]

    registered_segs: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    kept_line_ids: set[str] = set()

    for l in sorted_candidates:
        segs = line_segs[l.id]
        if not segs:
            excluded_records.append({"id": l.id, "reason": "zero_length"})
            continue
        if all(s in registered_segs for s in segs):
            excluded_records.append({"id": l.id, "reason": "duplicate_segments"})
        else:
            kept_line_ids.add(l.id)
            registered_segs.update(segs)

    final_lines = tuple(l for l in candidate_lines if l.id in kept_line_ids)
    if return_excluded:
        return final_lines, excluded_records
    return final_lines


def compute_pst_six_syntax_layers(
    features: Sequence[Mapping[str, Any]],
    *,
    calculate_radii_m: Sequence[float] = (800.0,),
    unlinks: Sequence[tuple[float, float]] = (),
    study_area_geometry: Any | None = None,
    acquisition_envelope_geometry: Any | None = None,
    extract_covers_envelope: bool = False,
    stability_validated_radii_m: Sequence[float] = (),
    pst_manifest_path: Path | None = None,
    metric_mode: MetricMode = "both",
) -> dict[str, Any]:
    """Compute syntax layers using pinned PST 3.3.1 adapter."""
    manifest_path = pst_manifest_path or DEFAULT_PST_MANIFEST
    adapter = PSTAdapter(manifest_path=manifest_path)

    pst_lines, excluded_lines = prepare_pst_lines(features, return_excluded=True)
    if not pst_lines:
        raise ValueError("No valid line features provided for PST syntax analysis")

    all_radii = [800.0, 2000.0, 10000.0]
    calc_radii = [float(r) for r in calculate_radii_m]
    if not set(calc_radii).issubset(set(all_radii)):
        raise ValueError("calculate_radii_m may contain only 800m, 2000m, and 10000m")

    # Run PST for each requested radius
    pst_results: dict[float, PSTResult] = {}
    unlink_tuples = tuple(unlinks)
    for r in calc_radii:
        req = PSTRequest(
            lines=pst_lines,
            radius_m=r,
            radius_mode="walking",
            unlinks=unlink_tuples,
            metric_mode=metric_mode,
        )
        pst_results[r] = adapter.compute(req)

    # Reference segments from the first result
    ref_result = next(iter(pst_results.values()))
    segments = ref_result.segments
    segment_ids = [s.id for s in segments]

    study_area = shape(study_area_geometry) if isinstance(study_area_geometry, dict) else study_area_geometry
    acquisition_envelope = (
        shape(acquisition_envelope_geometry)
        if isinstance(acquisition_envelope_geometry, dict)
        else acquisition_envelope_geometry
    )

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
    stability_radii = {float(r) for r in stability_validated_radii_m}

    # Filter to segments intersecting study_area if provided
    analysis_segment_indices: list[int] = []
    for idx, seg in enumerate(segments):
        if study_area is None:
            analysis_segment_indices.append(idx)
        else:
            seg_line = LineString([seg.start, seg.end])
            if seg_line.intersects(study_area):
                analysis_segment_indices.append(idx)

    layers_def = [
        ("syntax_local_800m_integration", 800.0, "nain", "Local Scale (800m) Angular Integration", "NAIN (normalized)"),
        ("syntax_local_800m_choice", 800.0, "nach", "Local Scale (800m) Angular Choice", "NACH (normalized)"),
        ("syntax_mid_2000m_integration", 2000.0, "nain", "Mid Scale (2000m) Angular Integration", "NAIN (normalized)"),
        ("syntax_mid_2000m_choice", 2000.0, "nach", "Mid Scale (2000m) Angular Choice", "NACH (normalized)"),
        ("syntax_regional_10000m_integration", 10000.0, "nain", "Regional Scale (10000m) Angular Integration", "NAIN (normalized)"),
        ("syntax_regional_10000m_choice", 10000.0, "nach", "Regional Scale (10000m) Angular Choice", "NACH (normalized)"),
    ]

    layers_output = []
    for layer_id, radius, metric_key, title, unit in layers_def:
        was_calculated = radius in pst_results
        segment_values: dict[str, float] = {}

        if was_calculated:
            res = pst_results[radius]
            for seg_idx in analysis_segment_indices:
                sid = segment_ids[seg_idx]
                nc_raw = res.node_counts[seg_idx]
                td = res.total_depths[seg_idx]
                choice_raw = res.choices[seg_idx]

                # Harmonization per method manifest:
                nc = max(0, nc_raw - 1)
                choice = choice_raw / 2.0

                if metric_key == "nain":
                    val = (nc ** 1.2) / (td + 2.0) if (nc > 0 and td > 0) else 0.0
                elif metric_key == "nach":
                    val = math.log(choice + 1.0) / math.log(td + 3.0) if (choice > 0 and td > 0) else 0.0
                else:
                    val = 0.0
                segment_values[sid] = round(val, 6)

        values_clean = [v for v in segment_values.values() if math.isfinite(v)]
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
        elif not extract_covers_envelope:
            readiness = "BLOCKED_EXTRACT_ENVELOPE_COVERAGE_UNVERIFIED"
            limitations = (
                "The regional extract is not verified to cover this analysis envelope; "
                "the input does not establish OSM feature completeness or semantics."
            )
        elif coverage_buffer_m is None or coverage_buffer_m + 1e-6 < radius:
            readiness = "EDGE_AFFECTED_INSUFFICIENT_ACQUISITION_BUFFER"
            limitations = f"StudyArea-to-acquisition-boundary clearance is {coverage_buffer_m or 0.0:.1f}m, below {radius:.0f}m radius."
        elif radius not in stability_radii:
            readiness = "BLOCKED_BOUNDARY_STABILITY_UNASSESSED"
            limitations = "Boundary stability has not been demonstrated for this metric radius."
        else:
            readiness = "EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY"
            limitations = (
                "The regional extract envelope contains the StudyArea with the required radius clearance "
                "and radius-specific stability was assessed; OSM feature completeness and semantics are not established."
            )

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
                "formula_version": "pstalgo-3.3.1-walking-radius-v1",
                "engine": "PST 3.3.1",
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
        "engine": "PST 3.3.1",
        "method_manifest": "config/runtimes/pst-method-manifest-v1.json",
        "network_segment_count": len(segments),
        "analysis_segment_count": len(analysis_segment_indices),
        "coverage_buffer_m": coverage_buffer_m,
        "extract_covers_envelope": extract_covers_envelope,
        "stability_validated_radii_m": sorted(stability_radii),
        "excluded_lines": excluded_lines,
        "layers": layers_output,
    }
