"""Compute and record measured PST layers from verified retained OSM extracts.

All outputs are written to a fresh directory outside the Git worktree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pyproj
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_regional_network import load_geofabrik_poly, sha256_file
from urban_design.pst_syntax import compute_pst_six_syntax_layers, prepare_pst_lines

DEFAULT_DATA_ROOT = Path.home() / ".local/share/urban-design-data/week5-syntax-modes"
_PRIMARY_STUDY_AREA = (
    ROOT
    / ".urban_design_runtime/artifacts/study-area-bridge/study-areas/"
    "4818687ee13f2c4fe78471d52320074948de269d5687c494ca2fa213afe39533.geojson"
)
_FALLBACK_STUDY_AREA_PROJECT = (
    Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/artifacts/study-area-bridge/study-areas/4818687ee13f2c4fe78471d52320074948de269d5687c494ca2fa213afe39533.geojson")
)
_FALLBACK_STUDY_AREA_REPO = ROOT / "artifacts/week4-repair-r02/syntax/study-area.geojson"

DEFAULT_STUDY_AREA = (
    _PRIMARY_STUDY_AREA
    if _PRIMARY_STUDY_AREA.exists()
    else (_FALLBACK_STUDY_AREA_PROJECT if _FALLBACK_STUDY_AREA_PROJECT.exists() else _FALLBACK_STUDY_AREA_REPO)
)
DEFAULT_METHOD_MANIFEST = ROOT / "config/runtimes/pst-method-manifest-v1.json"
DEFAULT_RUNTIME_MANIFEST = ROOT / "config/runtimes/pstalgo-3.3.1.json"
MAX_RUNTIME_SECONDS = 7200.0


def rank_data(seq: list[float]) -> list[float]:
    """Compute average ranks for tied values."""
    indexed = sorted(enumerate(seq), key=lambda item: item[1])
    ranks = [0.0] * len(seq)
    i = 0
    while i < len(seq):
        j = i
        while j < len(seq) and math.isclose(indexed[j][1], indexed[i][1], abs_tol=1e-12):
            j += 1
        rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = rank
        i = j
    return ranks


def spearman_corr(x: list[float], y: list[float]) -> float:
    """Compute Spearman rank-order correlation coefficient, including ties."""
    if len(x) != len(y) or not x:
        return 0.0
    rx, ry = rank_data(x), rank_data(y)
    mean_x, mean_y = sum(rx) / len(rx), sum(ry) / len(ry)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry))
    denominator = math.sqrt(
        sum((a - mean_x) ** 2 for a in rx) * sum((b - mean_y) ** 2 for b in ry)
    )
    return numerator / denominator if denominator else 0.0


def estimate_10km_runtime_seconds(
    *,
    seconds_2km_4k: float,
    segments_2km_4k: int,
    seconds_2km_6k: float,
    segments_2km_6k: int,
    estimated_segments_15k: int,
    estimated_segments_20k: int,
    seconds_800m_6k: float,
) -> dict[str, Any]:
    """Screen 10km runs using measured graph-size and radius costs.

    Network growth uses an empirical power-law exponent from the two measured 2km
    runs, floored at linear scaling. Radius growth uses the larger of observed
    2km/800m cost on the same 6km network or a 2D area-ratio screen.
    """
    measured = (seconds_2km_4k, seconds_2km_6k, seconds_800m_6k)
    if any(not math.isfinite(value) or value <= 0 for value in measured):
        raise ValueError("runtime measurements must be positive finite values")
    if min(segments_2km_4k, segments_2km_6k, estimated_segments_15k, estimated_segments_20k) <= 0:
        raise ValueError("network segment counts must be positive")
    if segments_2km_6k <= segments_2km_4k:
        raise ValueError("6km network must contain more measured PST segments than the 4km network")

    observed_size_ratio = segments_2km_6k / segments_2km_4k
    observed_time_ratio = seconds_2km_6k / seconds_2km_4k
    if observed_time_ratio > 0:
        exponent = max(1.0, math.log(observed_time_ratio) / math.log(observed_size_ratio))
    else:
        exponent = 1.0

    coefficient = max(
        seconds_2km_4k / (segments_2km_4k ** exponent),
        seconds_2km_6k / (segments_2km_6k ** exponent),
    )
    radius_floor = (10000.0 / 2000.0) ** 2
    observed_radius_ratio = seconds_2km_6k / seconds_800m_6k
    radius_factor = max(radius_floor, observed_radius_ratio)

    projected: dict[str, float] = {}
    for label, candidate_segments in (
        ("15k", estimated_segments_15k),
        ("20k", estimated_segments_20k),
    ):
        projected_2km = coefficient * (candidate_segments ** exponent)
        projected[label] = projected_2km * radius_factor

    return {
        "runtime_model": "empirical_network_power_law_with_quadratic_radius_screen",
        "network_size_exponent": exponent,
        "measured_network_size_ratio_6k_to_4k": observed_size_ratio,
        "measured_runtime_ratio_2km_6k_to_4k": observed_time_ratio,
        "radius_scaling_factor": radius_factor,
        "radius_factor_basis": {
            "quadratic_search_area_floor": radius_floor,
            "measured_2km_to_800m_ratio_on_6km_network": observed_radius_ratio,
        },
        "estimated_segments_15k": estimated_segments_15k,
        "estimated_segments_20k": estimated_segments_20k,
        "predicted_15k_seconds": projected["15k"],
        "predicted_20k_seconds": projected["20k"],
        "max_single_run_seconds": MAX_RUNTIME_SECONDS,
        "under_budget": max(projected.values()) <= MAX_RUNTIME_SECONDS,
        "limitations": [
            "This is a screening extrapolation, not a runtime guarantee.",
            "Network growth is extrapolated from two measured 2km runs.",
            "Radius growth is screened using a quadratic area ratio and measured 2km/800m cost on the same 6km network.",
            "Any forecast above the two-hour cap blocks both 10km runs.",
        ],
    }


def _verify_file_record(record: Mapping[str, Any], *, label: str) -> Path:
    path_value = record.get("path")
    expected_size = record.get("size_bytes")
    expected_hash = record.get("sha256")
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise ValueError(f"{label} manifest path must be absolute")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int):
        raise ValueError(f"{label} manifest size is invalid")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ValueError(f"{label} manifest SHA-256 is invalid")
    path = Path(path_value)
    if not path.is_file():
        raise FileNotFoundError(f"{label} file is missing: {path}")
    actual_size = path.stat().st_size
    actual_hash = sha256_file(path)
    if actual_size != expected_size or actual_hash != expected_hash:
        raise ValueError(f"{label} file does not match its retained manifest identity")
    return path


def _load_verified_extraction(
    extraction_dir: Path,
    buffer_m: int,
    study_area_path: Path,
    study_area_geometry: Any,
    *,
    source_identity_cache: dict[tuple[str, str], Path],
    network_mode: str | None = None,
) -> dict[str, Any]:
    mode_prefix = f"{network_mode}_" if network_mode else ""
    candidate_path = extraction_dir / f"extraction-manifest_{mode_prefix}{buffer_m}m.json"
    if candidate_path.exists():
        manifest_path = candidate_path
        suffix = f"{mode_prefix}{buffer_m}m"
    else:
        suffix = f"{buffer_m}m"
        manifest_path = extraction_dir / f"extraction-manifest_{suffix}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "regional-osm-extraction-manifest-v1":
        raise ValueError(f"{manifest_path} has an unsupported schema")
    extraction = manifest.get("extraction", {})
    if extraction.get("buffer_radius_m") != buffer_m:
        raise ValueError(f"{manifest_path} describes a different buffer radius")

    inputs = manifest.get("inputs", {})
    study_record = inputs.get("study_area", {})
    recorded_study_path = Path(study_record.get("path", "")).resolve()
    if recorded_study_path != study_area_path.resolve():
        raise ValueError(f"{manifest_path} uses a different StudyArea file")
    _verify_file_record(study_record, label=f"{suffix} StudyArea")
    if study_record.get("sha256") != sha256_file(study_area_path):
        raise ValueError(f"{manifest_path} StudyArea hash is stale")

    source = inputs.get("source", {})
    for key in ("pbf", "poly"):
        record = inputs.get(key, {})
        identity = (str(record.get("path")), str(record.get("sha256")))
        if identity not in source_identity_cache:
            source_identity_cache[identity] = _verify_file_record(record, label=f"{suffix} {key}")
        elif not source_identity_cache[identity].is_file():
            raise FileNotFoundError(f"retained {key} source disappeared")
    retrieval_record = {
        "path": source.get("retrieval_record_path"),
        "size_bytes": source.get("retrieval_record_size_bytes"),
        "sha256": source.get("retrieval_record_sha256"),
    }
    if retrieval_record["size_bytes"] is not None:
        _verify_file_record(retrieval_record, label=f"{suffix} source retrieval record")

    output_records = manifest.get("outputs", {})
    network_record = output_records.get("network", {})
    unlinks_record = output_records.get("unlinks", {})
    network_path = _verify_file_record(network_record, label=f"{suffix} network")
    unlinks_path = _verify_file_record(unlinks_record, label=f"{suffix} unlinks")
    if network_path.parent.resolve() != extraction_dir.resolve() or unlinks_path.parent.resolve() != extraction_dir.resolve():
        raise ValueError(f"{manifest_path} points outside the selected extraction directory")
    if network_path.name != f"network_{suffix}.geojson" or unlinks_path.name != f"unlinks_{suffix}.json":
        raise ValueError(f"{manifest_path} output names do not match its buffer radius")

    data = json.loads(network_path.read_text(encoding="utf-8"))
    if data.get("crs", {}).get("properties", {}).get("name") != "EPSG:28992":
        raise ValueError(f"{network_path} is not tagged as EPSG:28992")
    features = data.get("features")
    unlinks = json.loads(unlinks_path.read_text(encoding="utf-8"))
    if not isinstance(features, list) or not isinstance(unlinks, list):
        raise ValueError(f"{manifest_path} does not reference valid network and unlink arrays")
    if len(features) != extraction.get("line_count") or len(unlinks) != extraction.get("unlink_count"):
        raise ValueError(f"{manifest_path} counts do not match its output files")

    poly_path = source_identity_cache[(str(inputs["poly"]["path"]), str(inputs["poly"]["sha256"]))]
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)
    coverage = load_geofabrik_poly(poly_path, transformer)
    envelope = study_area_geometry.buffer(buffer_m)
    poly_contains_envelope = coverage.covers(envelope)
    if extraction.get("extract_covers_envelope") is not poly_contains_envelope:
        raise ValueError(f"{manifest_path} coverage flag disagrees with the retained .poly geometry")

    return {
        "manifest_path": manifest_path,
        "manifest_sha256": sha256_file(manifest_path),
        "manifest": manifest,
        "features": features,
        "unlinks": [tuple(point) for point in unlinks],
        "buffer_m": buffer_m,
        "network_path": network_path,
        "unlinks_path": unlinks_path,
        "poly_contains_envelope": poly_contains_envelope,
    }


def compare_radius_stability(
    smaller_result: Mapping[str, Any],
    larger_result: Mapping[str, Any],
    *,
    radius_m: float,
) -> dict[str, Any]:
    """Compare common in-StudyArea segment IDs and record >5% changes."""
    comparisons: dict[str, Any] = {}
    segment_sets: list[set[str]] = []
    for metric in ("nain", "nach"):
        smaller_layers = [
            layer for layer in smaller_result["layers"]
            if layer["radius_m"] == radius_m and layer["metric_key"] == metric
        ]
        larger_layers = [
            layer for layer in larger_result["layers"]
            if layer["radius_m"] == radius_m and layer["metric_key"] == metric
        ]
        if len(smaller_layers) != 1 or len(larger_layers) != 1:
            raise ValueError(f"expected exactly one {metric} layer for radius {radius_m:g}m")
        smaller_values = smaller_layers[0]["segment_values"]
        larger_values = larger_layers[0]["segment_values"]
        common = sorted(set(smaller_values).intersection(larger_values))
        segment_sets.append(set(common))
        if not common:
            comparisons[metric] = {
                "spearman_correlation": None,
                "spearman_pass": False,
                "edge_affected_segment_ids": [],
                "edge_affected_count": 0,
                "edge_affected_percent": None,
            }
            continue
        values_a = [float(smaller_values[key]) for key in common]
        values_b = [float(larger_values[key]) for key in common]
        rho = spearman_corr(values_a, values_b)
        edge_ids = [
            key for key, left, right in zip(common, values_a, values_b)
            if abs(right - left) / max(abs(left), abs(right), 1e-12) > 0.05
        ]
        comparisons[metric] = {
            "spearman_correlation": rho,
            "spearman_pass": rho >= 0.98,
            "edge_affected_segment_ids": edge_ids,
            "edge_affected_count": len(edge_ids),
            "edge_affected_percent": len(edge_ids) / len(common) * 100.0,
        }

    common_ids = sorted(segment_sets[0].intersection(segment_sets[1]))
    smaller_all = {
        str(key)
        for layer in smaller_result["layers"]
        if layer["radius_m"] == radius_m and layer["metric_key"] in {"nain", "nach"}
        for key in layer["segment_values"]
    }
    larger_all = {
        str(key)
        for layer in larger_result["layers"]
        if layer["radius_m"] == radius_m and layer["metric_key"] in {"nain", "nach"}
        for key in layer["segment_values"]
    }
    return {
        "radius_m": radius_m,
        "common_segment_count": len(common_ids),
        "smaller_only_count": len(smaller_all - larger_all),
        "larger_only_count": len(larger_all - smaller_all),
        "metrics": comparisons,
        "stability_pass": (
            bool(common_ids)
            and comparisons["nain"]["spearman_pass"]
            and comparisons["nach"]["spearman_pass"]
        ),
        "criterion": "Spearman >= 0.98 for both NAIN and NACH; segments changing >5% are listed EDGE_AFFECTED.",
    }


def _apply_stability_status(result: dict[str, Any], report: Mapping[str, Any], *, radius_m: float) -> dict[str, Any]:
    result = json.loads(json.dumps(result))
    passed = report.get("stability_pass") is True
    if passed and radius_m not in result.get("stability_validated_radii_m", []):
        result.setdefault("stability_validated_radii_m", []).append(radius_m)
        result["stability_validated_radii_m"].sort()
    for layer in result["layers"]:
        if layer["radius_m"] != radius_m:
            continue
        if layer["data_readiness"] in {
            "BLOCKED_COVERAGE_EVIDENCE_ABSENT",
            "BLOCKED_EXTRACT_ENVELOPE_COVERAGE_UNVERIFIED",
            "EDGE_AFFECTED_INSUFFICIENT_ACQUISITION_BUFFER",
        }:
            continue
        if passed:
            layer["data_readiness"] = "EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY"
            layer["limitations"] = (
                "The retained extract boundary contains the StudyArea with the required radius clearance "
                "and radius stability was assessed; OSM feature completeness and semantics are not established."
            )
        else:
            layer["data_readiness"] = "BLOCKED_BOUNDARY_STABILITY_FAIL"
            layer["limitations"] = (
                "Radius stability did not meet the project criterion; see the paired stability report. "
                "OSM feature completeness and semantics are not established."
            )
    return result


def estimate_network_segment_factor(
    four_k_result: Mapping[str, Any],
    six_k_result: Mapping[str, Any],
    four_k_features: list[Mapping[str, Any]],
    six_k_features: list[Mapping[str, Any]],
    candidate_features: list[Mapping[str, Any]],
) -> tuple[int, int, float]:
    """Estimate full graph segments from extracted geometry and measured split factors."""
    def source_edges(features: list[Mapping[str, Any]]) -> int:
        total = 0
        for feature in features:
            coordinates = feature.get("geometry", {}).get("coordinates", [])
            total += max(0, len(coordinates) - 1)
        return total

    input_four = source_edges(four_k_features)
    input_six = source_edges(six_k_features)
    input_candidate = source_edges(candidate_features)
    if min(input_four, input_six, input_candidate) <= 0:
        raise ValueError("extracted network geometries must contain source edges")
    factor_four = four_k_result["network_segment_count"] / input_four
    factor_six = six_k_result["network_segment_count"] / input_six
    factor = max(1.0, factor_four, factor_six)
    return (
        math.ceil(input_candidate * factor),
        input_candidate,
        factor,
    )


def _measure(
    loaded: Mapping[str, Any],
    *,
    radius_m: float,
    study_area_geometry: Any,
    study_area_segment_geometry: Any,
    runtime_manifest_path: Path,
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    result = compute_pst_six_syntax_layers(
        loaded["features"],
        calculate_radii_m=[radius_m],
        unlinks=loaded["unlinks"],
        study_area_geometry=study_area_geometry,
        acquisition_envelope_geometry=study_area_segment_geometry,
        extract_covers_envelope=loaded["poly_contains_envelope"],
        stability_validated_radii_m=(),
        pst_manifest_path=runtime_manifest_path,
    )
    elapsed = time.perf_counter() - started
    if not math.isfinite(elapsed) or elapsed <= 0:
        raise ValueError("PST elapsed time must be a positive finite measurement")
    return result, elapsed


def _measure_split(
    loaded: Mapping[str, Any],
    *,
    radius_m: float,
    study_area_geometry: Any,
    study_area_segment_geometry: Any,
    runtime_manifest_path: Path,
) -> tuple[dict[str, Any], float, float]:
    print(f"  Measuring AngularIntegration for radius {radius_m:g}m ...", flush=True)
    started_int = time.perf_counter()
    result_int = compute_pst_six_syntax_layers(
        loaded["features"],
        calculate_radii_m=[radius_m],
        unlinks=loaded["unlinks"],
        study_area_geometry=study_area_geometry,
        acquisition_envelope_geometry=study_area_segment_geometry,
        extract_covers_envelope=loaded["poly_contains_envelope"],
        stability_validated_radii_m=(),
        pst_manifest_path=runtime_manifest_path,
        metric_mode="integration",
    )
    elapsed_int = time.perf_counter() - started_int
    if not math.isfinite(elapsed_int) or elapsed_int <= 0:
        raise ValueError("PST integration elapsed time must be a positive finite measurement")
    print(f"  AngularIntegration completed in {elapsed_int:.3f}s", flush=True)

    print(f"  Measuring AngularChoice for radius {radius_m:g}m ...", flush=True)
    started_cho = time.perf_counter()
    result_cho = compute_pst_six_syntax_layers(
        loaded["features"],
        calculate_radii_m=[radius_m],
        unlinks=loaded["unlinks"],
        study_area_geometry=study_area_geometry,
        acquisition_envelope_geometry=study_area_segment_geometry,
        extract_covers_envelope=loaded["poly_contains_envelope"],
        stability_validated_radii_m=(),
        pst_manifest_path=runtime_manifest_path,
        metric_mode="choice",
    )
    elapsed_cho = time.perf_counter() - started_cho
    if not math.isfinite(elapsed_cho) or elapsed_cho <= 0:
        raise ValueError("PST choice elapsed time must be a positive finite measurement")
    print(f"  AngularChoice completed in {elapsed_cho:.3f}s", flush=True)

    combined = json.loads(json.dumps(result_int))
    for layer in combined["layers"]:
        if layer["radius_m"] == radius_m and layer["metric_key"] == "nach":
            cho_layer = next(
                l for l in result_cho["layers"]
                if l["radius_m"] == radius_m and l["metric_key"] == "nach"
            )
            layer.update(cho_layer)
    return combined, elapsed_int, elapsed_cho


def _set_regional_not_computed(result: dict[str, Any], estimate: Mapping[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(result))
    reason = (
        "Both 10km runs were withheld because at least one empirically screened estimate exceeds "
        f"the {MAX_RUNTIME_SECONDS:.0f}s single-run cap. Forecasts: "
        f"15km={estimate['predicted_15k_seconds']:.1f}s; "
        f"20km={estimate['predicted_20k_seconds']:.1f}s."
    )
    for layer in result["layers"]:
        if layer["radius_m"] == 10000.0:
            layer["calculation_status"] = "NOT_COMPUTED_RUNTIME_BUDGET"
            layer["data_readiness"] = "BLOCKED_RUNTIME_BUDGET_ESTIMATE"
            layer["segment_values"] = {}
            layer["statistics"] = None
            layer.pop("legend_breaks", None)
            layer["limitations"] = reason + " Forecasting is a screening estimate, not a guarantee."
    return result


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def _unique_output_dir(requested: Path | None) -> Path:
    path = requested or (
        DEFAULT_DATA_ROOT / "syntax"
        / f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    resolved = path.expanduser().resolve()
    if resolved.is_relative_to(ROOT.resolve()):
        raise ValueError("syntax outputs must be outside the Git worktree")
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extraction-dir", required=True, type=Path)
    parser.add_argument("--study-area", type=Path, default=DEFAULT_STUDY_AREA)
    parser.add_argument("--runtime-manifest", type=Path, default=DEFAULT_RUNTIME_MANIFEST)
    parser.add_argument("--method-manifest", type=Path, default=DEFAULT_METHOD_MANIFEST)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--force-10km", action="store_true", help="Force execution of 10km regional computation")
    parser.add_argument("--skip-20km", action="store_true", help="Skip 20km extraction computation")
    parser.add_argument("--reuse-15km-from", type=Path, help="Path to existing syntax_10000m_15000m.json to avoid recomputing 15km")
    args = parser.parse_args(argv)

    try:
        study_area_path = args.study_area.expanduser().resolve()
        study_data = json.loads(study_area_path.read_text(encoding="utf-8"))
        study_area_geometry = shape(study_data["geometry"])
        if study_area_geometry.is_empty or not study_area_geometry.is_valid:
            raise ValueError("StudyArea geometry must be valid and non-empty")
        runtime_manifest_path = args.runtime_manifest.expanduser().resolve()
        method_manifest_path = args.method_manifest.expanduser().resolve()
        if not runtime_manifest_path.is_file():
            raise FileNotFoundError(f"PST runtime manifest is missing: {runtime_manifest_path}")
        if not method_manifest_path.is_file():
            raise FileNotFoundError(f"PST method manifest is missing: {method_manifest_path}")
        extraction_dir = args.extraction_dir.expanduser().resolve()
        source_identity_cache: dict[tuple[str, str], Path] = {}
        mode_map = {
            1500: "pedestrian",
            4000: "bicycle",
            6000: "bicycle",
            15000: "motor_vehicle",
            20000: "motor_vehicle",
        }
        loaded = {
            buffer_m: _load_verified_extraction(
                extraction_dir,
                buffer_m,
                study_area_path,
                study_area_geometry,
                source_identity_cache=source_identity_cache,
                network_mode=mode_map.get(buffer_m),
            )
            for buffer_m in (1500, 4000, 6000, 15000, 20000)
        }

        output_dir = _unique_output_dir(args.output_dir)
        started_at = datetime.now(timezone.utc).isoformat()
        method_manifest_hash = sha256_file(method_manifest_path)

        print("Computing fresh 800m PST layers on the 1500m extract...")
        result_800, seconds_800 = _measure(
            loaded[1500],
            radius_m=800.0,
            study_area_geometry=study_area_geometry,
            study_area_segment_geometry=study_area_geometry.buffer(1500.0),
            runtime_manifest_path=runtime_manifest_path,
        )
        print(f"800m / 1500m elapsed: {seconds_800:.6f}s")

        print("Computing fresh 2000m PST layers on the 4000m extract...")
        result_2k_4k, seconds_2k_4k = _measure(
            loaded[4000],
            radius_m=2000.0,
            study_area_geometry=study_area_geometry,
            study_area_segment_geometry=study_area_geometry.buffer(4000.0),
            runtime_manifest_path=runtime_manifest_path,
        )
        print(f"2000m / 4000m elapsed: {seconds_2k_4k:.6f}s")

        print("Computing fresh 2000m PST layers on the 6000m extract...")
        result_2k_6k, seconds_2k_6k = _measure(
            loaded[6000],
            radius_m=2000.0,
            study_area_geometry=study_area_geometry,
            study_area_segment_geometry=study_area_geometry.buffer(6000.0),
            runtime_manifest_path=runtime_manifest_path,
        )
        print(f"2000m / 6000m elapsed: {seconds_2k_6k:.6f}s")

        print("Measuring auxiliary 800m runtime on the same 6000m graph for radius scaling...")
        result_800_6k, seconds_800_6k = _measure(
            loaded[6000],
            radius_m=800.0,
            study_area_geometry=study_area_geometry,
            study_area_segment_geometry=study_area_geometry.buffer(6000.0),
            runtime_manifest_path=runtime_manifest_path,
        )
        print(f"800m / 6000m auxiliary runtime: {seconds_800_6k:.6f}s")

        stability_2k = compare_radius_stability(result_2k_4k, result_2k_6k, radius_m=2000.0)
        result_2k_4k = _apply_stability_status(result_2k_4k, stability_2k, radius_m=2000.0)
        result_2k_6k = _apply_stability_status(result_2k_6k, stability_2k, radius_m=2000.0)

        estimated_segments: dict[int, int] = {}
        segment_factor: dict[str, Any] = {}
        for buffer_m in (15000, 20000):
            estimated, source_edges, split_factor = estimate_network_segment_factor(
                result_2k_4k,
                result_2k_6k,
                loaded[4000]["features"],
                loaded[6000]["features"],
                loaded[buffer_m]["features"],
            )
            estimated_segments[buffer_m] = estimated
            segment_factor[str(buffer_m)] = {
                "candidate_source_edge_count": source_edges,
                "measured_intersection_expansion_factor_upper": split_factor,
                "estimated_pst_segment_count": estimated,
            }
        runtime_estimate = estimate_10km_runtime_seconds(
            seconds_2km_4k=seconds_2k_4k,
            segments_2km_4k=result_2k_4k["network_segment_count"],
            seconds_2km_6k=seconds_2k_6k,
            segments_2km_6k=result_2k_6k["network_segment_count"],
            estimated_segments_15k=estimated_segments[15000],
            estimated_segments_20k=estimated_segments[20000],
            seconds_800m_6k=seconds_800_6k,
        )
        runtime_estimate["network_segment_estimation"] = segment_factor

        timings = {
            "800m_1500m": seconds_800,
            "2000m_4000m": seconds_2k_4k,
            "2000m_6000m": seconds_2k_6k,
            "800m_6000m_runtime_benchmark_only": seconds_800_6k,
            "10km_15000m_predicted": runtime_estimate["predicted_15k_seconds"],
            "10km_20000m_predicted": runtime_estimate["predicted_20k_seconds"],
        }
        regional_15 = regional_20 = None
        stability_10k = None
        regional_status = "NOT_COMPUTED_RUNTIME_BUDGET"
        if args.force_10km or runtime_estimate["under_budget"]:
            if args.reuse_15km_from:
                reuse_path = args.reuse_15km_from.expanduser().resolve()
                print(f"Loading existing 10km / 15km regional syntax result from {reuse_path}...")
                regional_15 = json.loads(reuse_path.read_text(encoding="utf-8"))
                timings["10000m_15000m"] = regional_15.get("elapsed_seconds", 0.0)
            else:
                print("Computing 10km regional network (15km extraction) with split integration and choice...")
                regional_15, sec_10k_15_int, sec_10k_15_cho = _measure_split(
                    loaded[15000],
                    radius_m=10000.0,
                    study_area_geometry=study_area_geometry,
                    study_area_segment_geometry=study_area_geometry.buffer(15000.0),
                    runtime_manifest_path=runtime_manifest_path,
                )
                timings["10000m_15000m_integration"] = sec_10k_15_int
                timings["10000m_15000m_choice"] = sec_10k_15_cho
                timings["10000m_15000m"] = sec_10k_15_int + sec_10k_15_cho

            if not args.skip_20km:
                print("Computing 10km regional network (20km extraction) with split integration and choice...")
                regional_20, sec_10k_20_int, sec_10k_20_cho = _measure_split(
                    loaded[20000],
                    radius_m=10000.0,
                    study_area_geometry=study_area_geometry,
                    study_area_segment_geometry=study_area_geometry.buffer(20000.0),
                    runtime_manifest_path=runtime_manifest_path,
                )
                timings["10000m_20000m_integration"] = sec_10k_20_int
                timings["10000m_20000m_choice"] = sec_10k_20_cho
                timings["10000m_20000m"] = sec_10k_20_int + sec_10k_20_cho
                stability_10k = compare_radius_stability(regional_15, regional_20, radius_m=10000.0)
                regional_20 = _apply_stability_status(regional_20, stability_10k, radius_m=10000.0)
                regional_status = "COMPUTED_STABLE" if stability_10k["stability_pass"] else "COMPUTED_UNSTABLE"
            else:
                print("Skipping 20km extraction computation as requested.")
                regional_20 = regional_15
                regional_status = "COMPUTED_15KM_ONLY"
        else:
            print("At least one forecast exceeds two hours; neither 10km run will be started.")
            regional_20 = _set_regional_not_computed(result_2k_6k, runtime_estimate)
            regional_status = "WITHHELD_OVER_TWO_HOURS"

        six_layers = [
            *[layer for layer in result_800["layers"] if layer["radius_m"] == 800.0],
            *[layer for layer in result_2k_6k["layers"] if layer["radius_m"] == 2000.0],
            *[layer for layer in regional_20["layers"] if layer["radius_m"] == 10000.0],
        ]
        if len(six_layers) != 6:
            raise ValueError("combined syntax candidate does not contain exactly six layers")
        for layer in six_layers:
            layer["network_mode"] = (
                "pedestrian" if layer["radius_m"] == 800.0
                else ("bicycle" if layer["radius_m"] == 2000.0 else "motor_vehicle")
            )
        combined = {
            "schema_version": "week5-six-syntax-layer-candidate-v1",
            "policy_version": "syntax-network-policy-v2",
            "status": "EXPLORATORY_CANDIDATE",
            "engine": "PST 3.3.1",
            "method_manifest": str(method_manifest_path),
            "method_manifest_sha256": method_manifest_hash,
            "study_area_sha256": sha256_file(study_area_path),
            "layers": six_layers,
            "layer_plan": six_layers,
            "timings_seconds": timings,
            "stability_2000m": stability_2k,
            "stability_10000m": stability_10k,
            "regional_status": regional_status,
            "runtime_estimate_10km": runtime_estimate,
            "limitations": [
                "All values are exploratory; syntax-network-policy-v2 remains pending designer approval.",
                "Geofabrik polygon containment does not prove OSM feature or semantic completeness.",
                "800m boundary stability was not independently assessed at a second envelope.",
                "10km computation status is stated per layer; motor_vehicle network used per PD-20.",
            ],
        }

        output_values = {
            "syntax_800m_1500m.json": result_800,
            "syntax_2000m_4000m.json": result_2k_4k,
            "syntax_2000m_6000m.json": result_2k_6k,
            "runtime_benchmark_800m_6000m.json": {
                "purpose": "runtime scaling measurement only; not an additional published layer",
                "elapsed_seconds": seconds_800_6k,
                "network_segment_count": result_800_6k["network_segment_count"],
                "method_manifest_sha256": method_manifest_hash,
            },
            "stability_2000m_4000m_vs_6000m.json": stability_2k,
            "runtime_estimate_10km.json": runtime_estimate,
            "syntax_six_layer_candidate.json": combined,
        }
        if regional_15 is not None:
            output_values["syntax_10000m_15000m.json"] = regional_15
        if regional_20 is not None and not args.skip_20km:
            output_values["syntax_10000m_20000m.json"] = regional_20
        if stability_10k is not None:
            output_values["stability_10000m_15000m_vs_20000m.json"] = stability_10k

        output_records: dict[str, Any] = {}
        for name, value in output_values.items():
            path = output_dir / name
            _write_json(path, value)
            output_records[name] = {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }

        finished_at = datetime.now(timezone.utc).isoformat()
        run_manifest = {
            "schema_version": "week5-syntax-run-manifest-v1",
            "policy_version": "syntax-network-policy-v2",
            "started_at_utc": started_at,
            "completed_at_utc": finished_at,
            "study_area_path": str(study_area_path),
            "study_area_sha256": sha256_file(study_area_path),
            "method_manifest_path": str(method_manifest_path),
            "method_manifest_sha256": method_manifest_hash,
            "runtime_manifest_path": str(runtime_manifest_path),
            "runtime_manifest_sha256": sha256_file(runtime_manifest_path),
            "extraction_manifests": {
                str(buffer): {
                    "path": str(loaded[buffer]["manifest_path"]),
                    "sha256": loaded[buffer]["manifest_sha256"],
                }
                for buffer in (1500, 4000, 6000, 15000, 20000)
            },
            "runtime_seconds": timings,
            "regional_status": regional_status,
            "excluded_lines": {
                "1500m": result_800.get("excluded_lines", []),
                "4000m": result_2k_4k.get("excluded_lines", []),
                "6000m": result_2k_6k.get("excluded_lines", []),
                "15000m": regional_15.get("excluded_lines", []) if regional_15 is not None else [],
                "20000m": regional_20.get("excluded_lines", []) if regional_20 is not None and not args.skip_20km else [],
            },
            "outputs": output_records,
            "source_requests": 0,
            "authority_database_writes": 0,
        }
        manifest_path = output_dir / "run-manifest.json"
        _write_json(manifest_path, run_manifest)
        for name, record in output_records.items():
            path = Path(record["path"])
            if path.stat().st_size != record["size_bytes"] or sha256_file(path) != record["sha256"]:
                raise ValueError(f"post-write integrity check failed for {name}")

        print(json.dumps({
            "output_dir": str(output_dir),
            "manifest": str(manifest_path),
            "regional_status": regional_status,
            "timings_seconds": timings,
            "runtime_estimate_10km": runtime_estimate,
            "stability_2000m": stability_2k,
            "stability_10000m": stability_10k,
        }, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, pyproj.exceptions.ProjError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
