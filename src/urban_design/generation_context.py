"""Read-only W6-03 context freeze. No approval or proposal is created here."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from shapely.geometry import mapping
from shapely.ops import unary_union

from .approved_generation import (
    ApprovedGenerationBlocked, _load_approved_inputs, _floor_estimates,
    _verify_artifact_bytes,
)
from .generation.height_binding import bind_retained_heights
from .far import FarSiteContext, resolve_far_denominator
from .store import EntityNotFoundError, ProjectStateStore


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FreezeRequest(Contract):
    expected_workspace_revision: StrictInt = Field(ge=1)
    expected_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class GenerationContext(Contract):
    project_id: str
    workspace_revision: int
    input_hash: str
    refs: tuple[dict[str, Any], ...]
    far_denominator: dict[str, Any]
    allocation_policy: str | None
    zones: tuple[dict[str, Any], ...]
    floor_estimates: tuple[dict[str, Any], ...]
    height_source_manifest: tuple[dict[str, Any], ...] = ()
    limitations: tuple[str, ...] = (
        "Exploration Design Area is a conceptual denominator, not a legal parcel.",
        "Floor counts and GFA are ESTIMATE; industrial upper bounds check FAR; unmatched GFA remains unavailable.",
        "Freeze is a read-only manifest, not a HumanDecision or generated proposal.",
    )


class Readiness(Contract):
    status: Literal["READY", "BLOCKED"]
    blockers: tuple[str, ...] = ()
    context_hash: str | None = None
    context: GenerationContext | None = None


def context_digest(context: GenerationContext) -> str:
    raw = json.dumps(context.model_dump(mode="json"), sort_keys=True,
                     separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def allocated_zones(inputs: Any) -> tuple[dict[str, Any], ...]:
    """Match existing generator semantics: workspace list order is priority order."""
    covered = None
    result = []
    for index, (zone_id, target_use, geometry) in enumerate(inputs.zones):
        effective = geometry
        if covered is not None and geometry.intersection(covered).area > 1e-3:
            if inputs.constraint_set.allocation_policy != "priority":
                raise ApprovedGenerationBlocked(["zone overlap has no approved priority allocation"])
        if covered is not None and inputs.constraint_set.allocation_policy == "priority":
            effective = geometry.difference(covered)
        covered = geometry if covered is None else unary_union((covered, geometry))
        result.append(dict(zone_id=zone_id, target_use=target_use, priority=index,
                           geometry=mapping(effective), allocated_area_m2=effective.area,
                           original_area_m2=geometry.area, crs="EPSG:28992"))
    return tuple(result)


def _get_project_db_head(connection: Any, project_id: str) -> tuple | None:
    if connection is None:
        return None
    try:
        row = connection.execute(
            """
            SELECT 
                (SELECT MAX(sequence) FROM ledger_events WHERE project_id = ? OR project_id IS NULL),
                (SELECT COUNT(*) FROM ledger_events WHERE project_id = ? OR project_id IS NULL),
                (SELECT SUM(current_revision) FROM state_heads WHERE project_id = ? OR project_id IS NULL),
                (SELECT COUNT(*) FROM state_heads WHERE project_id = ? OR project_id IS NULL)
            """,
            (project_id, project_id, project_id, project_id),
        ).fetchone()
        return (row[0], row[1], row[2], row[3])
    except Exception:
        return None


def _resolve(store: ProjectStateStore, project_id: str, *, connection: Any = None, use_cache: bool = True) -> Readiness:
    current_conn = connection or getattr(store, "_connection", None)
    current_db_head = _get_project_db_head(current_conn, project_id)
    cache = getattr(store, "_generation_context_cache", None)

    # 1. Cheap cache check before loading approved inputs or verifying hashes
    if use_cache and cache is not None and project_id in cache:
        cached_entry = cache[project_id]
        if current_db_head is not None and current_db_head == cached_entry.get("db_head"):
            files_valid = True
            for _aid, path_str, recorded_mtime, recorded_size in cached_entry.get("artifact_file_stats", ()):
                p = Path(path_str)
                if not p.is_file():
                    files_valid = False
                    break
                st = p.stat()
                if st.st_mtime_ns != recorded_mtime or st.st_size != recorded_size:
                    files_valid = False
                    break
            if files_valid:
                return cached_entry["readiness"]

    artifact_stats: list[tuple[str, str, int, int]] = []
    try:
        inputs = _load_approved_inputs(store, project_id, site_generation=True)
        try:
            store_artifacts = store.list_current("Artifact", project_id)
        except Exception:
            store_artifacts = []
        try:
            store_snapshots = store.list_current("DatasetSnapshot", project_id)
        except Exception:
            store_snapshots = []

        for s in (*inputs.source_snapshots, *store_snapshots):
            for field in ("raw_artifact_id", "normalized_artifact_id"):
                aid = s.payload.get(field)
                if isinstance(aid, str):
                    try:
                        rec = store.current(aid)
                        uri = rec.payload.get("uri")
                        if isinstance(uri, str):
                            p = Path(uri)
                            if p.is_file():
                                st = p.stat()
                                artifact_stats.append((aid, str(p.resolve()), st.st_mtime_ns, st.st_size))
                    except Exception:
                        pass
        for art in (*inputs.source_artifacts, *store_artifacts):
            uri = art.payload.get("uri")
            if isinstance(uri, str):
                p = Path(uri)
                if p.is_file():
                    st = p.stat()
                    artifact_stats.append((art.entity_id, str(p.resolve()), st.st_mtime_ns, st.st_size))

        # The legacy loader resolves disposition/road artifacts. Freeze also
        # binds every referenced raw/normalized source, including 3D BAG.
        artifacts = {r.entity_id: r for r in inputs.source_artifacts}
        for snapshot in inputs.source_snapshots:
            if any(token in str(snapshot.payload.get("source", "")).casefold()
                   for token in ("weather", "epw")):
                raise ApprovedGenerationBlocked(["weather sources remain suspended"])
            for field in ("raw_artifact_id", "normalized_artifact_id"):
                artifact_id = snapshot.payload.get(field)
                if not isinstance(artifact_id, str) or not artifact_id:
                    raise ApprovedGenerationBlocked([f"source {snapshot.entity_id}: missing {field}"])
                try:
                    artifacts[artifact_id] = _verify_artifact_bytes(store, artifact_id, project_id)
                except (EntityNotFoundError, ValueError, KeyError) as exc:
                    raise ApprovedGenerationBlocked([str(exc)]) from exc
        binding = bind_retained_heights(store, inputs) if getattr(inputs, "retained_buildings", ()) else None
        if binding is None:
            _, floors = _floor_estimates(store, inputs)
        else:
            floors = binding.estimates
            artifacts.update({a.entity_id: a for a in binding.artifacts})
            for art in binding.artifacts:
                uri = art.payload.get("uri")
                if isinstance(uri, str):
                    p = Path(uri)
                    if p.is_file():
                        st = p.stat()
                        artifact_stats.append((art.entity_id, str(p.resolve()), st.st_mtime_ns, st.st_size))
        records = (inputs.workspace_record, inputs.study_area, inputs.constraint_record,
                   *{s.entity_id: s for s in (*inputs.source_snapshots, *(binding.snapshots if binding else ()))}.values(),
                   *[artifacts[key] for key in sorted(artifacts)])
        refs = [dict(id=r.entity_id, revision=r.revision, entity_type=r.entity_type,
                     payload_hash=hashlib.sha256(json.dumps(r.payload, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode()).hexdigest()) for r in records]
        # Include the complete bound decisions without exposing any decision secret.
        for decision in (inputs.workspace_decision, inputs.constraint_decision):
            refs.append(dict(id=decision.id, target_id=decision.target_id,
                             target_version=decision.target_version,
                             target_payload_digest=decision.target_payload_digest))
        far_constraint = next(item for item in inputs.constraint_set.constraints if item.name == "far_upper_limit" and item.scope == "whole_site")
        far_area, far_label = resolve_far_denominator(far_constraint, FarSiteContext(inputs.design_area, inputs.water_geometry))
        context = GenerationContext(
            project_id=project_id, workspace_revision=inputs.workspace.revision,
            input_hash=inputs.input_hash, refs=tuple(refs),
            far_denominator=dict(scope="LAND_AREA" if far_constraint.denominator == "land_area" else "EXPLORATION_DESIGN_AREA", unit="m2",
                label=far_label, area_m2=far_area,
                water_geometry_hash=None if inputs.water_geometry is None else hashlib.sha256(inputs.water_geometry.normalize().wkb).hexdigest(),
                geometry_hash=hashlib.sha256(inputs.design_area.normalize().wkb).hexdigest(),
                decision_id=inputs.workspace_decision.id),
            allocation_policy=inputs.constraint_set.allocation_policy,
            zones=allocated_zones(inputs), floor_estimates=tuple(floors),
            height_source_manifest=binding.manifest if binding else ())
        readiness = Readiness(status="READY", context_hash=context_digest(context), context=context)
        if not hasattr(store, "_generation_context_cache"):
            store._generation_context_cache = {}
        if current_db_head is not None:
            store._generation_context_cache[project_id] = {
                "db_head": current_db_head,
                "artifact_file_stats": tuple(sorted(set(artifact_stats))),
                "readiness": readiness,
            }
        return readiness
    except ApprovedGenerationBlocked as exc:
        return Readiness(status="BLOCKED", blockers=tuple(exc.missing))


def resolve_readiness(store: ProjectStateStore, project_id: str, *, use_cache: bool = True) -> Readiness:
    # One SQLite read snapshot plus the store's existing lock prevents mixed revisions.
    with store.locked_connection() as connection:
        if connection.in_transaction:
            raise RuntimeError("context resolution requires its own read transaction")
        connection.execute("BEGIN")
        try:
            return _resolve(store, project_id, connection=connection, use_cache=use_cache)
        finally:
            connection.rollback()


def freeze_context(store: ProjectStateStore, project_id: str, request: FreezeRequest) -> Readiness:
    current = resolve_readiness(store, project_id, use_cache=False)
    if current.status != "READY":
        raise HTTPException(409, detail={"status": "BLOCKED", "blockers": current.blockers})
    assert current.context is not None
    if (current.context.workspace_revision != request.expected_workspace_revision
            or current.context_hash != request.expected_context_hash):
        raise HTTPException(409, detail={"status": "STALE", "context_hash": current.context_hash})
    return current


def create_generation_context_router(store: ProjectStateStore) -> APIRouter:
    from urban_design.route_aliases import with_legacy_prefix

    router = APIRouter(tags=["generation-context"])

    @router.get("/readiness", response_model=Readiness)
    def readiness(project_id: str) -> Readiness:
        return resolve_readiness(store, project_id)

    @router.post("/freeze", response_model=Readiness)
    def freeze(project_id: str, request: FreezeRequest) -> Readiness:
        return freeze_context(store, project_id, request)

    return with_legacy_prefix(
        router,
        canonical="/api/v1/projects/{project_id}/generation-context",
        legacy="/projects/{project_id}/generation-context",
    )
