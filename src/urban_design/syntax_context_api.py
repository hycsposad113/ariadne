from __future__ import annotations

import hashlib
import json
import logging
import math
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path as FPath, Query
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

SUPPORTED_MODES = ("pedestrian", "bicycle", "motor_vehicle")
SyntaxContextMode = Literal["pedestrian", "bicycle", "motor_vehicle"]
ManifestBinding = Literal["SHIPPED", "UNBOUND_MANIFEST"]

# The surrounding-syntax run of record. Readiness labels cite this hash.
# Matching it does not promote a layer to PASS or to a formal result.
SHIPPED_SYNTAX_CONTEXT_MANIFEST_SHA256 = "a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1"

_READINESS_BY_RADIUS_M: dict[float, str] = {
    800.0: "BLOCKED_BOUNDARY_STABILITY_UNASSESSED",
    2000.0: "EXPLORATORY",
    10000.0: "EXPLORATORY",
}


def syntax_context_readiness(*, mode: str, radius_m: float, manifest_sha256: str) -> dict[str, Any]:
    """Radius label bound to the verified manifest hash. Never a formal result."""
    pin = manifest_sha256.lower()
    binding: ManifestBinding = (
        "SHIPPED" if pin == SHIPPED_SYNTAX_CONTEXT_MANIFEST_SHA256 else "UNBOUND_MANIFEST"
    )
    status = next(
        (label for known, label in _READINESS_BY_RADIUS_M.items() if abs(float(radius_m) - known) <= 1e-6),
        "BLOCKED_BOUNDARY_STABILITY_UNASSESSED",
    )
    if abs(float(radius_m) - 800.0) <= 1e-6:
        reason = (
            "Boundary stability has not been demonstrated for the 800 m radius. "
            f"Manifest {pin} stays BLOCKED_BOUNDARY_STABILITY_UNASSESSED and is not PASS."
        )
    elif status == "EXPLORATORY":
        reason = (
            f"The {float(radius_m):g} m layer on manifest {pin} is EXPLORATORY display. "
            "It is not a formal result. Network policy and method thresholds remain a Founder decision."
        )
    else:
        reason = (
            f"Radius {float(radius_m):g} m has no assessed boundary-stability binding. "
            f"Manifest {pin} is not a formal result."
        )
    return {
        "mode": mode,
        "radius_m": float(radius_m),
        "status": status,
        "reason": reason,
        "manifest_sha256": pin,
        "formal_result": False,
        "bound_manifest_sha256": SHIPPED_SYNTAX_CONTEXT_MANIFEST_SHA256,
        "manifest_binding": binding,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def calculate_quantile_breaks(values: list[float]) -> list[float]:
    ordered = sorted(v for v in values if math.isfinite(v))
    if not ordered:
        return [0.0] * 6
    pick = lambda q: round(ordered[min(len(ordered) - 1, int(len(ordered) * q))], 4)  # noqa: E731
    return [round(ordered[0], 4), pick(0.2), pick(0.4), pick(0.6), pick(0.8), round(ordered[-1], 4)]


def load_verified_manifest(root: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest missing: {manifest_path}")
    actual_sha = sha256_file(manifest_path)
    if expected_sha256 is not None and actual_sha.lower() != expected_sha256.lower():
        raise ValueError(f"manifest sha256 mismatch: expected {expected_sha256}, got {actual_sha}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "syntax-context-v1":
        raise ValueError(f"unsupported syntax context schema version: {data.get('schema_version')}")
    return data


def load_verified_mode(root: Path, manifest: dict[str, Any], mode: str) -> dict[str, Any]:
    outputs = manifest.get("outputs", {})
    if mode not in outputs:
        raise KeyError(f"mode {mode} not present in manifest outputs")
    entry = outputs[mode]
    path_val = entry.get("path")
    if not path_val:
        raise ValueError(f"missing path in manifest entry for mode {mode}")
    mode_file = root / path_val
    if not mode_file.is_file():
        raise FileNotFoundError(f"mode file missing: {mode_file}")
    expected_sha = entry.get("sha256")
    actual_sha = sha256_file(mode_file)
    if expected_sha is not None and actual_sha.lower() != expected_sha.lower():
        raise ValueError(f"mode {mode} sha256 mismatch: expected {expected_sha}, got {actual_sha}")
    data = json.loads(mode_file.read_text(encoding="utf-8"))
    return data


class LegendBreaks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nain: list[float]
    nach: list[float]


class SyntaxContextSegment(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    coordinates: list[list[float]]
    distance_to_site_m: float
    inside_site: bool
    boundary_effect_risk: bool
    nain: float
    nach: float


class SyntaxContextReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str
    radius_m: float
    status: str
    reason: str
    manifest_sha256: str
    formal_result: bool
    bound_manifest_sha256: str
    manifest_binding: ManifestBinding


class SyntaxContextCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    status: Literal["AVAILABLE", "NOT_CONFIGURED", "VALIDATION_FAILED"]
    reason_zh: str
    modes: list[str]


class SyntaxContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str
    radius_m: float
    distance_m: float
    reliable_within_m: float
    evidence_level: str
    limitations: str
    attribution: str
    segment_count: int
    legend_breaks: LegendBreaks
    segments: list[dict[str, Any]]
    readiness: SyntaxContextReadiness


def create_syntax_context_router(
    root: Path | None = None,
    manifest_sha256: str | None = None,
    *,
    strict: bool = False,
) -> APIRouter:
    manifest_cache: dict[str, Any] | None = None
    mode_cache: dict[str, dict[str, Any]] = {}
    load_error: str | None = None
    verified_manifest_sha: str | None = None

    if root is not None:
        try:
            manifest_cache = load_verified_manifest(Path(root), manifest_sha256)
            verified_manifest_sha = (manifest_sha256 or sha256_file(Path(root) / "manifest.json")).lower()
        except Exception as exc:
            load_error = str(exc)
            logger.warning("Syntax context manifest verification failed: %s", exc)
            if strict:
                raise

    router = APIRouter(prefix="/api/v1/projects", tags=["syntax-context"])

    @router.get("/{project_id}/syntax/context/capabilities", response_model=SyntaxContextCapabilities)
    def syntax_context_capabilities(project_id: str = FPath(..., min_length=1)) -> dict[str, Any]:
        enabled = root is not None and load_error is None
        return {
            "enabled": enabled,
            "status": "AVAILABLE" if enabled else ("NOT_CONFIGURED" if root is None else "VALIDATION_FAILED"),
            "reason_zh": "周邊語法圖層可供探索性顯示。" if enabled else (
                "此工作階段未啟用周邊語法圖層；方案語法摘要仍可在方案側欄查看。"
                if root is None else "周邊語法資料未通過來源驗證，暫停顯示。"
            ),
            "modes": list(manifest_cache.get("outputs", {})) if enabled and manifest_cache else [],
        }

    @router.get("/{project_id}/syntax/context", response_model=SyntaxContextResponse)
    def get_syntax_context(
        project_id: str = FPath(..., min_length=1),
        mode: SyntaxContextMode = Query(...),
        distance_m: float = Query(1000.0, ge=0),
    ) -> dict[str, Any]:
        if root is None:
            raise HTTPException(status_code=503, detail="SYNTAX_CONTEXT_NOT_CONFIGURED")
        if load_error is not None:
            raise HTTPException(status_code=503, detail=f"SYNTAX_CONTEXT_HASH_MISMATCH: {load_error}")
        assert manifest_cache is not None
        assert verified_manifest_sha is not None

        max_context_m = float(manifest_cache.get("max_context_m", 3000.0))
        if distance_m > max_context_m or distance_m < 0:
            raise HTTPException(
                status_code=422,
                detail=f"distance_m must be between 0 and {max_context_m}",
            )

        outputs = manifest_cache.get("outputs", {})
        if mode not in outputs:
            raise HTTPException(status_code=404, detail="SYNTAX_CONTEXT_MODE_UNAVAILABLE")

        if mode not in mode_cache:
            try:
                mode_cache[mode] = load_verified_mode(Path(root), manifest_cache, mode)
            except (ValueError, FileNotFoundError) as exc:
                if isinstance(exc, FileNotFoundError):
                    raise HTTPException(status_code=404, detail="SYNTAX_CONTEXT_MODE_UNAVAILABLE") from exc
                raise HTTPException(status_code=503, detail=f"SYNTAX_CONTEXT_CORRUPT: {exc}") from exc

        mode_data = mode_cache[mode]
        all_segments = mode_data.get("segments", [])
        filtered_segments = [s for s in all_segments if s["distance_to_site_m"] <= distance_m]

        nain_breaks = calculate_quantile_breaks([s["nain"] for s in filtered_segments])
        nach_breaks = calculate_quantile_breaks([s["nach"] for s in filtered_segments])
        radius_m = float(mode_data.get("radius_m", 800.0))

        return {
            "mode": mode,
            "radius_m": radius_m,
            "distance_m": distance_m,
            "reliable_within_m": float(mode_data.get("reliable_within_m", 700.0)),
            "evidence_level": mode_data.get("evidence_level", "EXPLORATORY"),
            "limitations": mode_data.get("limitations", ""),
            "attribution": mode_data.get("attribution", "© OpenStreetMap contributors (ODbL 1.0)"),
            "segment_count": len(filtered_segments),
            "legend_breaks": {
                "nain": nain_breaks,
                "nach": nach_breaks,
            },
            "segments": filtered_segments,
            "readiness": syntax_context_readiness(
                mode=mode,
                radius_m=radius_m,
                manifest_sha256=verified_manifest_sha,
            ),
        }

    return router
