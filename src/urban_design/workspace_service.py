"""Workspace synchronization service managing versioned feature dispositions and QGIS sync.

Ensures:
- Deterministic idempotency handling (identical payload replays, differing payload 409 conflict).
- Optimistic concurrency control via expected_workspace_revision.
- Atomic commit to ProjectStateStore and append-only Design Ledger.
- Fail-closed validation against unverified client claims.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence

from .models import ActorKind
from .store import (
    EntityNotFoundError,
    ProjectStateStore,
    RevisionConflictError,
    StateRecord,
    StoreError,
)
from .workspace_contracts import (
    FeatureDisposition,
    SyncRequest,
    WorkspaceRevision,
    WorkspaceSyncResponse,
    validate_spatial_brief_zoning,
)
from .workspace_sources import WorkspaceSourceCatalog, WorkspaceSourceError


class WorkspaceError(Exception):
    """Base exception for workspace operations."""


class WorkspaceConflictError(WorkspaceError):
    """Raised on stale revisions or idempotency key collisions."""


class WorkspaceValidationError(WorkspaceError):
    """Raised when sync inputs fail domain semantic checks."""


def _compute_sync_digest(
    request: SyncRequest,
    dispositions: Sequence[FeatureDisposition] | None,
    spatial_brief: Any = None,
) -> str:
    brief_payload = (
        spatial_brief.model_dump(mode="json")
        if hasattr(spatial_brief, "model_dump")
        else spatial_brief or {}
    )
    if isinstance(brief_payload, dict) and brief_payload.get("exploration_design_area") is None:
        # Keep replay digests for pre-EDA workspaces stable when no area is set.
        brief_payload = dict(brief_payload)
        brief_payload.pop("exploration_design_area", None)
    data = {
        "project_id": request.project_id,
        "study_area_id": request.study_area_id,
        "source_snapshot_ids": sorted(request.source_snapshot_ids),
        "dispositions": sorted(
            [d.model_dump() for d in (dispositions or [])],
            key=lambda d: (d["source_artifact_id"], d["feature_id"]),
        ),
        "spatial_brief": brief_payload,
    }
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class WorkspaceService:
    """Manages workspace synchronization and durable feature dispositions."""

    # Canonical default source artifacts for M4H pilot
    CANONICAL_BUILDING_ARTIFACT = "artifact-pdok-bag-pand-p001-normalized-3390e215019805a1"
    CANONICAL_ROAD_ARTIFACT = "artifact-osm-overpass-v5-normalized-3390e215019805a1"

    def __init__(self, store: ProjectStateStore, source_catalog: WorkspaceSourceCatalog | None = None):
        self.store = store
        self.source_catalog = source_catalog

    def _workspace_id(self, project_id: str) -> str:
        return f"workspace-{project_id}"

    @staticmethod
    def _actor_label(actor_kind: ActorKind) -> str:
        return actor_kind.value.lower().replace("_", "-")

    def sync(
        self,
        request: SyncRequest,
        dispositions: Sequence[FeatureDisposition] | None = None,
        *,
        validate_study_area: bool = True,
        validate_snapshots: bool = True,
    ) -> WorkspaceRevision:
        actor = self._actor_label(request.actor_kind)
        try:
            validate_spatial_brief_zoning(request.spatial_brief)
        except ValueError as exc:
            raise WorkspaceValidationError(str(exc)) from exc

        # 1. Validate StudyArea against SQLite
        if validate_study_area:
            try:
                area_rec = self.store.current(request.study_area_id)
                status = str(area_rec.payload.get("status", "")).upper()
                if status in {"SUPERSEDED", "BLOCKED", "REJECTED"} or area_rec.payload.get("superseded_by_id"):
                    raise WorkspaceValidationError(
                        f"StudyArea {request.study_area_id!r} is {status or 'SUPERSEDED'} and cannot be synchronized"
                    )
            except EntityNotFoundError as exc:
                raise WorkspaceValidationError(f"StudyArea {request.study_area_id!r} not found in state store") from exc

        if self.source_catalog is not None:
            try:
                project = self.store.current(request.project_id)
                if project.entity_type != "Project" or project.payload.get("active_study_area_id") != request.study_area_id:
                    raise WorkspaceValidationError("workspace StudyArea does not match the active project pointer")
                try:
                    self.source_catalog.validate_snapshot_ids(
                        request.project_id, request.study_area_id, request.source_snapshot_ids
                    )
                except WorkspaceSourceError as exc:
                    raise WorkspaceValidationError(str(exc)) from exc
            except EntityNotFoundError as exc:
                raise WorkspaceValidationError("workspace project is missing from authoritative state") from exc
            if request.spatial_brief is not None:
                for zone in request.spatial_brief.zones:
                    try:
                        self.source_catalog.validate_zone_scope(zone.geometry)
                    except WorkspaceSourceError as exc:
                        raise WorkspaceValidationError(str(exc)) from exc
                if request.spatial_brief.exploration_design_area is not None:
                    try:
                        self.source_catalog.validate_zone_scope(
                            request.spatial_brief.exploration_design_area.geometry
                        )
                    except WorkspaceSourceError as exc:
                        raise WorkspaceValidationError(
                            "ExplorationDesignArea " + str(exc)
                        ) from exc

        # 2. Validate all source snapshot references against SQLite
        if validate_snapshots:
            for snap_id in request.source_snapshot_ids:
                try:
                    snap_rec = self.store.current(snap_id)
                    s_status = str(snap_rec.payload.get("status", "")).upper()
                    if s_status in {"SUPERSEDED", "BLOCKED", "REJECTED"}:
                        raise WorkspaceValidationError(f"Source snapshot {snap_id!r} is {s_status}")
                except EntityNotFoundError as exc:
                    raise WorkspaceValidationError(
                        f"Source snapshot {snap_id!r} not found in state store"
                    ) from exc

        # 3. Resolve each submitted ID to its verified source parent.
        combined_disps: list[FeatureDisposition] = []
        raw_disps = list(dispositions or request.feature_dispositions or [])
        seen_features: set[str] = set()
        for d in raw_disps:
            if d.feature_id in seen_features:
                raise WorkspaceValidationError(f"duplicate feature disposition: {d.feature_id!r}")
            seen_features.add(d.feature_id)
            combined_disps.append(self._resolve_disposition(d, request.project_id))

        ws_id = self._workspace_id(request.project_id)
        current_rec: StateRecord | None = None
        try:
            current_rec = self.store.current(ws_id)
        except EntityNotFoundError:
            current_rec = None

        current_rev = current_rec.revision if current_rec else 0
        payload_digest = _compute_sync_digest(request, combined_disps, request.spatial_brief)

        # Check existing revisions for idempotency key replay
        if current_rec:
            history = self.store.history(ws_id)
            for rec in history:
                rec_key = rec.payload.get("idempotency_key")
                if rec_key == request.idempotency_key:
                    rec_digest = rec.payload.get("payload_digest")
                    if rec_digest == payload_digest:
                        # Idempotent replay: return exact existing revision
                        return WorkspaceRevision.model_validate(rec.payload)
                    else:
                        raise WorkspaceConflictError(
                            f"Idempotency key {request.idempotency_key!r} already used with different payload"
                        )

        # Optimistic concurrency check
        if request.expected_workspace_revision != current_rev:
            raise WorkspaceConflictError(
                f"Stale workspace revision: expected {request.expected_workspace_revision}, current is {current_rev}"
            )

        next_rev = current_rev + 1
        disp_dicts = [d.model_dump() for d in combined_disps]
        payload = {
            "workspace_id": ws_id,
            "project_id": request.project_id,
            "revision": next_rev,
            "study_area_id": request.study_area_id,
            "source_snapshot_ids": request.source_snapshot_ids,
            "feature_dispositions": disp_dicts,
            "spatial_brief": request.spatial_brief.model_dump(mode="json") if request.spatial_brief else None,
            "status": "DRAFT",
            "idempotency_key": request.idempotency_key,
            "payload_digest": payload_digest,
        }

        if current_rev == 0:
            rec = self.store.create(
                entity_type="WorkspaceRevision",
                payload=payload,
                entity_id=ws_id,
                project_id=request.project_id,
                actor=actor,
                actor_kind=request.actor_kind,
                actor_session_id=request.actor_session_id,
                action="SyncWorkspace",
                reason=f"Workspace synchronization rev {next_rev}",
                resulting_refs=request.source_snapshot_ids,
            )
        else:
            try:
                rec = self.store.update(
                    ws_id,
                    payload,
                    expected_revision=current_rev,
                    actor=actor,
                    actor_kind=request.actor_kind,
                    actor_session_id=request.actor_session_id,
                    reason=f"Workspace synchronization rev {next_rev}",
                    resulting_refs=request.source_snapshot_ids,
                    replace=True,
                )
            except RevisionConflictError as err:
                raise WorkspaceConflictError(str(err)) from err

        return WorkspaceRevision.model_validate(rec.payload)

    def _resolve_disposition(self, disposition: FeatureDisposition, project_id: str) -> FeatureDisposition:
        if self.source_catalog is not None:
            try:
                feature = self.source_catalog.resolve_feature(
                    disposition.feature_id,
                    disposition.feature_kind,
                    disposition.source_artifact_id,
                )
            except WorkspaceSourceError as exc:
                raise WorkspaceValidationError(str(exc)) from exc
            if disposition.source_snapshot_id and disposition.source_snapshot_id != feature.source_snapshot_id:
                raise WorkspaceValidationError(f"feature {feature.feature_id!r} source snapshot does not match its parent")
            if disposition.source_feature_id and disposition.source_feature_id != feature.source_feature_id:
                raise WorkspaceValidationError(f"feature {feature.feature_id!r} source feature identity does not match")
            return FeatureDisposition(
                feature_id=feature.feature_id,
                feature_kind=feature.feature_kind,
                disposition=disposition.disposition,
                source_artifact_id=feature.source_artifact_id,
                source_snapshot_id=feature.source_snapshot_id,
                source_feature_id=feature.source_feature_id,
                annotation=disposition.annotation,
            )
        if not disposition.source_artifact_id:
            raise WorkspaceValidationError("source_artifact_id must resolve to an Artifact; no default source is assigned")
        try:
            artifact = self.store.current(disposition.source_artifact_id)
        except EntityNotFoundError as exc:
            raise WorkspaceValidationError(f"source Artifact {disposition.source_artifact_id!r} not found") from exc
        if artifact.entity_type != "Artifact" or artifact.project_id not in {None, project_id}:
            raise WorkspaceValidationError("feature source reference is not a project-scoped Artifact")
        return disposition

    def get_workspace(self, workspace_id: str, revision: int | None = None) -> WorkspaceRevision | None:
        try:
            rec = self.store.replay(workspace_id, revision=revision) if revision else self.store.current(workspace_id)
            return WorkspaceRevision.model_validate(rec.payload)
        except EntityNotFoundError:
            return None

    def list_revisions(self, workspace_id: str) -> list[WorkspaceRevision]:
        try:
            history = self.store.history(workspace_id)
            return [WorkspaceRevision.model_validate(rec.payload) for rec in history]
        except EntityNotFoundError:
            return []

    def update_dispositions(
        self,
        workspace_id: str,
        dispositions: Sequence[FeatureDisposition],
        expected_revision: int,
        *,
        actor_kind: ActorKind,
        actor_session_id: str,
    ) -> WorkspaceRevision:
        current = self.store.current(workspace_id)
        if current.revision != expected_revision:
            raise WorkspaceConflictError(
                f"Stale workspace revision: expected {expected_revision}, current is {current.revision}"
            )
        if self.source_catalog is not None:
            try:
                self.source_catalog.validate_snapshot_ids(
                    current.project_id or "",
                    str(current.payload.get("study_area_id", "")),
                    current.payload.get("source_snapshot_ids", []),
                )
            except WorkspaceSourceError as exc:
                raise WorkspaceValidationError(str(exc)) from exc

        combined_disps: list[FeatureDisposition] = []
        seen_features: set[str] = set()
        for d in dispositions:
            if d.feature_id in seen_features:
                raise WorkspaceValidationError(f"duplicate feature disposition: {d.feature_id!r}")
            seen_features.add(d.feature_id)
            combined_disps.append(self._resolve_disposition(d, current.project_id or ""))

        payload = current.as_dict()
        next_rev = current.revision + 1
        payload["revision"] = next_rev
        payload["feature_dispositions"] = [d.model_dump() for d in combined_disps]
        payload["status"] = "DRAFT"

        rec = self.store.update(
            workspace_id,
            payload,
            expected_revision=current.revision,
            actor=self._actor_label(actor_kind),
            actor_kind=actor_kind,
            actor_session_id=actor_session_id,
            reason=f"Update feature dispositions to rev {next_rev}",
            replace=True,
        )
        return WorkspaceRevision.model_validate(rec.payload)
