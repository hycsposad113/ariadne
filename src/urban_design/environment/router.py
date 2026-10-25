"""FastAPI router module for environmental simulation endpoints (W6-11 E1).

To be included in main api.py by integration owner (W6-2):
    from urban_design.environment.router import router as environment_router
    app.include_router(environment_router)
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union

from .comparison import IncompatibleComparisonError, compare_environmental_runs
from .contracts import (
    AnalysisPeriod,
    ComparisonResult,
    E1_PLAN_LABEL,
    E1_PLAN_REVISION,
    E1_PUBLIC_SPACE_DOMAIN_DEFINITION,
    E1ExperimentPlan,
    E1PipelineRunResult,
    GroundGridDefinition,
    Obstacle,
    SiteLocation,
)
from .geometry_adapter import (
    UnknownRetainedHeightError,
    compute_grid_convergence_deg,
    formal_scenario_geojson_to_environment,
    footprint_to_obstacle,
    supplement_missing_domain_features,
    verify_geometry_roundtrip,
)
from .pipeline import run_e1_environment_pipeline
from .sunlight import (
    RadianceExecutionError,
    create_sunlight_colormap_spec,
    get_rotterdam_m4h_demo_location,
    verify_radiance_runtime,
)
from ..store import EntityNotFoundError

router = APIRouter(prefix="/api/environment", tags=["environment"])


class RuntimeStatusResponse(BaseModel):
    radiance_available: bool
    radiance_version: str | None = None
    radiance_reason: str | None = None
    ladybug_available: bool = True
    engine: str = "ladybug-sunpath+ladybug-radiance"
    engine_available: bool = True
    fallback_reason: str | None = None
    default_timezone: str = "Europe/Amsterdam"
    grid_convergence_m4h_deg: float


class E1SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = "rotterdam-m4h-pilot-project"
    baseline_scenario_id: str = Field(min_length=1)
    modified_scenario_id: str = Field(min_length=1)
    plan_artifact_id: str | None = None


def _polygonal_overlap(first: Any, second: Any) -> Polygon | MultiPolygon | GeometryCollection:
    overlap = first.intersection(second)
    if overlap.geom_type != "GeometryCollection":
        return overlap
    polygon_parts = [
        part
        for part in overlap.geoms
        if isinstance(part, (Polygon, MultiPolygon)) and part.area > 0.0
    ]
    return unary_union(polygon_parts) if polygon_parts else GeometryCollection()


def get_default_draft_plan() -> E1ExperimentPlan:
    """Return the visible, unapproved E1 proposal; values remain Founder-editable."""
    location = SiteLocation(
        latitude=51.90,
        longitude=4.45,
        elevation=0.0,
        timezone="Europe/Amsterdam",
        location_tag="ROTTERDAM_E1_DRAFT_LOCATION",
    )
    gamma = compute_grid_convergence_deg(location.longitude, location.latitude)
    analysis_dates = [date(2026, 3, 21), date(2026, 6, 21), date(2026, 12, 21)]
    return E1ExperimentPlan(
        plan_id="e1-plan-rotterdam-domain-founder-20261004",
        name="Rotterdam sunlight and shadow plan (draft)",
        status="DRAFT_UNAPPROVED",
        period=AnalysisPeriod(
            start_date=analysis_dates[0],
            end_date=analysis_dates[-1],
            dates=analysis_dates,
            start_hour=8.0,
            end_hour=18.0,
            timestep=4,
        ),
        location=location,
        grid_definition=GroundGridDefinition(
            origin_x=0.0,
            origin_y=0.0,
            spacing_m=5.0,
            crs="EPSG:28992",
            tag="E1_PLAN_DRAFT_UNAPPROVED",
        ),
        baseline_scenario_id=None,
        modified_scenario_id=None,
        accuracy_rule="15-minute direct-sun sampling; 5 m ground sensor spacing; 0.05 m sensor offset",
        true_north_offset_deg=gamma,
        comparison_domain=E1_PUBLIC_SPACE_DOMAIN_DEFINITION,
        notes=(
            f"{E1_PLAN_LABEL}; plan status remains DRAFT_UNAPPROVED. The Founder selected the public-space domain; "
            "dates, time window, sensor grid, and resolution remain unapproved pending formal plan approval."
        ),
    )


def get_default_fixture_plan() -> E1ExperimentPlan:
    """Return default E1 Experiment Plan for Rotterdam M4H in FIXTURE_ONLY mode."""
    loc = get_rotterdam_m4h_demo_location()
    gamma = compute_grid_convergence_deg(loc.longitude, loc.latitude)
    return E1ExperimentPlan(
        plan_id="e1-plan-m4h-fixture",
        name="Rotterdam M4H Midsummer Direct Sunlight (Fixture)",
        status="FIXTURE_ONLY",
        period=AnalysisPeriod(
            start_date=date(2026, 6, 21),
            end_date=date(2026, 6, 21),
            start_hour=8.0,
            end_hour=18.0,
            timestep=4,
        ),
        location=loc,
        grid_definition=GroundGridDefinition(
            origin_x=0.0,
            origin_y=0.0,
            spacing_m=5.0,
            crs="EPSG:28992",
            tag="FIXTURE_ONLY",
        ),
        baseline_scenario_id="scenario-baseline",
        modified_scenario_id="scenario-proposal-m4h",
        accuracy_rule="timestep=4, surface_offset=0.05m, spacing=5.0m",
        true_north_offset_deg=gamma,
        notes="Fixture execution for development and testing. Real design acceptance requires Founder approval.",
    )


def get_default_unapproved_plan() -> E1ExperimentPlan:
    """Return official E1 Experiment Plan requiring Founder approval (BLOCKED by default)."""
    loc = get_rotterdam_m4h_demo_location()
    gamma = compute_grid_convergence_deg(loc.longitude, loc.latitude)
    return E1ExperimentPlan(
        plan_id="e1-plan-m4h-official",
        name="Rotterdam M4H Official Direct Sunlight Experiment Plan",
        status="PENDING_FOUNDER_APPROVAL",
        period=AnalysisPeriod(
            start_date=date(2026, 6, 21),
            end_date=date(2026, 6, 21),
            start_hour=8.0,
            end_hour=18.0,
            timestep=4,
        ),
        location=loc,
        grid_definition=GroundGridDefinition(
            origin_x=0.0,
            origin_y=0.0,
            spacing_m=5.0,
            crs="EPSG:28992",
            tag="OFFICIAL_DESIGN_DRAFT",
        ),
        baseline_scenario_id="scenario-baseline",
        modified_scenario_id="scenario-proposal-m4h",
        accuracy_rule="timestep=4, surface_offset=0.05m, spacing=5.0m",
        true_north_offset_deg=gamma,
        notes="Founder approval required for official design evaluation.",
    )


@router.get("/runtimes", response_model=RuntimeStatusResponse)
def get_runtime_status() -> RuntimeStatusResponse:
    """Report manifest-verified Radiance availability and the selected E1 engine."""
    radiance = verify_radiance_runtime()
    loc = get_default_draft_plan().location
    gamma = compute_grid_convergence_deg(loc.longitude, loc.latitude)
    engine = (
        "ladybug-sunpath+ladybug-radiance"
        if radiance.available
        else "ladybug-sunpath+python-raycast"
    )
    return RuntimeStatusResponse(
        radiance_available=radiance.available,
        radiance_version=radiance.version,
        radiance_reason=radiance.reason,
        ladybug_available=True,
        engine=engine,
        engine_available=True,
        fallback_reason=None if radiance.available else radiance.reason,
        default_timezone="Europe/Amsterdam",
        grid_convergence_m4h_deg=gamma,
    )


@router.get("/e1/plan", response_model=E1ExperimentPlan)
def get_e1_plan(mode: Literal["draft", "official", "fixture"] = "draft") -> E1ExperimentPlan:
    """Retrieve the explicit draft, pending official plan, or isolated fixture plan."""
    if mode == "draft":
        return get_default_draft_plan()
    if mode == "fixture":
        return get_default_fixture_plan()
    return get_default_unapproved_plan()


def _formal_scenario_environment(
    store: Any,
    scenario_id: str,
    project_id: str,
    approved_inputs_cache: dict[str, Any] | None = None,
) -> tuple[Any, Any, dict[str, Any], Any, dict[str, Any]]:
    try:
        scenario = store.current(scenario_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail="FORMAL_SCENARIO_NOT_FOUND") from exc
    if scenario.entity_type not in {"Scenario", "DesignScenario"} or scenario.project_id != project_id:
        raise HTTPException(status_code=409, detail="FORMAL_SCENARIO_PROJECT_OR_TYPE_MISMATCH")

    record = scenario.payload
    generator = str(record.get("generator", ""))
    if not generator.startswith("formal-dictionary-"):
        raise HTTPException(status_code=409, detail="SCENARIO_IS_NOT_A_FORMAL_PROPOSAL")
    if str(record.get("status", "")).lower() in {"rejected", "stale", "blocked"}:
        raise HTTPException(status_code=409, detail="SCENARIO_STATUS_NOT_ELIGIBLE_FOR_ANALYSIS")
    if record.get("parameters", {}).get("validation", {}).get("valid") is not True:
        raise HTTPException(status_code=409, detail="FORMAL_SCENARIO_GEOMETRY_IS_NOT_VALIDATED")

    artifact_id = record.get("geometry_artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id:
        raise HTTPException(status_code=409, detail="FORMAL_SCENARIO_GEOMETRY_ARTIFACT_MISSING")
    try:
        artifact_record = store.current(artifact_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=409, detail="FORMAL_SCENARIO_GEOMETRY_ARTIFACT_MISSING") from exc
    artifact = artifact_record.payload
    if (
        artifact_record.entity_type != "Artifact"
        or artifact_record.project_id != project_id
        or artifact.get("project_id") != project_id
        or artifact.get("crs") != "EPSG:28992"
        or artifact.get("mime") != "application/geo+json"
        or artifact.get("sha256") != record.get("geometry_sha256")
    ):
        raise HTTPException(status_code=409, detail="FORMAL_SCENARIO_GEOMETRY_ARTIFACT_CONTRACT_FAILED")
    try:
        raw = Path(str(artifact["uri"])).read_bytes()
    except (KeyError, OSError) as exc:
        raise HTTPException(status_code=409, detail="FORMAL_SCENARIO_GEOMETRY_UNAVAILABLE") from exc
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if digest != artifact.get("sha256"):
        raise HTTPException(status_code=409, detail="FORMAL_SCENARIO_GEOMETRY_HASH_MISMATCH")
    try:
        geometry_doc = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail="FORMAL_SCENARIO_GEOMETRY_JSON_INVALID") from exc

    roles = {
        feature.get("properties", {}).get("role")
        for feature in geometry_doc.get("features", [])
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict)
    }
    domain_sources: dict[str, Any] = {"site_area": "scenario_artifact", "water": "scenario_artifact"}
    if "site_area" not in roles or "water" not in roles:
        cache = approved_inputs_cache if approved_inputs_cache is not None else {}
        if "inputs" not in cache:
            from urban_design.approved_generation import ApprovedGenerationBlocked, _load_approved_inputs

            try:
                cache["inputs"] = _load_approved_inputs(store, project_id, site_generation=True)
            except ApprovedGenerationBlocked as exc:
                raise HTTPException(
                    status_code=409,
                    detail="FORMAL_DOMAIN_INPUTS_UNAVAILABLE: " + "; ".join(exc.missing),
                ) from exc
        inputs = cache["inputs"]
        geometry_doc, domain_sources = supplement_missing_domain_features(
            geometry_doc,
            site_area=None if "site_area" in roles else inputs.design_area,
            water=None if "water" in roles else inputs.water_geometry,
            site_properties={
                "workspace_id": inputs.workspace.workspace_id,
                "workspace_revision": inputs.workspace.revision,
                "workspace_payload_digest": inputs.workspace.payload_digest,
            },
            water_properties={"water_artifact_ids": ",".join(inputs.water_artifact_ids)},
        )
        domain_sources.update({
            "workspace_id": inputs.workspace.workspace_id,
            "workspace_revision": inputs.workspace.revision,
            "workspace_payload_digest": inputs.workspace.payload_digest,
            "water_artifact_ids": list(inputs.water_artifact_ids),
            "approved_inputs_hash": inputs.input_hash,
        })

    floor_estimates = record.get("parameters", {}).get("floor_estimates", [])
    try:
        environment_geometry = formal_scenario_geojson_to_environment(
            geometry_doc,
            floor_estimates=floor_estimates if isinstance(floor_estimates, list) else (),
        )
    except UnknownRetainedHeightError:
        raise
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"FORMAL_SCENARIO_GEOMETRY_INVALID: {exc}") from exc
    return scenario, artifact_record, geometry_doc, environment_geometry, domain_sources


def _approved_handler(store):
    """Re-check the bound plan hash, then run the same formal comparison."""

    def run(job, staging, token):
        from .plan_service import RESULT_NAME, approved_plan, verify_scenario_inputs, write_e1_job_manifest

        if token.cancelled:
            raise ValueError("cancelled")
        body = job.request
        loaded = approved_plan(store, body["plan_artifact_id"], body["project_id"])
        if loaded.decision_id != body["decision_id"] or loaded.sha256 != job.input_refs[0]["sha256"]:
            raise ValueError("PLAN_APPROVAL_HASH_MISMATCH")
        if (
            loaded.plan.baseline_scenario_id != body["baseline_scenario_id"]
            or loaded.plan.modified_scenario_id != body["modified_scenario_id"]
        ):
            raise ValueError("APPROVED_PLAN_SCENARIO_PAIR_MISMATCH")
        verify_scenario_inputs(store, loaded.plan, body["project_id"])
        plan = loaded.plan.model_copy(update={
            "status": "APPROVED",
            "founder_decision_id": loaded.decision_id,
            "founder_approval_ref": loaded.decision_id,
        })
        approved_request = E1SimulateRequest(
            project_id=body["project_id"],
            baseline_scenario_id=body["baseline_scenario_id"],
            modified_scenario_id=body["modified_scenario_id"],
            plan_artifact_id=body["plan_artifact_id"],
        )
        from urban_design.generation.job_runner import PostDispatchOutcomeUnknown
        try:
            result = _execute_formal_e1(approved_request, store, plan)
        except (ConnectionError, TimeoutError) as exc:
            # Preflight failures above are known refusals. A lost transport at
            # this calculation boundary may have executed; retain and reconcile.
            raise PostDispatchOutcomeUnknown("E1_OUTCOME_UNKNOWN_POST_DISPATCH") from exc
        payload = result.model_dump(mode="json")
        payload.setdefault("metadata", {})["e1_job_id"] = job.job_id
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        (Path(staging) / RESULT_NAME).write_bytes(raw)
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        return write_e1_job_manifest(staging, job, digest, len(raw))

    return run


def _simulate_approved(req: E1SimulateRequest, request: Request, store) -> E1PipelineRunResult:
    from .plan_service import RESULT_NAME, PlanNotApproved, STAGE, approved_plan, open_e1_jobs, verify_scenario_inputs

    try:
        loaded = approved_plan(store, req.plan_artifact_id or "", req.project_id)
    except PlanNotApproved as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    if (
        loaded.plan.baseline_scenario_id != req.baseline_scenario_id
        or loaded.plan.modified_scenario_id != req.modified_scenario_id
    ):
        raise HTTPException(status_code=409, detail="APPROVED_PLAN_SCENARIO_PAIR_MISMATCH")
    try:
        verify_scenario_inputs(store, loaded.plan, req.project_id)
    except PlanNotApproved as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    if not verify_radiance_runtime().available:
        raise HTTPException(status_code=409, detail="RADIANCE_REQUIRED_FOR_APPROVED_PLAN")
    jobs, runner, output_root = open_e1_jobs(
        store,
        getattr(request.app.state, "e1_job_database", None),
        _approved_handler(store),
    )
    job, _created = jobs.enqueue(
        project_id=req.project_id,
        idempotency_key=f"e1:{loaded.sha256}:{loaded.decision_id}:{req.baseline_scenario_id}:{req.modified_scenario_id}",
        stage=STAGE,
        request={
            "plan_artifact_id": loaded.artifact_id,
            "project_id": req.project_id,
            "baseline_scenario_id": req.baseline_scenario_id,
            "modified_scenario_id": req.modified_scenario_id,
            "decision_id": loaded.decision_id,
        },
        input_refs=[{"id": loaded.artifact_id, "sha256": loaded.sha256, "kind": "e1_experiment_plan"}],
        expected_revision=loaded.revision,
    )
    def revision_is_current(_job):
        try:
            current = approved_plan(store, loaded.artifact_id, req.project_id)
            verify_scenario_inputs(store, current.plan, req.project_id)
            return (current.revision, current.sha256, current.decision_id) == (loaded.revision, loaded.sha256, loaded.decision_id)
        except PlanNotApproved:
            return False
    runner.revision_is_current = revision_is_current
    finished = runner.run(job.job_id)
    try:
        current = approved_plan(store, loaded.artifact_id, req.project_id)
        if current.decision_id != loaded.decision_id:
            raise PlanNotApproved("E1_PROMOTION_DECISION_CHANGED")
    except PlanNotApproved as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    if finished.status.value != "READY":
        raise HTTPException(status_code=409, detail=f"E1_JOB_{finished.status.value}:{finished.error_code or ''}")
    payload = json.loads((output_root / finished.job_id / RESULT_NAME).read_bytes())
    return E1PipelineRunResult.model_validate(payload)


@router.post("/e1/simulate", response_model=E1PipelineRunResult)
def simulate_e1(req: E1SimulateRequest, request: Request) -> E1PipelineRunResult:
    """Run a provisional comparison, or a hash-bound approved plan when one is named."""
    if req.baseline_scenario_id == req.modified_scenario_id:
        raise HTTPException(status_code=422, detail="BASELINE_AND_MODIFIED_SCENARIOS_MUST_DIFFER")
    store = getattr(request.app.state, "project_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="PROJECT_STATE_STORE_UNAVAILABLE")
    if req.plan_artifact_id:
        return _simulate_approved(req, request, store)

    plan = get_default_draft_plan().model_copy(update={
        "baseline_scenario_id": req.baseline_scenario_id,
        "modified_scenario_id": req.modified_scenario_id,
    })
    return _execute_formal_e1(req, store, plan)


def _execute_formal_e1(req: E1SimulateRequest, store, plan: E1ExperimentPlan) -> E1PipelineRunResult:
    """Score persisted formal geometry. Draft and approved callers share this path."""
    try:
        approved_inputs_cache: dict[str, Any] = {}
        baseline = _formal_scenario_environment(
            store, req.baseline_scenario_id, req.project_id, approved_inputs_cache,
        )
        modified = _formal_scenario_environment(
            store, req.modified_scenario_id, req.project_id, approved_inputs_cache,
        )
    except UnknownRetainedHeightError as exc:
        return E1PipelineRunResult(
            run_id=f"e1_blocked_{uuid.uuid4().hex[:12]}",
            status="BLOCKED",
            blocked_reason=f"RETAINED_BUILDING_HEIGHT_UNKNOWN: {exc}",
            plan=plan,
            engine="NOT_RUN",
            metadata={
                "E1_PLAN": E1_PLAN_REVISION if plan.status == "DRAFT_UNAPPROVED" else plan.status,
                "plan_status": plan.status,
                "blocked_at": "formal_geometry_validation",
                "blocked_building_id": exc.building_id,
            },
        )
    common_open_space = _polygonal_overlap(
        baseline[3].public_open_space,
        modified[3].public_open_space,
    )
    if (
        common_open_space.is_empty
        or not common_open_space.is_valid
        or common_open_space.geom_type not in {"Polygon", "MultiPolygon"}
    ):
        raise HTTPException(status_code=409, detail="COMMON_PUBLIC_OPEN_SPACE_DOMAIN_UNAVAILABLE")

    radiance = verify_radiance_runtime()
    if plan.status == "APPROVED" and not radiance.available:
        raise HTTPException(status_code=409, detail="RADIANCE_REQUIRED_FOR_APPROVED_PLAN")
    chosen_method: Literal["ladybug_radiance", "pure_python_box_ray"] = (
        "ladybug_radiance" if radiance.available else "pure_python_box_ray"
    )
    excluded_obstacles = {
        "baseline": baseline[3].excluded_obstacles,
        "modified": modified[3].excluded_obstacles,
    }
    pipeline_inputs = {
        "plan": plan,
        "baseline_geometry": baseline[3].obstacles,
        "modified_geometry": modified[3].obstacles,
        "boundary_polygon": common_open_space,
        "baseline_domain": baseline[3].public_open_space,
        "modified_domain": modified[3].public_open_space,
        "store": store,
        "project_id": req.project_id,
        "input_scenario_ids": (req.baseline_scenario_id, req.modified_scenario_id),
        "input_artifact_ids": (baseline[1].entity_id, modified[1].entity_id),
        "input_artifact_hashes": (baseline[1].payload["sha256"], modified[1].payload["sha256"]),
        "excluded_obstacles_by_scenario": excluded_obstacles,
        "domain_sources": {"baseline": baseline[4], "modified": modified[4]},
    }

    if plan.status == "APPROVED":
        from .plan_service import approved_plan, PlanNotApproved, verify_scenario_inputs
        def authority_check():
            current = approved_plan(store, req.plan_artifact_id, req.project_id)
            if current.decision_id != plan.founder_decision_id:
                raise PlanNotApproved("E1_PROMOTION_DECISION_CHANGED")
            verify_scenario_inputs(store, current.plan, req.project_id)
        pipeline_inputs["authority_check"] = authority_check

    def selected_engine_info(
        method: Literal["ladybug_radiance", "pure_python_box_ray"],
        fallback_reason: str | None,
    ) -> dict[str, Any]:
        return {
            "requested_engine": "ladybug-sunpath+ladybug-radiance",
            "selected_engine": (
                "ladybug-sunpath+ladybug-radiance"
                if method == "ladybug_radiance"
                else "ladybug-sunpath+python-raycast"
            ),
            "radiance_manifest_version": radiance.version,
            "fallback_reason": fallback_reason,
        }

    if chosen_method == "pure_python_box_ray":
        return run_e1_environment_pipeline(
            **pipeline_inputs,
            method=chosen_method,
            engine_selection=selected_engine_info(chosen_method, radiance.reason),
        )

    def run_python_fallback(reason: str) -> E1PipelineRunResult:
        if plan.status == "APPROVED":
            raise HTTPException(status_code=409, detail="RADIANCE_REQUIRED_FOR_APPROVED_PLAN")
        return run_e1_environment_pipeline(
            **pipeline_inputs,
            method="pure_python_box_ray",
            engine_selection=selected_engine_info("pure_python_box_ray", reason),
        )

    try:
        result = run_e1_environment_pipeline(
            **pipeline_inputs,
            method=chosen_method,
            cross_check_method="pure_python_box_ray",
            engine_selection=selected_engine_info(chosen_method, None),
        )
    except RadianceExecutionError as exc:
        return run_python_fallback(f"{type(exc).__name__}: {exc}")
    if result.status == "BLOCKED" and (result.blocked_reason or "").startswith("RUNTIME_NOT_AVAILABLE:"):
        return run_python_fallback(result.blocked_reason or "RADIANCE_RUNTIME_NOT_AVAILABLE")
    return result


@router.post("/e1/compare", response_model=ComparisonResult)
def compare_runs(payload: dict[str, Any]) -> ComparisonResult:
    """Perform strict within-method comparison between two runs."""
    base_run = payload.get("baseline_run", {})
    mod_run = payload.get("modified_run", {})
    try:
        return compare_environmental_runs(base_run, mod_run, raise_on_incompatible=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/e1/demo-fixtures")
def get_demo_fixtures() -> dict[str, Any]:
    """Retrieve verified geometry fixtures (asymmetric, unobstructed, winter, summer)."""
    loc = get_rotterdam_m4h_demo_location()
    gamma = compute_grid_convergence_deg(loc.longitude, loc.latitude)

    # Asymmetric L-shaped building
    l_shaped_footprint = [
        (0.0, 0.0),
        (30.0, 0.0),
        (30.0, 15.0),
        (15.0, 15.0),
        (15.0, 35.0),
        (0.0, 35.0),
    ]
    roundtrip = verify_geometry_roundtrip(l_shaped_footprint, height_m=18.0)

    return {
        "location": loc.model_dump(),
        "true_north_grid_convergence_deg": gamma,
        "asymmetric_l_shaped_footprint": l_shaped_footprint,
        "asymmetric_roundtrip_verification": roundtrip,
        "colormap_spec": create_sunlight_colormap_spec(max_hours=10.0, num_bins=5).model_dump(),
        "disclaimer": "位置示範，非分析結果 (DEMO_LOCATION_NOT_ANALYSIS_RESULT)",
    }
