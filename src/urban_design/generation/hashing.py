"""Stable semantic hashing and request projection for generation contracts."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Mapping

from pydantic import BaseModel
import shapely
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from urban_design.generation.contracts import FrozenRef, GenerationContext, LocalWorldTransform


_CONTEXT_FIELDS = tuple(GenerationContext.model_fields)
GEOMETRY_TOLERANCE_VERSION = "geom-tolerance-v1"
_GEOMETRY_HASH_GRID_M = 0.001
_HASH_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _plain_coordinates(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_plain_coordinates(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("geometry coordinates must be finite")
    return 0.0 if isinstance(value, float) and value == 0.0 else value


def _geometry_structure(geometry: BaseGeometry) -> tuple[str, int, tuple[int, ...]]:
    if geometry.geom_type == "Polygon":
        polygons = (geometry,)
    elif geometry.geom_type == "MultiPolygon":
        polygons = tuple(geometry.geoms)
    elif geometry.geom_type.startswith("Multi"):
        return geometry.geom_type, len(geometry.geoms), ()
    else:
        return geometry.geom_type, 1, ()
    return geometry.geom_type, len(polygons), tuple(sorted(len(polygon.interiors) for polygon in polygons))


def canonical_geometry_payload(
    geometry: BaseGeometry | Mapping[str, Any], *, crs: str = "EPSG:28992"
) -> dict[str, Any]:
    """Canonicalize geometry for hashing without changing the source geometry.

    The 1 mm precision grid is hash-only. If snapping changes the geometry
    family, component count, or polygon hole topology, hashing fails rather
    than concealing a potentially meaningful narrow passage or void.
    """

    if crs != "EPSG:28992":
        raise ValueError("geometry hash requires projected metre CRS EPSG:28992")
    if isinstance(geometry, Mapping):
        declared_crs = geometry.get("crs")
        if declared_crs is not None and declared_crs != crs:
            raise ValueError("geometry CRS metadata disagrees with the declared projected CRS")
    try:
        original = geometry if isinstance(geometry, BaseGeometry) else shape(geometry)
    except Exception as error:
        raise ValueError(f"geometry cannot be parsed for semantic hashing: {error}") from error
    if original.is_empty:
        raise ValueError("geometry hash requires non-empty valid geometry")
    coordinates = shapely.get_coordinates(original)
    if not all(math.isfinite(float(value)) for row in coordinates for value in row):
        raise ValueError("geometry hash requires finite coordinates")
    if not original.is_valid:
        raise ValueError("geometry hash requires non-empty valid geometry")
    try:
        snapped = shapely.set_precision(original, grid_size=_GEOMETRY_HASH_GRID_M, mode="valid_output")
    except Exception as error:
        raise ValueError(f"geometry cannot be normalized to hash precision: {error}") from error
    if snapped.is_empty or not snapped.is_valid or _geometry_structure(snapped) != _geometry_structure(original):
        raise ValueError("geometry collapses or changes topology at hash precision")
    normalized = shapely.normalize(snapped)
    geometry_mapping = mapping(normalized)
    return {
        "crs": crs.strip(),
        "tolerance_version": GEOMETRY_TOLERANCE_VERSION,
        "geometry": {
            "type": geometry_mapping["type"],
            "coordinates": _plain_coordinates(geometry_mapping["coordinates"]),
        },
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="json"))
    if isinstance(value, BaseGeometry):
        return canonical_geometry_payload(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value({field.name: getattr(value, field.name) for field in fields(value)})
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("semantic hash mappings must use string keys")
        if "type" in value and "coordinates" in value and isinstance(value["type"], str):
            return canonical_geometry_payload(value, crs=str(value.get("crs", "EPSG:28992")))
        return {key: _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_json_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("semantic hash payload must not contain NaN or infinity")
    if isinstance(value, float) and value == 0.0:
        return 0.0
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported semantic hash value: {type(value).__name__}")


def semantic_digest(payload: Any) -> str:
    rendered = json.dumps(_json_value(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def project_request_to_context(request: Mapping[str, Any]) -> GenerationContext:
    """Project a request onto the explicit computation contract.

    UI mode, creation time, job identity, and other presentation metadata are
    intentionally dropped; all required context fields fail closed if absent.
    """

    missing = [field for field in _CONTEXT_FIELDS if field not in request and field != "local_world_transform"]
    if missing:
        raise KeyError(missing[0])
    return GenerationContext.model_validate({field: request[field] for field in _CONTEXT_FIELDS if field in request})


def generation_context_digest(context: GenerationContext | Mapping[str, Any]) -> str:
    projected = project_request_to_context(context) if isinstance(context, Mapping) else context
    return semantic_digest(projected)


def geometry_request_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return only fields that can change a generated geometry result.

    Required fields are checked explicitly so a malformed request cannot
    acquire a plausible hash from missing computation inputs. UI mode,
    timestamps, job identity, and other presentation metadata are omitted.
    """

    fields = (
        "input_refs",
        "input_hash",
        "geometry",
        "seed",
        "strategy_id",
        "algorithm_version",
        "method_parameters",
    )
    missing = [field for field in fields if field not in request]
    if missing:
        raise KeyError(missing[0])
    input_hash = request["input_hash"]
    if not isinstance(input_hash, str) or not _HASH_SHA256.fullmatch(input_hash):
        raise ValueError("input_hash must use sha256:<64 lowercase hex characters>")
    raw_refs = request["input_refs"]
    if not isinstance(raw_refs, (list, tuple)) or not raw_refs:
        raise ValueError("input_refs must contain at least one frozen reference")
    refs = [FrozenRef.model_validate(reference).model_dump(mode="json") for reference in raw_refs]
    refs.sort(key=lambda reference: (reference["id"], reference["sha256"], reference["kind"]))
    seed = request["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    for field in ("strategy_id", "algorithm_version"):
        if not isinstance(request[field], str) or not request[field].strip():
            raise ValueError(f"{field} must be non-empty")
    geometry = request["geometry"]
    geometry_crs = request.get("crs")
    if geometry_crs is None and isinstance(geometry, Mapping):
        geometry_crs = geometry.get("crs", "EPSG:28992")
    geometry_payload = canonical_geometry_payload(
        geometry,
        crs=geometry_crs or "EPSG:28992",
    )
    method_parameters = request["method_parameters"]
    if not isinstance(method_parameters, Mapping):
        raise ValueError("method_parameters must be a JSON object")
    normalized_parameters = _json_value(method_parameters)
    transform = request.get("local_world_transform")
    transform = LocalWorldTransform.model_validate(transform) if transform is not None else None
    return {
        "local_world_transform": transform.model_dump(mode="json") if transform is not None else None,
        "input_refs": refs,
        "input_hash": input_hash,
        "geometry": geometry_payload,
        "seed": seed,
        "strategy_id": request["strategy_id"].strip(),
        "algorithm_version": request["algorithm_version"].strip(),
        "method_parameters": normalized_parameters,
    }


def stage_artifact_digest(artifact: BaseModel | Mapping[str, Any]) -> str:
    payload = artifact.model_dump(mode="json") if isinstance(artifact, BaseModel) else dict(artifact)
    payload.pop("created_at", None)
    payload.pop("artifact_id", None)
    payload.pop("mode", None)
    payload.pop("job_id", None)
    return semantic_digest(payload)


def stage_seed(run_seed: int, strategy_id: str, stage: str) -> int:
    return int(semantic_digest({"seed": run_seed, "strategy": strategy_id, "stage": stage}).split(":", 1)[1][:16], 16)


__all__ = [
    "generation_context_digest",
    "canonical_geometry_payload",
    "geometry_request_payload",
    "project_request_to_context",
    "semantic_digest",
    "stage_artifact_digest",
    "stage_seed",
]
