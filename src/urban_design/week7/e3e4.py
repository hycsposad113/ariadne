"""E3 energy and E4 heat-storage entry. Not an accepted core result."""

from __future__ import annotations

from typing import Any, Mapping

STATUS = "NOT_ACCEPTED"
BLOCKED = "BLOCKED"

REQUIRED = ("scenario_id", "revision", "floor_area_m2", "use_mix")


class E3E4InputError(ValueError):
    def __init__(self, code: str, detail: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.detail = dict(detail or {})
        super().__init__(code)


def inspect_inputs(payload: Mapping[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED if payload.get(key) in (None, "")]
    if missing:
        raise E3E4InputError("input_incomplete", {"missing": missing})
    try:
        area = float(payload["floor_area_m2"])
    except (TypeError, ValueError) as exc:
        raise E3E4InputError("floor_area_not_numeric") from exc
    if area < 0:
        raise E3E4InputError("floor_area_negative", {"floor_area_m2": area})
    return {
        "scenario_id": str(payload["scenario_id"]),
        "revision": str(payload["revision"]),
        "floor_area_m2": area,
        "use_mix": payload["use_mix"],
        "external_engine_called": False,
    }


def entry(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    checked = inspect_inputs(payload) if payload else None
    return {
        "e3": {
            "name": "building_energy",
            "status": STATUS,
            "run_status": BLOCKED,
            "reason": "benchmark plan only; no engine is wired",
        },
        "e4": {
            "name": "heat_storage",
            "status": STATUS,
            "run_status": BLOCKED,
            "reason": "benchmark plan only; no engine is wired",
        },
        "benchmark_plan": {
            "status": BLOCKED,
            "compares": "the same revision, area, and use mix against a published method",
            "does_not_rank": True,
            "external_engine": None,
        },
        "checked_input": checked,
        "core_feature": False,
    }
