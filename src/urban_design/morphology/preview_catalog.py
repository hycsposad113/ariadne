from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, StrictInt, StrictStr
from shapely.geometry import shape


MANIFEST_NAME = "artifact-manifest.json"
COMPARISON_NAME = "comparison.json"
COMPARISON_SCHEMA = "dictionary-generator-comparison-v1"
MANIFEST_SCHEMA = "dictionary-generator-artifact-manifest-v1"
RECIPE_SCHEMA = "morphology-recipe-v1"
GENERATOR_VERSION = "dictionary-generator-v4"
INTENSITIES = ("A", "B")
STRATEGY_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_KEYS = {"algorithm", "files", "manifest_excludes_self", "schema_version"}
COMPARISON_KEYS = {
    "decision_rule", "generator_version", "human_decision_created", "limitations",
    "overall_winner", "run_status", "schema_version", "seed", "strategy_count",
    "valid_count_by_intensity", "study_area", "strategies",
}
STUDY_AREA_KEYS = {
    "file_sha256", "geometry_area_m2", "geometry_sha256", "horizontal_crs",
    "id", "source_file", "units", "version",
}
STRATEGY_KEYS = {
    "artifact_hashes", "building_count", "coverage_ratio", "external_contacts",
    "failure_reasons", "intensity", "land_far", "maximum_height_m",
    "open_space_ratio", "scenario_hash", "scenario_id", "strategy_id",
    "strategy_label", "type_composition", "valid", "warnings",
}
ARTIFACT_NAMES = ("scenario.geojson", "metrics.json", "recipe.json", "plan.png", "axonometric.png")
SERVED_KINDS = ("plan", "axonometric", "geometry")
ASSET_NAME_BY_KIND = {
    "plan": "plan.png",
    "axonometric": "axonometric.png",
    "geometry": "scenario.geojson",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
EPSG_28992_X_RANGE = (0.0, 300_000.0)
EPSG_28992_Y_RANGE = (289_000.0, 629_000.0)


class PreviewCatalogError(ValueError):
    """A configured preview bundle is malformed or has changed."""

    def __init__(self, message: str, *, category: str = "schema_error") -> None:
        super().__init__(message)
        self.category = category


class PreviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PreviewIdentity(PreviewModel):
    intensity: Literal["A", "B"]
    strategy_id: StrictStr = Field(min_length=1)
    status: Literal["UNAPPROVED_PREVIEW"]
    human_decision_created: Literal[False]
    generator_version: StrictStr = Field(min_length=1)
    run_created_at: StrictStr | None
    generator_commit: StrictStr | None


class IntensityLimits(PreviewModel):
    intensity: Literal["A", "B"]
    far_upper_bound_land: FiniteFloat
    coverage_upper_bound: FiniteFloat | None
    height_upper_bound_new_buildings_m: FiniteFloat


class PreviewInputReference(PreviewModel):
    label: StrictStr = Field(min_length=1)
    sha256: StrictStr = Field(pattern=SHA256_PATTERN)


class PreviewMetrics(PreviewModel):
    building_count: StrictInt = Field(ge=0)
    known_part_land_far: FiniteFloat
    coverage_ratio: FiniteFloat
    maximum_height_m: FiniteFloat
    open_space_ratio: FiniteFloat
    generator_valid: StrictBool
    warnings: tuple[StrictStr, ...]


class RetainedBuilding(PreviewModel):
    feature_id: StrictStr | StrictInt | None
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    floor_estimate_status: StrictStr = Field(min_length=1)
    floor_count: StrictInt | None
    height_m: FiniteFloat | None


class VerifiedAsset(PreviewModel):
    kind: Literal["plan", "axonometric", "geometry"]
    content: bytes
    media_type: Literal["image/png", "application/geo+json"]
    sha256: StrictStr = Field(pattern=SHA256_PATTERN)


class PreviewRecord(PreviewModel):
    identity: PreviewIdentity
    strategy_label: StrictStr = Field(min_length=1)
    limits: IntensityLimits
    metrics: PreviewMetrics
    retained_buildings: tuple[RetainedBuilding, ...]
    input_refs: tuple[PreviewInputReference, ...]
    limitations: tuple[StrictStr, ...]
    verified_assets: tuple[VerifiedAsset, ...] = Field(repr=False, exclude=True)


class PreviewCatalog(PreviewModel):
    identities: tuple[PreviewIdentity, ...]
    limits: tuple[IntensityLimits, ...]
    records: tuple[PreviewRecord, ...]
    manifest_sha256: StrictStr = Field(pattern=SHA256_PATTERN)
    comparison_sha256: StrictStr = Field(pattern=SHA256_PATTERN)
    input_refs: tuple[PreviewInputReference, ...]
    limitations: tuple[StrictStr, ...]
    seed: StrictInt

    @property
    def limits_by_intensity(self) -> dict[str, IntensityLimits]:
        return {item.intensity: item for item in self.limits}

    def get_preview(self, intensity: str, strategy_id: str) -> PreviewRecord:
        for record in self.records:
            if record.identity.intensity == intensity and record.identity.strategy_id == strategy_id:
                return record
        raise PreviewCatalogError("unknown preview identity")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PreviewCatalogError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise PreviewCatalogError(f"non-finite JSON number: {value}")


def _check_finite(value: Any, *, context: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise PreviewCatalogError(f"non-finite value in {context}")
    if isinstance(value, dict):
        for nested in value.values():
            _check_finite(nested, context=context)
    elif isinstance(value, list):
        for nested in value:
            _check_finite(nested, context=context)


def _loads_json(data: bytes, *, context: str) -> Any:
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except PreviewCatalogError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PreviewCatalogError(f"invalid JSON in {context}") from exc
    _check_finite(value, context=context)
    return value


def _require_keys(value: Any, expected: set[str], *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise PreviewCatalogError(f"unknown schema or fields in {context}")
    return value


def _safe_manifest_path(value: Any) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value or ":" in value:
        raise PreviewCatalogError("unsafe manifest path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PreviewCatalogError("unsafe manifest path traversal")
    return value


def _read_beneath(root_fd: int, relative_path: str, *, expected_size: int | None = None) -> bytes:
    relative_path = _safe_manifest_path(relative_path)
    parts = relative_path.split("/")
    current_fd = os.dup(root_fd)
    try:
        for index, part in enumerate(parts):
            is_file = index == len(parts) - 1
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            if not is_file:
                flags |= getattr(os, "O_DIRECTORY", 0)
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        metadata = os.fstat(current_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise PreviewCatalogError("preview bundle path is not a regular file", category="unsafe_path")
        read_size = metadata.st_size if expected_size is None else expected_size
        if expected_size is not None and metadata.st_size != expected_size:
            raise PreviewCatalogError("asset size integrity mismatch", category="hash_mismatch")
        chunks: list[bytes] = []
        remaining = read_size + 1
        while remaining > 0:
            chunk = os.read(current_fd, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) != read_size:
            raise PreviewCatalogError("preview bundle file size changed while being read", category="hash_mismatch")
        return content
    except PreviewCatalogError:
        raise
    except FileNotFoundError as exc:
        raise PreviewCatalogError("preview bundle file is missing", category="missing_file") from exc
    except OSError as exc:
        raise PreviewCatalogError("unsafe path or symlink in preview bundle", category="unsafe_path") from exc
    finally:
        os.close(current_fd)


def _manifest_entry(manifest_files: dict[str, Any], path: str) -> tuple[str, int]:
    entry = manifest_files.get(path)
    if not isinstance(entry, dict) or set(entry) != {"sha256", "size_bytes"}:
        raise PreviewCatalogError(f"unknown or malformed manifest entry: {path}")
    sha = entry["sha256"]
    size = entry["size_bytes"]
    if not isinstance(sha, str) or not SHA256_PATTERN.fullmatch(sha):
        raise PreviewCatalogError(f"invalid manifest hash for {path}")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise PreviewCatalogError(f"invalid manifest size for {path}")
    return sha, size


def _verified_files(root_fd: int, manifest_files: dict[str, Any]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for raw_path in manifest_files:
        path = _safe_manifest_path(raw_path)
        expected_hash, expected_size = _manifest_entry(manifest_files, path)
        content = _read_beneath(root_fd, path, expected_size=expected_size)
        if len(content) != expected_size:
            raise PreviewCatalogError("asset size integrity mismatch", category="hash_mismatch")
        if not hmac.compare_digest(_sha256(content), expected_hash):
            raise PreviewCatalogError("asset hash integrity mismatch", category="hash_mismatch")
        result[path] = content
    return result


def _number(value: Any, *, context: str, nullable: bool = False) -> float | None:
    if nullable and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PreviewCatalogError(f"invalid numeric field in {context}")
    return float(value)


def _safe_strategy_id(value: Any) -> str:
    if not isinstance(value, str) or not STRATEGY_ID_PATTERN.fullmatch(value):
        raise PreviewCatalogError("invalid strategy identity")
    return value


def _iter_coordinate_pairs(value: Any):
    if not isinstance(value, list):
        return
    if len(value) >= 2 and isinstance(value[0], (int, float)) and isinstance(value[1], (int, float)):
        x, y = value[0], value[1]
        if isinstance(x, bool) or isinstance(y, bool) or not math.isfinite(float(x)) or not math.isfinite(float(y)):
            raise PreviewCatalogError("invalid GeoJSON coordinate")
        yield float(x), float(y)
        return
    for nested in value:
        yield from _iter_coordinate_pairs(nested)


def _geometry_coordinate_pairs(geometry: dict[str, Any]):
    if "coordinates" in geometry:
        yield from _iter_coordinate_pairs(geometry["coordinates"])
        return
    if geometry.get("type") == "GeometryCollection" and isinstance(geometry.get("geometries"), list):
        for nested in geometry["geometries"]:
            if isinstance(nested, dict):
                yield from _geometry_coordinate_pairs(nested)


def _validate_geojson(
    geojson: Any,
    *,
    scenario_id: str,
    scenario_hash: str,
    generator_version: str,
) -> tuple[tuple[RetainedBuilding, ...], int]:
    if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
        raise PreviewCatalogError("scenario geometry is not a GeoJSON FeatureCollection")
    if geojson.get("crs", {}).get("properties", {}).get("name") != "EPSG:28992":
        raise PreviewCatalogError("scenario geometry CRS must be EPSG:28992")
    if geojson.get("name") != scenario_id:
        raise PreviewCatalogError("scenario identity mismatch in GeoJSON")
    properties = geojson.get("properties")
    if not isinstance(properties, dict):
        raise PreviewCatalogError("scenario identity properties are missing")
    if (
        properties.get("scenario_hash") != scenario_hash
        or properties.get("generator_version") != generator_version
        or properties.get("validation_valid") is not True
    ):
        raise PreviewCatalogError("scenario identity or validation status mismatch in GeoJSON")
    features = geojson.get("features")
    if not isinstance(features, list) or not features:
        raise PreviewCatalogError("scenario GeoJSON has no features")

    retained: list[RetainedBuilding] = []
    parsed_features = []
    study_area_geometries = []
    generated_building_count = 0
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise PreviewCatalogError("invalid GeoJSON feature schema")
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            raise PreviewCatalogError("GeoJSON feature geometry is missing")
        _check_finite(geometry, context="GeoJSON geometry")
        try:
            parsed_geometry = shape(geometry)
        except Exception as exc:
            raise PreviewCatalogError(f"invalid GeoJSON geometry at feature {index}") from exc
        if parsed_geometry.is_empty or not parsed_geometry.is_valid:
            raise PreviewCatalogError(f"empty or invalid geometry at feature {index}")
        coordinate_pairs = tuple(_geometry_coordinate_pairs(geometry))
        if not coordinate_pairs:
            raise PreviewCatalogError(f"GeoJSON geometry has no coordinates at feature {index}")
        for x, y in coordinate_pairs:
            if not (EPSG_28992_X_RANGE[0] <= x <= EPSG_28992_X_RANGE[1]) or not (
                EPSG_28992_Y_RANGE[0] <= y <= EPSG_28992_Y_RANGE[1]
            ):
                raise PreviewCatalogError("EPSG:28992 coordinate bounds are invalid")
        feature_properties = feature.get("properties")
        if not isinstance(feature_properties, dict):
            raise PreviewCatalogError("invalid GeoJSON feature properties")
        feature_kind = feature_properties.get("feature_kind")
        parsed_features.append(parsed_geometry)
        if feature_kind == "study_area":
            study_area_geometries.append(parsed_geometry)
        elif feature_kind == "generated_building":
            generated_building_count += 1
        elif feature_kind == "preserved_building":
            confidence = feature_properties.get("confidence")
            floor_status = feature_properties.get("floor_estimate_status")
            floor_count = feature_properties.get("floor_count")
            height = feature_properties.get("height_m")
            if confidence not in {"LOW", "MEDIUM", "HIGH"}:
                raise PreviewCatalogError("unknown retained-building confidence")
            if not isinstance(floor_status, str) or not floor_status:
                raise PreviewCatalogError("retained-building floor status is missing")
            if floor_count is not None and (isinstance(floor_count, bool) or not isinstance(floor_count, int)):
                raise PreviewCatalogError("invalid retained-building floor count")
            if floor_status == "UNKNOWN" and (
                "floor_count" not in feature_properties
                or "height_m" not in feature_properties
                or floor_count is not None
                or height is not None
            ):
                raise PreviewCatalogError("UNKNOWN retained-building floor count and height must be null")
            retained.append(
                RetainedBuilding(
                    feature_id=str(feature.get("id")) if feature.get("id") is not None else None,
                    confidence=confidence,
                    floor_estimate_status=floor_status,
                    floor_count=floor_count,
                    height_m=_number(height, context="retained height", nullable=True),
                )
            )
    if len(study_area_geometries) != 1:
        raise PreviewCatalogError("scenario geometry must contain exactly one StudyArea")
    min_x, min_y, max_x, max_y = study_area_geometries[0].bounds
    for parsed_geometry in parsed_features:
        feature_min_x, feature_min_y, feature_max_x, feature_max_y = parsed_geometry.bounds
        if (
            feature_min_x < min_x
            or feature_min_y < min_y
            or feature_max_x > max_x
            or feature_max_y > max_y
        ):
            raise PreviewCatalogError("feature geometry lies outside the candidate StudyArea bounding box")
    return tuple(retained), generated_building_count


def _collect_hash_refs(value: Any, *, prefix: str = "") -> tuple[PreviewInputReference, ...]:
    refs: list[PreviewInputReference] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            label = f"{prefix}.{key}" if prefix else key
            if key.endswith("sha256") and isinstance(nested, str):
                normalized = nested.removeprefix("sha256:")
                if SHA256_PATTERN.fullmatch(normalized):
                    refs.append(PreviewInputReference(label=label, sha256=normalized))
            else:
                refs.extend(_collect_hash_refs(nested, prefix=label))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            refs.extend(_collect_hash_refs(nested, prefix=f"{prefix}[{index}]"))
    return tuple(refs)


def load_catalog(root: Path, manifest_sha256: str) -> PreviewCatalog:
    """Load a pinned preview bundle and retain the exact verified bytes served later."""
    if not isinstance(manifest_sha256, str) or not SHA256_PATTERN.fullmatch(manifest_sha256):
        raise PreviewCatalogError("configured manifest SHA-256 is invalid")
    try:
        resolved_root = Path(root).resolve(strict=True)
        if not resolved_root.is_dir():
            raise PreviewCatalogError("configured preview root is not a directory")
        root_fd = os.open(
            resolved_root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NONBLOCK", 0),
        )
    except PreviewCatalogError:
        raise
    except FileNotFoundError as exc:
        raise PreviewCatalogError("configured preview root is missing", category="missing_file") from exc
    except OSError as exc:
        raise PreviewCatalogError("configured preview root is unreadable", category="unsafe_path") from exc

    try:
        manifest_bytes = _read_beneath(root_fd, MANIFEST_NAME)
        actual_manifest_sha = _sha256(manifest_bytes)
        if not hmac.compare_digest(actual_manifest_sha, manifest_sha256):
            raise PreviewCatalogError("manifest digest does not match the configured pin", category="hash_mismatch")
        manifest = _require_keys(
            _loads_json(manifest_bytes, context=MANIFEST_NAME), MANIFEST_KEYS, context=MANIFEST_NAME
        )
        if (
            manifest["schema_version"] != MANIFEST_SCHEMA
            or manifest["algorithm"] != "SHA-256"
            or manifest["manifest_excludes_self"] is not True
            or not isinstance(manifest["files"], dict)
        ):
            raise PreviewCatalogError("unsupported artifact manifest schema or status")
        manifest_files = manifest["files"]
        for manifest_path in manifest_files:
            _safe_manifest_path(manifest_path)

        comparison_sha, comparison_size = _manifest_entry(manifest_files, COMPARISON_NAME)
        comparison_bytes = _read_beneath(root_fd, COMPARISON_NAME, expected_size=comparison_size)
        if len(comparison_bytes) != comparison_size or not hmac.compare_digest(_sha256(comparison_bytes), comparison_sha):
            raise PreviewCatalogError("comparison artifact hash or size integrity mismatch", category="hash_mismatch")
        comparison = _require_keys(
            _loads_json(comparison_bytes, context=COMPARISON_NAME), COMPARISON_KEYS, context=COMPARISON_NAME
        )
        if (
            comparison["schema_version"] != COMPARISON_SCHEMA
            or comparison["generator_version"] != GENERATOR_VERSION
            or comparison["run_status"] != "UNAPPROVED_PREVIEW"
            or comparison["human_decision_created"] is not False
            or comparison["overall_winner"] is not None
            or comparison["decision_rule"] is not None
        ):
            raise PreviewCatalogError("unsupported comparison schema or preview decision status")
        study_area = _require_keys(comparison["study_area"], STUDY_AREA_KEYS, context="study area")
        if study_area["horizontal_crs"] != "EPSG:28992" or study_area["units"] != "m":
            raise PreviewCatalogError("comparison StudyArea CRS or units mismatch")
        if not isinstance(comparison["limitations"], list) or not all(
            isinstance(item, str) for item in comparison["limitations"]
        ):
            raise PreviewCatalogError("comparison limitations schema is invalid")
        seed = comparison["seed"]
        strategies = comparison["strategies"]
        if isinstance(seed, bool) or not isinstance(seed, int) or not isinstance(strategies, list) or not strategies:
            raise PreviewCatalogError("comparison strategy schema is invalid")
        if comparison["strategy_count"] != len(strategies):
            raise PreviewCatalogError("comparison strategy count mismatch")

        identities_seen: set[tuple[str, str]] = set()
        expected_paths = {COMPARISON_NAME, "comparison.png"}
        normalized_strategies: list[dict[str, Any]] = []
        valid_counts = {"A": 0, "B": 0}
        for raw_candidate in strategies:
            candidate = _require_keys(raw_candidate, STRATEGY_KEYS, context="comparison strategy")
            intensity = candidate["intensity"]
            strategy_id = _safe_strategy_id(candidate["strategy_id"])
            if intensity not in INTENSITIES:
                raise PreviewCatalogError("unsupported candidate intensity")
            identity_key = (intensity, strategy_id)
            if identity_key in identities_seen:
                raise PreviewCatalogError("duplicate preview identity")
            identities_seen.add(identity_key)
            if (
                not isinstance(candidate["scenario_id"], str)
                or not candidate["scenario_id"]
                or not isinstance(candidate["scenario_hash"], str)
                or not SHA256_PATTERN.fullmatch(candidate["scenario_hash"])
                or candidate["valid"] is not True
                or candidate["failure_reasons"] != []
                or not isinstance(candidate["warnings"], list)
                or not all(isinstance(item, str) for item in candidate["warnings"])
                or not isinstance(candidate["artifact_hashes"], dict)
                or set(candidate["artifact_hashes"]) != set(ARTIFACT_NAMES)
            ):
                raise PreviewCatalogError("candidate schema, identity, or validation status is invalid")
            for name in ARTIFACT_NAMES:
                relative = f"{intensity}/{strategy_id}/{name}"
                expected_paths.add(relative)
                candidate_hash = candidate["artifact_hashes"][name]
                if not isinstance(candidate_hash, str) or not SHA256_PATTERN.fullmatch(candidate_hash):
                    raise PreviewCatalogError(f"candidate artifact hash is invalid: {relative}")
                manifest_hash, _ = _manifest_entry(manifest_files, relative)
                if not hmac.compare_digest(candidate_hash, manifest_hash):
                    raise PreviewCatalogError("candidate artifact hash mismatch", category="hash_mismatch")
            valid_counts[intensity] += 1
            normalized_strategies.append(candidate)

        if set(manifest_files) != expected_paths:
            raise PreviewCatalogError("manifest file inventory does not match comparison candidates")
        if comparison["valid_count_by_intensity"] != valid_counts:
            raise PreviewCatalogError("comparison intensity counts mismatch")
        if any(valid_counts[intensity] == 0 for intensity in INTENSITIES):
            raise PreviewCatalogError("comparison does not contain both intensity sets")

        all_bytes = _verified_files(root_fd, manifest_files)
        if not all_bytes[COMPARISON_NAME] == comparison_bytes:
            raise PreviewCatalogError("comparison bytes changed during catalog load", category="hash_mismatch")
        comparison_png = all_bytes["comparison.png"]
        if not comparison_png.startswith(PNG_SIGNATURE):
            raise PreviewCatalogError("comparison image is not a PNG")

        limits_by_intensity: dict[str, IntensityLimits] = {}
        records: list[PreviewRecord] = []
        catalog_refs = list(_collect_hash_refs(study_area, prefix="study_area"))
        catalog_limitations = list(comparison["limitations"])
        catalog_limitations.extend(
            (
                "Run creation time is UNKNOWN because the source bundle does not record it.",
                "Generator source commit is UNKNOWN because the source bundle does not attest it.",
            )
        )
        for candidate in normalized_strategies:
            intensity = candidate["intensity"]
            strategy_id = candidate["strategy_id"]
            scenario_id = candidate["scenario_id"]
            scenario_hash = candidate["scenario_hash"]
            prefix = f"{intensity}/{strategy_id}/"
            json_values = {
                name: _loads_json(all_bytes[prefix + name], context=prefix + name)
                for name in ("metrics.json", "recipe.json", "scenario.geojson")
            }
            metrics = _require_keys(
                json_values["metrics.json"],
                {
                    "generation_metadata", "human_decision_created", "intensity", "metrics",
                    "orientation", "scenario_hash", "scenario_id", "scenario_status", "valid", "validation",
                },
                context=prefix + "metrics.json",
            )
            recipe = json_values["recipe.json"]
            if not isinstance(recipe, dict) or recipe.get("schema_version") != RECIPE_SCHEMA:
                raise PreviewCatalogError("unsupported morphology recipe schema")
            recipe_run = recipe.get("run")
            generation = metrics["generation_metadata"]
            metric_intensity = metrics["intensity"]
            validation = metrics["validation"]
            metric_results = metrics["metrics"]
            if (
                not isinstance(generation, dict)
                or not isinstance(metric_intensity, dict)
                or not isinstance(validation, dict)
                or not isinstance(metric_results, dict)
            ):
                raise PreviewCatalogError("metrics identity schema is invalid")
            generator_version = generation.get("generator_version")
            if (
                metrics["scenario_id"] != scenario_id
                or metrics["scenario_hash"] != scenario_hash
                or metrics["scenario_status"] != "UNAPPROVED_PREVIEW"
                or metrics["human_decision_created"] is not False
                or metrics["valid"] is not True
                or validation.get("valid") is not True
                or metric_intensity.get("code") != intensity
                or recipe.get("id") != strategy_id
                or not isinstance(recipe_run, dict)
                or recipe_run.get("intensity") != intensity
                or recipe_run.get("scenario_hash") != scenario_hash
                or recipe_run.get("seed") != seed
                or generation.get("recipe_id") != strategy_id
                or not isinstance(generator_version, str)
                or generator_version != comparison["generator_version"]
            ):
                raise PreviewCatalogError(f"candidate scenario identity or status mismatch: {scenario_id}")
            measured_summary: dict[str, float] = {}
            for summary_field, metric_group, metric_field in (
                ("land_far", "far_land_area", "known_value"),
                ("coverage_ratio", "coverage_ratio", "value"),
                ("maximum_height_m", "maximum_height_m", "known_all_building_m"),
                ("open_space_ratio", "open_space_ratio", "value"),
            ):
                metric_group_value = metric_results.get(metric_group)
                if not isinstance(metric_group_value, dict):
                    raise PreviewCatalogError(f"metrics.json is missing {metric_group}")
                measured_value = _number(
                    metric_group_value.get(metric_field),
                    context=f"metrics.json {metric_group}.{metric_field}",
                )
                summary_value = _number(candidate[summary_field], context=f"comparison {summary_field}")
                if summary_value != measured_value:
                    raise PreviewCatalogError(
                        f"comparison {summary_field} summary does not match metrics.json"
                    )
                measured_summary[summary_field] = measured_value

            measured_building_count = metric_results.get("building_count")
            summary_building_count = candidate["building_count"]
            if (
                isinstance(measured_building_count, bool)
                or not isinstance(measured_building_count, int)
                or measured_building_count < 0
                or isinstance(summary_building_count, bool)
                or not isinstance(summary_building_count, int)
                or summary_building_count != measured_building_count
            ):
                raise PreviewCatalogError(
                    "comparison building_count summary does not match metrics.json"
                )
            metric_warnings = validation.get("warnings")
            if not isinstance(metric_warnings, list) or not all(
                isinstance(item, str) for item in metric_warnings
            ):
                raise PreviewCatalogError("metrics.json validation warnings schema is invalid")
            if candidate["warnings"] != metric_warnings:
                raise PreviewCatalogError("comparison warnings summary does not match metrics.json")

            geojson = json_values["scenario.geojson"]
            retained, generated_building_count = _validate_geojson(
                geojson,
                scenario_id=scenario_id,
                scenario_hash=scenario_hash,
                generator_version=generator_version,
            )
            if measured_building_count != generated_building_count:
                raise PreviewCatalogError(
                    "metrics.json building_count does not match generated_building feature count"
                )
            recipe_digest = generation.get("recipe_sha256")
            if (
                not isinstance(recipe_digest, str)
                or recipe.get("recipe_sha256") != recipe_digest
            ):
                raise PreviewCatalogError("recipe provenance hash mismatch")
            limits = IntensityLimits(
                intensity=intensity,
                far_upper_bound_land=_number(
                    metric_intensity.get("far_upper_bound_land"), context="FAR upper bound"
                ),
                coverage_upper_bound=_number(
                    metric_intensity.get("coverage_upper_bound"), context="coverage upper bound", nullable=True
                ),
                height_upper_bound_new_buildings_m=_number(
                    metric_intensity.get("height_upper_bound_new_buildings_m"),
                    context="new-building height upper bound",
                ),
            )
            prior_limits = limits_by_intensity.setdefault(intensity, limits)
            if prior_limits != limits:
                raise PreviewCatalogError("intensity assumptions differ among candidates")
            metrics_summary = PreviewMetrics(
                building_count=measured_building_count,
                known_part_land_far=measured_summary["land_far"],
                coverage_ratio=measured_summary["coverage_ratio"],
                maximum_height_m=measured_summary["maximum_height_m"],
                open_space_ratio=measured_summary["open_space_ratio"],
                generator_valid=metrics["valid"],
                warnings=tuple(metric_warnings),
            )
            identity = PreviewIdentity(
                intensity=intensity,
                strategy_id=strategy_id,
                status="UNAPPROVED_PREVIEW",
                human_decision_created=False,
                generator_version=generator_version,
                run_created_at=None,
                generator_commit=None,
            )
            source_refs = _collect_hash_refs(generation.get("source_provenance", {}), prefix="source_provenance")
            source_refs += _collect_hash_refs(generation.get("dictionary_catalogue", {}), prefix="dictionary_catalogue")
            source_refs += _collect_hash_refs(study_area, prefix="study_area")
            for ref in source_refs:
                catalog_refs.append(ref)
            record_limitations = tuple(catalog_limitations)
            for image_name in ("plan.png", "axonometric.png"):
                if not all_bytes[prefix + image_name].startswith(PNG_SIGNATURE):
                    raise PreviewCatalogError(f"preview image is not a PNG: {prefix + image_name}")
            assets = tuple(
                VerifiedAsset(
                    kind=kind,
                    content=all_bytes[prefix + ASSET_NAME_BY_KIND[kind]],
                    media_type="application/geo+json" if kind == "geometry" else "image/png",
                    sha256=_sha256(all_bytes[prefix + ASSET_NAME_BY_KIND[kind]]),
                )
                for kind in SERVED_KINDS
            )
            records.append(
                PreviewRecord(
                    identity=identity,
                    strategy_label=candidate["strategy_label"],
                    limits=limits,
                    metrics=metrics_summary,
                    retained_buildings=retained,
                    input_refs=tuple(dict.fromkeys(source_refs)),
                    limitations=record_limitations,
                    verified_assets=assets,
                )
            )

        return PreviewCatalog(
            identities=tuple(record.identity for record in records),
            limits=tuple(limits_by_intensity[key] for key in INTENSITIES),
            records=tuple(records),
            manifest_sha256=actual_manifest_sha,
            comparison_sha256=comparison_sha,
            input_refs=tuple(dict.fromkeys(catalog_refs)),
            limitations=tuple(dict.fromkeys(catalog_limitations)),
            seed=seed,
        )
    except PreviewCatalogError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise PreviewCatalogError("configured bundle schema or typed value is invalid") from exc
    finally:
        os.close(root_fd)


def get_asset(catalog: PreviewCatalog, intensity: str, strategy_id: str, kind: str) -> VerifiedAsset:
    if kind not in SERVED_KINDS:
        raise PreviewCatalogError("unknown preview asset kind")
    record = catalog.get_preview(intensity, strategy_id)
    asset = next((item for item in record.verified_assets if item.kind == kind), None)
    if asset is None:
        raise PreviewCatalogError("preview asset is unavailable")
    if not hmac.compare_digest(_sha256(asset.content), asset.sha256):
        raise PreviewCatalogError("in-memory preview asset integrity mismatch", category="hash_mismatch")
    return asset
