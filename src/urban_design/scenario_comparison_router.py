"""Standalone router for formal scenario comparison and human baseline decision."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictStr, field_validator

from .decision_key import DecisionKeyUnavailable, default_key_path, verify_decision_key_strict
from .models import ActorKind, DecisionAction, HumanDecision, HumanStatus
from .scenario_comparison import build_scenario_comparison
from .store import EntityNotFoundError, PayloadError, ProjectStateStore


class ScenarioComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_ids: list[StrictStr] = Field(..., min_length=2)


class ScenarioComparisonDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: StrictStr = Field(..., min_length=1)
    scenario_ids: list[StrictStr] = Field(..., min_length=2)
    accepted_scenario_id: StrictStr = Field(..., min_length=1)
    acceptance_reason: StrictStr = Field(..., min_length=1, max_length=2000)
    rejected_reasons: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    decision_key: SecretStr
    actor_session_id: StrictStr = Field(..., min_length=1, max_length=128)


class ScenarioReconsiderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: StrictStr = Field(min_length=1)
    scenario_id: StrictStr = Field(min_length=1)
    target_version: StrictStr = Field(min_length=1)
    target_geometry_sha256: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reason: StrictStr = Field(min_length=1, max_length=2000)
    decision_key: SecretStr
    actor_session_id: StrictStr = Field(min_length=1, max_length=128)
    @field_validator("project_id", "scenario_id", "target_version", "reason", "actor_session_id")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Reconsider fields must not be blank")
        return value.strip()


def _load_scenario_records(store: ProjectStateStore, scenario_ids: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for scenario_id in scenario_ids:
        try:
            record = store.current(scenario_id)
        except EntityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"scenario {scenario_id!r} was not found") from exc
        if record.entity_type != "DesignScenario":
            raise HTTPException(status_code=404, detail=f"scenario {scenario_id!r} was not found")

        parameters = record.payload.get("parameters", {})
        basis = parameters.get("comparison_basis", {})
        raw_metrics = parameters.get("metrics", {})
        if not isinstance(raw_metrics, Mapping):
            raw_metrics = {}

        from .decision_resolution import resolve_record_decision
        resolution = resolve_record_decision(store, record, record.payload.get("geometry_sha256"), "target_geometry_sha256")
        latest_decision = dict(resolution.decision.payload) if resolution.status == "EFFECTIVE" else None
        scenario_status = record.payload.get("status", "proposed")
        is_baseline = resolution.status == "EFFECTIVE" and resolution.reason == "Accept" and scenario_status == "accepted"
        rejection_reason = record.payload.get("rejection_reason")
        baseline_reason = record.payload.get("baseline_reason") if is_baseline else None
        validation = parameters.get("validation", {})
        is_valid = validation.get("valid", True)
        failure_reasons = validation.get("failure_reasons", [])

        # Spatial denominator hash:
        denom_hash = basis.get("denominator_hash")
        denom_label = raw_metrics.get("far_denominator") or basis.get("denominator_label")
        denom_m2 = raw_metrics.get("far_denominator_m2") or basis.get("denominator_area_m2")
        if not denom_hash and denom_label is not None and denom_m2 is not None:
            denom_hash = "sha256:" + hashlib.sha256(f"{denom_label}:{denom_m2}".encode()).hexdigest()

        # Rules version:
        rules_v = (
            basis.get("rules_version")
            or record.payload.get("generator_version")
            or parameters.get("recipe_version")
            or record.payload.get("generator")
        )

        normalized_metrics: dict[str, Any] = {}

        # 1. FAR
        far_val = raw_metrics.get("far")
        if isinstance(far_val, Mapping):
            normalized_metrics["far"] = far_val
        elif far_val is not None:
            normalized_metrics["far"] = {
                "value": float(far_val),
                "unit": "ratio",
                "method": "formal-pipeline",
                "validation_status": "VALIDATED" if is_valid else "INVALID",
                "denominator_label": denom_label or "land_area",
                "denominator_area_m2": denom_m2,
            }

        # 2. Coverage
        cov_val = raw_metrics.get("coverage_ratio") if "coverage_ratio" in raw_metrics else raw_metrics.get("coverage")
        if isinstance(cov_val, Mapping):
            normalized_metrics["coverage_ratio"] = cov_val
        elif cov_val is not None:
            normalized_metrics["coverage_ratio"] = {
                "value": float(cov_val),
                "unit": "ratio",
                "method": "formal-pipeline",
                "validation_status": "VALIDATED" if is_valid else "INVALID",
            }

        # 3. Height
        h_val = raw_metrics.get("height_m") if "height_m" in raw_metrics else raw_metrics.get("highest_new_height_m")
        if isinstance(h_val, Mapping):
            normalized_metrics["height_m"] = h_val
        elif h_val is not None:
            normalized_metrics["height_m"] = {
                "value": float(h_val),
                "unit": "m",
                "method": "formal-pipeline",
                "validation_status": "VALIDATED" if is_valid else "INVALID",
            }

        # 4. Open space ratio
        osr_val = raw_metrics.get("open_space_ratio")
        if isinstance(osr_val, Mapping):
            normalized_metrics["open_space_ratio"] = osr_val
        elif osr_val is not None:
            normalized_metrics["open_space_ratio"] = {
                "value": float(osr_val),
                "unit": "ratio",
                "method": "formal-pipeline",
                "validation_status": "VALIDATED" if is_valid else "INVALID",
            }

        # 5. Road ratio
        road_val = raw_metrics.get("road_ratio")
        if isinstance(road_val, Mapping):
            normalized_metrics["road_ratio"] = road_val
        elif road_val is not None:
            normalized_metrics["road_ratio"] = {
                "value": float(road_val),
                "unit": "ratio",
                "method": "formal-pipeline",
                "validation_status": "VALIDATED" if is_valid else "INVALID",
            }
        else:
            c_num = normalized_metrics.get("coverage_ratio", {}).get("value")
            o_num = normalized_metrics.get("open_space_ratio", {}).get("value")
            if c_num is not None and o_num is not None:
                derived = max(0.0, round(1.0 - float(c_num) - float(o_num), 4))
                normalized_metrics["road_ratio"] = {
                    "value": derived,
                    "unit": "ratio",
                    "method": "formal-pipeline",
                    "validation_status": "VALIDATED" if is_valid else "INVALID",
                }

        # Program uses (if any)
        prog = raw_metrics.get("program_gfa_m2")
        if isinstance(prog, Mapping) and prog:
            tot = sum(float(v) for v in prog.values() if isinstance(v, (int, float)))
            if tot > 0:
                for use, area in prog.items():
                    if isinstance(area, (int, float)):
                        normalized_metrics[f"use_ratio:{use.lower()}"] = {
                            "value": round(float(area) / tot, 4),
                            "unit": "ratio",
                            "method": "formal-pipeline",
                            "validation_status": "VALIDATED" if is_valid else "INVALID",
                        }

        # Preserve any other mapping metrics
        for k, v in raw_metrics.items():
            if k not in normalized_metrics and isinstance(v, Mapping):
                normalized_metrics[k] = v

        records.append({
            "scenario_id": scenario_id,
            "project_id": record.project_id,
            "site_id": record.payload.get("site_id"),
            "constraint_set_id": record.payload.get("constraint_set_id"),
            "revision": record.revision,
            "status": scenario_status,
            "is_baseline": is_baseline,
            "rejection_reason": rejection_reason,
            "baseline_reason": baseline_reason,
            "strategy_id": parameters.get("strategy_id") or parameters.get("recipe_id") or record.payload.get("morphology_family"),
            "strategy_label": parameters.get("strategy_label") or parameters.get("recipe_id") or scenario_id,
            "geometry_sha256": record.payload.get("geometry_sha256"),
            "provenance": parameters.get("provenance", "UNKNOWN"),
            "valid": is_valid,
            "failure_reasons": failure_reasons,
            "denominator_hash": denom_hash,
            "rules_version": rules_v,
            "syntax_layer_version": basis.get("syntax_layer_version"),
            "syntax_method_version": basis.get("syntax_method_version"),
            "metrics": normalized_metrics,
            "syntax_statuses": parameters.get("syntax_statuses", {}),
            "latest_decision": latest_decision,
        })
    return records


def create_scenario_comparison_router(
    store: ProjectStateStore,
    decision_key_path: str | Path | None = None,
    decision_attempt_limiter: Any | None = None,
) -> APIRouter:
    router = APIRouter(tags=["Scenario Comparison"])

    limiter = decision_attempt_limiter
    if limiter is None:
        try:
            from .api import DecisionAttemptLimiter
            limiter = DecisionAttemptLimiter()
        except Exception:
            limiter = None

    def _resolve_key_path() -> Path | None:
        if decision_key_path is not None:
            return Path(decision_key_path)
        return default_key_path()

    @router.post("/api/v1/scenarios/reconsider", status_code=201)
    def reconsider_scenario(body: ScenarioReconsiderRequest, request: Request):
        remote = request.client.host if request.client else "unknown"
        if not limiter.begin_attempt(remote):
            raise HTTPException(status_code=429, detail="Decision key attempts are temporarily rate-limited")
        secret = body.decision_key.get_secret_value()
        try:
            valid = verify_decision_key_strict(secret, path=_resolve_key_path())
        except DecisionKeyUnavailable:
            limiter.finish_attempt(remote, failed=False)
            raise HTTPException(status_code=423, detail="Decision key unavailable") from None
        limiter.finish_attempt(remote, failed=not valid)
        if not valid:
            raise HTTPException(status_code=403, detail="Decision key is incorrect")
        decision = HumanDecision(
            id=f"decision-{uuid.uuid4().hex}", project_id=body.project_id,
            target_id=body.scenario_id, target_type="DesignScenario", target_version=body.target_version,
            target_geometry_sha256=body.target_geometry_sha256,
            action=DecisionAction.RECONSIDER, status=HumanStatus.NOT_REVIEWED,
            actor="designer", actor_kind=ActorKind.HUMAN_UI, actor_session_id=body.actor_session_id,
            reason=body.reason, timestamp=datetime.now(timezone.utc))
        try:
            store.record_human_decision(decision, decision_key=secret, decision_key_path=_resolve_key_path())
        except (PayloadError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "proposed", "scenario_id": body.scenario_id, "decision_id": decision.id,
                "revision": store.current(body.scenario_id).revision}

    @router.post("/api/v1/scenarios/comparison")
    def compare_scenarios(request: ScenarioComparisonRequest) -> dict[str, Any]:
        """Perform deterministic comparison without overall ranking or default winner."""
        if len(request.scenario_ids) != len(set(request.scenario_ids)):
            raise HTTPException(status_code=422, detail="scenario identifiers must be unique")

        records = _load_scenario_records(store, request.scenario_ids)
        try:
            return build_scenario_comparison(records)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post(
        "/api/v1/scenarios/comparison/decision",
        status_code=status.HTTP_201_CREATED,
    )
    def submit_comparison_decision(
        request: ScenarioComparisonDecisionRequest,
        http_request: Request,
    ) -> dict[str, Any]:
        """Record HumanDecision accepting one proposal as baseline and rejecting other proposals."""
        if request.accepted_scenario_id not in request.scenario_ids:
            raise HTTPException(
                status_code=422,
                detail=f"accepted_scenario_id {request.accepted_scenario_id!r} must be in scenario_ids list",
            )

        if not request.acceptance_reason.strip():
            raise HTTPException(
                status_code=422,
                detail="Baseline acceptance reason cannot be empty",
            )

        rejected_ids = [sid for sid in request.scenario_ids if sid != request.accepted_scenario_id]
        missing_reasons = [
            sid for sid in rejected_ids
            if not request.rejected_reasons.get(sid, "").strip()
        ]
        if missing_reasons:
            raise HTTPException(
                status_code=422,
                detail=f"Every unselected proposal must have an explicit human rejection reason. Missing: {', '.join(missing_reasons)}",
            )

        # Check existing accepted baseline in project
        existing_scenarios = store.list_current("Scenario", project_id=request.project_id)
        for s in existing_scenarios:
            s_status = (s.payload.get("status") or "").lower()
            if s_status == "accepted" or s.payload.get("baseline") is True:
                raise HTTPException(
                    status_code=409,
                    detail=f"A baseline scenario has already been accepted for project {request.project_id!r}",
                )

        records = _load_scenario_records(store, request.scenario_ids)

        # Verify all scenarios belong to project and are in PROPOSED status
        for rec in records:
            if rec["project_id"] != request.project_id:
                raise HTTPException(
                    status_code=422,
                    detail=f"Scenario {rec['scenario_id']!r} does not belong to project {request.project_id!r}",
                )
            if str(rec["status"]).lower() != "proposed":
                raise HTTPException(
                    status_code=409,
                    detail=f"Scenario {rec['scenario_id']!r} is not in proposed status (current: {rec['status']!r})",
                )

        try:
            comparison = build_scenario_comparison(records)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if comparison["status"] != "COMPARABLE":
            reasons_str = "; ".join(comparison.get("incompatibility_reasons", ["inconsistent comparison basis"]))
            raise HTTPException(
                status_code=409,
                detail=f"Comparison is NOT_COMPARABLE; acceptance entrance is closed: {reasons_str}",
            )

        eligibility = comparison.get("eligibility_for_decision", {})
        if not eligibility.get("can_accept"):
            raise HTTPException(
                status_code=409,
                detail=eligibility.get("reason", "Proposals are not eligible for baseline acceptance"),
            )

        # Verify designer decision key
        key_path = _resolve_key_path()
        key_str = request.decision_key.get_secret_value()
        if not key_str or not key_str.strip():
            raise HTTPException(status_code=401, detail="Decision key is required")

        remote_key = http_request.client.host if (http_request and http_request.client is not None) else "unknown"

        if limiter is not None and not limiter.begin_attempt(remote_key):
            raise HTTPException(status_code=429, detail="Decision key attempts are temporarily rate-limited")

        try:
            verified = verify_decision_key_strict(key_str, path=key_path)
        except DecisionKeyUnavailable:
            if limiter is not None:
                limiter.finish_attempt(remote_key, failed=False)
            raise HTTPException(
                status_code=401,
                detail="Designer decision key is not initialized or is unavailable.",
            )
        if not verified:
            if limiter is not None:
                limiter.finish_attempt(remote_key, failed=True)
            raise HTTPException(status_code=403, detail="Decision key is incorrect")
        if limiter is not None:
            limiter.finish_attempt(remote_key, failed=False)

        # 1. Prepare HumanDecision for accepted baseline proposal
        accepted_rec = store.current(request.accepted_scenario_id)
        accepted_geom_hash = accepted_rec.payload.get("geometry_sha256")
        accepted_decision_id = f"decision-{uuid.uuid4().hex}"

        accepted_decision = HumanDecision(
            id=accepted_decision_id,
            project_id=request.project_id,
            target_id=accepted_rec.entity_id,
            target_type="DesignScenario",
            target_version=str(accepted_rec.revision),
            target_geometry_sha256=accepted_geom_hash,
            action=DecisionAction.ACCEPT,
            status=HumanStatus.ACCEPTED,
            actor="designer",
            actor_kind=ActorKind.HUMAN_UI,
            actor_session_id=request.actor_session_id,
            reason=request.acceptance_reason.strip(),
            timestamp=datetime.now(timezone.utc),
            decision_event_id=f"event-{uuid.uuid4().hex}",
        )

        # 2. Prepare HumanDecision for each rejected proposal
        rejected_decisions: list[HumanDecision] = []
        for rej_id in rejected_ids:
            rej_rec = store.current(rej_id)
            rej_geom_hash = rej_rec.payload.get("geometry_sha256")
            rej_reason = request.rejected_reasons[rej_id].strip()
            rej_decision_id = f"decision-{uuid.uuid4().hex}"

            rej_decision = HumanDecision(
                id=rej_decision_id,
                project_id=request.project_id,
                target_id=rej_rec.entity_id,
                target_type="DesignScenario",
                target_version=str(rej_rec.revision),
                target_geometry_sha256=rej_geom_hash,
                action=DecisionAction.REJECT,
                status=HumanStatus.REJECTED,
                actor="designer",
                actor_kind=ActorKind.HUMAN_UI,
                actor_session_id=request.actor_session_id,
                reason=rej_reason,
                timestamp=datetime.now(timezone.utc),
                decision_event_id=f"event-{uuid.uuid4().hex}",
            )
            rejected_decisions.append(rej_decision)

        # 3. Atomically persist all decisions and status transitions
        try:
            store.record_scenario_comparison_decision(
                project_id=request.project_id,
                accepted_decision=accepted_decision,
                rejected_decisions=rejected_decisions,
                decision_key=key_str,
                decision_key_path=key_path,
            )
        except PayloadError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return {
            "status": "ACCEPTED",
            "project_id": request.project_id,
            "baseline_scenario_id": request.accepted_scenario_id,
            "baseline_decision_id": accepted_decision_id,
            "baseline_geometry_sha256": accepted_geom_hash,
            "rejected_decisions": {d.target_id: d.id for d in rejected_decisions},
            "message": "Baseline scenario accepted and unselected proposals rejected by HumanDecision.",
        }

    return router
