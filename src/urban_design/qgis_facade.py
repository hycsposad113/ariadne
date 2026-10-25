"""A small policy boundary around the external QGIS MCP transport.

The facade accepts only named, registered operations and JSON-object request
payloads.  It does not expose an escape hatch for arbitrary code, SQL, or
batch execution.  The transport callback is deliberately injected so the
domain tests can exercise policy and failure semantics without starting QGIS;
the real socket smoke is recorded separately by ``scripts/tool_feasibility_probe``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Mapping

from .models import QgisAuditRecord


DEFAULT_ALLOWED_OPERATIONS = frozenset(
    {
        "urban.capture_selected_study_area",
        "urban.get_project_info",
        "urban.buffer_fixture",
        "urban.validate_crs",
        "urban.load_snapshot",
        "urban.calculate_far",
        "urban.build_pedestrian_graph",
        "urban.destination_accessibility",
        "urban.intersection_density",
        "urban.landuse_entropy",
        "urban.green_access",
        "urban.render_evidence_map",
    }
)

# The facade names domain operations instead of accepting a caller-supplied
# QGIS algorithm.  Each operation therefore has a small, explicit parameter
# vocabulary.  ``output_path`` is the only filesystem target and is checked
# against ``controlled_root`` below.
OPERATION_PARAMETERS = {
    # The capture command is deliberately a claim-free envelope.  The bridge
    # uses these values only to identify the already-selected QGIS feature;
    # it generates the export path, expression and target CRS itself.
    "urban.capture_selected_study_area": frozenset(
        {
            "project_id", "instance", "layer_id", "fid", "actor",
            "actor_kind", "actor_session_id", "request_id",
        }
    ),
    "urban.get_project_info": frozenset({"project_id"}),
    "urban.buffer_fixture": frozenset({"input_path", "output_path", "distance_m", "segments"}),
    "urban.validate_crs": frozenset({"layer_id", "snapshot_id", "expected_crs", "output_path"}),
    "urban.load_snapshot": frozenset({"snapshot_id", "snapshot_path", "output_path"}),
    "urban.calculate_far": frozenset({"scenario_id", "footprint_area_m2", "site_area_m2", "output_path"}),
    "urban.build_pedestrian_graph": frozenset({"network_snapshot_id", "policy_id", "output_path"}),
    "urban.destination_accessibility": frozenset({
        "graph_id", "origin_set_id", "destination_set_id", "threshold_m", "scenario_id", "output_path"
    }),
    "urban.intersection_density": frozenset({"network_snapshot_id", "area_m2", "output_path"}),
    "urban.landuse_entropy": frozenset({"landuse_snapshot_id", "area_m2", "output_path"}),
    "urban.green_access": frozenset({"green_snapshot_id", "origin_set_id", "threshold_m", "output_path"}),
    "urban.render_evidence_map": frozenset({"project_id", "layer_ids", "output_path"}),
}

REQUIRED_PARAMETERS = {
    "urban.capture_selected_study_area": frozenset(
        {
            "project_id", "instance", "layer_id", "fid", "actor",
            "actor_kind", "actor_session_id", "request_id",
        }
    ),
    "urban.get_project_info": frozenset({"project_id"}),
    "urban.buffer_fixture": frozenset({"input_path", "output_path", "distance_m", "segments"}),
    "urban.validate_crs": frozenset({"layer_id", "snapshot_id", "expected_crs"}),
    "urban.load_snapshot": frozenset({"snapshot_id", "snapshot_path"}),
    "urban.calculate_far": frozenset({"scenario_id", "footprint_area_m2", "site_area_m2"}),
    "urban.build_pedestrian_graph": frozenset({"network_snapshot_id", "policy_id"}),
    "urban.destination_accessibility": frozenset({"graph_id", "origin_set_id", "destination_set_id", "threshold_m"}),
    "urban.intersection_density": frozenset({"network_snapshot_id", "area_m2"}),
    "urban.landuse_entropy": frozenset({"landuse_snapshot_id", "area_m2"}),
    "urban.green_access": frozenset({"green_snapshot_id", "origin_set_id", "threshold_m"}),
    "urban.render_evidence_map": frozenset({"project_id", "layer_ids", "output_path"}),
}

FORBIDDEN_OPERATIONS = frozenset(
    {"execute_code", "qgis.execute_code", "dynamic_python", "run_sql", "batch_process"}
)

Dispatch = Callable[[str, Mapping[str, Any]], Any]


class QgisMCPPreDispatchError(ConnectionError):
    """The QGIS MCP transport could not reach QGIS before sending a command."""


class QgisMCPPostDispatchError(ConnectionError):
    """The QGIS MCP connection was lost after a command may have started."""


class QgisFacadeOperationError(RuntimeError):
    """A domain operation returned a structured, non-transport failure."""

    def __init__(
        self,
        message: str,
        *,
        status: str = "FAILED",
        dispatched: bool = True,
        retry_allowed: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.dispatched = dispatched
        self.retry_allowed = retry_allowed


def _reject_symlink_components(path: Path, label: str) -> Path:
    """Resolve a root only when none of its existing components are symlinks."""
    raw = path.expanduser()
    current = Path(raw.anchor) if raw.is_absolute() else Path.cwd()
    parts = raw.parts[1:] if raw.is_absolute() else raw.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} cannot contain symlink components")
    return raw.resolve()


@dataclass(frozen=True)
class QgisFacadePolicy:
    """Validation policy with separate approved input and run output roots.

    ``controlled_root`` remains as a compatibility constructor alias for the
    original Milestone 1 tests. Production callers should provide both explicit
    ``approved_input_roots`` and ``run_output_root`` values.
    """

    controlled_root: Path | None = None
    allowed_operations: frozenset[str] = DEFAULT_ALLOWED_OPERATIONS
    approved_input_roots: tuple[Path, ...] = ()
    run_output_root: Path | None = None

    def __post_init__(self) -> None:
        legacy_root = _reject_symlink_components(Path(self.controlled_root), "controlled_root") if self.controlled_root is not None else None
        configured_roots = (
            (self.approved_input_roots,)
            if isinstance(self.approved_input_roots, (str, Path))
            else tuple(self.approved_input_roots)
        )
        roots = tuple(_reject_symlink_components(Path(root), "approved input root") for root in configured_roots)
        if not roots and legacy_root is not None:
            roots = (legacy_root,)
        if not roots:
            raise ValueError("at least one approved input root is required")
        if any(not root.exists() or not root.is_dir() for root in roots):
            raise ValueError("approved input roots must be existing directories")
        output_root = _reject_symlink_components(Path(self.run_output_root), "run_output_root") if self.run_output_root is not None else legacy_root
        if output_root is None or not output_root.exists() or not output_root.is_dir():
            raise ValueError("run_output_root must be an existing directory")
        object.__setattr__(self, "approved_input_roots", roots)
        object.__setattr__(self, "run_output_root", output_root)
        object.__setattr__(self, "controlled_root", output_root)
        if not self.allowed_operations:
            raise ValueError("at least one QGIS facade operation is required")
        if not self.allowed_operations <= DEFAULT_ALLOWED_OPERATIONS:
            raise ValueError("facade operations must remain within the closed allowlist")
        if self.allowed_operations & FORBIDDEN_OPERATIONS:
            raise ValueError("forbidden operation cannot be added to the facade")

    def validate(self, operation: str, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(operation, str) or not operation.strip():
            raise PermissionError("QGIS operation denied: operation must be non-empty")
        operation = operation.strip()
        if operation in FORBIDDEN_OPERATIONS or operation not in self.allowed_operations:
            raise PermissionError(f"QGIS operation denied by default facade: {operation}")
        if not isinstance(request, Mapping):
            raise TypeError("QGIS request must be a JSON object")
        cleaned = dict(request)
        permitted = OPERATION_PARAMETERS.get(operation, frozenset())
        unknown_keys = set(cleaned) - permitted
        if unknown_keys:
            names = ", ".join(sorted(str(key) for key in unknown_keys))
            raise PermissionError(f"QGIS parameter(s) denied for {operation}: {names}")
        required = REQUIRED_PARAMETERS.get(operation, frozenset())
        missing = required - set(cleaned)
        if missing:
            names = ", ".join(sorted(missing))
            raise PermissionError(f"QGIS required parameter(s) missing for {operation}: {names}")
        path_keys = {"output_path", "snapshot_path", "input_path"}
        for key in path_keys & set(cleaned):
            value = cleaned[key]
            if not isinstance(value, (str, Path)):
                raise TypeError(f"QGIS {key} must be a path")
            target = Path(value).expanduser().resolve()
            if key == "output_path":
                allowed = self.run_output_root
                label = "run output root"
            else:
                allowed = None
                label = "approved input roots"
            if allowed is not None:
                inside = target == allowed or allowed in target.parents
            else:
                inside = any(target == root or root in target.parents for root in self.approved_input_roots)
            if not inside:
                raise PermissionError(f"QGIS path is outside the {label}")
            cleaned[key] = str(target)
        numeric_keys = {"footprint_area_m2", "site_area_m2", "area_m2", "threshold_m", "distance_m", "segments"}
        for key in numeric_keys & set(cleaned):
            value = cleaned[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise ValueError(f"QGIS {key} must be finite")
            if value <= 0:
                raise ValueError(f"QGIS {key} must be positive")
        if "segments" in cleaned and (not isinstance(cleaned["segments"], int) or cleaned["segments"] > 32):
            raise ValueError("QGIS segments must be an integer no greater than 32")
        if "fid" in cleaned:
            if not isinstance(cleaned["fid"], int) or isinstance(cleaned["fid"], bool):
                raise ValueError("QGIS fid must be an integer")
            if cleaned["fid"] < 0:
                raise ValueError("QGIS fid must be non-negative")
        for key, value in cleaned.items():
            if key.endswith("_id") or key in {"project_id", "policy_id", "expected_crs"}:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"QGIS {key} must be a non-empty string")
        if "footprint_area_m2" in cleaned and "site_area_m2" in cleaned:
            if cleaned["footprint_area_m2"] > cleaned["site_area_m2"]:
                raise ValueError("QGIS footprint area cannot exceed site area")
        if "layer_ids" in cleaned:
            layer_ids = cleaned["layer_ids"]
            if not isinstance(layer_ids, (list, tuple)) or not layer_ids or any(
                not isinstance(item, str) or not item.strip() for item in layer_ids
            ):
                raise ValueError("QGIS layer_ids must be a non-empty list of identifiers")
        return cleaned


@dataclass(frozen=True)
class QgisFacadeResult:
    """Auditable result envelope for one serialized facade dispatch."""

    request_id: str
    operation: str
    status: str
    dispatched: bool
    retry_allowed: bool
    reason: str | None = None
    response: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "operation": self.operation,
            "status": self.status,
            "dispatched": self.dispatched,
            "retry_allowed": self.retry_allowed,
            "reason": self.reason,
            "response": self.response,
        }


class QgisMCPFacade:
    """Serialize and bound calls to an injected QGIS MCP transport."""

    def __init__(
        self,
        policy: QgisFacadePolicy,
        dispatch: Dispatch,
        *,
        audit_sink: Callable[[QgisAuditRecord], None] | None = None,
    ):
        if not isinstance(policy, QgisFacadePolicy):
            raise TypeError("policy must be a QgisFacadePolicy")
        if not callable(dispatch):
            raise TypeError("dispatch must be callable")
        self.policy = policy
        self._dispatch = dispatch
        self._lock = Lock()
        self._audit_sink = audit_sink
        self.audit_records: list[QgisAuditRecord] = []

    @staticmethod
    def _request_hash(operation: Any, request: Any) -> str:
        canonical = json.dumps(
            {"operation": operation, "request": request},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return "sha256:" + sha256(canonical.encode("utf-8")).hexdigest()

    def _record_audit(
        self,
        *,
        request_id: str,
        operation: Any,
        status: str,
        dispatched: bool,
        transport_called: bool,
        reason: str,
        request: Any,
    ) -> None:
        record = QgisAuditRecord(
            request_id=request_id.strip() or "invalid-request",
            operation=str(operation).strip() or "<invalid>",
            status=status,
            dispatched=dispatched,
            transport_called=transport_called,
            reason=reason,
            created_at=datetime.now(timezone.utc),
            request_hash=self._request_hash(operation, request),
        )
        self.audit_records.append(record)
        if self._audit_sink is not None:
            try:
                self._audit_sink(record)
            except Exception:
                # An audit sink cannot turn a denied request into a dispatch.
                pass

    def execute(
        self,
        operation: str,
        request: Mapping[str, Any],
        *,
        request_id: str,
    ) -> QgisFacadeResult:
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id must be non-empty")
        try:
            cleaned = self.policy.validate(operation, request)
        except Exception as exc:
            self._record_audit(
                request_id=request_id if isinstance(request_id, str) else "invalid-request",
                operation=operation,
                status="REJECTED",
                dispatched=False,
                transport_called=False,
                reason=str(exc),
                request=request,
            )
            raise
        operation = operation.strip()
        # Holding the lock across the transport call prevents concurrent calls
        # from interleaving QGIS project state or artifact writes.
        with self._lock:
            try:
                response = self._dispatch(operation, cleaned)
            except QgisMCPPreDispatchError as exc:
                result = QgisFacadeResult(
                    request_id=request_id.strip(),
                    operation=operation,
                    status="FAILED",
                    dispatched=False,
                    retry_allowed=True,
                    reason=f"transport unavailable before dispatch: {exc}",
                )
                self._record_audit(
                    request_id=request_id.strip(), operation=operation, status=result.status,
                    dispatched=False, transport_called=True, reason=result.reason or "", request=cleaned,
                )
                return result
            except QgisMCPPostDispatchError as exc:
                result = QgisFacadeResult(
                    request_id=request_id.strip(),
                    operation=operation,
                    status="OUTCOME_UNKNOWN",
                    dispatched=True,
                    retry_allowed=False,
                    reason=f"transport lost after dispatch: {exc}",
                )
                self._record_audit(
                    request_id=request_id.strip(), operation=operation, status=result.status,
                    dispatched=True, transport_called=True, reason=result.reason or "", request=cleaned,
                )
                return result
            except QgisFacadeOperationError as exc:
                result = QgisFacadeResult(
                    request_id=request_id.strip(),
                    operation=operation,
                    status=exc.status,
                    dispatched=exc.dispatched,
                    retry_allowed=exc.retry_allowed,
                    reason=str(exc),
                )
                self._record_audit(
                    request_id=request_id.strip(), operation=operation, status=result.status,
                    dispatched=exc.dispatched, transport_called=True,
                    reason=result.reason or "", request=cleaned,
                )
                return result
            except (ConnectionError, TimeoutError, BrokenPipeError) as exc:
                result = QgisFacadeResult(
                    request_id=request_id.strip(),
                    operation=operation,
                    status="OUTCOME_UNKNOWN",
                    dispatched=True,
                    retry_allowed=False,
                    reason=f"transport lost after dispatch: {exc}",
                )
                self._record_audit(
                    request_id=request_id.strip(), operation=operation, status=result.status,
                    dispatched=True, transport_called=True, reason=result.reason or "", request=cleaned,
                )
                return result
            except Exception as exc:
                result = QgisFacadeResult(
                    request_id=request_id.strip(),
                    operation=operation,
                    status="FAILED",
                    dispatched=True,
                    retry_allowed=False,
                    reason=f"QGIS operation failed: {type(exc).__name__}: {exc}",
                )
                self._record_audit(
                    request_id=request_id.strip(), operation=operation, status=result.status,
                    dispatched=True, transport_called=True, reason=result.reason or "", request=cleaned,
                )
                return result
        result = QgisFacadeResult(
            request_id=request_id.strip(),
            operation=operation,
            status="SUCCEEDED",
            dispatched=True,
            retry_allowed=False,
            response=response,
        )
        self._record_audit(
            request_id=request_id.strip(),
            operation=operation,
            status=result.status,
            dispatched=True,
            transport_called=True,
            reason=result.reason or "dispatch completed",
            request=cleaned,
        )
        return result


__all__ = [
    "DEFAULT_ALLOWED_OPERATIONS",
    "FORBIDDEN_OPERATIONS",
    "OPERATION_PARAMETERS",
    "REQUIRED_PARAMETERS",
    "QgisFacadePolicy",
    "QgisFacadeResult",
    "QgisMCPFacade",
    "QgisMCPPreDispatchError",
    "QgisMCPPostDispatchError",
    "QgisFacadeOperationError",
]
