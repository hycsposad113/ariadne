"""Read persisted site intelligence and save immutable, non-binding brief drafts."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator
from shapely.geometry import shape

from ..models import ActorKind
from ..store import EntityNotFoundError, PayloadError, ProjectStateStore, StateRecord
from ..workspace_contracts import WorkspaceRevision
from ..workspace_service import WorkspaceService
from .contracts import (
    DesignBriefRevision,
    DesignIntent,
    FrozenRef,
    Opportunity,
    SiteAnalysisBundle,
    compute_site_analysis_bundle_ref,
)


_HASH_PATTERN = "^sha256:[0-9a-f]{64}$"
_ANALYSIS_ARTIFACT_TYPES = {"site-analysis-bundle", "site_analysis_bundle"}
_OPPORTUNITY_ARTIFACT_TYPES = {"site-opportunity-set", "site_opportunity_set"}


class BriefServiceError(ValueError):
    """Base error for a rejected site-intelligence or brief operation."""


class BriefNotFoundError(BriefServiceError):
    """Raised when a project workspace or immutable brief revision is absent."""


class BriefConflictError(BriefServiceError):
    """Raised when a workspace, parent revision, or idempotency precondition is stale."""


class BriefValidationError(BriefServiceError):
    """Raised when a client reference or draft relationship fails validation."""


class OpportunityRejection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    opportunity_id: StrictStr = Field(min_length=1, max_length=128)
    reason: StrictStr = Field(min_length=1, max_length=1000)

    @field_validator("opportunity_id", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("opportunity id and rejection reason must be non-empty")
        return normalized


class CreateDesignBriefRequest(BaseModel):
    """User-authored draft command. Approval fields are deliberately forbidden."""

    model_config = ConfigDict(extra="forbid")

    brief_id: StrictStr = Field(min_length=1, max_length=128)
    expected_workspace_revision: StrictInt = Field(ge=1)
    input_hashes: dict[StrictStr, StrictStr] = Field(min_length=2)
    idempotency_key: StrictStr = Field(min_length=1, max_length=128)
    actor_session_id: StrictStr = Field(min_length=1, max_length=128)
    intents: tuple[DesignIntent, ...] = ()
    selected_opportunity_ids: tuple[StrictStr, ...] = ()
    rejected_opportunities: tuple[OpportunityRejection, ...] = ()
    parent_ref: FrozenRef | None = None
    change_reason: StrictStr = Field(default="Save editable design brief draft.", min_length=1, max_length=1000)

    @field_validator("brief_id", "idempotency_key", "actor_session_id", "change_reason")
    @classmethod
    def nonblank_command_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("brief command fields must be non-empty")
        return normalized

    @field_validator("input_hashes")
    @classmethod
    def valid_input_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not key.strip() or not re.fullmatch(_HASH_PATTERN, digest) for key, digest in value.items()):
            raise ValueError("input_hashes must map non-empty record ids to sha256 digests")
        return dict(value)

    @model_validator(mode="after")
    def unique_references(self) -> "CreateDesignBriefRequest":
        intent_ids = [item.id for item in self.intents]
        selected_ids = list(self.selected_opportunity_ids)
        rejected_ids = [item.opportunity_id for item in self.rejected_opportunities]
        if len(intent_ids) != len(set(intent_ids)):
            raise ValueError("design intent ids must be unique in a brief revision")
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("selected opportunity ids must be unique")
        if len(rejected_ids) != len(set(rejected_ids)):
            raise ValueError("rejected opportunity ids must be unique")
        if set(selected_ids) & set(rejected_ids):
            raise ValueError("an opportunity cannot be selected and rejected in one revision")
        return self


class SiteIntelligenceBriefService:
    """Project the latest persisted bundle and persist draft brief artifacts."""

    def __init__(self, store: ProjectStateStore):
        self.store = store
        self.workspace_service = WorkspaceService(store)

    @staticmethod
    def _canonical_bytes(value: Any) -> bytes:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    @classmethod
    def _digest(cls, value: Any) -> str:
        return "sha256:" + hashlib.sha256(cls._canonical_bytes(value)).hexdigest()

    @staticmethod
    def _workspace_id(project_id: str) -> str:
        return f"workspace-{project_id}"

    @classmethod
    def _workspace_ref(cls, record: StateRecord) -> FrozenRef:
        return FrozenRef(
            id=record.entity_id,
            revision=record.revision,
            sha256=cls._digest(record.payload),
        )

    @staticmethod
    def _artifact_ref(record: StateRecord) -> FrozenRef:
        digest = record.payload.get("sha256")
        try:
            return FrozenRef(id=record.entity_id, revision=record.revision, sha256=digest)
        except Exception as exc:
            raise BriefValidationError(f"Artifact {record.entity_id!r} has no valid content hash") from exc

    def _workspace(self, project_id: str) -> tuple[StateRecord, WorkspaceRevision, FrozenRef]:
        workspace_id = self._workspace_id(project_id)
        workspace = self.workspace_service.get_workspace(workspace_id)
        if workspace is None:
            raise BriefNotFoundError(f"workspace {workspace_id!r} not found")
        try:
            record = self.store.current(workspace_id)
        except EntityNotFoundError as exc:
            raise BriefNotFoundError(f"workspace {workspace_id!r} not found") from exc
        if record.entity_type != "WorkspaceRevision" or record.project_id != project_id:
            raise BriefValidationError("workspace record does not belong to this project")
        if workspace.revision != record.revision or workspace.project_id != project_id:
            raise BriefValidationError("workspace payload revision or project does not match its stored version")
        if workspace.status == "STALE":
            raise BriefConflictError("current workspace is stale")
        return record, workspace, self._workspace_ref(record)

    @staticmethod
    def _geojson_from_artifact(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
        geometry = payload.get("geometry")
        if isinstance(geometry, Mapping):
            return geometry
        content = payload.get("content")
        if isinstance(content, Mapping):
            geometry = content.get("geometry")
            if isinstance(geometry, Mapping):
                return geometry
        return None

    @staticmethod
    def _as_valid_polygon(geometry: Mapping[str, Any], *, description: str):
        try:
            polygon = shape(geometry)
        except Exception as exc:
            raise BriefValidationError(f"{description} is not valid GeoJSON") from exc
        if (
            polygon.geom_type not in {"Polygon", "MultiPolygon"}
            or polygon.is_empty
            or not polygon.is_valid
            or polygon.area <= 0
        ):
            raise BriefValidationError(f"{description} must be a valid, positive-area Polygon or MultiPolygon")
        return polygon

    @staticmethod
    def _is_epsg_28992(payload: Mapping[str, Any]) -> bool:
        crs = payload.get("crs", payload.get("horizontal_crs"))
        if isinstance(crs, Mapping):
            crs = crs.get("name") or crs.get("properties", {}).get("name")
        return str(crs or "").strip().upper() == "EPSG:28992"

    def _active_scope_context(
        self,
        project_id: str,
        workspace: WorkspaceRevision,
        workspace_ref: FrozenRef,
    ) -> tuple[Any, list[dict[str, Any]], FrozenRef | None]:
        """Resolve the active StudyArea and expose saved EDA/zone scopes as artifact refs."""
        try:
            study_area = self.store.current(workspace.study_area_id)
        except EntityNotFoundError as exc:
            raise BriefValidationError("workspace StudyArea does not resolve in the project store") from exc
        if study_area.entity_type != "StudyArea" or study_area.project_id != project_id:
            raise BriefValidationError("workspace StudyArea is not a project-scoped StudyArea")
        if str(study_area.payload.get("status", "")).upper() in {"BLOCKED", "REJECTED", "SUPERSEDED"}:
            raise BriefValidationError("workspace StudyArea is not available for design exploration")
        try:
            project = self.store.current(project_id)
        except EntityNotFoundError:
            project = None
        if project is not None:
            active_study_area_id = project.payload.get("active_study_area_id")
            if active_study_area_id is not None and active_study_area_id != workspace.study_area_id:
                raise BriefConflictError("workspace StudyArea no longer matches the active project pointer")

        geometry_artifact_id = study_area.payload.get(
            "geometry_artifact_id", study_area.payload.get("geometry_artifact")
        )
        base_scope_ref: FrozenRef | None = None
        base_geometry = None
        if isinstance(geometry_artifact_id, str):
            try:
                geometry_record = self.store.current(geometry_artifact_id)
            except EntityNotFoundError:
                geometry_record = None
            if geometry_record is not None and geometry_record.entity_type == "Artifact":
                if geometry_record.project_id != project_id:
                    raise BriefValidationError("StudyArea geometry Artifact belongs to another project")
                geometry_payload = geometry_record.payload
                geometry_data = self._geojson_from_artifact(geometry_payload)
                if geometry_data is not None and self._is_epsg_28992(geometry_payload):
                    base_geometry = self._as_valid_polygon(geometry_data, description="StudyArea geometry")
                    base_scope_ref = self._artifact_ref(geometry_record)

        spatial_brief = workspace.spatial_brief
        eda_geometry = None
        if spatial_brief is not None and spatial_brief.exploration_design_area is not None:
            eda_geometry_data = spatial_brief.exploration_design_area.geometry
            eda_geometry = self._as_valid_polygon(eda_geometry_data, description="Exploration Design Area")
            if base_geometry is not None and not base_geometry.covers(eda_geometry):
                raise BriefValidationError("Exploration Design Area is outside the active StudyArea")
        scope_boundary = eda_geometry or base_geometry
        if scope_boundary is None:
            raise BriefValidationError("a hash-verified EPSG:28992 StudyArea geometry Artifact is required")

        scope_refs: list[dict[str, Any]] = []
        if base_scope_ref is not None:
            scope_refs.append({"ref": base_scope_ref.model_dump(mode="json"), "scope_id": workspace.study_area_id, "label": "StudyArea"})

        candidates: dict[str, tuple[FrozenRef, dict[str, Any], str]] = {}
        if spatial_brief is not None and spatial_brief.exploration_design_area is not None:
            eda = spatial_brief.exploration_design_area
            ref, metadata = self._derived_scope_ref(
                workspace_ref,
                scope_id=f"exploration-design-area-r{eda.revision}",
                label="Exploration Design Area",
                geometry=eda.geometry,
            )
            candidates[ref.id] = (ref, metadata, "EXPLORATION_DESIGN_AREA")
            scope_refs.append({"ref": ref.model_dump(mode="json"), "scope_id": metadata["scope_id"], "label": metadata["label"]})
        if spatial_brief is not None:
            for zone in spatial_brief.zones:
                zone_geometry = self._as_valid_polygon(zone.geometry, description=f"zone {zone.zone_id!r}")
                if not scope_boundary.covers(zone_geometry):
                    raise BriefValidationError(f"zone {zone.zone_id!r} lies outside the active design area")
                ref, metadata = self._derived_scope_ref(
                    workspace_ref,
                    scope_id=f"zone:{zone.zone_id}:r{zone.revision}",
                    label=zone.name,
                    geometry=zone.geometry,
                )
                candidates[ref.id] = (ref, metadata, "ZONE")
                scope_refs.append({"ref": ref.model_dump(mode="json"), "scope_id": metadata["scope_id"], "label": metadata["label"]})

        return scope_boundary, scope_refs, base_scope_ref

    def _derived_scope_ref(
        self,
        workspace_ref: FrozenRef,
        *,
        scope_id: str,
        label: str,
        geometry: Mapping[str, Any],
    ) -> tuple[FrozenRef, dict[str, Any]]:
        content_hash = self._digest({"geometry": geometry, "crs": "EPSG:28992"})
        stable_key = self._digest(
            {"workspace_ref": workspace_ref.model_dump(mode="json"), "scope_id": scope_id, "content_hash": content_hash}
        ).split(":", 1)[1]
        artifact_id = f"workspace-scope-{stable_key[:32]}"
        metadata = {
            "scope_id": scope_id,
            "label": label,
            "geometry": dict(geometry),
            "crs": "EPSG:28992",
            "content_hash": content_hash,
            "source_workspace_ref": workspace_ref.model_dump(mode="json"),
        }
        return FrozenRef(id=artifact_id, revision=1, sha256=content_hash), metadata

    def _analysis_bundle(
        self,
        project_id: str,
        workspace_ref: FrozenRef,
        workspace_record: StateRecord,
        workspace: WorkspaceRevision,
    ) -> tuple[SiteAnalysisBundle | None, StateRecord | None, Literal["AVAILABLE", "PARTIAL", "BLOCKED", "NOT_RUN", "STALE"], str | None]:
        records = [
            item for item in self.store.list_current("Artifact", project_id=project_id)
            if item.payload.get("type") in _ANALYSIS_ARTIFACT_TYPES
        ]
        if not records:
            return self._not_run_bundle(workspace_record, workspace, workspace_ref), None, "NOT_RUN", None
        record = max(records, key=lambda item: (str(item.payload.get("created_at", "")), item.entity_id))
        payload = record.payload
        try:
            bundle = SiteAnalysisBundle.model_validate(payload.get("bundle"))
            if (
                bundle.bundle_ref != compute_site_analysis_bundle_ref(bundle)
                or bundle.bundle_ref.id != record.entity_id
                or bundle.bundle_ref.sha256 != payload.get("sha256")
            ):
                raise ValueError("persisted site analysis bundle hash mismatch")
            if bundle.workspace_ref != workspace_ref:
                return bundle, record, "STALE", "latest analysis bundle is bound to a different workspace revision"
        except Exception as exc:
            return None, record, "BLOCKED", str(exc)

        statuses = {observation.status for observation in bundle.observations}
        if "AVAILABLE" in statuses:
            status: Literal["AVAILABLE", "PARTIAL", "BLOCKED", "NOT_RUN", "STALE"] = "AVAILABLE"
        elif "PARTIAL" in statuses:
            status = "PARTIAL"
        elif statuses and statuses <= {"BLOCKED", "NOT_RUN"}:
            status = "BLOCKED" if "BLOCKED" in statuses else "NOT_RUN"
        else:
            status = "NOT_RUN"
        return bundle, record, status, None

    def _not_run_bundle(
        self,
        workspace_record: StateRecord,
        workspace: WorkspaceRevision,
        workspace_ref: FrozenRef,
    ) -> SiteAnalysisBundle:
        """Describe that no analysis has run, without inventing any measurements."""
        try:
            study_area = self.store.current(workspace.study_area_id)
        except EntityNotFoundError as exc:
            raise BriefValidationError("workspace StudyArea does not resolve in the project store") from exc
        study_area_ref = FrozenRef(
            id=study_area.entity_id,
            revision=study_area.revision,
            sha256=self._digest(study_area.payload),
        )
        provisional = SiteAnalysisBundle(
            bundle_ref=FrozenRef(id="not-run-provisional", revision=1, sha256="sha256:" + "0" * 64),
            study_area_ref=study_area_ref,
            workspace_ref=workspace_ref,
            observations=(),
            created_at=workspace_record.created_at,
            tool_versions={"site_intelligence": "not-run-snapshot-v1"},
            method_parameters={
                "analysis_status": "NOT_RUN",
                "reason": "No analysis job has been executed for this workspace revision.",
            },
        )
        return provisional.model_copy(update={"bundle_ref": compute_site_analysis_bundle_ref(provisional)})

    def _opportunity_set(
        self,
        project_id: str,
        bundle: SiteAnalysisBundle,
        scope_boundary: Any,
        workspace: WorkspaceRevision,
        workspace_ref: FrozenRef,
    ) -> tuple[list[Opportunity], StateRecord | None, str | None]:
        records = [
            item for item in self.store.list_current("Artifact", project_id=project_id)
            if item.payload.get("type") in _OPPORTUNITY_ARTIFACT_TYPES
            and item.payload.get("analysis_ref") == bundle.bundle_ref.model_dump(mode="json")
        ]
        if not records:
            return [], None, None
        record = max(records, key=lambda item: (str(item.payload.get("created_at", "")), item.entity_id))
        payload = record.payload
        try:
            opportunities = [Opportunity.model_validate(value) for value in payload.get("opportunities", [])]
            content = {
                "analysis_ref": bundle.bundle_ref.model_dump(mode="json"),
                "opportunities": [item.model_dump(mode="json") for item in opportunities],
            }
            if self._digest(content) != payload.get("sha256"):
                raise ValueError("persisted opportunity set hash mismatch")
            if len({item.id for item in opportunities}) != len(opportunities):
                raise ValueError("persisted opportunity ids are not unique")
            # The input bundle and opportunities remain read-only; references must resolve to
            # existing Artifact geometry or to a scope saved in this exact workspace revision.
            candidates = self._scope_candidates(workspace, workspace_ref)
            for item in opportunities:
                geometry, _ = self._resolve_scope(item.scope_ref, project_id, candidates, scope_boundary)
                if geometry is None:
                    raise ValueError(f"opportunity scope {item.scope_ref.id!r} cannot be resolved")
            return opportunities, record, None
        except Exception as exc:
            return [], record, str(exc)

    def _scope_candidates(
        self,
        workspace: WorkspaceRevision,
        workspace_ref: FrozenRef,
    ) -> dict[str, tuple[FrozenRef, dict[str, Any], str]]:
        candidates: dict[str, tuple[FrozenRef, dict[str, Any], str]] = {}
        brief = workspace.spatial_brief
        if brief is None:
            return candidates
        if brief.exploration_design_area is not None:
            eda = brief.exploration_design_area
            ref, metadata = self._derived_scope_ref(
                workspace_ref,
                scope_id=f"exploration-design-area-r{eda.revision}",
                label="Exploration Design Area",
                geometry=eda.geometry,
            )
            candidates[ref.id] = (ref, metadata, "EXPLORATION_DESIGN_AREA")
        for zone in brief.zones:
            ref, metadata = self._derived_scope_ref(
                workspace_ref,
                scope_id=f"zone:{zone.zone_id}:r{zone.revision}",
                label=zone.name,
                geometry=zone.geometry,
            )
            candidates[ref.id] = (ref, metadata, "ZONE")
        return candidates

    def _resolve_scope(
        self,
        ref: FrozenRef,
        project_id: str,
        candidates: Mapping[str, tuple[FrozenRef, dict[str, Any], str]],
        scope_boundary: Any,
    ) -> tuple[Any, dict[str, Any] | None]:
        candidate = candidates.get(ref.id)
        if candidate is not None:
            candidate_ref, metadata, _kind = candidate
            if ref != candidate_ref:
                raise BriefValidationError(f"scope reference revision or hash mismatch: {ref.id}")
            geometry = self._as_valid_polygon(metadata["geometry"], description=f"scope {ref.id!r}")
            if not scope_boundary.covers(geometry):
                raise BriefValidationError(f"scope {ref.id!r} lies outside the active design area")
            try:
                existing_scope = self.store.get_record(ref.id, revision=ref.revision)
            except EntityNotFoundError:
                return geometry, metadata
            if (
                existing_scope.entity_type != "Artifact"
                or existing_scope.project_id != project_id
                or self._artifact_ref(existing_scope) != ref
                or not self._is_epsg_28992(existing_scope.payload)
                or self._geojson_from_artifact(existing_scope.payload) != metadata["geometry"]
            ):
                raise BriefValidationError(f"materialized workspace scope Artifact {ref.id!r} does not match its saved geometry")
            return geometry, None

        try:
            record = self.store.get_record(ref.id, revision=ref.revision)
        except EntityNotFoundError as exc:
            raise BriefValidationError(f"unresolved scope Artifact: {ref.id}") from exc
        if record.entity_type != "Artifact" or record.project_id != project_id:
            raise BriefValidationError(f"scope {ref.id!r} is not a project Artifact")
        actual_ref = self._artifact_ref(record)
        if actual_ref != ref:
            raise BriefValidationError(f"scope Artifact revision or hash mismatch: {ref.id}")
        if not self._is_epsg_28992(record.payload):
            raise BriefValidationError(f"scope Artifact {ref.id!r} must use EPSG:28992")
        geojson = self._geojson_from_artifact(record.payload)
        if geojson is None:
            raise BriefValidationError(f"scope Artifact {ref.id!r} has no geometry")
        geometry = self._as_valid_polygon(geojson, description=f"scope Artifact {ref.id!r}")
        if not scope_boundary.covers(geometry):
            raise BriefValidationError(f"scope Artifact {ref.id!r} lies outside the active design area")
        return geometry, None

    def site_intelligence(self, project_id: str) -> dict[str, Any]:
        workspace_record, workspace, workspace_ref = self._workspace(project_id)
        scope_boundary, scope_refs, default_scope_ref = self._active_scope_context(project_id, workspace, workspace_ref)
        bundle, bundle_record, analysis_status, analysis_issue = self._analysis_bundle(
            project_id, workspace_ref, workspace_record, workspace
        )
        opportunity_ref: FrozenRef | None = None
        opportunities: list[Opportunity] = []
        opportunity_issue = None
        input_hashes = {workspace_ref.id: workspace_ref.sha256}
        if bundle is not None:
            input_hashes[bundle.bundle_ref.id] = bundle.bundle_ref.sha256
            if bundle_record is not None and analysis_status in {"AVAILABLE", "PARTIAL", "BLOCKED", "NOT_RUN"}:
                try:
                    opportunity_rows, opportunity_record, opportunity_issue = self._opportunity_set(
                        project_id, bundle, scope_boundary, workspace, workspace_ref
                    )
                    opportunities = opportunity_rows
                    if opportunity_record is not None and opportunity_issue is None:
                        opportunity_ref = self._artifact_ref(opportunity_record)
                        input_hashes[opportunity_ref.id] = opportunity_ref.sha256
                except BriefServiceError as exc:
                    opportunity_issue = str(exc)
        return {
            "project_id": project_id,
            "status": analysis_status,
            "analysis_status": analysis_status,
            "latest_bundle_ref": bundle.bundle_ref.model_dump(mode="json") if bundle is not None else None,
            "bundle_persisted": bundle_record is not None,
            "workspace_ref": workspace_ref.model_dump(mode="json"),
            "default_scope_ref": default_scope_ref.model_dump(mode="json") if default_scope_ref is not None else None,
            "scope_refs": scope_refs,
            "opportunity_ref": opportunity_ref.model_dump(mode="json") if opportunity_ref is not None else None,
            "opportunities": [item.model_dump(mode="json") for item in opportunities],
            "input_hashes": input_hashes,
            "latest_brief": self.latest_brief(project_id),
            "limitations": [message for message in (analysis_issue, opportunity_issue) if message],
        }

    def _brief_records(self, project_id: str, brief_id: str) -> list[StateRecord]:
        records = [
            item for item in self.store.list_current("Artifact", project_id=project_id)
            if item.payload.get("type") == "design-brief-revision"
            and item.payload.get("brief_id") == brief_id
        ]
        records.sort(key=lambda item: int(item.payload.get("brief_revision", 0)))
        return records

    def _brief_payload(self, record: StateRecord) -> dict[str, Any]:
        content = record.payload.get("content")
        if not isinstance(content, Mapping) or self._digest(content) != record.payload.get("sha256"):
            raise BriefValidationError(f"brief Artifact {record.entity_id!r} failed its content hash check")
        brief = DesignBriefRevision.model_validate(content.get("brief"))
        if content.get("status") != "DRAFT" or brief.id != record.payload.get("brief_id"):
            raise BriefValidationError("stored design brief Artifact is not a valid draft revision")
        return {
            "status": "DRAFT",
            "brief": brief.model_dump(mode="json"),
            "rejected_opportunities": content.get("rejected_opportunities", []),
            "change_reason": content.get("change_reason"),
            "input_hashes": content.get("input_hashes", {}),
            "artifact_ref": self._artifact_ref(record).model_dump(mode="json"),
            "idempotent_replay": False,
        }

    def get_brief_revision(self, project_id: str, brief_id: str, revision: int) -> dict[str, Any]:
        if revision < 1:
            raise BriefNotFoundError("brief revision must be at least one")
        records = self._brief_records(project_id, brief_id)
        record = next((item for item in records if item.payload.get("brief_revision") == revision), None)
        if record is None:
            raise BriefNotFoundError(f"design brief {brief_id!r} revision {revision} not found")
        return self._brief_payload(record)

    def latest_brief(self, project_id: str) -> dict[str, Any] | None:
        records = [
            item for item in self.store.list_current("Artifact", project_id=project_id)
            if item.payload.get("type") == "design-brief-revision"
        ]
        if not records:
            return None
        latest = max(records, key=lambda item: (str(item.payload.get("created_at", "")), item.entity_id))
        return self._brief_payload(latest)

    def save_draft(self, project_id: str, request: CreateDesignBriefRequest) -> dict[str, Any]:
        request_content = request.model_dump(mode="json", exclude={"idempotency_key"})
        request_digest = self._digest(request_content)
        key_digest = hashlib.sha256(f"{project_id}\0{request.idempotency_key}".encode()).hexdigest()[:32]
        artifact_id = f"design-brief-{key_digest}"
        try:
            existing = self.store.current(artifact_id)
        except EntityNotFoundError:
            existing = None
        if existing is not None:
            if (
                existing.entity_type != "Artifact"
                or existing.project_id != project_id
                or existing.payload.get("type") != "design-brief-revision"
            ):
                raise BriefConflictError("idempotency key is already bound to another artifact")
            if existing.payload.get("request_digest") != request_digest:
                raise BriefConflictError("idempotency key was already used with different draft content")
            response = self._brief_payload(existing)
            response["idempotent_replay"] = True
            return response

        workspace_record, workspace, workspace_ref = self._workspace(project_id)
        if request.expected_workspace_revision != workspace_record.revision:
            raise BriefConflictError(
                f"stale workspace revision: expected {request.expected_workspace_revision}, current is {workspace_record.revision}"
            )
        scope_boundary, _scope_refs, _default_scope_ref = self._active_scope_context(project_id, workspace, workspace_ref)
        bundle, bundle_record, analysis_status, analysis_issue = self._analysis_bundle(
            project_id, workspace_ref, workspace_record, workspace
        )
        if bundle is None:
            raise BriefValidationError("no hash-bound SiteAnalysisBundle snapshot is available for this workspace")
        if analysis_status == "STALE":
            raise BriefConflictError(analysis_issue or "latest analysis bundle is stale")
        if analysis_status == "BLOCKED":
            raise BriefValidationError(analysis_issue or "latest analysis bundle failed validation")

        opportunities, opportunity_record, opportunity_issue = self._opportunity_set(
            project_id, bundle, scope_boundary, workspace, workspace_ref
        )
        uses_opportunities = bool(request.selected_opportunity_ids or request.rejected_opportunities) or any(
            intent.source_opportunity_ids for intent in request.intents
        )
        if opportunity_issue and uses_opportunities:
            raise BriefValidationError(opportunity_issue)
        if opportunity_issue:
            opportunity_record = None
            opportunities = []
        opportunity_by_id = {item.id: item for item in opportunities}
        selected = set(request.selected_opportunity_ids)
        rejected = {item.opportunity_id for item in request.rejected_opportunities}
        unknown_opportunities = (selected | rejected) - set(opportunity_by_id)
        if unknown_opportunities:
            raise BriefValidationError(
                "unknown or unverified opportunity ids: " + ", ".join(sorted(unknown_opportunities))
            )
        if not selected and not rejected and any(intent.source_opportunity_ids for intent in request.intents):
            raise BriefValidationError("opportunity-derived intents must resolve to selected opportunity ids")
        for intent in request.intents:
            if intent.origin == "AI_SUGGESTED" and not intent.source_opportunity_ids:
                raise BriefValidationError("AI-suggested intents must retain their source opportunity ids")
            unknown_sources = set(intent.source_opportunity_ids) - set(opportunity_by_id)
            if unknown_sources:
                raise BriefValidationError("intent references an unknown opportunity id")
            if set(intent.source_opportunity_ids) & rejected:
                raise BriefValidationError("a rejected opportunity cannot remain as an active brief intent")
            if not set(intent.source_opportunity_ids) <= selected:
                raise BriefValidationError("source opportunities for an intent must be explicitly selected")

        candidates = self._scope_candidates(workspace, workspace_ref)
        expected_hashes: dict[str, str] = {
            workspace_ref.id: workspace_ref.sha256,
            bundle.bundle_ref.id: bundle.bundle_ref.sha256,
        }
        if opportunity_record is not None:
            expected_hashes[opportunity_record.entity_id] = self._artifact_ref(opportunity_record).sha256

        scope_records_to_create: dict[str, dict[str, Any]] = {}
        for intent in request.intents:
            geometry, metadata = self._resolve_scope(intent.scope_ref, project_id, candidates, scope_boundary)
            expected_hashes[intent.scope_ref.id] = intent.scope_ref.sha256
            if metadata is not None:
                scope_records_to_create[intent.scope_ref.id] = metadata
            if geometry is None:
                raise BriefValidationError(f"intent scope {intent.scope_ref.id!r} cannot be resolved")
        if request.input_hashes != expected_hashes:
            raise BriefValidationError("input_hashes do not match the current workspace, analysis, opportunity, and scope artifacts")

        previous_records = self._brief_records(project_id, request.brief_id)
        previous = previous_records[-1] if previous_records else None
        if previous is None:
            if request.parent_ref is not None:
                raise BriefConflictError("parent_ref does not identify an existing revision of this brief")
            next_revision = 1
            parent_ref = None
        else:
            previous_ref = self._artifact_ref(previous)
            if request.parent_ref != previous_ref:
                raise BriefConflictError("design brief parent revision is stale or missing")
            next_revision = int(previous.payload["brief_revision"]) + 1
            parent_ref = previous_ref

        revision = DesignBriefRevision(
            id=request.brief_id,
            revision=next_revision,
            parent_ref=parent_ref,
            workspace_ref=workspace_ref,
            analysis_ref=bundle.bundle_ref,
            intents=request.intents,
            selected_opportunity_ids=tuple(request.selected_opportunity_ids),
            assumption_refs=(),
            required_decision_refs=(),
        )
        rejected_payload = [item.model_dump(mode="json") for item in request.rejected_opportunities]
        content = {
            "schema_version": "design-brief-artifact-v1",
            "status": "DRAFT",
            "brief": revision.model_dump(mode="json"),
            "rejected_opportunities": rejected_payload,
            "change_reason": request.change_reason,
            "input_hashes": dict(request.input_hashes),
            "idempotency_key": request.idempotency_key,
        }
        artifact_sha = self._digest(content)
        now = datetime.now(timezone.utc).isoformat()
        parent_ids = [bundle.bundle_ref.id]
        if opportunity_record is not None:
            parent_ids.append(opportunity_record.entity_id)
        parent_ids.extend(intent.scope_ref.id for intent in request.intents)
        if parent_ref is not None:
            parent_ids.append(parent_ref.id)
        parent_ids = list(dict.fromkeys(parent_ids))
        artifact_payload = {
            "id": artifact_id,
            "type": "design-brief-revision",
            "uri": f"sqlite-artifact://{project_id}/{artifact_id}",
            "sha256": artifact_sha,
            "mime": "application/json",
            "producer": "site-intelligence-brief-service-v1",
            "created_at": now,
            "project_id": project_id,
            "size_bytes": len(self._canonical_bytes(content)),
            "parent_artifact_ids": parent_ids,
            "status": "DRAFT",
            "brief_id": request.brief_id,
            "brief_revision": next_revision,
            "request_digest": request_digest,
            "content": content,
        }
        actor_session_id = request.actor_session_id
        action = "CreateDesignBriefDraft" if next_revision == 1 else "CreateDesignBriefRevision"
        entities: list[dict[str, Any]] = []
        if bundle_record is None:
            bundle_content = bundle.model_dump(mode="json")
            bundle_payload = {
                "id": bundle.bundle_ref.id,
                "type": "site-analysis-bundle",
                "uri": f"sqlite-artifact://{project_id}/{bundle.bundle_ref.id}",
                "sha256": bundle.bundle_ref.sha256,
                "mime": "application/json",
                "producer": "site-intelligence-not-run-snapshot-v1",
                "created_at": bundle.created_at.isoformat(),
                "project_id": project_id,
                "size_bytes": len(self._canonical_bytes(bundle_content)),
                "parent_artifact_ids": [],
                "status": "NOT_RUN",
                "bundle": bundle_content,
            }
            event_suffix = bundle.bundle_ref.sha256.split(":", 1)[1][:24]
            entities.append({
                "entity_type": "Artifact",
                "entity_id": bundle.bundle_ref.id,
                "project_id": project_id,
                "payload": bundle_payload,
                "event_id": f"event-analysis-not-run-{event_suffix}",
                "actor": "site-intelligence-brief-service",
                "action": "CaptureAnalysisNotRunSnapshot",
                "reason": "Record that no analysis has run for this workspace revision; no measurements were produced.",
                "resulting_refs": [bundle.bundle_ref.id, workspace_ref.id],
                "event_payload": {
                    "analysis_status": "NOT_RUN",
                    "workspace_ref": workspace_ref.model_dump(mode="json"),
                    "study_area_ref": bundle.study_area_ref.model_dump(mode="json"),
                },
            })
        for scope_id, metadata in scope_records_to_create.items():
            ref = self._scope_candidates(workspace, workspace_ref)[scope_id][0]
            payload = {
                "id": ref.id,
                "type": "workspace_scope_geometry",
                "uri": f"sqlite-artifact://{project_id}/{ref.id}",
                "sha256": ref.sha256,
                "mime": "application/geo+json",
                "crs": "EPSG:28992",
                "producer": "workspace-scope-materializer-v1",
                "created_at": now,
                "project_id": project_id,
                "size_bytes": len(self._canonical_bytes(metadata["geometry"])),
                "parent_artifact_ids": [],
                "scope_id": metadata["scope_id"],
                "source_workspace_ref": workspace_ref.model_dump(mode="json"),
                "geometry": metadata["geometry"],
            }
            entities.append({
                "entity_type": "Artifact",
                "entity_id": ref.id,
                "project_id": project_id,
                "payload": payload,
                "event_id": f"event-{uuid.uuid4().hex}",
                "actor": "human-ui",
                "actor_kind": ActorKind.HUMAN_UI,
                "actor_session_id": actor_session_id,
                "action": "MaterializeWorkspaceScopeArtifact",
                "reason": "Materialize an already-saved workspace scope for an immutable brief reference.",
                "resulting_refs": [ref.id],
            })
        entities.append({
            "entity_type": "Artifact",
            "entity_id": artifact_id,
            "project_id": project_id,
            "payload": artifact_payload,
            "event_id": f"event-{uuid.uuid4().hex}",
            "actor": "human-ui",
            "actor_kind": ActorKind.HUMAN_UI,
            "actor_session_id": actor_session_id,
            "action": action,
            "reason": request.change_reason,
            "changed_refs": [request.brief_id, *request.selected_opportunity_ids],
            "resulting_refs": [artifact_id, *parent_ids],
            "event_payload": {
                "brief_revision": next_revision,
                "workspace_ref": workspace_ref.model_dump(mode="json"),
                "analysis_ref": bundle.bundle_ref.model_dump(mode="json"),
                "rejected_opportunities": rejected_payload,
                "request_digest": request_digest,
            },
        })
        try:
            records, _events = self.store.commit_batch(entities=entities, events=[])
        except PayloadError as exc:
            raise BriefValidationError(str(exc)) from exc
        saved_artifact = next(record for record in records if record.entity_id == artifact_id)
        return self._brief_payload(saved_artifact)


__all__ = [
    "BriefConflictError",
    "BriefNotFoundError",
    "BriefServiceError",
    "BriefValidationError",
    "CreateDesignBriefRequest",
    "OpportunityRejection",
    "SiteIntelligenceBriefService",
]
