"""FastAPI REST application for workspace synchronization and feature dispositions.

Provides typed endpoints for:
- POST /api/v1/workspaces/sync
- GET /api/v1/workspaces/{workspace_id}
- GET /api/v1/workspaces/{workspace_id}/history
- PUT /api/v1/workspaces/{workspace_id}/dispositions
- GET /api/v1/projects/{project_id}/site-context
- POST /api/v1/critic/evaluate
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from pathlib import PurePosixPath
from threading import RLock
from typing import Any, Literal, Mapping, Sequence
from fastapi import FastAPI, HTTPException, Path as FPath, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictStr, ValidationError, field_validator, model_validator

from .model_provider import DeterministicFixtureProvider, get_configured_provider
from . import model_profiles
from .model_profiles import (
    ModelProfileSelectionStore,
    ModelProfilesStatusResponse,
    default_ariadne_profile_id,
    describe_model_profiles,
    load_model_provider_config,
)
from .geometry import canonical_geometry_hash
from .decision_key import DecisionKeyUnavailable, verify_decision_key_strict
from .models import ActorKind, Constraint, DecisionAction, HumanDecision, HumanStatus
from .constraint_sets import ConstraintSetService
from .analysis_persistence import get_persisted_site_analysis, get_persisted_syntax_bundle
from .r04_evidence import (
    EvidenceAlignmentError,
    build_r04_observational_evidence_bundle,
    validate_r04_observational_evidence_bundle,
)
from .r03_evidence import select_verified_cards
from .r03_syntax import SyntaxEvidenceError, load_verified_exploratory_syntax, sha256_file
from .morphology.preview_api import create_preview_router
from .syntax_context_api import create_syntax_context_router
from .store import EntityNotFoundError, PayloadError, ProjectStateStore
from .site_intelligence.brief_service import (
    BriefConflictError,
    BriefNotFoundError,
    BriefServiceError,
    CreateDesignBriefRequest,
    SiteIntelligenceBriefService,
)
from .scenario_api import register_scenario_routes
from .site_critic import CriticValidationError, SiteCriticService
from .ariadne_chat import create_ariadne_chat_router
from .workspace_contracts import (
    FeatureDisposition,
    SyncRequest,
    WorkspaceRevision,
    WorkspaceSyncResponse,
)
from .workspace_service import (
    WorkspaceConflictError,
    WorkspaceError,
    WorkspaceService,
    WorkspaceValidationError,
)
from .workspace_sources import WorkspaceSourceCatalog, WorkspaceSourceError
from .surrounding_context import ContextDataError, ContextRepository


class UpdateDispositionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=1)
    dispositions: list[FeatureDisposition]
    actor_kind: ActorKind
    actor_session_id: StrictStr = Field(..., min_length=1, max_length=128)

    @field_validator("actor_session_id")
    @classmethod
    def nonempty_actor_session(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("actor_session_id must not be blank")
        return value.strip()


class ConstraintSetDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraints: list[Constraint] = Field(..., min_length=1)
    actor_kind: Literal["HUMAN_UI", "AGENT_AUTOMATION"] = "HUMAN_UI"
    id: StrictStr | None = Field(None, min_length=1, max_length=128)
    idempotency_key: StrictStr | None = Field(None, min_length=1, max_length=128)
    notes: StrictStr | None = None
    allocation_policy: Literal["priority"] | None = None
    actor_session_id: StrictStr = Field(..., min_length=1, max_length=128)

    @field_validator("actor_session_id", "id", "idempotency_key")
    @classmethod
    def nonempty_constraint_session(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("actor_session_id must not be blank")
        return value.strip()


class DesignAreaPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geometry: dict[str, Any]
    horizontal_crs: Literal["EPSG:28992"]


class DesignAreaPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["CLIPPED", "UNCHANGED", "EMPTY", "MULTIPLE_COMPONENTS"]
    clipped: bool
    area_m2: float
    component_count: int
    geometry: dict[str, Any] | None
    horizontal_crs: Literal["EPSG:28992"]
    units: Literal["m"]


class ContextFeatureGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: StrictStr
    coordinates: Any


class ContextFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["Feature"]
    id: StrictStr | None = None
    properties: dict[str, Any]
    geometry: ContextFeatureGeometry | None


class ContextFeatureCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["FeatureCollection"]
    features: list[ContextFeature]


class SurroundingContextMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: StrictStr
    project_id: StrictStr
    study_area_id: StrictStr
    study_area_version: StrictStr
    study_area_geometry_sha256: StrictStr
    crs: Literal["EPSG:28992"]
    units: Literal["m"]
    context_distance_m: float
    source: Literal["OpenStreetMap"]
    source_data_version: StrictStr
    source_pbf_sha256: StrictStr
    license: Literal["ODbL 1.0"]
    attribution: StrictStr
    tolerance_m: float
    height_policy: dict[str, Any] | None = None
    three_dbag: dict[str, Any] | None = Field(default=None, alias="3dbag")


class SurroundingContextLayers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    buildings: ContextFeatureCollection
    water: ContextFeatureCollection
    green: ContextFeatureCollection
    roads: ContextFeatureCollection


class SurroundingContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: SurroundingContextMetadata
    layers: SurroundingContextLayers


class HumanDecisionSubmission(BaseModel):
    """Validated user input; the server fixes actor_kind to HUMAN_UI."""

    model_config = ConfigDict(extra="forbid")

    target_id: StrictStr = Field(..., min_length=1)
    target_type: StrictStr = Field(..., min_length=1)
    target_version: StrictStr = Field(..., min_length=1)
    target_geometry_sha256: StrictStr | None = None
    target_artifact_sha256: StrictStr | None = None
    target_payload_digest: StrictStr | None = None
    action: DecisionAction
    status: HumanStatus
    reason: StrictStr = Field(..., min_length=1, max_length=2000)
    decision_key: SecretStr
    actor_session_id: StrictStr = Field(..., min_length=1, max_length=128)

    @model_validator(mode="after")
    def reconsider_contract(self):
        if self.action is DecisionAction.RECONSIDER and (
            self.target_type != "DesignScenario" or self.status is not HumanStatus.NOT_REVIEWED
        ):
            raise ValueError("Reconsider requires DesignScenario and not_reviewed status")
        return self

    @field_validator("target_id", "target_type", "target_version", "actor_session_id")
    @classmethod
    def nonempty_decision_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("decision identifiers and actor session must not be blank")
        return value.strip()

    @field_validator("reason")
    @classmethod
    def nonempty_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("decision reason must not be blank")
        return value.strip()

    @field_validator("target_geometry_sha256", "target_artifact_sha256", "target_payload_digest")
    @classmethod
    def valid_target_hash(cls, value: str | None) -> str | None:
        if value is not None:
            if re.fullmatch(r"[0-9a-f]{64}", value):
                return f"sha256:{value}"
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                raise ValueError("target hashes must use sha256:<64 lowercase hex characters>")
        return value

    @model_validator(mode="after")
    def target_hash_required(self) -> "HumanDecisionSubmission":
        if (
            self.target_geometry_sha256 is None
            and self.target_artifact_sha256 is None
            and self.target_payload_digest is None
        ):
            raise ValueError("decision must bind a target geometry, artifact hash, or payload digest")
        return self


class DecisionAttemptLimiter:
    """Bound failed key checks per remote client for a short in-memory window."""

    MAX_FAILURES = 5
    WINDOW_SECONDS = 15 * 60

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = {}
        self._in_flight: dict[str, int] = {}
        self._lock = RLock()

    def _recent(self, client_key: str, now: float) -> deque[float]:
        attempts = self._failures.setdefault(client_key, deque())
        while attempts and now - attempts[0] >= self.WINDOW_SECONDS:
            attempts.popleft()
        return attempts

    def is_limited(self, client_key: str) -> bool:
        with self._lock:
            return len(self._recent(client_key, time.monotonic())) >= self.MAX_FAILURES

    def begin_attempt(self, client_key: str) -> bool:
        """Reserve a verification slot atomically, including concurrent checks."""

        with self._lock:
            now = time.monotonic()
            failures = self._recent(client_key, now)
            if len(failures) + self._in_flight.get(client_key, 0) >= self.MAX_FAILURES:
                return False
            self._in_flight[client_key] = self._in_flight.get(client_key, 0) + 1
            return True

    def finish_attempt(self, client_key: str, *, failed: bool) -> None:
        with self._lock:
            now = time.monotonic()
            in_flight = self._in_flight.get(client_key, 0)
            if in_flight <= 0:
                raise RuntimeError("decision key attempt was not reserved")
            if in_flight == 1:
                self._in_flight.pop(client_key, None)
            else:
                self._in_flight[client_key] = in_flight - 1
            failures = self._recent(client_key, now)
            if failed:
                failures.append(now)
            else:
                failures.clear()
                if not self._in_flight.get(client_key):
                    self._failures.pop(client_key, None)

    def clear(self, client_key: str) -> None:
        with self._lock:
            self._failures.pop(client_key, None)


class CriticRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    language: Literal["zh-TW", "en"] = "zh-TW"
    evidence_card_ids: list[str] | None = None
    expected_study_area_id: str = "study-area-rotterdam-m4h-pilot-project-v5"
    expected_study_area_revision: int | None = Field(None, ge=1)
    expected_source_package_revision: str | None = None
    expected_evidence_bundle_sha256: str | None = None
    expected_workspace_id: str | None = Field(None, min_length=1)
    expected_workspace_revision: int | None = Field(None, ge=1)


class ActiveModelProfileSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: StrictStr = Field(..., min_length=1, max_length=128)

    @field_validator("profile_id")
    @classmethod
    def nonempty_profile_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("profile_id must not be blank")
        return value.strip()


def create_workspace_app(
    store: ProjectStateStore | None = None,
    *,
    source_package_root: str | Path | None = None,
    evidence_bundle_path: str | Path | None = None,
    syntax_figure_record_path: str | Path | None = None,
    critic_provider: Any | None = None,
    allow_live_critic: bool = False,
    decision_key_path: str | Path | None = None,
    scenario_artifact_root: str | Path | None = None,
    context_data_dir: str | Path | None = None,
    context_manifest_path: str | Path | None = None,
    morphology_preview_root: str | Path | None = None,
    morphology_preview_manifest_sha256: str | None = None,
    syntax_context_root: str | Path | None = None,
    syntax_context_manifest_sha256: str | None = None,
    climate_artifact_root: str | Path | None = None,
    model_profile_selection_path: str | Path | None = None,
) -> FastAPI:
    if morphology_preview_root is not None and not str(morphology_preview_root).strip():
        raise ValueError("morphology preview root must not be blank")
    if morphology_preview_manifest_sha256 is not None and not morphology_preview_manifest_sha256.strip():
        raise ValueError("morphology preview manifest sha256 must not be blank")
    if (morphology_preview_root is None) != (morphology_preview_manifest_sha256 is None):
        raise ValueError(
            "morphology preview root and manifest sha256 must be configured together or both omitted"
        )
    if syntax_context_root is not None and not str(syntax_context_root).strip():
        raise ValueError("syntax context root must not be blank")
    if syntax_context_manifest_sha256 is not None and not syntax_context_manifest_sha256.strip():
        raise ValueError("syntax context manifest sha256 must not be blank")
    if (syntax_context_root is None) != (syntax_context_manifest_sha256 is None):
        raise ValueError(
            "syntax context root and manifest sha256 must be configured together or both omitted"
        )

    app = FastAPI(title="Urban Design Workspace API", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    owned_store = store is None
    if store is None:
        db_path = Path.cwd() / ".urban_design_runtime" / "state.sqlite3"
        store = ProjectStateStore(db_path)

    source_catalog = None
    if owned_store or source_package_root is not None:
        try:
            source_catalog = WorkspaceSourceCatalog.load(store, source_package_root)
        except WorkspaceSourceError as exc:
            raise RuntimeError(f"workspace API startup blocked by source verification: {exc}") from exc

    service = WorkspaceService(store, source_catalog=source_catalog)
    brief_service = SiteIntelligenceBriefService(store)
    constraint_set_service = ConstraintSetService(store, service)
    store_access_lock = RLock()
    decision_attempt_limiter = DecisionAttemptLimiter()
    context_repository = ContextRepository(
        data_root=context_data_dir or Path.home() / ".local" / "share" / "urban-design-data" / "context",
        manifest_path=context_manifest_path or Path(__file__).resolve().parents[2] / "config" / "context" / "manifest.json",
    )

    def serialize_store_access(endpoint):
        @wraps(endpoint)
        def synchronized_endpoint(*args, **kwargs):
            with store_access_lock:
                return endpoint(*args, **kwargs)
        return synchronized_endpoint

    app.state.source_catalog = source_catalog
    from .site_extents import create_extent_router
    app.include_router(create_extent_router(store))
    app.state.project_store = store
    app.state.site_intelligence_brief_service = brief_service
    app.state.decision_attempt_limiter = decision_attempt_limiter
    app.state.decision_key_path = Path(decision_key_path) if decision_key_path is not None else None
    selection_path = (
        Path(model_profile_selection_path)
        if model_profile_selection_path is not None
        else Path(store.database).expanduser().resolve().parent / "model-profile-selection.json"
    )
    model_profile_selection_store = ModelProfileSelectionStore(selection_path)
    model_profile_config = load_model_provider_config()
    selected_profile_id = model_profile_selection_store.load()
    configured_ids = {profile.id for profile in model_profile_config.profiles}
    if selected_profile_id not in configured_ids:
        selected_profile_id = default_ariadne_profile_id(model_profile_config)
    app.state.model_profile_selection_store = model_profile_selection_store
    app.state.active_model_profile_id = selected_profile_id

    from .ariadne_chat import _configured_ariadne_provider

    def selected_ariadne_provider_factory(target_store: ProjectStateStore, project_id: str) -> Any:
        return _configured_ariadne_provider(
            target_store,
            project_id,
            selected_profile_id=app.state.active_model_profile_id,
        )

    app.include_router(create_ariadne_chat_router(
        project_store=store,
        source_catalog=source_catalog,
        provider_factory=selected_ariadne_provider_factory,
    ))
    from .judgement import create_judgement_router
    app.include_router(create_judgement_router(
        project_store=store,
        source_catalog=source_catalog,
        provider_factory=selected_ariadne_provider_factory,
    ))
    artifact_root = scenario_artifact_root or (Path.cwd() / ".urban_design_runtime" / "scenario-artifacts")
    app.state.scenario_artifact_root = Path(artifact_root).resolve()
    register_scenario_routes(app, store, app.state.scenario_artifact_root)
    from urban_design.generation_context import create_generation_context_router
    from urban_design.generation.formal_service import install_formal_service
    app.include_router(create_generation_context_router(store))
    install_formal_service(app, store, app.state.scenario_artifact_root)
    from urban_design.environment.router import router as environment_router
    app.include_router(environment_router)
    from urban_design.fabric_plans_api import create_fabric_plans_router
    app.include_router(create_fabric_plans_router())
    from urban_design.environment.e2_router import router as e2_router
    app.include_router(e2_router)
    if climate_artifact_root is not None:
        app.state.climate_artifact_root = Path(climate_artifact_root).resolve()
    from urban_design.environment.climate_extras_router import router as climate_extras_router
    app.include_router(climate_extras_router)

    # Commander decision (2026-09-30):
    # Source drift: Service startup validates the configured source and freezes its verified
    # bytes in memory. After startup, the API does not detect filesystem drift and does not
    # return 409. This is an intentional deviation from the exploratory P2 table in
    # docs/superpowers/plans/2026-09-30-preview-and-ui-zh.md, documented in
    # docs/technical/preview-catalog-v1.md.
    preview_root = Path(morphology_preview_root) if morphology_preview_root is not None else None
    app.include_router(
        create_preview_router(
            root=preview_root,
            manifest_sha256=morphology_preview_manifest_sha256,
        )
    )
    syntax_root = Path(syntax_context_root) if syntax_context_root is not None else None
    from .site_intelligence.basic_analysis import create_basic_analysis_router
    app.include_router(create_basic_analysis_router(store, syntax_root=syntax_root, syntax_hash=syntax_context_manifest_sha256))
    app.include_router(
        create_syntax_context_router(
            root=syntax_root,
            manifest_sha256=syntax_context_manifest_sha256,
        )
    )
    from urban_design.week7.router import create_week7_router
    app.include_router(create_week7_router(store))
    from urban_design.skills.router import create_skills_router
    app.include_router(create_skills_router(store))
    project_root = Path(__file__).resolve().parents[2]
    evidence_path = Path(evidence_bundle_path).resolve() if evidence_bundle_path else None
    figure_record_path = Path(syntax_figure_record_path).resolve() if syntax_figure_record_path else None
    project_ai_authorized = os.environ.get("PROJECT_AI_AUTHORIZED", "").strip() == "1"
    live_provider_configured = allow_live_critic or project_ai_authorized
    provider = critic_provider or (
        get_configured_provider(store=store, project_id=source_catalog.project_id)
        if live_provider_configured and source_catalog is not None
        else DeterministicFixtureProvider(status="BLOCKED_NO_LIVE_AUTHORIZATION")
    )

    def current_verified_catalog() -> WorkspaceSourceCatalog:
        if source_catalog is None:
            raise EvidenceAlignmentError("verified spatial-r01 source catalog is unavailable")
        return WorkspaceSourceCatalog.load(store, source_catalog.package_root)

    def current_evidence_bundle(catalog: WorkspaceSourceCatalog) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
        if evidence_path is None:
            candidate = build_r04_observational_evidence_bundle(catalog, store)
        else:
            try:
                candidate = json.loads(evidence_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise EvidenceAlignmentError("R04 Evidence Card bundle is unavailable or invalid") from exc
        cards = validate_r04_observational_evidence_bundle(candidate, catalog, store)
        bundle_bytes = json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return candidate, cards, "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()

    def current_syntax_bundle(catalog: WorkspaceSourceCatalog) -> dict[str, Any]:
        try:
            return load_verified_exploratory_syntax(project_root, catalog)
        except SyntaxEvidenceError as exc:
            raise EvidenceAlignmentError(f"verified Syntax evidence is unavailable: {exc}") from exc

    def persisted_or_file_syntax_bundle(
        project_id: str,
        catalog: WorkspaceSourceCatalog,
    ) -> dict[str, Any]:
        bundle = get_persisted_syntax_bundle(store, project_id, catalog, project_root)
        if bundle.get("status") != "NOT_COMPUTED" or bundle.get("result_source") != "none":
            return bundle
        try:
            fallback = current_syntax_bundle(catalog)
        except EvidenceAlignmentError:
            return bundle
        fallback = dict(fallback)
        fallback["result_source"] = "verified_file_fallback"
        fallback["limitations"] = [
            *fallback.get("limitations", []),
            "No persisted Syntax record was found; this response uses hash-verified local file evidence.",
        ]
        return fallback

    def verified_figure_path(extension: str, catalog: WorkspaceSourceCatalog, syntax_bundle: Mapping[str, Any]) -> Path:
        if figure_record_path is None:
            raise HTTPException(status_code=503, detail="R03 exploratory figure artifact is not available")
        try:
            record = json.loads(figure_record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=503, detail="R03 exploratory figure record is unavailable") from exc
        if (
            record.get("formal_result_eligible") is not False
            or record.get("status") != "EXPLORATORY_RENDERED"
            or record.get("warning") != syntax_bundle["figure"]["warning"]
            or record.get("source_manifest_sha256") != syntax_bundle["source_manifest_sha256"]
            or record.get("syntax_result_sha256") != syntax_bundle["syntax_result_sha256"]
            or record.get("r02_integrity_manifest_sha256") != syntax_bundle["r02_integrity_manifest_sha256"]
            or record.get("study_area_id") != catalog.study_area_id
            or record.get("study_area_geometry_sha256") != catalog.study_area_geometry_sha256
        ):
            raise HTTPException(status_code=409, detail="R03 figure lineage or exploratory status does not match current evidence")
        file_info = record.get("files", {}).get(extension)
        if not isinstance(file_info, Mapping) or not isinstance(file_info.get("path"), str):
            raise HTTPException(status_code=404, detail=f"R03 exploratory {extension.upper()} figure is unavailable")
        relative = PurePosixPath(file_info["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise HTTPException(status_code=409, detail="R03 figure path is not confined to the project")
        resolved = (project_root.joinpath(*relative.parts)).resolve()
        package_root = (project_root / "artifacts/week4-repair-r03").resolve()
        if package_root not in resolved.parents or not resolved.is_file():
            raise HTTPException(status_code=404, detail="R03 exploratory figure file is missing")
        if resolved.stat().st_size != file_info.get("size_bytes") or sha256_file(resolved) != file_info.get("sha256"):
            raise HTTPException(status_code=409, detail="R03 exploratory figure hash or size does not match its record")
        return resolved

    def count_clarified_svg(path: Path, syntax_bundle: Mapping[str, Any]) -> str:
        """Return a count-labeled derivative without changing the frozen SVG bytes."""
        figure = syntax_bundle.get("figure")
        if not isinstance(figure, Mapping):
            raise HTTPException(status_code=409, detail="R03 figure counts are unavailable")
        displayed = figure.get("display_segment_count")
        valued = figure.get("mapped_display_segment_count")
        source_mapped = len(syntax_bundle.get("segments", []))
        if (
            not isinstance(displayed, int)
            or isinstance(displayed, bool)
            or not isinstance(valued, int)
            or isinstance(valued, bool)
            or not isinstance(source_mapped, int)
            or displayed < 0
            or valued < 0
            or valued > displayed
            or displayed > source_mapped
        ):
            raise HTTPException(status_code=409, detail="R03 figure counts are inconsistent")

        try:
            svg = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=409, detail="R03 exploratory SVG cannot be read as UTF-8") from exc

        segment_pattern = re.compile(r'(<text\b(?=[^>]*\by="487")[^>]*>)Segments: [0-9,]+(</text>)')
        svg, segment_replacements = segment_pattern.subn(
            lambda match: f"{match.group(1)}Displayed linework: {displayed:,}{match.group(2)}",
            svg,
            count=1,
        )
        footer_pattern = re.compile(r" · [0-9,]+ mapped segments · ")
        svg, footer_replacements = footer_pattern.subn(
            f" · Source-mapped network: {source_mapped:,} segments · ",
            svg,
            count=1,
        )
        status_header = '  <text x="956" y="520" font-size="13" font-weight="700" fill="#0f172a">STATUS</text>'
        if segment_replacements != 1 or footer_replacements != 1 or svg.count(status_header) != 1:
            raise HTTPException(status_code=409, detail="R03 SVG labels do not match the expected count-clarification template")
        for x, old_y, new_y in (
            ("956", "641", "659"),
            ("956", "623", "641"),
            ("956", "605", "623"),
            ("964", "566", "584"),
            ("964", "552", "570"),
            ("956", "535", "553"),
            ("956", "520", "538"),
        ):
            old_coordinates = f'x="{x}" y="{old_y}"'
            if svg.count(old_coordinates) != 1:
                raise HTTPException(status_code=409, detail="R03 SVG panel layout does not match the expected template")
            svg = svg.replace(old_coordinates, f'x="{x}" y="{new_y}"', 1)
        count_rows = (
            f'  <text x="956" y="500" font-size="9.5" fill="#475569">With Syntax values: {valued:,}</text>\n'
            f'  <text x="956" y="513" font-size="9.5" fill="#475569">Without Syntax values: {displayed - valued:,}</text>\n'
        )
        shifted_status_header = status_header.replace('y="520"', 'y="538"')
        return svg.replace(shifted_status_header, count_rows + shifted_status_header, 1)

    @app.post(
        "/api/v1/workspaces/sync",
        response_model=WorkspaceSyncResponse,
        status_code=status.HTTP_201_CREATED,
    )
    @serialize_store_access
    def sync_workspace(request: SyncRequest) -> Any:
        try:
            ws_id = service._workspace_id(request.project_id)
            current = service.get_workspace(ws_id)
            prior_rev = current.revision if current else 0

            revision = service.sync(request)
            is_replay = bool(current and revision.revision == prior_rev)
            status_code = status.HTTP_200_OK if is_replay else status.HTTP_201_CREATED
            return JSONResponse(
                status_code=status_code,
                content={
                    "workspace_revision": revision.model_dump(),
                    "idempotent_replay": is_replay,
                },
            )
        except WorkspaceConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except WorkspaceValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.get(
        "/api/v1/workspaces/{workspace_id}",
        response_model=WorkspaceRevision,
    )
    @serialize_store_access
    def get_workspace(
        workspace_id: str = FPath(..., min_length=1),
        revision: int | None = Query(None, ge=1),
    ) -> WorkspaceRevision:
        rev = service.get_workspace(workspace_id, revision=revision)
        if rev is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace {workspace_id!r} not found",
            )
        return rev

    @app.get(
        "/api/v1/workspaces/{workspace_id}/history",
        response_model=list[WorkspaceRevision],
    )
    @serialize_store_access
    def get_workspace_history(
        workspace_id: str = FPath(..., min_length=1),
    ) -> list[WorkspaceRevision]:
        return service.list_revisions(workspace_id)

    def _build_workspace_decision_summary(rev: WorkspaceRevision, cat: WorkspaceSourceCatalog | None) -> dict[str, Any]:
        eda_summary = None
        if rev.spatial_brief and rev.spatial_brief.exploration_design_area:
            eda = rev.spatial_brief.exploration_design_area
            eda_geom = eda.geometry
            geom_hash = None
            try:
                geom_hash = canonical_geometry_hash(eda_geom)
            except Exception:
                pass
            eda_summary = {
                "area_m2": eda.area_m2,
                "crs": eda.crs,
                "geometry": eda_geom,
                "geometry_hash": geom_hash,
                "revision": eda.revision,
                "status": eda.status,
            }

        disp_map = {d.feature_id: (d.feature_kind, d.disposition.lower()) for d in rev.feature_dispositions}
        building_pres = []
        building_edit = []
        building_undec = []
        road_pres = []
        road_edit = []
        road_undec = []

        if cat is not None:
            for b in cat.buildings:
                _kind, disp = disp_map.get(b.feature_id, ("building", "undecided"))
                if disp == "preserve":
                    building_pres.append(b.feature_id)
                elif disp == "editable":
                    building_edit.append(b.feature_id)
                else:
                    building_undec.append(b.feature_id)
            for r in cat.roads:
                _kind, disp = disp_map.get(r.feature_id, ("road", "undecided"))
                if disp == "preserve":
                    road_pres.append(r.feature_id)
                elif disp == "editable":
                    road_edit.append(r.feature_id)
                else:
                    road_undec.append(r.feature_id)
        else:
            for d in rev.feature_dispositions:
                if d.feature_kind == "building":
                    if d.disposition.lower() == "preserve":
                        building_pres.append(d.feature_id)
                    elif d.disposition.lower() == "editable":
                        building_edit.append(d.feature_id)
                    else:
                        building_undec.append(d.feature_id)
                elif d.feature_kind == "road":
                    if d.disposition.lower() == "preserve":
                        road_pres.append(d.feature_id)
                    elif d.disposition.lower() == "editable":
                        road_edit.append(d.feature_id)
                    else:
                        road_undec.append(d.feature_id)

        building_pres.sort()
        building_edit.sort()
        building_undec.sort()
        road_pres.sort()
        road_edit.sort()
        road_undec.sort()

        dispositions_summary = {
            "buildings": {
                "preserve": building_pres,
                "editable": building_edit,
                "undecided": building_undec,
                "counts": {
                    "preserve": len(building_pres),
                    "editable": len(building_edit),
                    "undecided": len(building_undec),
                    "total": len(building_pres) + len(building_edit) + len(building_undec),
                },
            },
            "roads": {
                "preserve": road_pres,
                "editable": road_edit,
                "undecided": road_undec,
                "counts": {
                    "preserve": len(road_pres),
                    "editable": len(road_edit),
                    "undecided": len(road_undec),
                    "total": len(road_pres) + len(road_edit) + len(road_undec),
                },
            },
        }

        zones_summary = []
        if rev.spatial_brief and rev.spatial_brief.zones:
            for z in rev.spatial_brief.zones:
                zones_summary.append({
                    "zone_id": z.zone_id,
                    "name": z.name,
                    "target_use": z.target_use,
                    "area_m2": z.area_m2,
                    "target_far": z.target_far.value if z.target_far else None,
                    "target_height_m": z.target_height_m.value if z.target_height_m else None,
                    "draft_constraints": list(z.draft_constraints),
                    "draft_preferences": list(z.draft_preferences),
                })

        all_decisions = store.list_current("HumanDecision", project_id=rev.project_id)
        ws_decisions = [
            d.payload for d in all_decisions
            if d.payload.get("target_id") == rev.workspace_id and d.payload.get("target_type") == "WorkspaceRevision"
        ]
        ws_decisions.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        latest_decision = ws_decisions[0] if ws_decisions else None

        is_current_revision = False
        is_stale_for_decision = False
        decision_status_label = "UNDECIDED"
        if latest_decision:
            target_v = str(latest_decision.get("target_version") or "")
            if target_v == str(rev.revision):
                is_current_revision = True
                is_stale_for_decision = False
                decision_status_label = str(latest_decision.get("status") or "APPROVED")
            else:
                is_current_revision = False
                is_stale_for_decision = True
                decision_status_label = "SUPERSEDED_PRIOR_REVISION"

        return {
            "workspace_id": rev.workspace_id,
            "project_id": rev.project_id,
            "revision": rev.revision,
            "payload_digest": rev.payload_digest,
            "exploration_design_area": eda_summary,
            "dispositions": dispositions_summary,
            "zones": zones_summary,
            "latest_decision": latest_decision,
            "is_current_revision": is_current_revision,
            "is_stale_for_decision": is_stale_for_decision,
            "decision_status_label": decision_status_label,
        }

    @app.get(
        "/api/v1/workspaces/{workspace_id}/decision-summary",
    )
    @serialize_store_access
    def get_workspace_decision_summary(
        workspace_id: str = FPath(..., min_length=1),
        revision: int | None = Query(None, ge=1),
    ) -> dict[str, Any]:
        rev = service.get_workspace(workspace_id, revision=revision)
        if rev is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace {workspace_id!r} not found",
            )
        catalog = None
        if source_catalog is not None:
            try:
                catalog = current_verified_catalog()
            except Exception:
                catalog = None
        return _build_workspace_decision_summary(rev, catalog)

    @app.get(
        "/api/v1/projects/{project_id}/decisions",
    )
    @serialize_store_access
    def list_project_decisions(
        project_id: str = FPath(..., min_length=1),
        target_id: str | None = Query(None),
        target_type: str | None = Query(None),
    ) -> list[dict[str, Any]]:
        all_decisions = store.list_current("HumanDecision", project_id=project_id)
        results = []
        for d in all_decisions:
            payload = d.payload
            if target_id is not None and payload.get("target_id") != target_id:
                continue
            if target_type is not None and payload.get("target_type") != target_type:
                continue
            results.append(payload)
        results.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        return results

    @app.put(
        "/api/v1/workspaces/{workspace_id}/dispositions",
        response_model=WorkspaceRevision,
    )
    @serialize_store_access
    def update_dispositions(
        request: UpdateDispositionsRequest,
        workspace_id: str = FPath(..., min_length=1),
    ) -> WorkspaceRevision:
        try:
            return service.update_dispositions(
                workspace_id,
                dispositions=request.dispositions,
                expected_revision=request.expected_revision,
                actor_kind=request.actor_kind,
                actor_session_id=request.actor_session_id,
            )
        except WorkspaceConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except WorkspaceValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except WorkspaceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/projects/{project_id}/site-intelligence")
    @serialize_store_access
    def get_site_intelligence(project_id: str = FPath(..., min_length=1, max_length=128)) -> dict[str, Any]:
        """Return the latest persisted analysis projection without starting a new run."""
        try:
            return brief_service.site_intelligence(project_id)
        except BriefNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BriefServiceError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    @app.post("/api/v1/projects/{project_id}/analysis-jobs")
    def create_analysis_job(project_id: str = FPath(..., min_length=1, max_length=128)) -> None:
        """Analysis execution is deferred until the shared U1 job contract exists."""
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Analysis jobs are deferred until the U1 job contract defines frozen inputs, idempotency, and outcome reconciliation.",
        )

    @app.post("/api/v1/projects/{project_id}/design-briefs")
    @serialize_store_access
    def save_design_brief(
        request: CreateDesignBriefRequest,
        project_id: str = FPath(..., min_length=1, max_length=128),
    ) -> JSONResponse:
        """Persist a draft Artifact and its ledger event; this route never records a decision."""
        try:
            response = brief_service.save_draft(project_id, request)
        except BriefConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except BriefNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BriefServiceError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
        response_status = status.HTTP_200_OK if response.get("idempotent_replay") else status.HTTP_201_CREATED
        return JSONResponse(status_code=response_status, content=response)

    @app.get("/api/v1/projects/{project_id}/design-briefs/{brief_id}/revisions/{revision}")
    @serialize_store_access
    def get_design_brief_revision(
        project_id: str = FPath(..., min_length=1, max_length=128),
        brief_id: str = FPath(..., min_length=1, max_length=128),
        revision: int = FPath(..., ge=1),
    ) -> dict[str, Any]:
        """Read one immutable draft revision by project, brief id, and revision."""
        try:
            return brief_service.get_brief_revision(project_id, brief_id, revision)
        except BriefNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BriefServiceError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    @app.get("/api/v1/projects/{project_id}/design-briefs/latest")
    @serialize_store_access
    def get_latest_design_brief(
        project_id: str = FPath(..., min_length=1, max_length=128),
    ) -> dict[str, Any]:
        """Read the latest immutable draft revision by project, or 404 if none exists."""
        try:
            brief = brief_service.latest_brief(project_id)
            if brief is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No design brief found for project")
            return brief
        except BriefNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except BriefServiceError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    @app.post(
        "/api/v1/projects/{project_id}/constraint-sets",
        status_code=status.HTTP_201_CREATED,
    )
    @serialize_store_access
    def create_constraint_set_draft(
        request: ConstraintSetDraftRequest,
        project_id: str = FPath(..., min_length=1),
    ) -> JSONResponse:
        try:
            record, payload_digest = constraint_set_service.create_draft(
                project_id=project_id,
                constraints=request.constraints,
                allocation_policy=request.allocation_policy,
                actor_session_id=request.actor_session_id,
                actor_kind=ActorKind(request.actor_kind),
                id=request.id,
                idempotency_key=request.idempotency_key,
                notes=request.notes,
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={
                    "constraint_set": record.payload,
                    "revision": record.revision,
                    "payload_digest": payload_digest,
                },
            )
        except PayloadError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.get("/api/v1/projects/{project_id}/constraint-sets")
    @serialize_store_access
    def list_constraint_sets(
        project_id: str = FPath(..., min_length=1),
    ) -> dict[str, Any]:
        """Read-only endpoint returning current head summaries for project ConstraintSets."""
        items = constraint_set_service.list(project_id)
        return {"items": items}

    @app.get("/api/v1/projects/{project_id}/constraint-sets/{constraint_set_id}")
    @serialize_store_access
    def get_constraint_set(
        project_id: str = FPath(..., min_length=1),
        constraint_set_id: str = FPath(..., min_length=1),
    ) -> dict[str, Any]:
        result = constraint_set_service.get(project_id, constraint_set_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ConstraintSet was not found for this project")
        record, payload_digest = result
        return {
            "constraint_set": record.payload,
            "revision": record.revision,
            "payload_digest": payload_digest,
        }

    @app.post(
        "/api/v1/projects/{project_id}/decisions",
        status_code=status.HTTP_201_CREATED,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": HumanDecisionSubmission.model_json_schema(),
                    }
                },
            }
        },
    )
    async def submit_human_decision(
        request: Request,
        project_id: str = FPath(..., min_length=1),
    ) -> JSONResponse:
        """Append a target-bound HumanDecision after verifying the designer key."""

        remote_key = request.client.host if request.client is not None else "unknown"
        try:
            raw_body = await request.json()
            if not isinstance(raw_body, dict):
                raise ValueError("decision request must be a JSON object")
            submission = HumanDecisionSubmission.model_validate(raw_body)
        except (ValueError, ValidationError):
            # Keep Pydantic's input payload out of the response because it contains the key.
            raise HTTPException(status_code=422, detail="Invalid human decision request") from None

        if not decision_attempt_limiter.begin_attempt(remote_key):
            raise HTTPException(status_code=429, detail="Decision key attempts are temporarily rate-limited")

        try:
            decision_key = submission.decision_key.get_secret_value()
            verified = verify_decision_key_strict(decision_key, path=decision_key_path)
        except DecisionKeyUnavailable:
            decision_attempt_limiter.finish_attempt(remote_key, failed=False)
            return JSONResponse(
                status_code=423,
                content={
                    "status": "BLOCKED",
                    "detail": "Designer decision key is not initialized or is unavailable.",
                },
            )
        if not verified:
            decision_attempt_limiter.finish_attempt(remote_key, failed=True)
            raise HTTPException(status_code=403, detail="Decision key is incorrect")
        decision_attempt_limiter.finish_attempt(remote_key, failed=False)

        decision = HumanDecision(
            id=f"decision-{uuid.uuid4().hex}",
            project_id=project_id,
            target_id=submission.target_id,
            target_type=submission.target_type,
            target_version=submission.target_version,
            target_geometry_sha256=submission.target_geometry_sha256,
            target_artifact_sha256=submission.target_artifact_sha256,
            target_payload_digest=submission.target_payload_digest,
            action=submission.action,
            status=submission.status,
            actor="designer",
            actor_kind=ActorKind.HUMAN_UI,
            actor_session_id=submission.actor_session_id,
            reason=submission.reason,
            timestamp=datetime.now(timezone.utc),
            decision_event_id=f"event-{uuid.uuid4().hex}",
        )
        try:
            with store_access_lock:
                record = store.record_human_decision(
                    decision,
                    decision_key=decision_key,
                    decision_key_path=decision_key_path,
                )
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Decision target was not found") from exc
        except PayloadError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content=record.payload)

    @app.get("/api/v1/projects/{project_id}/site-context")
    @serialize_store_access
    def get_site_context(project_id: str = FPath(..., min_length=1)) -> dict[str, Any]:
        """Return study area, buildings, road segments, syntax layers, and evidence cards for platform UI."""
        if source_catalog is None:
            raise HTTPException(status_code=503, detail="verified spatial-r01 source catalog is unavailable")
        try:
            catalog = current_verified_catalog()
        except (WorkspaceSourceError, EvidenceAlignmentError) as exc:
            raise HTTPException(status_code=503, detail=f"verified source state is unavailable: {exc}") from exc
        if project_id != catalog.project_id:
            raise HTTPException(status_code=404, detail="project is not present in the verified spatial-r01 package")
        try:
            project = store.current(project_id)
            if project.payload.get("active_study_area_id") != catalog.study_area_id:
                raise HTTPException(status_code=409, detail="active StudyArea changed; reload the verified source package")
            sa_rec = store.current(catalog.study_area_id)
            if sa_rec.payload.get("status") != "CONFIRMED_FOR_EXPLORATION":
                raise HTTPException(status_code=409, detail="active StudyArea is not confirmed for exploration")
            geometry_artifact = store.current(str(sa_rec.payload.get("geometry_artifact_id")))
            area_path = Path(str(geometry_artifact.payload.get("uri", "")))
            if not area_path.is_absolute():
                area_path = Path(store.database).resolve().parent / area_path
            sa_geojson = json.loads(area_path.read_text(encoding="utf-8"))
        except HTTPException:
            raise
        except (EntityNotFoundError, OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=409, detail="active StudyArea could not be re-resolved") from exc

        active_geometry = sa_geojson.get("geometry", sa_geojson)
        if canonical_geometry_hash(active_geometry) != catalog.study_area_geometry_sha256:
            raise HTTPException(status_code=409, detail="active StudyArea changed since source catalog verification")

        ws_id = service._workspace_id(project_id)
        current_ws = service.get_workspace(ws_id)
        verified_dispositions: dict[str, FeatureDisposition] = {}
        unverified_disposition_count = 0
        if current_ws:
            for disposition in current_ws.feature_dispositions:
                try:
                    parent = catalog.resolve_feature(
                        disposition.feature_id,
                        disposition.feature_kind,
                        disposition.source_artifact_id,
                    )
                    if (
                        disposition.source_snapshot_id not in (None, parent.source_snapshot_id)
                        or disposition.source_feature_id not in (None, parent.source_feature_id)
                    ):
                        raise WorkspaceSourceError("stored feature lineage does not match spatial-r01")
                    verified_dispositions[disposition.feature_id] = disposition
                except WorkspaceSourceError:
                    unverified_disposition_count += 1

        buildings = [feature.as_api_feature() for feature in catalog.buildings]
        roads = [feature.as_api_feature() for feature in catalog.roads]
        for collection in (buildings, roads):
            for feature in collection:
                disposition = verified_dispositions.get(feature["id"])
                if disposition:
                    feature["disposition"] = disposition.disposition.upper()
                    feature["annotation"] = disposition.annotation
        current_workspace = current_ws.model_dump() if current_ws else None
        if current_workspace is not None:
            # Preserve historical records in a separate field; only verified lineage
            # is returned as the active editable overlay.
            current_workspace["historical_feature_dispositions"] = current_workspace["feature_dispositions"]
            current_workspace["feature_dispositions"] = [item.model_dump() for item in verified_dispositions.values()]
            current_workspace["unverified_disposition_count"] = unverified_disposition_count
            stored_brief = current_workspace.get("spatial_brief")
            if isinstance(stored_brief, dict) and isinstance(stored_brief.get("zones"), list):
                verified_zones = []
                historical_zones = []
                for zone in stored_brief["zones"]:
                    try:
                        source_catalog.validate_zone_scope(zone.get("geometry", {}))
                        verified_zones.append(zone)
                    except (WorkspaceSourceError, AttributeError):
                        historical_zones.append(zone)
                raw_exploration_area = stored_brief.get("exploration_design_area")
                verified_exploration_area = raw_exploration_area
                historical_exploration_area = None
                if raw_exploration_area is not None:
                    if not isinstance(raw_exploration_area, Mapping):
                        historical_exploration_area = raw_exploration_area
                        verified_exploration_area = None
                    else:
                        try:
                            source_catalog.validate_zone_scope(raw_exploration_area.get("geometry", {}))
                        except WorkspaceSourceError:
                            historical_exploration_area = raw_exploration_area
                            verified_exploration_area = None

                historical_brief = {
                    key: value
                    for key, value in stored_brief.items()
                    if key not in {"zones", "exploration_design_area"}
                }
                historical_brief["zones"] = historical_zones
                if historical_exploration_area is not None:
                    historical_brief["exploration_design_area"] = historical_exploration_area
                current_workspace["historical_spatial_brief"] = historical_brief

                verified_brief = dict(stored_brief)
                verified_brief["exploration_design_area"] = verified_exploration_area
                verified_brief["zones"] = verified_zones
                verified_brief["status"] = "DRAFT_PENDING_HUMAN_DECISION"
                current_workspace["spatial_brief"] = verified_brief
                current_workspace["unverified_spatial_zone_count"] = len(historical_zones)
                current_workspace["unverified_exploration_design_area"] = int(
                    historical_exploration_area is not None
                )

        ws_decision_summary = None
        if current_ws is not None:
            try:
                ws_decision_summary = _build_workspace_decision_summary(current_ws, catalog)
                if current_workspace is not None:
                    current_workspace["decision_summary"] = ws_decision_summary
                    current_workspace["workspace_decision"] = ws_decision_summary.get("latest_decision")
            except Exception:
                ws_decision_summary = None

        evidence_bundle: dict[str, Any] | None = None
        evidence_cards: list[dict[str, Any]] = []
        evidence_status = "BLOCKED_SOURCE_RESULT_ALIGNMENT"
        evidence_bundle_sha256 = None
        evidence_gaps: list[dict[str, str]] = []
        evidence_bundle, evidence_cards, evidence_status, evidence_bundle_sha256, evidence_gaps = get_persisted_site_analysis(store, project_id, catalog)
        syntax_bundle = persisted_or_file_syntax_bundle(project_id, catalog)
        # The frozen R03 figure is a separately verified historical artifact. It may
        # remain downloadable when no current Syntax calculation has been persisted,
        # but its values never populate the persisted layer response above.
        figure_bundle = syntax_bundle
        if not isinstance(figure_bundle.get("figure"), Mapping) or not figure_bundle["figure"].get("warning"):
            try:
                figure_bundle = current_syntax_bundle(catalog)
            except EvidenceAlignmentError:
                figure_bundle = {}
        syntax_downloads = {}
        for extension in ("svg",):
            try:
                verified_figure_path(extension, catalog, figure_bundle)
                syntax_downloads[extension] = f"/api/v1/projects/{project_id}/syntax/exploratory-figure.{extension}"
            except HTTPException:
                pass

        return {
            "project_id": project_id,
            "source_package_id": catalog.package_id,
            "source_package_revision": catalog.package_revision,
            "source_integrity_status": "VERIFIED",
            "source_attributions": _source_attributions(catalog),
            "study_area": {
                "id": sa_rec.entity_id,
                "revision": sa_rec.revision,
                "version": sa_rec.payload.get("version", str(sa_rec.revision)),
                "status": sa_rec.payload.get("status"),
                "geometry_sha256": sa_rec.payload.get("geometry_sha256"),
                "artifact_sha256": sa_rec.payload.get("artifact_sha256"),
                "geometry": active_geometry,
            },
            "source_snapshot_ids": sorted(catalog.snapshots),
            "evidence_cards": evidence_cards,
            "evidence_cards_status": evidence_status,
            "evidence_bundle_sha256": evidence_bundle_sha256,
            "evidence_gaps": evidence_gaps,
            "syntax_layers": syntax_bundle["layers"],
            "syntax_layer_plan": syntax_bundle["layer_plan"],
            "syntax_segments": syntax_bundle["segments"],
            "syntax_layers_status": syntax_bundle["status"],
            "syntax_layers_source": syntax_bundle.get("result_source", "none"),
            "syntax_figure": syntax_bundle["figure"],
            "syntax_figure_downloads": syntax_downloads,
            "syntax_limitations": syntax_bundle["limitations"],
            "segments": roads,
            "roads": roads,
            "buildings": buildings,
            "current_workspace": current_workspace,
            "workspace_decision": ws_decision_summary.get("latest_decision") if ws_decision_summary else None,
            "decision_summary": ws_decision_summary,
        }

    @app.get("/api/v1/projects/{project_id}/site-analysis")
    @serialize_store_access
    def get_site_analysis_report(project_id: str = FPath(..., min_length=1)) -> dict[str, Any]:
        """Read-only endpoint returning verified site analysis summary, claims, and evidence cards."""
        if source_catalog is None:
            raise HTTPException(status_code=503, detail="verified spatial-r01 source catalog is unavailable")
        try:
            catalog = current_verified_catalog()
        except (WorkspaceSourceError, EvidenceAlignmentError) as exc:
            raise HTTPException(status_code=503, detail=f"verified source state is unavailable: {exc}") from exc
        if project_id != catalog.project_id:
            raise HTTPException(status_code=404, detail="project is not present in the verified spatial-r01 package")

        bundle, all_cards, evidence_status, bundle_sha, evidence_gaps = get_persisted_site_analysis(store, project_id, catalog)
        claims_file = project_root / "artifacts" / "w5-site-analysis" / "claims.json"
        claims = []
        if claims_file.is_file():
            try:
                loaded = json.loads(claims_file.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    claims = loaded
            except Exception:
                claims = []

        report_file = project_root / "docs" / "w5" / "site-analysis-report-zh.md"
        report_summary = ""
        if report_file.is_file():
            try:
                text = report_file.read_text(encoding="utf-8")
                if "## 執行摘要（Executive Summary）" in text:
                    report_summary = text.split("## 執行摘要（Executive Summary）")[1].split("---")[0].strip()
            except Exception:
                pass
        if not report_summary:
            report_summary = "Rotterdam M4H StudyArea v5（226,064.33 m²）為供探索使用之研究範圍。依據確定性工具與已驗證數據集計算。"

        return {
            "project_id": project_id,
            "study_area_id": catalog.study_area_id,
            "study_area_area_m2": 226064.33,
            "evidence_cards": all_cards,
            "evidence_cards_status": evidence_status,
            "evidence_bundle_sha256": bundle_sha,
            "evidence_gaps": evidence_gaps,
            "claims": claims,
            "report_summary": report_summary,
            "limitations": [
                "StudyArea v5 是供探索使用之研究範圍，非正式 Site 或 DesignBoundary",
                "投影計算以 EPSG:28992 為唯一基準",
                "建築圖徵數量與高度來自 BAG 與 3D BAG，不單獨證明現地實體使用狀態",
            ],
            "status": "VERIFIED",
        }

    def _source_attributions(catalog: WorkspaceSourceCatalog) -> list[dict[str, Any]]:
        """Expose source publisher and license metadata from verified snapshots."""
        grouped: dict[tuple[str, str], list[str]] = {}
        for snapshot_id, snapshot in catalog.snapshots.items():
            publisher = str(snapshot.get("publisher") or "UNAVAILABLE").strip()
            license_name = str(snapshot.get("license") or "UNAVAILABLE").strip()
            grouped.setdefault((publisher, license_name), []).append(snapshot_id)
        return [
            {
                "publisher": publisher,
                "license": license_name,
                "dataset_snapshot_ids": sorted(snapshot_ids),
            }
            for (publisher, license_name), snapshot_ids in sorted(grouped.items())
        ]

    def _verify_surrounding_context_project(project_id: str) -> dict[str, Any]:
        try:
            manifest = context_repository.manifest()
        except ContextDataError as exc:
            raise HTTPException(status_code=503, detail=f"surrounding context is unavailable: {exc}") from exc
        if project_id != manifest.get("project_id"):
            raise HTTPException(status_code=404, detail="surrounding context is not registered for this project")
        if source_catalog is not None:
            try:
                catalog = current_verified_catalog()
            except (WorkspaceSourceError, EvidenceAlignmentError) as exc:
                raise HTTPException(status_code=503, detail=f"verified StudyArea context is unavailable: {exc}") from exc
            if project_id != catalog.project_id:
                raise HTTPException(status_code=404, detail="project is not present in the verified spatial-r01 package")
            if (
                catalog.study_area_id != manifest.get("study_area_id")
                or catalog.study_area_geometry_sha256 != manifest.get("study_area_geometry_sha256")
            ):
                raise HTTPException(status_code=409, detail="surrounding context does not match the active verified StudyArea")
        return manifest

    @app.get(
        "/api/v1/projects/{project_id}/surrounding-context",
        response_model=SurroundingContextResponse,
    )
    @serialize_store_access
    def get_surrounding_context(
        project_id: str = FPath(..., min_length=1),
        tolerance_m: float = Query(0.0, ge=0.0, le=50.0),
    ) -> SurroundingContextResponse:
        """Return hash-verified OSM context layers as EPSG:28992 display geometry."""
        _verify_surrounding_context_project(project_id)
        try:
            return context_repository.get_context(tolerance_m=tolerance_m)
        except ContextDataError as exc:
            raise HTTPException(status_code=503, detail=f"surrounding context artifacts are unavailable: {exc}") from exc

    @app.post(
        "/api/v1/projects/{project_id}/design-area/preview",
        response_model=DesignAreaPreviewResponse,
    )
    @serialize_store_access
    def preview_design_area(
        request: DesignAreaPreviewRequest,
        project_id: str = FPath(..., min_length=1),
    ) -> dict[str, Any]:
        """Calculate a temporary StudyArea intersection; this endpoint never persists it."""
        _verify_surrounding_context_project(project_id)
        try:
            return context_repository.preview_design_area(request.geometry)
        except ContextDataError as exc:
            detail = str(exc)
            if "candidate" in detail.lower():
                raise HTTPException(status_code=422, detail=detail) from exc
            raise HTTPException(status_code=503, detail=f"StudyArea preview geometry is unavailable: {detail}") from exc

    @app.post("/api/v1/critic/evaluate")
    @serialize_store_access
    def evaluate_critic(req: CriticRequest) -> dict[str, Any]:
        """Evidence-bound AI critic inquiry endpoint."""
        if not req.evidence_card_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="select at least one current verified Evidence Card; unbounded baseline evidence is not used",
            )
        if source_catalog is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="critic StudyArea does not match the verified active source context",
            )
        try:
            catalog = current_verified_catalog()
            bundle, all_cards, evidence_status, bundle_sha, evidence_gaps = get_persisted_site_analysis(store, catalog.project_id, catalog)
            if bundle is None or evidence_status != "VERIFIED_SOURCE_RESULT_ALIGNMENT":
                raise EvidenceAlignmentError("current persisted Site Analysis is missing, stale, or blocked")
            if req.expected_study_area_id != catalog.study_area_id:
                raise EvidenceAlignmentError("critic StudyArea does not match the active source context")
            if req.expected_study_area_revision != bundle["scope"]["study_area_revision"]:
                raise EvidenceAlignmentError("critic request StudyArea revision is stale or missing")
            if req.expected_source_package_revision != catalog.package_revision:
                raise EvidenceAlignmentError("critic request source package revision is stale or missing")
            if req.expected_evidence_bundle_sha256 != bundle_sha:
                raise EvidenceAlignmentError("critic request Evidence Card bundle hash is stale or missing")
            workspace_id = service._workspace_id(catalog.project_id)
            current_workspace = service.get_workspace(workspace_id)
            if current_workspace is None:
                raise EvidenceAlignmentError("critic workspace is missing; synchronize and reload")
            if current_workspace.status == "STALE" or current_workspace.study_area_id != catalog.study_area_id:
                raise EvidenceAlignmentError("critic workspace context is stale or mismatched")
            if req.expected_workspace_id != current_workspace.workspace_id:
                raise EvidenceAlignmentError("critic workspace scope is stale or missing")
            if req.expected_workspace_revision != current_workspace.revision:
                raise EvidenceAlignmentError("critic workspace revision is stale or missing")
            model_run_project_id = getattr(provider, "model_run_project_id", None)
            if model_run_project_id is not None and model_run_project_id != catalog.project_id:
                raise EvidenceAlignmentError("critic ModelRun store is bound to a different project")
            cards = select_verified_cards(all_cards, req.evidence_card_ids or [])
            language_instruction = (
                "Respond entirely in English."
                if req.language == "en"
                else "請以繁體中文回答。"
            )
            response = SiteCriticService(provider=provider).generate_and_validate(
                study_area_id=catalog.study_area_id,
                evidence_bundle=cards,
                query=f"{req.prompt}\n\n{language_instruction}",
                workspace_id=current_workspace.workspace_id,
                workspace_revision=current_workspace.revision,
            )
        except (WorkspaceSourceError, EvidenceAlignmentError, CriticValidationError) as exc:
            raise HTTPException(status_code=422, detail=f"critic evidence gate blocked: {exc}") from exc
        payload = response.model_dump(mode="json")
        payload["workspace_id"] = current_workspace.workspace_id
        payload["workspace_revision"] = current_workspace.revision
        return payload

    @app.get("/api/v1/critic/status")
    def critic_status() -> dict[str, Any]:
        """Expose credential/configuration state without dispatching a model request."""
        project_authorized = os.environ.get("PROJECT_AI_AUTHORIZED", "").strip() == "1"
        return {
            "provider_name": provider.provider_name,
            "status": provider.status,
            "is_live_available": bool(provider.is_live_available) and project_authorized,
            "model": getattr(provider, "model_name", None),
            "request_dispatched": False,
            "live_request_authorized": project_authorized,
        }

    def model_profiles_status_payload() -> ModelProfilesStatusResponse:
        config = load_model_provider_config()
        weekly_calls_used = None
        accounting_available = False
        weekly_calls_query = getattr(provider, "weekly_calls_used", None)
        if callable(weekly_calls_query):
            try:
                used = weekly_calls_query()
                if isinstance(used, int) and not isinstance(used, bool) and used >= 0:
                    weekly_calls_used = used
                    accounting_available = True
            except Exception:
                weekly_calls_used = None
        project_authorized = os.environ.get("PROJECT_AI_AUTHORIZED", "").strip() == "1"
        if not project_authorized:
            dispatch_block_reason = "BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED"
        elif not accounting_available:
            dispatch_block_reason = "BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE"
        elif weekly_calls_used is not None and weekly_calls_used >= config.weekly_call_limit:
            dispatch_block_reason = "BLOCKED_BUDGET"
        elif not bool(getattr(provider, "is_live_available", False)):
            dispatch_block_reason = "BLOCKED_PROFILE_UNAVAILABLE"
        else:
            dispatch_block_reason = None
        live_dispatch_enabled = dispatch_block_reason is None
        return ModelProfilesStatusResponse(
            active_profile_id=app.state.active_model_profile_id,
            weekly_call_limit=config.weekly_call_limit,
            weekly_calls_used=weekly_calls_used,
            live_dispatch_enabled=live_dispatch_enabled,
            dispatch_block_reason=dispatch_block_reason,
            profiles=model_profiles.describe_model_profiles(
                config,
                active_profile_id=app.state.active_model_profile_id,
                weekly_calls_used=weekly_calls_used,
                project_ai_authorized=project_authorized,
                model_run_accounting_available=accounting_available,
            ),
        )

    @app.get("/api/v1/model-profiles/status", response_model=ModelProfilesStatusResponse)
    @serialize_store_access
    def model_profiles_status() -> ModelProfilesStatusResponse:
        """Return secret-free profile availability and current runtime selection."""
        return model_profiles_status_payload()

    @app.post("/api/v1/model-profiles/active", response_model=ModelProfilesStatusResponse)
    def select_active_model_profile(request: ActiveModelProfileSelectionRequest) -> ModelProfilesStatusResponse:
        """Persist the secret-free Ariadne profile selection without dispatching a model request."""
        config = load_model_provider_config()
        profile = next((item for item in config.profiles if item.id == request.profile_id), None)
        if profile is None:
            raise HTTPException(status_code=404, detail="model profile not found")
        if not profile.enabled:
            raise HTTPException(status_code=409, detail="model profile is disabled")
        if not profile.supports_json_schema:
            raise HTTPException(status_code=409, detail="model profile does not support Ariadne JSON Schema output")
        if profile.adapter == "cli_subprocess":
            if profile.cli_command is None or not model_profiles.cli_command_available(profile.cli_command):
                raise HTTPException(status_code=409, detail="model profile CLI is not installed")
            if not model_profiles.probe_cli_login(profile.cli_command):
                raise HTTPException(status_code=409, detail="model profile CLI is not logged in")
        select_provider_profile = getattr(provider, "set_active_profile", None)
        if callable(select_provider_profile):
            try:
                select_provider_profile(profile.id)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail="model profile has no configured dispatch adapter") from exc
        elif allow_live_critic or os.environ.get("PROJECT_AI_AUTHORIZED", "").strip() == "1":
            raise HTTPException(status_code=409, detail="configured live dispatch provider cannot apply profile selection")
        try:
            app.state.model_profile_selection_store.save(profile.id)
        except OSError as exc:
            raise HTTPException(status_code=500, detail="model profile selection could not be persisted") from exc
        app.state.active_model_profile_id = profile.id
        return model_profiles_status_payload()

    @app.get("/api/v1/projects/{project_id}/syntax/exploratory-figure.{extension}")
    @serialize_store_access
    def download_exploratory_syntax_figure(
        project_id: str = FPath(..., min_length=1),
        extension: str = FPath(..., pattern="^(svg|png)$"),
    ) -> Response:
        if extension == "png":
            raise HTTPException(
                status_code=409,
                detail="The frozen PNG still carries ambiguous segment count labels; only the count-labeled SVG is currently available.",
            )
        if source_catalog is None or project_id != source_catalog.project_id:
            raise HTTPException(status_code=404, detail="project has no verified Syntax evidence")
        try:
            catalog = current_verified_catalog()
            syntax_bundle = current_syntax_bundle(catalog)
            path = verified_figure_path(extension, catalog, syntax_bundle)
        except HTTPException:
            raise
        except (WorkspaceSourceError, EvidenceAlignmentError) as exc:
            raise HTTPException(status_code=503, detail=f"exploratory Syntax evidence is unavailable: {exc}") from exc
        return Response(
            content=count_clarified_svg(path, syntax_bundle),
            media_type="image/svg+xml",
            headers={
                "Content-Disposition": 'attachment; filename="rotterdam-m4h-800m-integration-exploratory.svg"',
                "X-Evidence-Status": "EXPLORATORY_ONLY_SOURCE_COVERAGE_INSUFFICIENT",
                "X-Formal-Result-Eligible": "false",
                "X-Study-Area-Id": catalog.study_area_id,
                "X-Source-Figure-SHA256": f"sha256:{sha256_file(path)}",
                "X-Rendered-Figure-Semantics": "week4-count-clarification-v1",
            },
        )

    @app.get("/api/v1/portfolio/baseline")
    def get_portfolio_baseline() -> dict[str, Any]:
        """Read-only endpoint returning portfolio original design baseline reference."""
        return {
            "title": "Rotterdam M4H Waterfront Circular District (Q2 Portfolio Original Design)",
            "designer": "Jack Hsieh",
            "provenance": "PORTFOLIO_ORIGINAL_BASELINE",
            "source_document": "urbanism-q2-portfolio.pdf",
            "baseline_metrics": {
                "far": {"value": 2.85, "unit": "ratio", "status": "PORTFOLIO_BASELINE_TARGET"},
                "max_height_m": {"value": 36.0, "unit": "m", "status": "PORTFOLIO_BASELINE_TARGET"},
                "coverage_ratio": {"value": 0.32, "unit": "ratio", "status": "PORTFOLIO_BASELINE_TARGET"},
                "open_space_ratio": {"value": 0.22, "unit": "ratio", "status": "PORTFOLIO_BASELINE_TARGET"},
                "waterfront_public_band_m": {"value": 15.0, "unit": "m", "status": "PORTFOLIO_BASELINE_TARGET"},
            },
            "spatial_principles": [
                "連續親水公共長廊（15m 水岸開放帶），維護港池開放視野",
                "工業遺產與既有大型倉庫（如 Gusto、Keilepand 意象）適應性再利用",
                "複合機能導向：創新產業工坊（maker spaces）與住商混合共融",
                "綠色藍色網絡滲透：透過線型綠帶連結內陸與馬斯河（Nieuwe Maas）水岸",
            ],
        }

    @app.get("/api/v1/projects/{project_id}/problems")
    def get_project_problems(
        project_id: str = FPath(..., min_length=1, max_length=128),
    ) -> dict[str, Any]:
        """Read-only endpoint returning defined spatial problems and statements."""
        candidate_dirs = [
            Path(__file__).resolve().parents[2] / "artifacts" / "w6-problem-definition",
            Path(__file__).resolve().parents[2] / "artifacts/w6-problem-definition",
        ]
        prob_dir = next((d for d in candidate_dirs if d.exists()), None)
        if prob_dir is None:
            raise HTTPException(status_code=404, detail="Problem definition artifacts not found")

        summary_file = prob_dir / "problem-summary.json"
        statements_file = prob_dir / "problem-statements.json"
        if not summary_file.exists() or not statements_file.exists():
            raise HTTPException(status_code=404, detail="Problem definition data files not found")

        summary_data = json.loads(summary_file.read_text(encoding="utf-8"))
        statements_data = json.loads(statements_file.read_text(encoding="utf-8"))
        return {
            "project_id": project_id,
            "status": "ANALYSIS_DEFINED",
            "summary": summary_data,
            "statements": statements_data.get("statements", []),
        }

    @app.get("/api/v1/projects/{project_id}/problems/{problem_id}")
    def get_project_problem_detail(
        project_id: str = FPath(..., min_length=1, max_length=128),
        problem_id: str = FPath(..., min_length=1, max_length=128),
    ) -> dict[str, Any]:
        """Read-only endpoint returning a single spatial problem definition and statement."""
        candidate_dirs = [
            Path(__file__).resolve().parents[2] / "artifacts" / "w6-problem-definition",
            Path(__file__).resolve().parents[2] / "artifacts/w6-problem-definition",
        ]
        prob_dir = next((d for d in candidate_dirs if d.exists()), None)
        if prob_dir is None:
            raise HTTPException(status_code=404, detail="Problem definition artifacts not found")

        statements_file = prob_dir / "problem-statements.json"
        if not statements_file.exists():
            raise HTTPException(status_code=404, detail="Problem statements file not found")

        statements_data = json.loads(statements_file.read_text(encoding="utf-8"))
        statement = next(
            (s for s in statements_data.get("statements", []) if s.get("problem_id") == problem_id),
            None,
        )
        if statement is None:
            raise HTTPException(status_code=404, detail=f"Problem {problem_id} not found")

        return {
            "project_id": project_id,
            "problem_id": problem_id,
            "statement": statement,
        }

    @app.get("/api/v1/projects/{project_id}/problems/{problem_id}/geojson")
    def get_project_problem_geojson(
        project_id: str = FPath(..., min_length=1, max_length=128),
        problem_id: str = FPath(..., min_length=1, max_length=128),
    ) -> dict[str, Any]:
        """Read-only endpoint returning GeoJSON feature collection for a spatial problem."""
        candidate_dirs = [
            Path(__file__).resolve().parents[2] / "artifacts" / "w6-problem-definition",
            Path(__file__).resolve().parents[2] / "artifacts/w6-problem-definition",
        ]
        prob_dir = next((d for d in candidate_dirs if d.exists()), None)
        if prob_dir is None:
            raise HTTPException(status_code=404, detail="Problem definition artifacts not found")

        file_map = {
            "prob-01-functional-monoculture": "problem_01_functional_monoculture.geojson",
            "prob-02-spatial-fragmentation": "problem_02_spatial_fragmentation.geojson",
            "prob-03-sociospatial-isolation": "problem_03_sociospatial_isolation.geojson",
            "prob-04-ecological-disconnection": "problem_04_ecological_disconnection.geojson",
            "prob-05-waterfront-inaccessibility": "problem_05_waterfront_inaccessibility.geojson",
            "prob-06-unclassified-residual-ground": "problem_06_unclassified_residual_ground.geojson",
        }
        filename = file_map.get(problem_id)
        if filename is None:
            raise HTTPException(status_code=404, detail=f"Unknown problem ID: {problem_id}")

        geojson_path = prob_dir / filename
        if not geojson_path.exists():
            raise HTTPException(status_code=404, detail=f"GeoJSON layer for {problem_id} not found")

        return json.loads(geojson_path.read_text(encoding="utf-8"))

    return app
