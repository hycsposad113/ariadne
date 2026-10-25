#!/usr/bin/env python3
"""Render a Syntax figure only from an explicitly linked source/result bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from shapely.geometry import shape

from urban_design.context_network import clean_osm_segments
from urban_design.figure_export import render_site_syntax_figure


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def render_formal_syntax_figure(
    output_path: Path,
    *,
    study_area_geojson_path: Path,
    context_geojson_path: Path,
    source_manifest_path: Path,
    syntax_result_path: Path,
    layer_id: str = "syntax_local_800m_integration",
    min_coverage_pct: float = 0.0,
) -> dict[str, Any]:
    """Render a deterministic figure after proving source/result/segment alignment.

    No historical file paths are implicit. Every source is supplied by the caller,
    and `source_manifest` carries the verified parent identities and hashes.
    """
    study_area_geojson_path = Path(study_area_geojson_path)
    context_geojson_path = Path(context_geojson_path)
    source_manifest_path = Path(source_manifest_path)
    syntax_result_path = Path(syntax_result_path)
    source_manifest = _load_json(source_manifest_path)
    syntax_result = _load_json(syntax_result_path)
    study_doc = _load_json(study_area_geojson_path)
    context_doc = _load_json(context_geojson_path)

    if "source_complete" in syntax_result:
        raise ValueError("obsolete source_complete flag is not accepted; use extract_covers_envelope")
    extract_covers_envelope = syntax_result.get("extract_covers_envelope")
    if "extract_covers_envelope" not in syntax_result or (
        extract_covers_envelope is not None and not isinstance(extract_covers_envelope, bool)
    ):
        raise ValueError("syntax result must declare extract_covers_envelope as true, false, or null")

    source_manifest_sha256 = _sha256(source_manifest_path)
    study_area_sha256 = _sha256(study_area_geojson_path)
    context_sha256 = _sha256(context_geojson_path)
    if syntax_result.get("source_manifest_sha256") != source_manifest_sha256:
        raise ValueError("syntax result does not reference the supplied source manifest hash")
    if source_manifest.get("study_area_geojson_sha256") != study_area_sha256:
        raise ValueError("source manifest StudyArea hash does not match the supplied geometry")
    if source_manifest.get("context_geojson_sha256") != context_sha256:
        raise ValueError("source manifest context hash does not match the supplied network")
    for key in ("package_id", "package_revision", "study_area_id", "crs"):
        if syntax_result.get(key) != source_manifest.get(key):
            raise ValueError(f"syntax result {key} does not match its source manifest")
    if source_manifest.get("crs") != "EPSG:28992":
        raise ValueError("figure source CRS must be EPSG:28992")
    if syntax_result.get("study_area_geojson_sha256") != study_area_sha256:
        raise ValueError("syntax result does not reference the supplied StudyArea bytes")
    if syntax_result.get("context_geojson_sha256") != context_sha256:
        raise ValueError("syntax result does not reference the supplied context bytes")

    mapping = source_manifest.get("segment_mapping")
    if not isinstance(mapping, Mapping) or not mapping:
        raise ValueError("source manifest has no segment-to-source mapping")
    features = context_doc.get("features")
    if not isinstance(features, list):
        raise ValueError("context GeoJSON has no features array")
    cleaned_segments = clean_osm_segments(features)
    if not cleaned_segments:
        raise ValueError("context source produced no cleaned segments")

    source_ids_by_feature_id = {
        str(feature.get("id")): str(
            (feature.get("properties") or {}).get("source_feature_id") or feature.get("id") or ""
        )
        for feature in features
    }
    for segment in cleaned_segments:
        parent = mapping.get(segment.id)
        if not isinstance(parent, Mapping):
            raise ValueError(f"cleaned segment {segment.id!r} has no source mapping")
        cleaning_feature_id = segment.id.removeprefix("osm_").split("_seg_", 1)[0]
        source_feature_id = source_ids_by_feature_id.get(cleaning_feature_id)
        if not source_feature_id:
            raise ValueError(f"cleaned segment {segment.id!r} has no source feature identity")
        if parent.get("source_feature_id") != source_feature_id:
            raise ValueError(f"cleaned segment {segment.id!r} maps to the wrong source feature")
        if not parent.get("source_artifact_id") or not parent.get("source_snapshot_id"):
            raise ValueError(f"cleaned segment {segment.id!r} has incomplete parent references")

    layers = syntax_result.get("layers")
    if not isinstance(layers, list):
        raise ValueError("syntax result has no layers array")
    layers_by_id = {layer.get("layer_id"): layer for layer in layers if isinstance(layer, Mapping)}
    if layer_id not in layers_by_id:
        raise KeyError(f"Layer {layer_id!r} not found in {sorted(str(key) for key in layers_by_id)}")
    selected_layer = layers_by_id[layer_id]
    if selected_layer.get("calculation_status") != "COMPUTED":
        raise ValueError("selected Syntax layer has not been computed")
    segment_values = selected_layer.get("segment_values")
    if not isinstance(segment_values, Mapping):
        raise ValueError("selected syntax layer has no segment_values mapping")
    unknown_result_ids = set(segment_values) - set(mapping)
    if unknown_result_ids:
        raise ValueError(f"syntax result includes unmapped segments: {sorted(unknown_result_ids)[:5]}")
    values = [float(value) for value in segment_values.values() if value is not None and math.isfinite(float(value))]
    statistics = selected_layer.get("statistics") or {}
    if values and (
        not math.isclose(min(values), float(statistics.get("min")), abs_tol=1e-4)
        or not math.isclose(max(values), float(statistics.get("max")), abs_tol=1e-4)
    ):
        raise ValueError("syntax layer statistics do not match its segment values")

    readiness = str(selected_layer.get("data_readiness", "BLOCKED_READINESS_UNDECLARED"))
    radius_m = float(selected_layer.get("radius_m", 0.0))
    if readiness == "VALIDATED_COVERAGE":
        buffer_m = syntax_result.get("coverage_buffer_m")
        stability_radii = {float(value) for value in syntax_result.get("stability_validated_radii_m", [])}
        if (
            extract_covers_envelope is not True
            or buffer_m is None
            or float(buffer_m) < radius_m
            or radius_m not in stability_radii
            or not source_manifest.get("source_completeness_evidence")
            or radius_m not in {
                float(value) for value in source_manifest.get("boundary_stability_evidence_by_radius_m", {})
            }
        ):
            raise ValueError("VALIDATED_COVERAGE lacks matching extract-envelope/completeness/stability evidence")

    study_geometry = shape(study_doc.get("geometry", study_doc))
    from shapely.geometry import box as make_box

    minx, miny, maxx, maxy = study_geometry.bounds
    view_box = make_box(minx - 120.0, miny - 120.0, maxx + 120.0, maxy + 120.0)
    display_segments = [segment for segment in cleaned_segments if segment.geometry.intersects(view_box)]
    valued_count = 0
    joined_segments = []
    for segment in display_segments:
        value = segment_values.get(segment.id)
        if value is not None:
            value = float(value)
            if not math.isfinite(value):
                value = None
        if value is not None:
            valued_count += 1
        joined_segments.append({"id": segment.id, "geometry": segment.geometry, "value": value})

    total_segments = len(display_segments)
    coverage_pct = valued_count / total_segments * 100.0 if total_segments else 0.0
    if coverage_pct < min_coverage_pct:
        raise ValueError(
            f"Mapped segment value coverage {coverage_pct:.1f}% is below required {min_coverage_pct:.1f}%"
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    render = render_site_syntax_figure(
        study_area_geom=study_geometry,
        study_area_id=str(source_manifest["study_area_id"]),
        segments_data=joined_segments,
        metric_name=f"{selected_layer.get('title', layer_id)} · R={radius_m:g}m",
        output_path=output_path,
        title="Rotterdam M4H — Space Syntax (Source-Linked)",
        subtitle=f"{selected_layer.get('metric_key')} · {readiness}",
        revision=str(source_manifest["package_revision"]),
        validation_status=readiness,
        source_label=(
            f"Package {source_manifest['package_id']} · {len(mapping)} mapped segments"
        ),
    )
    svg_path = output_path.with_suffix(".svg")
    svg_content = svg_path.read_text(encoding="utf-8")
    stroke_colors = set(re.findall(r'stroke="(#[0-9a-fA-F]{6})"', svg_content))
    data_colors = stroke_colors - {"#94a3b8", "#cbd5e1", "#86efac", "#ffffff"}

    formal_result_eligible = readiness == "VALIDATED_COVERAGE"
    return {
        "status": "RENDERED" if formal_result_eligible else "EXPLORATORY_RENDERED",
        "formal_result_eligible": formal_result_eligible,
        "exploratory_only": not formal_result_eligible,
        "layer_id": layer_id,
        "radius_m": radius_m,
        "data_readiness": readiness,
        "total_segments": total_segments,
        "valued_segments": valued_count,
        "unvalued_segment_ids": [item["id"] for item in joined_segments if item["value"] is None],
        "coverage_pct": round(coverage_pct, 2),
        "data_colors_count": len(data_colors),
        "distinct_colors": sorted(data_colors),
        "min_value": min(values) if values else None,
        "max_value": max(values) if values else None,
        "study_area_sha256": study_area_sha256,
        "context_sha256": context_sha256,
        "source_manifest_sha256": source_manifest_sha256,
        "syntax_result_sha256": _sha256(syntax_result_path),
        "png_path": str(output_path),
        "png_sha256": _sha256(output_path),
        "svg_path": str(svg_path),
        "svg_sha256": _sha256(svg_path),
        "render_metadata": render,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a source-linked Space Syntax figure.")
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--study-area", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--syntax-result", type=Path, required=True)
    parser.add_argument("--layer", "-l", default="syntax_local_800m_integration")
    args = parser.parse_args()
    result = render_formal_syntax_figure(
        args.output,
        study_area_geojson_path=args.study_area,
        context_geojson_path=args.context,
        source_manifest_path=args.source_manifest,
        syntax_result_path=args.syntax_result,
        layer_id=args.layer,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
