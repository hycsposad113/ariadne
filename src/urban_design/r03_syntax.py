"""Verified R02 Syntax lineage exposed explicitly as exploratory R03 data."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from shapely.geometry import box, shape

from .context_network import clean_osm_segments
from .geometry import canonical_geometry_hash
from .workspace_sources import WorkspaceSourceCatalog, WorkspaceSourceError


class SyntaxEvidenceError(ValueError):
    """Historical Syntax bytes cannot be aligned with current verified sources."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyntaxEvidenceError(f"Syntax evidence file is missing or invalid: {path}") from exc
    if not isinstance(value, dict):
        raise SyntaxEvidenceError(f"Syntax evidence file is not an object: {path}")
    return value


def _verify_r02_package_files(project_root: Path, r02_root: Path) -> tuple[dict[str, Any], str]:
    manifest_path = r02_root / "integrity-manifest.json"
    manifest = _read_json(manifest_path)
    manifest_sha = sha256_file(manifest_path)
    errors = []
    for entry in manifest.get("files", []):
        if not isinstance(entry, Mapping):
            errors.append("invalid R02 package file entry")
            continue
        rel = Path(str(entry.get("path", "")))
        path = r02_root / rel
        if rel.is_absolute() or ".." in rel.parts or not path.is_file():
            errors.append(f"R02 package file missing or unsafe: {rel}")
            continue
        if path.stat().st_size != entry.get("size_bytes") or sha256_file(path) != entry.get("sha256"):
            errors.append(f"R02 package file hash mismatch: {rel}")
    if len(manifest.get("files", [])) != 31:
        errors.append("R02 package must retain its 31-file frozen manifest")
    if errors:
        raise SyntaxEvidenceError("R02 historical package is not byte intact: " + "; ".join(errors[:5]))
    return manifest, manifest_sha


def load_verified_exploratory_syntax(
    project_root: Path,
    catalog: WorkspaceSourceCatalog,
) -> dict[str, Any]:
    """Validate all R02 package bytes, then expose only its actual computed layers."""
    r02_root = project_root / "artifacts/week4-repair-r02"
    _manifest, manifest_sha = _verify_r02_package_files(project_root, r02_root)
    if manifest_sha != "3080e17b7840efcaee66b762e7fad08a95acc0083bbf796149dc076e334454c4":
        raise SyntaxEvidenceError("R02 integrity manifest hash differs from the frozen CP0 capture")

    syntax_dir = r02_root / "syntax"
    source_path = syntax_dir / "source-manifest.json"
    context_path = syntax_dir / "context.geojson"
    study_path = syntax_dir / "study-area.geojson"
    result_path = syntax_dir / "syntax-result.json"
    figure_review_path = syntax_dir / "figure-review-report.json"
    source = _read_json(source_path)
    context = _read_json(context_path)
    study_doc = _read_json(study_path)
    result = _read_json(result_path)
    figure_review = _read_json(figure_review_path)
    source_sha = sha256_file(source_path)
    context_sha = sha256_file(context_path)
    study_sha = sha256_file(study_path)
    result_sha = sha256_file(result_path)

    for field, expected in (
        ("package_id", catalog.package_id),
        ("package_revision", catalog.package_revision),
        ("study_area_id", catalog.study_area_id),
        ("project_id", catalog.project_id),
        ("crs", "EPSG:28992"),
    ):
        if source.get(field) != expected or result.get(field) != expected:
            raise SyntaxEvidenceError(f"R02 Syntax {field} does not match current verified spatial-r01")
    if source.get("spatial_r01_manifest_sha256") != sha256_file(catalog.package_root / "source-and-integrity-manifest.json"):
        raise SyntaxEvidenceError("R02 Syntax does not reference the current spatial-r01 integrity manifest")
    if source.get("study_area_geojson_sha256") != study_sha or result.get("study_area_geojson_sha256") != study_sha:
        raise SyntaxEvidenceError("R02 Syntax StudyArea file hash chain is inconsistent")
    if source.get("context_geojson_sha256") != context_sha or result.get("context_geojson_sha256") != context_sha:
        raise SyntaxEvidenceError("R02 Syntax context file hash chain is inconsistent")
    if result.get("source_manifest_sha256") != source_sha:
        raise SyntaxEvidenceError("R02 Syntax result does not reference its source manifest")
    study_geometry = shape(study_doc.get("geometry", study_doc))
    if canonical_geometry_hash(study_geometry.__geo_interface__) != catalog.study_area_geometry_sha256:
        raise SyntaxEvidenceError("R02 Syntax geometry is not the active StudyArea v5 geometry")

    source_artifacts = {str(item.get("id")): item for item in source.get("source_artifacts", [])}
    source_snapshots = {str(item.get("id")): item for item in source.get("source_snapshots", [])}
    normalized_road_ids = {
        artifact_id for artifact_id, record in catalog.normalized_artifacts.items()
        if str(record.get("uri", "")).endswith("/osm-overpass-v5-epsg28992.geojson")
    }
    for artifact_id in normalized_road_ids:
        actual = catalog.normalized_artifacts[artifact_id]
        declared = source_artifacts.get(artifact_id)
        if not declared or declared.get("sha256") != actual.get("sha256"):
            raise SyntaxEvidenceError("R02 Syntax road Artifact does not match current spatial-r01")
    if source.get("source_completeness_evidence") is not None or source.get("boundary_stability_evidence_by_radius_m"):
        raise SyntaxEvidenceError("R02 contains unexpected completeness or radius-stability evidence")

    context_features = context.get("features")
    if not isinstance(context_features, list):
        raise SyntaxEvidenceError("R02 Syntax context GeoJSON has no features")
    # This mode exists only to reproduce and validate the immutable historical
    # R02 mapping. It is not the topology policy for new source analysis.
    segments = clean_osm_segments(context_features, topology_policy="legacy_r02_replay")
    mapping = source.get("segment_mapping")
    if not isinstance(mapping, Mapping) or set(mapping) != {item.id for item in segments}:
        raise SyntaxEvidenceError("R02 Syntax segment-to-source mapping does not cover the context network")
    source_feature_ids = {
        str(feature.get("id")): str((feature.get("properties") or {}).get("source_feature_id") or feature.get("id") or "")
        for feature in context_features
    }
    syntax_segments = []
    for segment in segments:
        parent = mapping.get(segment.id)
        source_feature_id = source_feature_ids.get(segment.id.removeprefix("osm_").split("_seg_", 1)[0])
        if not isinstance(parent, Mapping) or not source_feature_id or parent.get("source_feature_id") != source_feature_id:
            raise SyntaxEvidenceError(f"R02 Syntax segment {segment.id!r} has an invalid source mapping")
        artifact_id = str(parent.get("source_artifact_id") or "")
        snapshot_id = str(parent.get("source_snapshot_id") or "")
        try:
            feature = catalog.resolve_feature(source_feature_id, "road", artifact_id)
        except WorkspaceSourceError as exc:
            raise SyntaxEvidenceError(f"R02 Syntax segment parent is not selectable in spatial-r01: {segment.id}") from exc
        if feature.source_snapshot_id != snapshot_id:
            raise SyntaxEvidenceError(f"R02 Syntax segment snapshot parent mismatch: {segment.id}")
        if artifact_id not in source_artifacts or snapshot_id not in source_snapshots:
            raise SyntaxEvidenceError(f"R02 Syntax segment references an undeclared parent: {segment.id}")
        syntax_segments.append({
            "id": segment.id,
            "geometry": segment.geometry.__geo_interface__,
            "length_m": float(segment.length_m),
            "layer": segment.layer,
            "highway": segment.highway,
            "feature_kind": "syntax-segment",
            "source_feature_id": source_feature_id,
            "source_artifact_id": artifact_id,
            "source_snapshot_id": snapshot_id,
            "lineage_status": "VERIFIED_SUBSET_EXPLORATORY",
        })

    layer_records = result.get("layers")
    if not isinstance(layer_records, list) or len(layer_records) != 6:
        raise SyntaxEvidenceError("R02 Syntax result must preserve the six-layer plan")
    layers = []
    layer_plan = []
    for raw_layer in layer_records:
        if not isinstance(raw_layer, Mapping):
            raise SyntaxEvidenceError("R02 Syntax result contains an invalid layer record")
        values = raw_layer.get("segment_values")
        if not isinstance(values, Mapping):
            raise SyntaxEvidenceError("R02 Syntax segment values are invalid")
        radius = float(raw_layer.get("radius_m", 0))
        computed = raw_layer.get("calculation_status") == "COMPUTED"
        if radius == 800.0:
            if not computed or raw_layer.get("data_readiness") != "BLOCKED_COVERAGE_EVIDENCE_ABSENT":
                raise SyntaxEvidenceError("800 m Syntax must remain computed exploratory output with insufficient coverage")
            if set(values) - set(mapping):
                raise SyntaxEvidenceError("800 m Syntax values cite an unmapped segment")
            if len(values) != int((raw_layer.get("statistics") or {}).get("count", -1)):
                raise SyntaxEvidenceError("800 m Syntax values and statistics count do not match")
            if any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in values.values()):
                raise SyntaxEvidenceError("800 m Syntax contains a non-finite result")
            layer = {
                **dict(raw_layer),
                "exploratory_only": True,
                "formal_result_eligible": False,
                "topology_status": "UNVERIFIED_LEGACY_COORDINATE_NODING",
                "blocking_conditions": [
                    "BLOCKED_COVERAGE_EVIDENCE_ABSENT",
                    "BLOCKED_TOPOLOGY_PROVENANCE_UNVERIFIED",
                ],
                "limitations": (
                    str(raw_layer.get("limitations", ""))
                    + " Historical R02 geometry noding predates source OSM node identity and is not topology-validated."
                ).strip(),
                "source_manifest_sha256": source_sha,
                "syntax_result_sha256": result_sha,
                "coverage_message": "EXPLORATORY ONLY — source coverage is insufficient for formal Rotterdam conclusions.",
            }
            layers.append(layer)
            layer_plan.append({
                "layer_id": raw_layer.get("layer_id"),
                "radius_m": radius,
                "metric_key": raw_layer.get("metric_key"),
                "calculation_status": "COMPUTED",
                "data_readiness": "BLOCKED_COVERAGE_EVIDENCE_ABSENT",
                "segment_value_count": len(values),
                "formal_result_eligible": False,
                "exploratory_only": True,
                "topology_status": "UNVERIFIED_LEGACY_COORDINATE_NODING",
            })
        else:
            if computed or raw_layer.get("calculation_status") != "NOT_COMPUTED_COVERAGE_BLOCKED" or values:
                raise SyntaxEvidenceError("2 km and 10 km Syntax must remain explicitly uncomputed with no values")
            layer_plan.append({
                "layer_id": raw_layer.get("layer_id"),
                "radius_m": radius,
                "metric_key": raw_layer.get("metric_key"),
                "calculation_status": "NOT_COMPUTED_COVERAGE_BLOCKED",
                "data_readiness": "BLOCKED_COVERAGE_EVIDENCE_ABSENT",
                "segment_value_count": 0,
                "formal_result_eligible": False,
                "exploratory_only": False,
            })

    view_bounds = study_geometry.bounds
    view_box = box(view_bounds[0] - 120.0, view_bounds[1] - 120.0, view_bounds[2] + 120.0, view_bounds[3] + 120.0)
    display_segments = [item for item in segments if item.geometry.intersects(view_box)]
    integration = next(item for item in layers if item["layer_id"] == "syntax_local_800m_integration")
    valued = sum(1 for segment in display_segments if segment.id in integration["segment_values"])
    calculated_coverage = round(valued / len(display_segments) * 100.0, 2) if display_segments else 0.0
    if figure_review.get("coverage_pct") != calculated_coverage or figure_review.get("valued_segments") != valued:
        raise SyntaxEvidenceError("R02 figure coverage statistics do not match the segment result and mapping")
    figure = r02_root / "syntax/syntax-local-800m-integration-r02.png"
    figure_record = {
        "path": "artifacts/week4-repair-r02/syntax/syntax-local-800m-integration-r02.png",
        "sha256": sha256_file(figure),
        "size_bytes": figure.stat().st_size,
        "status": "EXPLORATORY_ONLY_SOURCE_COVERAGE_INSUFFICIENT",
        "source_manifest_sha256": source_sha,
        "syntax_result_sha256": result_sha,
        "mapped_segment_count": len(integration["segment_values"]),
        "display_segment_count": len(display_segments),
        "mapped_display_segment_count": valued,
        "display_mapping_coverage_pct": calculated_coverage,
        "warning": "EXPLORATORY ONLY — SOURCE COVERAGE INSUFFICIENT — NOT A FORMAL ROTTERDAM RESULT",
    }
    return {
        "status": "EXPLORATORY_800M_ONLY_SOURCE_COVERAGE_INSUFFICIENT",
        "package_id": catalog.package_id,
        "package_revision": catalog.package_revision,
        "study_area_id": catalog.study_area_id,
        "study_area_geometry_sha256": catalog.study_area_geometry_sha256,
        "source_manifest_sha256": source_sha,
        "syntax_result_sha256": result_sha,
        "r02_integrity_manifest_sha256": manifest_sha,
        "layers": layers,
        "layer_plan": layer_plan,
        "segments": syntax_segments,
        "figure": figure_record,
        "limitations": [
            "800 m integration and choice are computed over the retained study-area subset only; source acquisition completeness is unverified.",
            "No complete acquisition envelope or radius-specific boundary-stability evidence exists for the 800 m results.",
            "2 km and 10 km integration and choice are not computed and have no values.",
            "Historical R02 geometry noding predates source OSM node identity and is not topology-validated.",
            "These measures do not predict movement, access, desirability, or behavior.",
        ],
    }
