"""Small, dependency-free policy helpers used by the QGIS plugin.

The bridge deliberately receives an opaque layer identity and integer FID.  A
QGIS canvas geometry is never part of this request: the backend independently
reads the selected feature through its bounded QGIS MCP adapter.
"""

from __future__ import annotations

import os
import json
import math
from pathlib import Path
import uuid
from typing import Any, Mapping
from urllib.parse import urlsplit

PROJECT_ID = "rotterdam-m4h-pilot-project"
DRAFT_LAYER_NAME = "Study Area Draft"
DRAFT_CRS_AUTHID = "EPSG:28992"
HERMES_RESERVED_PORT = 8787
DEFAULT_BRIDGE_PORT = 8788
DEFAULT_BRIDGE_URL = f"http://127.0.0.1:{DEFAULT_BRIDGE_PORT}"
DEFAULT_PLATFORM_API_URL = "http://127.0.0.1:8795"
PLATFORM_API_URL_ENV = "URBAN_DESIGN_API_BASE_URL"
SESSION_TOKEN_ENV = "URBAN_DESIGN_SESSION_TOKEN"
BRIDGE_URL_ENV = "URBAN_DESIGN_BRIDGE_URL"
ACTOR_ENV = "URBAN_DESIGN_ACTOR"
ANCHOR_CONFIG_ENV = "URBAN_DESIGN_ANCHOR_CONFIG"
CONTEXT_LAYER_NAME = "NON_AUTHORITATIVE_DRAWING_CONTEXT"
PENDING_PLATFORM_SYNC_SETTINGS_KEY = "urban_design_study_area/pending_platform_sync"


def bridge_url() -> str:
    """Resolve the bridge URL without ever targeting Hermes's reserved port."""
    value = os.environ.get(BRIDGE_URL_ENV, DEFAULT_BRIDGE_URL).rstrip("/")
    try:
        port = urlsplit(value).port
    except ValueError as exc:
        raise ValueError(f"invalid Urban Design bridge URL: {value}") from exc
    if port == HERMES_RESERVED_PORT:
        raise ValueError(
            "Urban Design bridge URL cannot target port 8787; that port is reserved for the Hermes Web UI"
        )
    return value


def platform_api_base_url(*, environ: Mapping[str, str] | None = None) -> str:
    """Resolve a loopback-only platform API endpoint, separate from Hermes/QGIS."""
    env = os.environ if environ is None else environ
    value = str(env.get(PLATFORM_API_URL_ENV, DEFAULT_PLATFORM_API_URL)).rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port or (80 if parsed.scheme == "http" else 443)
    except ValueError as exc:
        raise ValueError("invalid platform API URL") from exc
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("platform API URL must use HTTP loopback")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("platform API URL must identify only a loopback origin")
    if port in {HERMES_RESERVED_PORT, DEFAULT_BRIDGE_PORT, 8644}:
        raise ValueError(f"platform API port {port} is reserved for Hermes or the QGIS bridge")
    if not 1 <= port <= 65535:
        raise ValueError("platform API port must be within 1..65535")
    return f"http://{parsed.hostname}:{port}"


def qgis_source_feature_reference(layer_name: str, attributes: Mapping[str, Any]) -> dict[str, str]:
    """Derive a stable source ID from feature attributes, never from geometry/FID."""
    explicit_id = str(attributes.get("urban_design_feature_id", "")).strip()
    explicit_kind = str(attributes.get("urban_design_feature_kind", "")).strip().lower()
    if explicit_id and explicit_kind in {"building", "road"}:
        return {"feature_id": explicit_id, "feature_kind": explicit_kind}

    bag_id = ""
    for key in ("identificatie", "identificatie_pand", "identificatiepand", "bag_id"):
        value = attributes.get(key)
        if value not in (None, ""):
            bag_id = str(value).strip()
            break
    if bag_id and any(word in layer_name.casefold() for word in ("bag", "pand", "building")):
        return {"feature_id": f"bag:{bag_id}", "feature_kind": "building"}

    osm_type = str(attributes.get("osm_type", "")).strip().lower()
    osm_id = str(attributes.get("osm_id", "")).strip()
    if osm_type == "way" and osm_id.isdigit():
        return {"feature_id": f"way/{osm_id}", "feature_kind": "road"}
    raise ValueError("selected feature has no supported stable BAG/OSM source identity")


def build_platform_sync_payload(
    *,
    project_id: str,
    study_area_id: str,
    expected_workspace_revision: int,
    actor_session_id: str,
    source_snapshot_ids: list[str],
    selected_features: list[Mapping[str, Any]],
    current_workspace: Mapping[str, Any] | None,
    request_key: str | None = None,
) -> dict[str, Any]:
    """Build a non-binding draft sync using references from verified site-context."""
    if not project_id.strip() or not study_area_id.strip():
        raise ValueError("project and StudyArea references are required")
    if not actor_session_id.strip() or len(actor_session_id.strip()) > 128:
        raise ValueError("QGIS actor session must contain 1 to 128 characters")
    if isinstance(expected_workspace_revision, bool) or expected_workspace_revision < 0:
        raise ValueError("expected workspace revision must be a nonnegative integer")
    if not source_snapshot_ids or len(source_snapshot_ids) != len(set(source_snapshot_ids)):
        raise ValueError("verified source snapshot IDs are required and must be unique")
    if not selected_features or len(selected_features) > 100:
        raise ValueError("select between 1 and 100 source features before syncing")

    dispositions: dict[str, dict[str, Any]] = {}
    if current_workspace:
        for item in current_workspace.get("feature_dispositions", []):
            if not isinstance(item, Mapping):
                continue
            feature_id = str(item.get("feature_id", ""))
            if feature_id and all(item.get(key) for key in ("source_artifact_id", "source_snapshot_id", "source_feature_id")):
                dispositions[feature_id] = {
                    "feature_id": feature_id,
                    "feature_kind": str(item.get("feature_kind", item.get("feature_type", ""))),
                    "disposition": str(item.get("disposition", "undecided")).lower(),
                    "source_artifact_id": str(item["source_artifact_id"]),
                    "source_snapshot_id": str(item["source_snapshot_id"]),
                    "source_feature_id": str(item["source_feature_id"]),
                }

    seen: set[str] = set()
    for feature in selected_features:
        feature_id = str(feature.get("id", ""))
        kind = str(feature.get("feature_kind", ""))
        if feature.get("lineage_status") != "VERIFIED" or kind not in {"building", "road"}:
            raise ValueError("selected feature is not verified by the active spatial-r01 catalog")
        if not feature_id or feature_id in seen:
            raise ValueError("selected source feature IDs must be nonempty and unique")
        seen.add(feature_id)
        if feature_id not in dispositions:
            required = ("source_artifact_id", "source_snapshot_id", "source_feature_id")
            if any(not feature.get(key) for key in required):
                raise ValueError("verified feature is missing its source lineage")
            dispositions[feature_id] = {
                "feature_id": feature_id,
                "feature_kind": kind,
                "disposition": "undecided",
                "source_artifact_id": str(feature["source_artifact_id"]),
                "source_snapshot_id": str(feature["source_snapshot_id"]),
                "source_feature_id": str(feature["source_feature_id"]),
            }
        elif dispositions[feature_id]["feature_kind"] != kind:
            raise ValueError("selected source feature kind conflicts with existing verified workspace lineage")

    brief = None
    if current_workspace and isinstance(current_workspace.get("spatial_brief"), Mapping):
        brief = json.loads(json.dumps(current_workspace["spatial_brief"]))
    if brief is None:
        brief = {"zones": [], "status": "DRAFT_PENDING_HUMAN_DECISION"}
    return {
        "project_id": project_id,
        "study_area_id": study_area_id,
        "expected_workspace_revision": expected_workspace_revision,
        "actor_kind": "QGIS_PLUGIN",
        "actor_session_id": actor_session_id.strip(),
        "source_snapshot_ids": list(source_snapshot_ids),
        "idempotency_key": request_key or request_id(),
        "feature_dispositions": sorted(dispositions.values(), key=lambda item: item["feature_id"]),
        "spatial_brief": brief,
    }


def create_pending_platform_sync(api_base_url: str, request_body: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze one exact local sync request so an unknown result can be replayed safely."""
    base_url = platform_api_base_url(environ={PLATFORM_API_URL_ENV: str(api_base_url)})
    if not isinstance(request_body, Mapping):
        raise ValueError("pending platform sync body must be an object")
    required = {
        "project_id",
        "study_area_id",
        "expected_workspace_revision",
        "source_snapshot_ids",
        "idempotency_key",
        "actor_kind",
        "actor_session_id",
        "feature_dispositions",
        "spatial_brief",
    }
    if set(request_body) != required:
        raise ValueError("pending platform sync body does not match the typed sync request")
    project = str(request_body.get("project_id", "")).strip()
    study_area = str(request_body.get("study_area_id", "")).strip()
    expected_revision = request_body.get("expected_workspace_revision")
    key = str(request_body.get("idempotency_key", "")).strip()
    snapshots = request_body.get("source_snapshot_ids")
    actor_kind = request_body.get("actor_kind")
    actor_session = request_body.get("actor_session_id")
    if actor_kind != "QGIS_PLUGIN":
        raise ValueError("pending platform sync actor_kind must be QGIS_PLUGIN")
    if not isinstance(actor_session, str) or not actor_session.strip() or len(actor_session.strip()) > 128:
        raise ValueError("pending platform sync actor session must contain 1 to 128 characters")
    if not project or not study_area or not key:
        raise ValueError("pending platform sync is missing its project, StudyArea, or idempotency key")
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
        raise ValueError("pending platform sync has an invalid expected workspace revision")
    if not isinstance(snapshots, list) or not snapshots or any(not isinstance(item, str) or not item for item in snapshots):
        raise ValueError("pending platform sync has invalid source snapshot references")
    try:
        body = json.loads(json.dumps(dict(request_body), ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("pending platform sync body is not valid finite JSON") from exc
    return {
        "schema_version": 1,
        "api_base_url": base_url,
        "workspace_id": f"workspace-{project}",
        "project_id": project,
        "study_area_id": study_area,
        "expected_workspace_revision": expected_revision,
        "idempotency_key": key,
        "request_body": body,
    }


def _normalize_pending_platform_sync(pending: Mapping[str, Any]) -> dict[str, Any]:
    if (
        not isinstance(pending, Mapping)
        or isinstance(pending.get("schema_version"), bool)
        or pending.get("schema_version") != 1
        or not isinstance(pending.get("request_body"), Mapping)
    ):
        raise ValueError("saved pending platform sync record has an unsupported shape")
    body = pending["request_body"]
    normalized = create_pending_platform_sync(str(pending.get("api_base_url", "")), body)
    for key in ("workspace_id", "project_id", "study_area_id", "expected_workspace_revision", "idempotency_key"):
        if pending.get(key) != normalized[key]:
            raise ValueError(f"saved pending platform sync {key} does not match its request body")
    return normalized


def serialize_pending_platform_sync(pending: Mapping[str, Any]) -> str:
    """Serialize a validated request for the launcher's isolated QGIS profile."""
    normalized = _normalize_pending_platform_sync(pending)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def parse_pending_platform_sync(value: str | None) -> dict[str, Any] | None:
    """Load a saved operation, failing closed instead of discarding an unknown result."""
    if value is None or not str(value).strip():
        return None
    try:
        payload = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("saved pending platform sync record is unreadable") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("saved pending platform sync record is unreadable")
    return _normalize_pending_platform_sync(payload)


def validate_pending_sync_revision(revision: Mapping[str, Any], pending: Mapping[str, Any]) -> int:
    """Verify that a server revision is the exact draft operation being reconciled."""
    operation = _normalize_pending_platform_sync(pending)
    if not isinstance(revision, Mapping):
        raise ValueError("server workspace revision does not match the pending sync")
    if (
        revision.get("workspace_id") != operation["workspace_id"]
        or revision.get("project_id") != operation["project_id"]
        or revision.get("study_area_id") != operation["study_area_id"]
        or revision.get("idempotency_key") != operation["idempotency_key"]
        or str(revision.get("status", "")).upper() != "DRAFT"
    ):
        raise ValueError("server workspace revision does not match the pending sync")
    expected_result_revision = operation["expected_workspace_revision"] + 1
    actual_revision = revision.get("revision")
    if isinstance(actual_revision, bool) or actual_revision != expected_result_revision:
        raise ValueError("server workspace revision does not match the pending sync")
    digest = revision.get("payload_digest")
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("server workspace revision does not match the pending sync")
    return actual_revision


def matching_pending_sync_revision(history: Any, pending: Mapping[str, Any]) -> dict[str, Any] | None:
    """Find and validate the one immutable revision carrying the saved idempotency key."""
    operation = _normalize_pending_platform_sync(pending)
    if not isinstance(history, list):
        raise ValueError("platform workspace history is not a list")
    matches = [
        item for item in history
        if isinstance(item, Mapping) and item.get("idempotency_key") == operation["idempotency_key"]
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("platform workspace history contains multiple revisions for the pending idempotency key")
    validate_pending_sync_revision(matches[0], operation)
    return dict(matches[0])


def project_id(project: Any) -> str:
    """Read the launcher's project identity from QGIS custom properties."""
    try:
        value = project.customProperty("urban_design/project_id", PROJECT_ID)
    except Exception:
        value = PROJECT_ID
    return str(value or PROJECT_ID)


def session_token() -> str:
    """Return the launch-scoped token without creating a fallback token."""
    return os.environ.get(SESSION_TOKEN_ENV, "")


def anchor_config_path() -> Path | None:
    value = os.environ.get(ANCHOR_CONFIG_ENV, "").strip()
    return Path(value).expanduser() if value else None


def load_anchor_config() -> dict[str, Any]:
    """Load the launch-selected anchor without inventing a fallback."""
    path = anchor_config_path()
    if path is None:
        raise ValueError("project geographic anchor is not configured")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("project geographic anchor is unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError("project geographic anchor must be a JSON object")
    if payload.get("project_id") != PROJECT_ID:
        raise ValueError("project geographic anchor does not match this project")
    if payload.get("horizontal_crs") != DRAFT_CRS_AUTHID or payload.get("units") != "m":
        raise ValueError("project geographic anchor CRS/units are unresolved")
    if payload.get("status") != "DRAWING_LOCATION_GUARD_ONLY":
        raise ValueError("project geographic anchor is not a drawing-location guard")
    if payload.get("context_layer_name") != CONTEXT_LAYER_NAME:
        raise ValueError("project context layer label is unresolved")
    if payload.get("context_display_only") is not True or payload.get("analysis_eligible") is not False:
        raise ValueError("project context must be display-only and analysis-ineligible")
    extent = payload.get("anchor_extent")
    if not isinstance(extent, list) or len(extent) != 4:
        raise ValueError("project anchor extent is unresolved")
    try:
        values = tuple(float(item) for item in extent)
    except (TypeError, ValueError) as exc:
        raise ValueError("project anchor extent is invalid") from exc
    if not all(math.isfinite(item) for item in values) or not values[0] < values[2] or not values[1] < values[3]:
        raise ValueError("project anchor extent is invalid")
    context_path = Path(str(payload.get("context_layer_path", "")))
    root = path.parent.parent if path.parent.name == "config" else path.parent
    context_path = context_path if context_path.is_absolute() else root / context_path
    if not context_path.is_file():
        raise ValueError("project context layer is missing")
    return payload


def project_readiness(project: Any, *, context_layer_name: str = CONTEXT_LAYER_NAME) -> tuple[str, str, str]:
    """Return independent CRS/anchor/context readiness for the QGIS UI."""
    try:
        anchor = load_anchor_config()
    except ValueError as exc:
        return "UNAVAILABLE", "UNAVAILABLE", str(exc)
    try:
        project_crs = project.crs().authid().upper()
    except Exception as exc:
        return "UNAVAILABLE", "UNAVAILABLE", f"project CRS unavailable: {exc}"
    if project_crs != DRAFT_CRS_AUTHID:
        return "UNAVAILABLE", "UNAVAILABLE", f"project CRS must be {DRAFT_CRS_AUTHID}"
    try:
        extent = project.mapLayers()
        context = next((layer for layer in extent.values() if layer.name() == context_layer_name), None)
        if context is None or not context.isValid():
            return "READY", "UNAVAILABLE", "non-authoritative context layer is unresolved"
    except Exception as exc:
        return "READY", "UNAVAILABLE", f"context layer unavailable: {exc}"
    return "READY", "READY", "drawing-location guard and display context are ready"


def geometry_bbox_ready(bounds: Any, anchor: Mapping[str, Any]) -> bool:
    """Fast UI check; the backend repeats the authoritative validation."""
    if not isinstance(bounds, (tuple, list)) or len(bounds) != 4:
        return False
    try:
        values = tuple(float(item) for item in bounds)
        extent = tuple(float(item) for item in anchor["anchor_extent"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        all(math.isfinite(item) for item in values + extent)
        and values[0] < values[2]
        and values[1] < values[3]
        and values[0] >= extent[0]
        and values[1] >= extent[1]
        and values[2] <= extent[2]
        and values[3] <= extent[3]
    )


def request_id() -> str:
    """Create a new replay/idempotency key for one user action."""
    return str(uuid.uuid4())


def capture_payload(
    *,
    instance: str,
    layer_id: str,
    fid: int,
    actor: str | None = None,
    request_id_value: str | None = None,
) -> dict[str, object]:
    """Build the only payload shape accepted by the capture endpoint.

    Keeping this helper dependency-free makes the no-geometry boundary easy to
    test outside a QGIS runtime.  ``bool`` is rejected even though it is an
    ``int`` subclass because a feature id must be an actual integer id.
    """
    if isinstance(fid, bool) or not isinstance(fid, int):
        raise ValueError("fid must be an integer")
    if not str(instance).strip():
        raise ValueError("instance is required")
    if not str(layer_id).strip():
        raise ValueError("layer_id is required")
    return {
        "instance": str(instance),
        "layer_id": str(layer_id),
        "fid": fid,
        "actor": str(actor or os.environ.get(ACTOR_ENV, "qgis-designer")),
        "actor_kind": "QGIS_PLUGIN",
        "actor_session_id": str(instance),
        "request_id": str(request_id_value or request_id()),
    }


def response_error_text(payload: Mapping[str, Any], *, fallback: str = "request failed") -> str:
    """Prefer the typed bridge message over generic HTTP/QGIS network text."""
    for key in ("message", "detail", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    code = payload.get("code")
    if isinstance(code, str) and code.strip():
        return code.strip()
    return fallback


def capture_result_kind(payload: Mapping[str, Any], error: str | None) -> str:
    """Classify a capture HTTP payload, including 503 OUTCOME_UNKNOWN bodies."""
    status = str(payload.get("status", "")).upper()
    code = str(payload.get("code", "")).upper()
    if status == "OUTCOME_UNKNOWN" or code == "OUTCOME_UNKNOWN":
        return "unknown"
    if error:
        return "error"
    return "ok"


def format_status(
    payload: Mapping[str, Any],
    *,
    anchor_status: str | None = None,
    context_status: str | None = None,
) -> str:
    """Format separate live readiness values for the compact QGIS status label."""
    values = payload.get("integrations", payload)
    if not isinstance(values, Mapping):
        return "Backend: UNKNOWN | QGIS MCP: UNKNOWN | Ladybug: UNKNOWN"

    def value(*names: str) -> str:
        for name in names:
            item = values.get(name)
            if isinstance(item, Mapping):
                item = item.get("status", item.get("state", "UNKNOWN"))
            if item is not None:
                return str(item).upper()
        return "UNKNOWN"

    result = (
        f"Backend: {value('backend')} | "
        f"QGIS MCP: {value('qgis_mcp', 'qgis-mcp')} | "
        f"Ladybug: {value('ladybug')}"
    )
    if anchor_status is not None:
        result += f" | Anchor: {str(anchor_status).upper()}"
    if context_status is not None:
        result += f" | Context: {str(context_status).upper()}"
    return result
