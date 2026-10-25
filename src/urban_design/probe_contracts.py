"""Pydantic persistence contracts for the bounded Milestone 1 probe."""

from __future__ import annotations

from datetime import datetime
import math
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import _aware, _finite, _sha256


class ProbeArtifactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    # Empty tool outputs remain recorded so a failed run is inspectable; the
    # runtime gate separately requires non-empty artifacts before PASS.
    size_bytes: int = Field(ge=0)
    sha256: str

    _validate_hash = field_validator("sha256")(_sha256)

    @field_validator("path")
    @classmethod
    def artifact_path(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip() or value.startswith("/"):
            raise ValueError("probe artifact path must be a non-empty relative path")
        return value


class ProbeCommandRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""

    @field_validator("command")
    @classmethod
    def command_tokens(cls, value: list[str]) -> list[str]:
        if not value or any(not isinstance(item, str) or not item for item in value):
            raise ValueError("probe command must contain executable tokens")
        return value


class ProbeRunRecord(BaseModel):
    """Minimal typed view used to validate every climate run before persistence."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    offset_m: float
    status: str
    artifacts: list[ProbeArtifactRecord] = Field(default_factory=list)
    weather_sha256: str
    fixture_sha256: str
    commands: list[ProbeCommandRecord] = Field(default_factory=list)
    incident_radiation_values: list[float] = Field(default_factory=list)
    spatial_artifact: ProbeArtifactRecord | None = None

    _validate_fixture_hash = field_validator("fixture_sha256", "weather_sha256")(_sha256)

    @field_validator("offset_m")
    @classmethod
    def finite_offset(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("offset must be finite")
        return value

    @field_validator("status")
    @classmethod
    def run_status(cls, value: str) -> str:
        value = value.upper() if isinstance(value, str) else value
        if value not in {"SUCCEEDED", "BLOCKED", "TOOL_FAILED", "OUTCOME_UNKNOWN"}:
            raise ValueError("unsupported probe run status")
        return value

    @field_validator("incident_radiation_values")
    @classmethod
    def finite_radiation(cls, values: list[float]) -> list[float]:
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("incident radiation values must be finite and non-negative")
        return values

    @model_validator(mode="after")
    def successful_run_has_evidence(self) -> "ProbeRunRecord":
        if self.status == "SUCCEEDED" and not self.artifacts:
            raise ValueError("successful probe run requires non-empty artifact evidence")
        if self.status == "SUCCEEDED" and not self.weather_sha256:
            raise ValueError("successful probe run requires weather hash")
        return self


class ProbeTierRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    tier: str
    status: str
    runs: list[ProbeRunRecord]

    @field_validator("status")
    @classmethod
    def tier_status(cls, value: str) -> str:
        value = value.upper() if isinstance(value, str) else value
        if value not in {"PASS", "BLOCKED", "TOOL_FAILED", "OUTCOME_UNKNOWN"}:
            raise ValueError("unsupported probe tier status")
        return value

    @model_validator(mode="after")
    def status_matches_runs(self) -> "ProbeTierRecord":
        if self.status == "PASS" and (not self.runs or any(run.status != "SUCCEEDED" for run in self.runs)):
            raise ValueError("a passing probe tier requires all runs to succeed")
        return self


class ProbeReportRecord(BaseModel):
    """Top-level contract: only this validated shape may be written to disk."""

    model_config = ConfigDict(extra="forbid")

    probe_id: str
    run_id: str
    timestamp_utc: datetime
    runtime: dict[str, Any]
    fixture: dict[str, Any]
    qgis: dict[str, Any]
    climate: dict[str, ProbeTierRecord]
    output_root: str
    source_reports: dict[str, dict[str, Any]] = Field(default_factory=dict)
    gate_manifest: dict[str, Any] = Field(default_factory=dict)
    report_path: str | None = None

    _validate_timestamp = field_validator("timestamp_utc")(_aware)

    @field_validator("probe_id", "run_id", "output_root")
    @classmethod
    def report_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("probe report text must be non-empty")
        return value.strip()

    @model_validator(mode="after")
    def report_requires_tiers(self) -> "ProbeReportRecord":
        if set(self.climate) != {"ladybug", "honeybee_radiance"}:
            raise ValueError("probe report requires ladybug and honeybee_radiance tiers")
        if not isinstance(self.qgis.get("facade_smoke"), Mapping):
            raise ValueError("probe report requires typed qgis facade evidence")
        return self


class ProbeSourceReport(BaseModel):
    """Typed envelope for a raw QGIS or climate source report."""

    model_config = ConfigDict(extra="forbid")

    source_kind: str
    created_at: datetime
    status: str
    payload: dict[str, Any]

    _validate_created_at = field_validator("created_at")(_aware)

    @field_validator("source_kind")
    @classmethod
    def source_kind_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("source kind must be non-empty")
        return value.strip()

    @field_validator("status")
    @classmethod
    def source_status(cls, value: str) -> str:
        value = value.upper() if isinstance(value, str) else value
        if value not in {"PASS", "BLOCKED", "TOOL_FAILED", "OUTCOME_UNKNOWN"}:
            raise ValueError("unsupported source report status")
        return value


def validate_probe_report(payload: Mapping[str, Any]) -> ProbeReportRecord:
    """Validate a report before any persistence operation."""
    return ProbeReportRecord.model_validate(payload)


__all__ = [
    "ProbeArtifactRecord",
    "ProbeCommandRecord",
    "ProbeRunRecord",
    "ProbeTierRecord",
    "ProbeReportRecord",
    "ProbeSourceReport",
    "validate_probe_report",
]
