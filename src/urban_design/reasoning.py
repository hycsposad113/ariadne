"""Provider-neutral deterministic reasoning adapter.

The fixture adapter emits a bounded plan from typed input.  It never computes
design metrics and never silently repairs malformed provider-shaped data.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import _id, _sha256


class AdapterOutputError(ValueError):
    """Raised when an adapter response cannot be safely validated."""


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_id: str
    objective: str
    permitted_tools: list[str] = Field(default_factory=lambda: ["deterministic_verifier"])
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("project_id")
    @classmethod
    def request_project(cls, value: str) -> str:
        return _id(value)

    @field_validator("objective")
    @classmethod
    def request_objective(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("objective must be non-empty")
        return value.strip()

    @field_validator("permitted_tools")
    @classmethod
    def request_tools(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("at least one permitted tool is required")
        return [_id(value) for value in values]


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    tool: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("action", "tool")
    @classmethod
    def step_text(cls, value: str) -> str:
        return _id(value)


class PlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    project_id: str
    request_hash: str
    adapter_version: str
    model_id: str
    steps: list[PlanStep]
    rationale: str

    @field_validator("plan_id", "project_id", "adapter_version", "model_id")
    @classmethod
    def response_text(cls, value: str) -> str:
        return _id(value)

    @field_validator("request_hash")
    @classmethod
    def response_hash(cls, value: str) -> str:
        try:
            return _sha256(value)
        except ValueError as exc:
            raise ValueError("request_hash must be a sha256 digest") from exc

    @field_validator("rationale")
    @classmethod
    def response_rationale(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("rationale must be non-empty")
        return value.strip()

    @model_validator(mode="after")
    def requires_step(self) -> "PlanResponse":
        if not self.steps:
            raise ValueError("plan must contain at least one bounded step")
        for step in self.steps:
            if step.parameters.get("project_id") != self.project_id:
                raise ValueError("plan step project scope does not match response project")
        return self


class DeterministicReasoningAdapter:
    """A repeatable fixture implementation of the model adapter contract."""

    adapter_version = "deterministic-adapter-1"
    model_id = "deterministic-fixture"
    registered_tools = frozenset({"deterministic_verifier", "evidence_inspector"})

    def plan_workflow(self, request: PlanRequest) -> PlanResponse:
        request = request if isinstance(request, PlanRequest) else PlanRequest.model_validate(request)
        canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        request_hash = "sha256:" + sha256(canonical.encode("utf-8")).hexdigest()
        # Prefer the deterministic verifier when it is explicitly allowed;
        # otherwise select a stable lexical member of the caller's allow-list.
        tool = "deterministic_verifier" if "deterministic_verifier" in request.permitted_tools else sorted(request.permitted_tools)[0]
        plan_id = "plan-" + request_hash.removeprefix("sha256:")[:16]
        step = PlanStep(
            action="inspect",
            tool=tool,
            parameters={"project_id": request.project_id, "objective": request.objective},
        )
        return PlanResponse(
            plan_id=plan_id,
            project_id=request.project_id,
            request_hash=request_hash,
            adapter_version=self.adapter_version,
            model_id=self.model_id,
            steps=[step],
            rationale="Deterministic fixture plan; semantic interpretation remains a proposal.",
        )

    # Common adapter naming used by callers that refer to a generic plan API.
    generate_plan = plan_workflow

    def decode_plan(self, payload: Any, *, permitted_tools: set[str] | None = None) -> PlanResponse:
        if not isinstance(payload, dict):
            raise AdapterOutputError("model output must be an object")
        unknown_fields = set(payload) - set(PlanResponse.model_fields)
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise AdapterOutputError(f"unknown model output field(s): {names}")
        try:
            response = PlanResponse.model_validate(payload)
        except Exception as exc:
            raise AdapterOutputError(f"malformed model output: {exc}") from exc
        allowed = permitted_tools
        if allowed is None:
            allowed = set(self.registered_tools)
        unknown = [step.tool for step in response.steps if step.tool not in allowed]
        if unknown:
            raise AdapterOutputError(f"unregistered tool in model output: {unknown[0]}")
        if any(not step.parameters.get("project_id") for step in response.steps):
            raise AdapterOutputError("model step is missing project scope")
        return response

    validate_output = decode_plan


__all__ = [
    "AdapterOutputError",
    "DeterministicReasoningAdapter",
    "PlanRequest",
    "PlanResponse",
    "PlanStep",
]
