"""Fail-closed semantic checks for Rotterdam M4H boundary review evidence.

These checks are review guardrails, not planning standards.  They exist to
prevent a source-traced exterior from being presented as a locally bounded
road interface merely because its two endpoints happen to be road-like.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from shapely.geometry import Polygon


ROAD_LIKE_COLLECTIONS = frozenset({"wegdeel", "ondersteunendwegdeel"})
SUPPLEMENTARY_COLLECTIONS = frozenset(
    {"onbegroeidterreindeel", "begroeidterreindeel", "waterdeel"}
)

# These are deterministic semantic review guardrails.  They are deliberately
# recorded in every result and must never be presented as urban-planning rules.
MAX_LOCAL_INTERFACE_LENGTH_M = 250.0
MAX_LOCAL_INTERFACE_FRACTION = 0.10
MAX_LOCAL_INTERFACE_DETOUR_RATIO = 2.0
MAX_MULTI_COLLECTION_INTERFACE_LENGTH_M = 100.0
MAX_HYDROLOGY_INTERFACE_LENGTH_M = 50.0
MAX_TOTAL_SUPPLEMENTARY_REVIEW_LENGTH_M = 250.0
MAX_SEED_LOSS_RATIO_WITH_SUPPLEMENTARY_ANOMALY = 0.10


class BoundarySemanticGateError(ValueError):
    """Raised when a candidate cannot be treated as a local site interface."""


def _float(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BoundarySemanticGateError(f"invalid semantic-gate value: {field}") from exc
    if not math.isfinite(result):
        raise BoundarySemanticGateError(f"non-finite semantic-gate value: {field}")
    return result


def _run_points(run: Mapping[str, Any]) -> tuple[tuple[float, float], tuple[float, float]] | None:
    start = run.get("start_epsg28992")
    end = run.get("end_epsg28992")
    if not isinstance(start, Sequence) or not isinstance(end, Sequence) or len(start) != 2 or len(end) != 2:
        return None
    return ((float(start[0]), float(start[1])), (float(end[0]), float(end[1])))


def _normalise_run(run: Mapping[str, Any], *, perimeter_m: float | None) -> dict[str, Any]:
    length = _float(run.get("length_m"), "length_m")
    edge_count = int(run.get("edge_count", 0))
    collections = sorted({str(value) for value in run.get("source_collections", []) if value})
    if not collections and run.get("source_collection"):
        collections = [str(run["source_collection"])]
    points = _run_points(run)
    chord = None
    detour = None
    if points is not None:
        chord = math.dist(*points)
        detour = length / chord if chord > 1e-9 else math.inf
    fraction = length / perimeter_m if perimeter_m and perimeter_m > 0 else None
    return {
        "edge_start": run.get("edge_start"),
        "edge_end": run.get("edge_end"),
        "edge_count": edge_count,
        "length_m": length,
        "source_collection": run.get("source_collection"),
        "source_collections": collections,
        "source_feature_ids": sorted({str(value) for value in run.get("source_feature_ids", []) if value}),
        "previous_source_collection": run.get("previous_source_collection"),
        "next_source_collection": run.get("next_source_collection"),
        "previous_source_feature_id": run.get("previous_source_feature_id"),
        "next_source_feature_id": run.get("next_source_feature_id"),
        "source_functions": run.get("source_functions", []),
        "source_attributes": run.get("source_attributes", []),
        "start_epsg28992": list(points[0]) if points else None,
        "end_epsg28992": list(points[1]) if points else None,
        "chord_m": chord,
        "detour_ratio": detour,
        "perimeter_fraction": fraction,
    }


def _seed_loss_ratio(seed: Polygon | None, candidate: Polygon | None) -> float | None:
    if seed is None or candidate is None or seed.area <= 0:
        return None
    return seed.difference(candidate).area / seed.area


def evaluate_supplementary_semantics(
    runs: Sequence[Mapping[str, Any]],
    *,
    perimeter_m: float | None = None,
    candidate: Polygon | None = None,
    seed: Polygon | None = None,
) -> dict[str, Any]:
    """Evaluate whether supplementary spans are locally and semantically bounded.

    The total-length check makes the result invariant to how a caller groups
    the same contiguous arc.  Endpoint adjacency is retained as evidence but
    is explicitly insufficient for a pass.
    """

    normalised = [_normalise_run(run, perimeter_m=perimeter_m) for run in runs]
    failures: list[dict[str, Any]] = []

    def fail(code: str, run: Mapping[str, Any] | None, reason: str) -> None:
        failures.append({"code": code, "reason": reason, "run": dict(run) if run else None})

    total_length = sum(float(run["length_m"]) for run in normalised)
    max_length = max((float(run["length_m"]) for run in normalised), default=0.0)
    max_fraction = max(
        (float(run["perimeter_fraction"]) for run in normalised if run["perimeter_fraction"] is not None),
        default=0.0,
    )

    # A regrouping must not make the same continuous supplementary arc pass.
    if total_length > MAX_TOTAL_SUPPLEMENTARY_REVIEW_LENGTH_M:
        fail(
            "TOTAL_SUPPLEMENTARY_SPAN_EXCEEDS_LOCAL_REVIEW_BUDGET",
            None,
            f"combined supplementary span is {total_length:.6f} m; endpoint grouping cannot establish locality",
        )

    for run in normalised:
        length = float(run["length_m"])
        collections = set(run["source_collections"])
        if length > MAX_LOCAL_INTERFACE_LENGTH_M:
            fail(
                "SUPPLEMENTARY_SPAN_TOO_LONG_FOR_LOCAL_INTERFACE",
                run,
                f"supplementary span is {length:.6f} m; a local road interface is not proven",
            )
        fraction = run["perimeter_fraction"]
        if fraction is not None and float(fraction) > MAX_LOCAL_INTERFACE_FRACTION:
            fail(
                "SUPPLEMENTARY_SPAN_EXCESSIVE_PERIMETER_SHARE",
                run,
                f"supplementary span is {float(fraction) * 100.0:.3f}% of perimeter; a local junction role is not proven",
            )
        if len(collections) > 1 and length > MAX_MULTI_COLLECTION_INTERFACE_LENGTH_M:
            fail(
                "MULTI_COLLECTION_LOCALITY_UNPROVEN",
                run,
                "span crosses multiple supplementary collections and exceeds the local-interface length guardrail",
            )
        if "waterdeel" in collections and length > MAX_HYDROLOGY_INTERFACE_LENGTH_M:
            fail(
                "HYDROLOGY_SPAN_LOCALITY_UNPROVEN",
                run,
                "waterdeel participates in an extended supplementary span; endpoint roads do not prove a junction boundary",
            )
        detour = run["detour_ratio"]
        if detour is not None and float(detour) > MAX_LOCAL_INTERFACE_DETOUR_RATIO:
            fail(
                "SUPPLEMENTARY_DETOUR_OR_SPUR",
                run,
                f"span detour ratio is {float(detour):.6f}; a spur, deep notch, or large-scale detour requires human review",
            )

    seed_loss = _seed_loss_ratio(seed, candidate)
    if seed_loss is not None and seed_loss > MAX_SEED_LOSS_RATIO_WITH_SUPPLEMENTARY_ANOMALY and failures:
        fail(
            "SEED_LOSS_DEEP_NOTCH_OR_LARGE_DETOUR",
            None,
            f"candidate removes {seed_loss * 100.0:.3f}% of the v3 seed while supplementary topology is anomalous",
        )

    return {
        "schema_version": "m2-r07-boundary-semantic-gate",
        "pass": not failures,
        "status": "PASS" if not failures else "REJECTED",
        "endpoint_bracketing_is_sufficient": False,
        "guardrails_are_planning_standards": False,
        "guardrails": {
            "max_local_interface_length_m": MAX_LOCAL_INTERFACE_LENGTH_M,
            "max_local_interface_fraction": MAX_LOCAL_INTERFACE_FRACTION,
            "max_local_interface_detour_ratio": MAX_LOCAL_INTERFACE_DETOUR_RATIO,
            "max_multi_collection_interface_length_m": MAX_MULTI_COLLECTION_INTERFACE_LENGTH_M,
            "max_hydrology_interface_length_m": MAX_HYDROLOGY_INTERFACE_LENGTH_M,
            "max_total_supplementary_review_length_m": MAX_TOTAL_SUPPLEMENTARY_REVIEW_LENGTH_M,
            "max_seed_loss_ratio_with_supplementary_anomaly": MAX_SEED_LOSS_RATIO_WITH_SUPPLEMENTARY_ANOMALY,
        },
        "run_count": len(normalised),
        "total_supplementary_length_m": total_length,
        "max_supplementary_length_m": max_length,
        "max_perimeter_fraction": max_fraction,
        "seed_loss_ratio": seed_loss,
        "runs": normalised,
        "failures": failures,
    }


def require_semantically_bounded(
    runs: Sequence[Mapping[str, Any]],
    *,
    perimeter_m: float | None = None,
    candidate: Polygon | None = None,
    seed: Polygon | None = None,
) -> dict[str, Any]:
    """Return a passing result or raise a release-blocking semantic error."""

    result = evaluate_supplementary_semantics(
        runs,
        perimeter_m=perimeter_m,
        candidate=candidate,
        seed=seed,
    )
    if not result["pass"]:
        codes = ", ".join(item["code"] for item in result["failures"])
        raise BoundarySemanticGateError(f"supplementary topology is not semantically bounded: {codes}")
    return result


__all__ = [
    "BoundarySemanticGateError",
    "evaluate_supplementary_semantics",
    "require_semantically_bounded",
    "ROAD_LIKE_COLLECTIONS",
    "SUPPLEMENTARY_COLLECTIONS",
]
