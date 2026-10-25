from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr
from starlette.responses import Response

from .preview_catalog import (
    IntensityLimits,
    PreviewCatalog,
    PreviewCatalogError,
    PreviewIdentity,
    PreviewRecord,
    PreviewInputReference,
    PreviewMetrics,
    RetainedBuilding,
    get_asset,
    load_catalog,
)

logger = logging.getLogger(__name__)


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PreviewAssetLinks(_ResponseModel):
    plan: StrictStr
    axonometric: StrictStr
    geometry: StrictStr


class PreviewItemResponse(_ResponseModel):
    verified_at_utc: StrictStr
    source_reverified: Literal[False]
    identity: PreviewIdentity
    strategy_label: StrictStr
    limits: IntensityLimits
    metrics: PreviewMetrics
    retained_buildings: tuple[RetainedBuilding, ...]
    input_refs: tuple[PreviewInputReference, ...]
    limitations: tuple[StrictStr, ...]
    assets: PreviewAssetLinks


class PreviewCatalogResponse(_ResponseModel):
    status: Literal["DISABLED", "AVAILABLE"]
    verified_at_utc: StrictStr | None
    source_reverified: Literal[False]
    count: StrictInt
    previews: tuple[PreviewItemResponse, ...]
    limits: tuple[IntensityLimits, ...]
    manifest_sha256: StrictStr | None
    comparison_sha256: StrictStr | None
    input_refs: tuple[PreviewInputReference, ...]
    limitations: tuple[StrictStr, ...]
    seed: StrictInt | None


def _asset_url(intensity: str, strategy_id: str, kind: str) -> str:
    return f"/api/v1/morphology/previews/{intensity}/{strategy_id}/assets/{kind}"


def _item_response(record: PreviewRecord, verified_at_utc: str) -> PreviewItemResponse:
    return PreviewItemResponse(
        verified_at_utc=verified_at_utc,
        source_reverified=False,
        identity=record.identity,
        strategy_label=record.strategy_label,
        limits=record.limits,
        metrics=record.metrics,
        retained_buildings=record.retained_buildings,
        input_refs=record.input_refs,
        limitations=record.limitations,
        assets=PreviewAssetLinks(
            plan=_asset_url(record.identity.intensity, record.identity.strategy_id, "plan"),
            axonometric=_asset_url(record.identity.intensity, record.identity.strategy_id, "axonometric"),
            geometry=_asset_url(record.identity.intensity, record.identity.strategy_id, "geometry"),
        ),
    )


def create_preview_router(
    *,
    root: Path | None = None,
    manifest_sha256: str | None = None,
) -> APIRouter:
    """Create a standalone GET-only router; it has no project-store dependency."""
    if root is not None and not str(root).strip():
        raise ValueError("morphology preview root must not be blank")
    if manifest_sha256 is not None and not manifest_sha256.strip():
        raise ValueError("morphology preview manifest sha256 must not be blank")
    if (root is None) != (manifest_sha256 is None):
        raise ValueError("preview root and pinned manifest SHA-256 must be configured together")

    catalog: PreviewCatalog | None = None
    unavailable = False
    unavailable_category: str | None = None
    verified_at_utc: str | None = None
    if root is not None and manifest_sha256 is not None:
        try:
            catalog = load_catalog(root, manifest_sha256)
            verified_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except (PreviewCatalogError, OSError, ValueError) as exc:
            unavailable = True
            unavailable_category = getattr(
                exc,
                "category",
                "missing_file" if isinstance(exc, FileNotFoundError) else "schema_error",
            )
            logger.warning(
                "Morphology preview catalog load rejected (category=%s, error_type=%s)",
                unavailable_category,
                type(exc).__name__,
            )

    router = APIRouter(prefix="/api/v1/morphology/previews", tags=["morphology-previews"])

    def require_catalog() -> PreviewCatalog:
        if catalog is None:
            if unavailable:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Configured morphology preview bundle is unavailable "
                        f"(category={unavailable_category or 'schema_error'})."
                    ),
                )
            raise HTTPException(status_code=503, detail="Morphology preview catalog is disabled.")
        return catalog

    @router.get("", response_model=PreviewCatalogResponse)
    def list_previews() -> PreviewCatalogResponse:
        if root is None:
            return PreviewCatalogResponse(
                status="DISABLED",
                verified_at_utc=None,
                source_reverified=False,
                count=0,
                previews=(),
                limits=(),
                manifest_sha256=None,
                comparison_sha256=None,
                input_refs=(),
                limitations=(),
                seed=None,
            )
        active = require_catalog()
        assert verified_at_utc is not None
        items = tuple(_item_response(record, verified_at_utc) for record in active.records)
        return PreviewCatalogResponse(
            status="AVAILABLE",
            verified_at_utc=verified_at_utc,
            source_reverified=False,
            count=len(items),
            previews=items,
            limits=active.limits,
            manifest_sha256=active.manifest_sha256,
            comparison_sha256=active.comparison_sha256,
            input_refs=active.input_refs,
            limitations=active.limitations,
            seed=active.seed,
        )

    @router.get("/{intensity}/{strategy_id}", response_model=PreviewItemResponse)
    def get_preview_detail(intensity: str, strategy_id: str) -> PreviewItemResponse:
        active = require_catalog()
        try:
            record = active.get_preview(intensity, strategy_id)
        except PreviewCatalogError as exc:
            raise HTTPException(status_code=404, detail="Unknown morphology preview.") from exc
        assert verified_at_utc is not None
        return _item_response(record, verified_at_utc)

    @router.get("/{intensity}/{strategy_id}/assets/{kind}")
    def get_preview_asset(intensity: str, strategy_id: str, kind: str) -> Response:
        if kind not in {"plan", "axonometric", "geometry"}:
            raise HTTPException(status_code=404, detail="Unknown morphology preview asset.")
        active = require_catalog()
        try:
            asset = get_asset(active, intensity, strategy_id, kind)
        except PreviewCatalogError as exc:
            raise HTTPException(status_code=404, detail="Unknown morphology preview asset.") from exc
        return Response(
            content=asset.content,
            media_type=asset.media_type,
            headers={
                "ETag": f'"{asset.sha256}"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
