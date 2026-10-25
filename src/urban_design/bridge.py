"""Bounded local bridge between the QGIS MCP socket and StudyArea state.

This module is the small vertical slice used by the companion QGIS plugin.  The
plugin identifies a saved selection; it never supplies authoritative geometry.
The bridge re-reads the active layer and selection through the allow-listed
QGIS MCP commands, generates the only permitted export expression and output
path, validates the resulting GeoJSON, and then delegates the atomic state
transition to :class:`StudyAreaConfirmationService`.

The socket client below intentionally implements only the length-prefixed
protocol needed by this bridge.  It does not import or expose the broad
qgis-mcp command surface, and command names are checked against a closed set
before anything reaches the external process.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import argparse
import subprocess
import sys
from threading import RLock
from typing import Any, Literal, Protocol
from uuid import uuid4

from pyproj import CRS
from shapely.geometry import shape

from .geometry import GeometryValidationError, canonical_geometry_hash, validate_geometry
from .models import ActorKind, Project, StudyAreaStatus, canonical_units_for_crs
from .qgis_facade import (
    QgisFacadePolicy,
    QgisFacadeOperationError,
    QgisMCPFacade,
    QgisMCPPostDispatchError,
    QgisMCPPreDispatchError,
)
from .project_anchor import ProjectAnchorError, ProjectGeographicAnchor, load_project_anchor
from .store import EntityNotFoundError, ProjectStateStore
from .study_area_workflow import (
    StudyAreaConfirmationError,
    StudyAreaConfirmationService,
    StudyAreaValidationError,
    validate_study_area_artifact,
)


QGIS_MCP_VERSION = "0.14.0"
HERMES_RESERVED_PORT = 8787
DEFAULT_BRIDGE_PORT = 8788
STUDY_AREA_LAYER_NAME = "Study Area Draft"
STUDY_AREA_CRS = "EPSG:28992"
STUDY_AREA_UNITS = "m"
CAPTURE_OPERATION = "urban.capture_selected_study_area"
BRIDGE_SESSION_HEADER = "X-Urban-Design-Session-Token"

_SOCKET_HEADER = struct.Struct(">I")
_MAX_MESSAGE_SIZE = 10 * 1024 * 1024
_ALLOWED_QGIS_COMMANDS = frozenset(
    {"ping", "get_plugin_info", "get_active_layer", "get_layer_info", "get_selection", "export_layer"}
)
_RADIANCE_COMMANDS = (
    "rad",
    "rtrace",
    "rcontrib",
    "oconv",
    "rpict",
    "gensky",
    "gendaymtx",
    "rfluxmtx",
)


def validate_bridge_port(port: int) -> int:
    """Validate a bridge bind port and protect Hermes's reserved listener.

    The bridge is a local service with one documented default (8788).  Other
    explicit ports remain possible for isolated test/runtime instances, but
    8787 is never a valid Urban Design bind target because Hermes owns that
    namespace.
    """

    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Urban Design bridge port must be an integer between 1 and 65535")
    if port == HERMES_RESERVED_PORT:
        raise ValueError(
            "port 8787 is reserved for the Hermes Web UI; Urban Design bridge must use 8788 or another explicit non-Hermes port"
        )
    return port


def _listener_details(port: int) -> str:
    """Return non-secret listener ownership details when the OS can provide it."""

    lsof = shutil.which("lsof")
    if not lsof:
        return ""
    try:
        result = subprocess.run(
            [lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return result.stdout.strip()


def ensure_bridge_port_available(host: str, port: int) -> None:
    """Fail closed when the selected bind port already has a TCP listener."""

    validate_bridge_port(port)
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        addresses = []
    if not addresses:
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (host, port))]

    for family, socktype, _protocol, _canonname, sockaddr in addresses:
        probe = socket.socket(family, socktype)
        try:
            probe.bind(sockaddr)
        except OSError as exc:
            details = _listener_details(port)
            owner = f"\n{details}" if details else ""
            raise ValueError(
                f"bridge port {port} is already in use; refusing to stop or share the owner{owner}"
            ) from exc
        finally:
            probe.close()


class ReadinessStatus(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class BridgeError(RuntimeError):
    """Typed error surfaced by the HTTP bridge."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status: str = "FAILED",
        http_status: int = 422,
        request_id: str | None = None,
        dispatched: bool = False,
        retry_allowed: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = str(message)
        self.code = code
        self.status = status
        self.http_status = http_status
        self.request_id = request_id
        self.dispatched = dispatched
        self.retry_allowed = retry_allowed
        self.details = dict(details or {})

    def as_response(self) -> "BridgeErrorResponse":
        return BridgeErrorResponse(
            code=self.code,
            message=self.message,
            status=self.status,
            request_id=self.request_id,
            dispatched=self.dispatched,
            retry_allowed=self.retry_allowed,
            details=self.details,
        )


class QgisCommandError(RuntimeError):
    """A command reached QGIS and QGIS returned an application error."""


class QgisMCPTransport(Protocol):
    """Minimal injected transport contract used by the bridge."""

    def command(self, command: str, params: Mapping[str, Any] | None = None) -> Any:
        ...


try:  # Keep import errors explicit when the project runtime is incomplete.
    from pydantic import (
        BaseModel,
        ConfigDict,
        Field,
        StrictInt,
        StrictStr,
        field_validator,
        model_validator,
    )
except ImportError as exc:  # pragma: no cover - pydantic is a project dependency
    raise RuntimeError("M2-A02 requires pydantic >= 2") from exc


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class StudyAreaCaptureRequest(_StrictModel):
    """The only data a plugin may send to identify a QGIS selection."""

    instance: StrictStr
    layer_id: StrictStr
    fid: StrictInt
    actor: StrictStr
    actor_kind: Literal["QGIS_PLUGIN"]
    actor_session_id: StrictStr
    request_id: StrictStr

    @field_validator("instance", "layer_id", "actor", "actor_session_id", "request_id")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("capture identifiers and actor must be non-empty strings")
        return value.strip()

    @field_validator("fid")
    @classmethod
    def integer_fid(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("fid must be an integer")
        if value < 0:
            raise ValueError("fid must be non-negative")
        return value

    @model_validator(mode="after")
    def session_matches_instance(self) -> "StudyAreaCaptureRequest":
        if self.actor_session_id != self.instance:
            raise ValueError("QGIS actor session must match the dedicated bridge instance")
        return self


class LedgerEventReference(_StrictModel):
    event_id: str
    action: str
    target_id: str
    sequence: int = Field(ge=0)


class StudyAreaCaptureResponse(_StrictModel):
    project_id: str
    request_id: str
    instance: str
    study_area_id: str
    version: str
    artifact_id: str
    artifact_sha256: str
    geometry_sha256: str
    horizontal_crs: str
    units: str
    area_m2: float = Field(gt=0)
    status: str
    confirmation_event_id: str
    activation_event_id: str
    ledger_event_refs: list[LedgerEventReference]
    # A compact alias is useful to the QGIS plugin and keeps the response
    # explicit without making callers infer event IDs from target records.
    ledger_event_ids: list[str]

    @field_validator("area_m2")
    @classmethod
    def finite_area(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("area_m2 must be finite")
        return value


class BridgeErrorResponse(_StrictModel):
    code: str
    message: str
    status: str
    request_id: str | None = None
    dispatched: bool = False
    retry_allowed: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ComponentReadiness(_StrictModel):
    status: ReadinessStatus
    name: str
    version: str | None = None
    detail: str | None = None
    path: str | None = None


class QgisReadiness(_StrictModel):
    status: ReadinessStatus
    server_version: str | None = None
    plugin_version: str | None = None
    expected_version: str = QGIS_MCP_VERSION
    reachable: bool = False
    endpoint: str
    detail: str | None = None


class LadybugReadiness(_StrictModel):
    status: ReadinessStatus
    ladybug_core: ComponentReadiness
    ladybug_geometry: ComponentReadiness
    ladybug_radiance: ComponentReadiness
    honeybee_radiance: ComponentReadiness
    radiance_executables: ComponentReadiness


class IntegrationStatusResponse(_StrictModel):
    status: ReadinessStatus
    checked_at: datetime
    instance: str
    backend: ComponentReadiness
    qgis_mcp: QgisReadiness
    ladybug: LadybugReadiness
    anchor: ComponentReadiness | None = None
    context: ComponentReadiness | None = None


class SocketQgisMCPTransport:
    """Small, strict client for the qgis-mcp 0.14.0 framed socket."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9876,
        *,
        token: str | None = None,
        timeout: float = 30.0,
        server_version: str = QGIS_MCP_VERSION,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.token = token
        self.timeout = float(timeout)
        self.server_version = server_version
        self._socket: socket.socket | None = None
        self._command_sent = False

    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"

    def connect(self) -> None:
        if self._socket is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(min(self.timeout, 3.0))
        try:
            sock.connect((self.host, self.port))
            sock.settimeout(self.timeout)
        except Exception as exc:
            try:
                sock.close()
            finally:
                self._socket = None
            raise QgisMCPPreDispatchError(f"could not connect to QGIS MCP at {self.endpoint}: {exc}") from exc
        self._socket = sock

    def close(self) -> None:
        sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _receive_exact(self, size: int) -> bytes:
        if size < 0 or size > _MAX_MESSAGE_SIZE:
            raise ValueError("QGIS MCP response exceeds the bounded message size")
        if self._socket is None:
            raise QgisMCPPreDispatchError("QGIS MCP socket is not connected")
        result = bytearray()
        while len(result) < size:
            block = self._socket.recv(min(65536, size - len(result)))
            if not block:
                raise ConnectionError("QGIS MCP connection closed")
            result.extend(block)
        return bytes(result)

    def command(self, command: str, params: Mapping[str, Any] | None = None) -> Any:
        if command not in _ALLOWED_QGIS_COMMANDS:
            raise PermissionError(f"QGIS MCP command denied by bridge allowlist: {command}")
        self.connect()
        if self._socket is None:  # pragma: no cover - connect either returns or raises
            raise QgisMCPPreDispatchError("QGIS MCP socket is unavailable")
        request: dict[str, Any] = {"type": command, "params": dict(params or {})}
        if self.token:
            request["token"] = self.token
        encoded = json.dumps(request, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > _MAX_MESSAGE_SIZE:
            raise ValueError("QGIS MCP request exceeds the bounded message size")
        self._command_sent = True
        try:
            self._socket.sendall(_SOCKET_HEADER.pack(len(encoded)))
            self._socket.sendall(encoded)
            length = _SOCKET_HEADER.unpack(self._receive_exact(4))[0]
            response = json.loads(self._receive_exact(length).decode("utf-8"))
            return response
        except (QgisMCPPreDispatchError, QgisMCPPostDispatchError):
            raise
        except Exception as exc:
            self.close()
            raise QgisMCPPostDispatchError(f"QGIS MCP connection lost after dispatch: {exc}") from exc

    def probe(self) -> dict[str, Any]:
        self.command("ping")
        plugin = self.command("get_plugin_info", {"plugin_name": "qgis_mcp_plugin"})
        plugin_result = _unwrap_qgis_response(plugin, "get_plugin_info")
        return {
            "reachable": True,
            "server_version": self.server_version,
            "plugin_version": plugin_result.get("version") if isinstance(plugin_result, Mapping) else None,
        }


class BoundedQgisMCPAdapter:
    """Normalize an injected fake or socket transport without widening it."""

    def __init__(self, transport: Any, *, endpoint: str = "localhost:9876") -> None:
        self.transport = transport
        self.endpoint = endpoint
        self._completed_commands = 0

    def _invoke(self, command: str, params: Mapping[str, Any]) -> Any:
        if command not in _ALLOWED_QGIS_COMMANDS:
            raise PermissionError(f"QGIS MCP command denied by bridge allowlist: {command}")
        try:
            if hasattr(self.transport, "send_command"):
                return self.transport.send_command(command, dict(params))
            if hasattr(self.transport, "command"):
                return self.transport.command(command, dict(params))
            method = getattr(self.transport, command)
            if command == "ping":
                return method()
            return method(**dict(params))
        except QgisMCPPreDispatchError:
            raise
        except QgisMCPPostDispatchError:
            raise
        except ConnectionError as exc:
            # A generic fake transport can still express the important phase:
            # the first failed command is pre-dispatch; a later lost command is
            # uncertain because earlier QGIS commands already ran.
            if self._completed_commands == 0:
                raise QgisMCPPreDispatchError(str(exc)) from exc
            raise QgisMCPPostDispatchError(str(exc)) from exc

    def command(self, command: str, params: Mapping[str, Any] | None = None) -> Any:
        response = self._invoke(command, params or {})
        self._completed_commands += 1
        return _unwrap_qgis_response(response, command)

    def probe(self) -> dict[str, Any]:
        probe_method = getattr(self.transport, "probe", None)
        if callable(probe_method):
            try:
                result = probe_method()
            except QgisMCPPreDispatchError:
                raise
            except QgisMCPPostDispatchError:
                raise
            except ConnectionError as exc:
                raise QgisMCPPreDispatchError(str(exc)) from exc
            if not isinstance(result, Mapping):
                raise QgisCommandError("QGIS MCP probe returned a non-object")
            return dict(result)
        self.command("ping")
        plugin = self.command("get_plugin_info", {"plugin_name": "qgis_mcp_plugin"})
        return {
            "reachable": True,
            "server_version": getattr(self.transport, "server_version", QGIS_MCP_VERSION),
            "plugin_version": plugin.get("version") if isinstance(plugin, Mapping) else None,
        }

    def close(self) -> None:
        close = getattr(self.transport, "close", None) or getattr(self.transport, "disconnect", None)
        if callable(close):
            close()


def _unwrap_qgis_response(response: Any, command: str) -> Any:
    """Accept qgis-mcp's envelope, while keeping errors fail-closed."""

    if not isinstance(response, Mapping):
        raise QgisCommandError(f"QGIS MCP {command} returned a non-object response")
    status = response.get("status")
    if isinstance(status, str):
        if status.casefold() not in {"success", "ok"}:
            raise QgisCommandError(str(response.get("message") or f"QGIS MCP {command} failed"))
        result = response.get("result", {})
        if not isinstance(result, Mapping):
            raise QgisCommandError(f"QGIS MCP {command} result must be an object")
        return result
    return response


def _extract_crs(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, Mapping):
        properties = value.get("properties")
        if isinstance(properties, Mapping):
            for key in ("name", "href", "code"):
                item = properties.get(key)
                if isinstance(item, str) and item.strip():
                    return item.strip()
        for key in ("name", "href", "code"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None


def _extract_units(value: Mapping[str, Any]) -> str | None:
    for key in ("units", "linear_units", "unit"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    metadata = value.get("metadata")
    if isinstance(metadata, Mapping):
        item = metadata.get("units")
        if isinstance(item, str) and item.strip():
            return item.strip()
    return None


def _verified_crs(value: Any, units: Any = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BridgeError("QGIS layer CRS is missing", code="CRS_MISSING", http_status=422)
    try:
        actual = CRS.from_user_input(value)
        expected = CRS.from_user_input(STUDY_AREA_CRS)
    except Exception as exc:
        raise BridgeError("QGIS layer CRS is invalid", code="CRS_INVALID", http_status=422) from exc
    if not actual.equals(expected):
        raise BridgeError(
            f"QGIS layer CRS must be {STUDY_AREA_CRS}",
            code="CRS_MISMATCH",
            http_status=422,
            details={"observed_crs": value, "expected_crs": STUDY_AREA_CRS},
        )
    try:
        canonical_units_for_crs(STUDY_AREA_CRS, STUDY_AREA_UNITS)
    except ValueError as exc:  # pragma: no cover - locked project constant
        raise BridgeError("Study Area CRS does not expose metre axes", code="CRS_UNITS_INVALID") from exc
    if units is not None:
        try:
            observed_units = canonical_units_for_crs(STUDY_AREA_CRS, str(units))
        except ValueError as exc:
            raise BridgeError(
                "QGIS layer units must be metres for EPSG:28992",
                code="CRS_UNITS_MISMATCH",
                http_status=422,
                details={"observed_units": units, "expected_units": STUDY_AREA_UNITS},
            ) from exc
        if observed_units != STUDY_AREA_UNITS:
            raise BridgeError(
                "QGIS layer units must be metres for EPSG:28992",
                code="CRS_UNITS_MISMATCH",
                http_status=422,
            )
    return STUDY_AREA_CRS


def _is_polygon_geometry_type(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value == 2  # QgsWkbTypes.GeometryType.Polygon
    if isinstance(value, str):
        folded = value.casefold().replace("_", " ").replace("-", " ").strip()
        return folded in {"polygon", "multipolygon", "multi polygon"} or folded.endswith(" polygon")
    return False


def _is_vector_layer_type(value: Any) -> bool:
    """Accept qgis-mcp's vector type labels, including ``vector_<geometry>``."""

    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value == 0  # QgsMapLayer.VectorLayer
    if isinstance(value, str):
        folded = value.casefold().replace("_", " ").replace("-", " ").strip()
        return folded == "vector" or folded.startswith("vector ")
    return False


def _canonical_export_payload(payload: Mapping[str, Any], expected_crs: str) -> dict[str, Any]:
    payload_type = payload.get("type")
    feature: Mapping[str, Any] | None = None
    if payload_type == "FeatureCollection":
        features = payload.get("features")
        if not isinstance(features, list) or len(features) != 1 or not isinstance(features[0], Mapping):
            raise BridgeError(
                "QGIS export must contain exactly one selected feature",
                code="EXPORT_SELECTION_MISMATCH",
                http_status=422,
            )
        feature = features[0]
    elif payload_type == "Feature":
        feature = payload
    elif payload_type in {"Polygon", "MultiPolygon"}:
        feature = {"type": "Feature", "geometry": payload, "properties": {}}
    else:
        raise BridgeError("QGIS export is not GeoJSON Feature data", code="EXPORT_INVALID", http_status=422)

    embedded_crs = _extract_crs(payload.get("crs"))
    if embedded_crs is None and isinstance(feature, Mapping):
        embedded_crs = _extract_crs(feature.get("crs"))
    if embedded_crs is not None:
        try:
            if not CRS.from_user_input(embedded_crs).equals(CRS.from_user_input(expected_crs)):
                raise BridgeError(
                    "exported GeoJSON CRS does not match the independently verified layer",
                    code="EXPORT_CRS_MISMATCH",
                    http_status=422,
                )
        except BridgeError:
            raise
        except Exception as exc:
            raise BridgeError("exported GeoJSON CRS is invalid", code="EXPORT_CRS_INVALID", http_status=422) from exc
    embedded_units = _extract_units(payload)
    if embedded_units is not None:
        try:
            if canonical_units_for_crs(expected_crs, embedded_units) != STUDY_AREA_UNITS:
                raise BridgeError("exported GeoJSON units are not metres", code="EXPORT_UNITS_MISMATCH", http_status=422)
        except BridgeError:
            raise
        except ValueError as exc:
            raise BridgeError("exported GeoJSON units are invalid", code="EXPORT_UNITS_INVALID", http_status=422) from exc

    geometry = feature.get("geometry") if isinstance(feature, Mapping) else None
    if not isinstance(geometry, Mapping) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise BridgeError("selected QGIS feature must have polygon geometry", code="GEOMETRY_NOT_POLYGON", http_status=422)
    geometry = {"type": geometry.get("type"), "coordinates": geometry.get("coordinates")}
    try:
        validate_geometry(geometry)
        planar = shape(geometry)
    except (GeometryValidationError, TypeError, ValueError) as exc:
        raise BridgeError(f"selected QGIS geometry is invalid: {exc}", code="GEOMETRY_INVALID", http_status=422) from exc
    if planar.is_empty or not planar.is_valid or not math.isfinite(float(planar.area)) or float(planar.area) <= 0:
        raise BridgeError("selected QGIS polygon must be non-empty and valid", code="GEOMETRY_INVALID", http_status=422)
    properties = feature.get("properties", {}) if isinstance(feature, Mapping) else {}
    if not isinstance(properties, Mapping):
        properties = {}
    # Keep only deterministic JSON data from the exported feature.  Geometry
    # remains the authoritative content; properties are retained for audit
    # context but never interpreted as design measurements.
    try:
        json.dumps(properties, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise BridgeError("exported feature properties are not JSON-safe", code="EXPORT_INVALID", http_status=422) from exc
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": dict(properties),
        "crs": {"type": "name", "properties": {"name": expected_crs}},
        "units": STUDY_AREA_UNITS,
    }


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _package_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _component_readiness(distribution: str, import_name: str, label: str) -> ComponentReadiness:
    version = _package_version(distribution)
    if version is None:
        return ComponentReadiness(status=ReadinessStatus.UNAVAILABLE, name=label, detail=f"{distribution} is not installed")
    try:
        importlib.import_module(import_name)
    except Exception as exc:
        return ComponentReadiness(status=ReadinessStatus.DEGRADED, name=label, version=version, detail=f"import failed: {exc}")
    return ComponentReadiness(status=ReadinessStatus.READY, name=label, version=version)


def _ladybug_readiness() -> LadybugReadiness:
    core = _component_readiness("ladybug-core", "ladybug", "ladybug-core")
    geometry = _component_readiness("ladybug-geometry", "ladybug_geometry", "ladybug-geometry")
    radiance = _component_readiness("ladybug-radiance", "ladybug_radiance", "ladybug-radiance")
    honeybee = _component_readiness("honeybee-radiance", "honeybee_radiance", "honeybee-radiance")

    configured_bin: Path | None = None
    try:
        from honeybee_radiance.config import folders

        raw = getattr(folders, "radbin_path", None)
        if raw:
            configured_bin = Path(raw)
    except Exception:
        configured_bin = None
    paths: dict[str, str] = {}
    missing: list[str] = []
    for executable in _RADIANCE_COMMANDS:
        candidate = configured_bin / executable if configured_bin is not None else None
        if candidate is not None and candidate.is_file() and os.access(candidate, os.X_OK):
            paths[executable] = str(candidate)
            continue
        found = shutil.which(executable)
        if found:
            paths[executable] = str(Path(found).resolve())
        else:
            missing.append(executable)
    if len(paths) == len(_RADIANCE_COMMANDS):
        executable_status = ReadinessStatus.READY
        executable_detail = "all required Radiance executables are available"
    elif paths:
        executable_status = ReadinessStatus.DEGRADED
        executable_detail = "some required Radiance executables are unavailable: " + ", ".join(missing)
    else:
        executable_status = ReadinessStatus.UNAVAILABLE
        executable_detail = "required Radiance executables are unavailable"
    executable_component = ComponentReadiness(
        status=executable_status,
        name="Radiance executables",
        detail=executable_detail,
        path=json.dumps(paths, sort_keys=True),
    )
    components = (core, geometry, radiance, honeybee, executable_component)
    if all(item.status is ReadinessStatus.READY for item in components):
        overall = ReadinessStatus.READY
    elif any(item.status is not ReadinessStatus.UNAVAILABLE for item in components):
        overall = ReadinessStatus.DEGRADED
    else:
        overall = ReadinessStatus.UNAVAILABLE
    return LadybugReadiness(
        status=overall,
        ladybug_core=core,
        ladybug_geometry=geometry,
        ladybug_radiance=radiance,
        honeybee_radiance=honeybee,
        radiance_executables=executable_component,
    )


@dataclass
class _RequestEntry:
    fingerprint: str
    outcome: StudyAreaCaptureResponse | BridgeError | None = None


class StudyAreaBridge:
    """Application service implementing the bounded capture command."""

    def __init__(
        self,
        store: ProjectStateStore,
        *,
        artifact_root: str | Path,
        qgis_transport: Any | None = None,
        qgis_host: str = "localhost",
        qgis_port: int = 9876,
        qgis_token: str | None = None,
        qgis_server_version: str | None = None,
        instance_id: str = "urban-design-local",
        session_token: str | None = None,
        initialize_project: bool = False,
        default_project_id: str = "rotterdam-m4h-pilot-project",
        project_anchor: ProjectGeographicAnchor | None = None,
        anchor_config_path: str | Path | None = None,
        anchor_root: str | Path | None = None,
    ) -> None:
        if not isinstance(store, ProjectStateStore):
            raise TypeError("store must be a ProjectStateStore")
        self.store = store
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.instance_id = self._text(instance_id, "instance_id")
        self.session_token = session_token.strip() if isinstance(session_token, str) and session_token.strip() else None
        if qgis_transport is None:
            qgis_transport = SocketQgisMCPTransport(
                host=qgis_host,
                port=qgis_port,
                token=qgis_token or self.session_token,
                server_version=qgis_server_version or QGIS_MCP_VERSION,
            )
        self.qgis = BoundedQgisMCPAdapter(qgis_transport, endpoint=f"{qgis_host}:{qgis_port}")
        self.qgis_server_version = qgis_server_version or getattr(qgis_transport, "server_version", None) or QGIS_MCP_VERSION
        self.anchor_config_path = str(anchor_config_path) if anchor_config_path is not None else None
        self.project_anchor = project_anchor
        self.anchor_error: str | None = None
        if anchor_config_path is not None:
            try:
                self.project_anchor = load_project_anchor(
                    anchor_config_path,
                    root=anchor_root or Path(anchor_config_path).expanduser().resolve().parent,
                )
            except (OSError, ProjectAnchorError, ValueError) as exc:
                self.project_anchor = None
                self.anchor_error = str(exc)
        elif project_anchor is not None:
            try:
                resolved_anchor_root = anchor_root or Path.cwd()
                project_anchor.validate_context_files(root=resolved_anchor_root)
                project_anchor.validate_source_provenance(root=resolved_anchor_root)
            except (OSError, ProjectAnchorError, ValueError) as exc:
                self.project_anchor = None
                self.anchor_error = str(exc)
        self.confirmation_service = StudyAreaConfirmationService(
            self.store,
            artifact_root=self.artifact_root,
            project_anchor=self.project_anchor,
        )
        policy = QgisFacadePolicy(
            approved_input_roots=(self.artifact_root,),
            run_output_root=self.artifact_root,
            allowed_operations=frozenset({CAPTURE_OPERATION}),
        )
        self.facade = QgisMCPFacade(policy, self._dispatch_domain)
        self._lock = RLock()
        self._requests: dict[str, _RequestEntry] = {}
        if initialize_project:
            self.ensure_project(default_project_id)

    @staticmethod
    def _text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()

    def _require_project_anchor(self, project_id: str) -> None:
        """Require a configured and source-verified anchor when one was supplied."""

        if self.anchor_config_path is None and self.project_anchor is None and self.anchor_error is None:
            return
        if self.anchor_error is not None or self.project_anchor is None:
            raise BridgeError(
                "project geographic anchor is unresolved; refusing StudyArea capture",
                code="PROJECT_ANCHOR_UNRESOLVED",
                status="REJECTED",
                http_status=422,
                details={"reason": self.anchor_error or "anchor configuration is missing"},
            )
        if self.project_anchor.project_id != project_id:
            raise BridgeError(
                "project geographic anchor does not match the capture project",
                code="PROJECT_ANCHOR_PROJECT_MISMATCH",
                status="REJECTED",
                http_status=422,
            )

    def _anchor_readiness(self) -> ComponentReadiness:
        if self.anchor_error is not None:
            return ComponentReadiness(
                status=ReadinessStatus.UNAVAILABLE,
                name="Project geographic anchor",
                detail=self.anchor_error,
                path=self.anchor_config_path,
            )
        if self.project_anchor is None:
            return ComponentReadiness(
                status=ReadinessStatus.DEGRADED,
                name="Project geographic anchor",
                detail="no project-specific anchor configured",
            )
        return ComponentReadiness(
            status=ReadinessStatus.READY,
            name="Project geographic anchor",
            detail="drawing-location guard only; not analysis-eligible",
            path=self.anchor_config_path,
        )

    def _context_readiness(self) -> ComponentReadiness:
        if self.anchor_error is not None or self.project_anchor is None:
            return ComponentReadiness(
                status=ReadinessStatus.UNAVAILABLE,
                name="Non-authoritative drawing context",
                detail="project anchor is unresolved",
            )
        return ComponentReadiness(
            status=ReadinessStatus.READY,
            name=self.project_anchor.context_layer_name,
            detail="display-only; excluded from analysis snapshots",
            path=self.project_anchor.context_layer_path,
        )

    def ensure_project(self, project_id: str, *, name: str | None = None) -> None:
        project_id = self._text(project_id, "project_id")
        try:
            record = self.store.current(project_id)
        except EntityNotFoundError:
            self.store.create_typed(
                Project(id=project_id, name=name or project_id),
                actor="launcher",
                actor_kind=ActorKind.AGENT_AUTOMATION,
                actor_session_id=self.instance_id,
                reason="initialize the local M2-A02 project",
            )
            return
        if record.entity_type != "Project":
            raise BridgeError(f"{project_id!r} is not a Project", code="PROJECT_INVALID", http_status=409)

    def _fingerprint(self, project_id: str, request: StudyAreaCaptureRequest) -> str:
        encoded = json.dumps(
            {"project_id": project_id, **request.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def _cached_or_persisted(
        self, project_id: str, request: StudyAreaCaptureRequest, fingerprint: str
    ) -> StudyAreaCaptureResponse | BridgeError | None:
        entry = self._requests.get(request.request_id)
        if entry is not None:
            if entry.fingerprint != fingerprint:
                raise BridgeError(
                    "request_id was already used for different capture input",
                    code="REQUEST_ID_CONFLICT",
                    status="REJECTED",
                    http_status=409,
                    request_id=request.request_id,
                )
            return entry.outcome
        # The confirmation event stores the request fingerprint so idempotency
        # survives a bridge process restart without creating a second version.
        try:
            events = self.store.events(project_id=project_id)
        except Exception:
            events = []
        for event in reversed(events):
            if event.action.casefold() != "confirmstudyarea":
                continue
            if event.payload.get("capture_request_id") != request.request_id:
                continue
            if event.payload.get("capture_request_fingerprint") != fingerprint:
                raise BridgeError(
                    "request_id was already used for different capture input",
                    code="REQUEST_ID_CONFLICT",
                    status="REJECTED",
                    http_status=409,
                    request_id=request.request_id,
                )
            try:
                response = self._response_from_record(project_id, request, self.store.current(event.target_id))
            except Exception:
                # A partial or hand-edited event cannot authorize a replay.
                continue
            self._requests[request.request_id] = _RequestEntry(fingerprint=fingerprint, outcome=response)
            return response
        return None

    def capture(self, project_id: str, request: StudyAreaCaptureRequest) -> StudyAreaCaptureResponse:
        project_id = self._text(project_id, "project_id")
        if request.instance != self.instance_id:
            raise BridgeError(
                "capture instance does not match this dedicated QGIS session",
                code="INSTANCE_MISMATCH",
                status="REJECTED",
                http_status=409,
                request_id=request.request_id,
                details={"expected_instance": self.instance_id, "observed_instance": request.instance},
            )
        # Resolve the route target before entering the QGIS facade so a bad
        # project identifier remains a typed 404/409 domain error rather than
        # being misreported as a transport outage.
        try:
            project = self.store.current(project_id)
        except EntityNotFoundError as exc:
            raise BridgeError(
                f"project {project_id!r} does not exist",
                code="PROJECT_NOT_FOUND",
                http_status=404,
                request_id=request.request_id,
            ) from exc
        if project.entity_type != "Project":
            raise BridgeError(
                f"{project_id!r} is not a Project",
                code="PROJECT_INVALID",
                status="REJECTED",
                http_status=409,
                request_id=request.request_id,
            )
        # Configuration failures are rejected before the facade is entered so
        # they cannot be misclassified as a dispatched QGIS operation.
        self._require_project_anchor(project_id)
        fingerprint = self._fingerprint(project_id, request)
        # Keep the lock through the external sequence.  This prevents two
        # clicks from interleaving QGIS selection state or confirmation writes.
        with self._lock:
            cached = self._cached_or_persisted(project_id, request, fingerprint)
            if isinstance(cached, StudyAreaCaptureResponse):
                return cached
            if isinstance(cached, BridgeError):
                raise cached
            self._requests[request.request_id] = _RequestEntry(fingerprint=fingerprint)
            result = self.facade.execute(
                CAPTURE_OPERATION,
                {"project_id": project_id, **request.model_dump(mode="json")},
                request_id=request.request_id,
            )
            if result.status == "SUCCEEDED":
                try:
                    response = StudyAreaCaptureResponse.model_validate(result.response)
                except Exception as exc:
                    error = BridgeError(
                        f"bridge produced an invalid capture response: {exc}",
                        code="BRIDGE_RESPONSE_INVALID",
                        status="FAILED",
                        http_status=500,
                        request_id=request.request_id,
                        dispatched=True,
                    )
                    self._requests[request.request_id].outcome = error
                    raise error
                self._requests[request.request_id].outcome = response
                return response
            if result.status == "OUTCOME_UNKNOWN":
                error = BridgeError(
                    result.reason or "QGIS MCP outcome is unknown after dispatch",
                    code="OUTCOME_UNKNOWN",
                    status="OUTCOME_UNKNOWN",
                    http_status=503,
                    request_id=request.request_id,
                    dispatched=True,
                    retry_allowed=False,
                )
            elif not result.dispatched:
                error = BridgeError(
                    result.reason or "QGIS MCP was unavailable before dispatch",
                    code="QGIS_MCP_UNAVAILABLE",
                    status="FAILED",
                    http_status=503,
                    request_id=request.request_id,
                    dispatched=False,
                    retry_allowed=True,
                )
            else:
                error = BridgeError(
                    result.reason or "StudyArea capture was rejected",
                    code="CAPTURE_REJECTED",
                    status="FAILED",
                    http_status=422,
                    request_id=request.request_id,
                    dispatched=True,
                )
            self._requests[request.request_id].outcome = error
            raise error

    def _dispatch_domain(self, operation: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if operation != CAPTURE_OPERATION:
            raise PermissionError(f"domain operation denied: {operation}")
        project_id = request.get("project_id")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("capture project_id is required")
        request_payload = dict(request)
        request_payload.pop("project_id", None)
        capture_request = StudyAreaCaptureRequest.model_validate(request_payload)
        try:
            return self._capture_uncached(project_id.strip(), capture_request)
        except BridgeError as exc:
            raise QgisFacadeOperationError(
                exc.message,
                status=exc.status,
                dispatched=exc.dispatched or self.qgis._completed_commands > 0,
                retry_allowed=exc.retry_allowed,
            ) from exc

    def _capture_uncached(self, project_id: str, request: StudyAreaCaptureRequest) -> dict[str, Any]:
        try:
            project = self.store.current(project_id)
        except EntityNotFoundError as exc:
            raise BridgeError(f"project {project_id!r} does not exist", code="PROJECT_NOT_FOUND", http_status=404) from exc
        if project.entity_type != "Project":
            raise BridgeError(f"{project_id!r} is not a Project", code="PROJECT_INVALID", http_status=409)
        self._require_project_anchor(project_id)

        active = self.qgis.command("get_active_layer")
        if not active.get("active"):
            raise BridgeError("QGIS has no active layer", code="ACTIVE_LAYER_REQUIRED", http_status=422)
        if active.get("layer_id") != request.layer_id:
            raise BridgeError("active QGIS layer does not match the request", code="ACTIVE_LAYER_MISMATCH", http_status=422)
        if active.get("name") != STUDY_AREA_LAYER_NAME:
            raise BridgeError(
                f"active QGIS layer must be named {STUDY_AREA_LAYER_NAME}",
                code="DEDICATED_LAYER_REQUIRED",
                http_status=422,
            )

        info = self.qgis.command("get_layer_info", {"layer_id": request.layer_id})
        if info.get("id", request.layer_id) != request.layer_id or info.get("name") != STUDY_AREA_LAYER_NAME:
            raise BridgeError("QGIS layer identity changed during capture", code="LAYER_IDENTITY_CHANGED", http_status=422)
        if not _is_vector_layer_type(info.get("type")):
            raise BridgeError("Study Area layer must be a vector layer", code="LAYER_NOT_VECTOR", http_status=422)
        if not _is_polygon_geometry_type(info.get("geometry_type")):
            raise BridgeError("Study Area layer geometry type must be polygon", code="LAYER_NOT_POLYGON", http_status=422)
        expected_crs = _verified_crs(info.get("crs"), info.get("units"))

        selection = self.qgis.command("get_selection", {"layer_id": request.layer_id})
        fids = selection.get("fids")
        count = selection.get("count")
        if not isinstance(fids, list) or not isinstance(count, int) or count != 1 or len(fids) != 1:
            raise BridgeError("QGIS selection must contain exactly one saved feature", code="SELECTION_COUNT_INVALID", http_status=422)
        if fids[0] != request.fid:
            raise BridgeError(
                "selected QGIS FID does not match the request",
                code="FID_MISMATCH",
                http_status=422,
                details={"selected_fid": fids[0], "requested_fid": request.fid},
            )

        request_digest = hashlib.sha256(f"{project_id}\0{request.request_id}".encode("utf-8")).hexdigest()
        export_path = self.artifact_root / "qgis-exports" / f"{request_digest}.geojson"
        canonical_path = self.artifact_root / "study-areas" / f"{request_digest}.geojson"
        generated_expression = f"$id = {request.fid:d}"
        # qgis-mcp's export command writes directly to the caller-provided
        # path and does not create parent directories.  Create only the
        # bridge-owned artifact directories before dispatch; callers cannot
        # supply either path or filter expression.
        export_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        self.qgis.command(
            "export_layer",
            {
                "layer_id": request.layer_id,
                "output_path": str(export_path),
                "target_crs": None,
                "filter_expression": generated_expression,
            },
        )
        if not export_path.is_file():
            raise BridgeError("QGIS export did not produce the controlled GeoJSON", code="EXPORT_MISSING", http_status=422)
        try:
            exported = json.loads(export_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BridgeError("QGIS export is not readable UTF-8 GeoJSON", code="EXPORT_INVALID", http_status=422) from exc
        if not isinstance(exported, Mapping):
            raise BridgeError("QGIS export must be a JSON object", code="EXPORT_INVALID", http_status=422)
        canonical = _canonical_export_payload(exported, expected_crs)
        _write_json_atomic(canonical_path, canonical)
        try:
            validated = validate_study_area_artifact(
                canonical_path,
                horizontal_crs=expected_crs,
                units=STUDY_AREA_UNITS,
                artifact_root=self.artifact_root,
                project_anchor=self.project_anchor,
            )
        except (StudyAreaValidationError, OSError, ValueError) as exc:
            raise BridgeError(f"retained StudyArea GeoJSON failed validation: {exc}", code="ARTIFACT_INVALID", http_status=422) from exc
        try:
            area = float(shape(validated.geometry).area)
        except Exception as exc:
            raise BridgeError("retained StudyArea geometry area could not be calculated", code="GEOMETRY_INVALID", http_status=422) from exc
        try:
            study_area = self.confirmation_service.confirm(
                project_id,
                actor=request.actor,
                actor_kind=ActorKind.QGIS_PLUGIN,
                actor_session_id=request.actor_session_id,
                artifact_path=canonical_path,
                confirmed_at=datetime.now(timezone.utc),
                reason="Human confirmed the selected QGIS Study Area through the bounded bridge",
                confirmation_payload={
                    "capture_request_id": request.request_id,
                    "capture_request_fingerprint": self._fingerprint(project_id, request),
                    "capture_instance": request.instance,
                    "capture_layer_id": request.layer_id,
                    "capture_fid": request.fid,
                },
            )
        except (StudyAreaConfirmationError, StudyAreaValidationError, ValueError) as exc:
            raise BridgeError(f"StudyArea confirmation failed atomically: {exc}", code="CONFIRMATION_FAILED", http_status=422) from exc
        return self._response_from_record(project_id, request, self.store.current(study_area.id), area_override=area).model_dump(mode="json")

    def _response_from_record(
        self,
        project_id: str,
        request: StudyAreaCaptureRequest,
        record: Any,
        *,
        area_override: float | None = None,
    ) -> StudyAreaCaptureResponse:
        if getattr(record, "entity_type", None) != "StudyArea":
            raise ValueError("capture event target is not a StudyArea")
        payload = record.payload
        artifact_id = payload.get("geometry_artifact_id")
        artifact = self.store.current(artifact_id)
        if artifact.entity_type != "Artifact":
            raise ValueError("StudyArea artifact is not an Artifact")
        if area_override is None:
            artifact_uri = artifact.get("uri")
            validated = validate_study_area_artifact(
                artifact_uri,
                expected_sha256=artifact.get("sha256"),
                horizontal_crs=payload.get("horizontal_crs"),
                units=payload.get("units"),
                expected_geometry_sha256=payload.get("geometry_sha256"),
                artifact_root=self.artifact_root,
            )
            area_override = float(shape(validated.geometry).area)
        events = self.store.events(project_id=project_id)
        activation = next(
            (
                event
                for event in reversed(events)
                if event.action.casefold() == "activatestudyarea"
                and event.payload.get("active_study_area_id") == record.entity_id
                and event.payload.get("confirmation_event_id") == payload.get("confirmation_event_id")
            ),
            None,
        )
        if activation is None:
            raise ValueError("StudyArea activation event is missing")
        relevant = [
            event
            for event in events
            if event.event_id in {record.event_id, payload.get("confirmation_event_id"), activation.event_id}
            or event.target_id == record.entity_id
            or record.entity_id in event.changed_refs
        ]
        refs = [
            LedgerEventReference(event_id=e.event_id, action=e.action, target_id=e.target_id, sequence=e.sequence)
            for e in relevant
        ]
        return StudyAreaCaptureResponse(
            project_id=project_id,
            request_id=request.request_id,
            instance=request.instance,
            study_area_id=record.entity_id,
            version=str(payload.get("version")),
            artifact_id=str(artifact_id),
            artifact_sha256=str(payload.get("artifact_sha256") or artifact.get("sha256")),
            geometry_sha256=str(payload.get("geometry_sha256")),
            horizontal_crs=str(payload.get("horizontal_crs")),
            units=str(payload.get("units")),
            area_m2=float(area_override),
            status=str(payload.get("status", StudyAreaStatus.CONFIRMED_FOR_EXPLORATION.value)),
            confirmation_event_id=str(payload.get("confirmation_event_id")),
            activation_event_id=activation.event_id,
            ledger_event_refs=refs,
            ledger_event_ids=[item.event_id for item in refs],
        )

    def integration_status(self) -> IntegrationStatusResponse:
        checked_at = datetime.now(timezone.utc)
        backend = ComponentReadiness(status=ReadinessStatus.READY, name="FastAPI bridge", version="m2-a02")
        try:
            probe = self.qgis.probe()
            server_version = str(probe.get("server_version")) if probe.get("server_version") is not None else None
            plugin_version = str(probe.get("plugin_version")) if probe.get("plugin_version") is not None else None
            reachable = bool(probe.get("reachable", True))
            if reachable and server_version == QGIS_MCP_VERSION and plugin_version == QGIS_MCP_VERSION:
                qgis_status = ReadinessStatus.READY
                detail = "qgis-mcp server and QGIS plugin versions match the pinned route"
            elif reachable:
                qgis_status = ReadinessStatus.DEGRADED
                detail = "qgis-mcp server/plugin version mismatch"
            else:
                qgis_status = ReadinessStatus.UNAVAILABLE
                detail = "QGIS MCP reported unreachable"
        except (QgisMCPPreDispatchError, QgisMCPPostDispatchError, ConnectionError, QgisCommandError) as exc:
            server_version = getattr(self.qgis.transport, "server_version", self.qgis_server_version)
            plugin_version = None
            reachable = False
            qgis_status = ReadinessStatus.UNAVAILABLE
            detail = str(exc)
        qgis = QgisReadiness(
            status=qgis_status,
            server_version=server_version,
            plugin_version=plugin_version,
            reachable=reachable,
            endpoint=self.qgis.endpoint,
            detail=detail,
        )
        ladybug = _ladybug_readiness()
        if qgis.status is ReadinessStatus.READY and ladybug.status is ReadinessStatus.READY:
            overall = ReadinessStatus.READY
        elif qgis.status is ReadinessStatus.UNAVAILABLE and ladybug.status is ReadinessStatus.UNAVAILABLE:
            overall = ReadinessStatus.UNAVAILABLE
        else:
            overall = ReadinessStatus.DEGRADED
        return IntegrationStatusResponse(
            status=overall,
            checked_at=checked_at,
            instance=self.instance_id,
            backend=backend,
            qgis_mcp=qgis,
            ladybug=ladybug,
            anchor=self._anchor_readiness(),
            context=self._context_readiness(),
        )


def create_app(
    *,
    store: ProjectStateStore | None = None,
    artifact_root: str | Path | None = None,
    database_path: str | Path | None = None,
    qgis_transport: Any | None = None,
    qgis_host: str = "localhost",
    qgis_port: int = 9876,
    qgis_token: str | None = None,
    qgis_server_version: str | None = None,
    instance_id: str = "urban-design-local",
    session_token: str | None = None,
    initialize_project: bool = False,
    default_project_id: str = "rotterdam-m4h-pilot-project",
    project_anchor: ProjectGeographicAnchor | None = None,
    anchor_config_path: str | Path | None = None,
    anchor_root: str | Path | None = None,
):
    """Create the local FastAPI application with explicit injected boundaries."""

    from fastapi import FastAPI, Header, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    if store is None:
        db_path = Path(database_path or Path.cwd() / "state.sqlite3")
        store = ProjectStateStore(db_path)
    root = Path(artifact_root or Path.cwd() / "artifacts" / "study-area-bridge")
    bridge = StudyAreaBridge(
        store,
        artifact_root=root,
        qgis_transport=qgis_transport,
        qgis_host=qgis_host,
        qgis_port=qgis_port,
        qgis_token=qgis_token,
        qgis_server_version=qgis_server_version,
        instance_id=instance_id,
        session_token=session_token,
        initialize_project=initialize_project,
        default_project_id=default_project_id,
        project_anchor=project_anchor,
        anchor_config_path=anchor_config_path,
        anchor_root=anchor_root,
    )
    app = FastAPI(title="Urban Design M2-A02 Bridge", version="m2-a02")
    app.state.bridge = bridge

    def _authorized(provided: str | None) -> None:
        if bridge.session_token is None:
            return
        if not isinstance(provided, str) or provided != bridge.session_token:
            raise BridgeError(
                "invalid or missing local bridge session token",
                code="SESSION_UNAUTHORIZED",
                status="REJECTED",
                http_status=401,
            )

    @app.exception_handler(BridgeError)
    async def bridge_error_handler(_request: Request, exc: BridgeError):
        return JSONResponse(status_code=exc.http_status, content=exc.as_response().model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError):
        error = BridgeError(
            "request validation failed",
            code="INVALID_REQUEST",
            status="REJECTED",
            http_status=422,
            details={"errors": exc.errors()},
        )
        return JSONResponse(status_code=422, content=error.as_response().model_dump(mode="json"))

    @app.get("/api/v1/integrations/status", response_model=IntegrationStatusResponse)
    async def integration_status(
        x_urban_design_session_token: str | None = Header(default=None, alias=BRIDGE_SESSION_HEADER),
    ):
        _authorized(x_urban_design_session_token)
        return bridge.integration_status()

    @app.post(
        "/api/v1/projects/{project_id}/study-area/capture",
        response_model=StudyAreaCaptureResponse,
        responses={401: {"model": BridgeErrorResponse}, 409: {"model": BridgeErrorResponse}, 422: {"model": BridgeErrorResponse}, 503: {"model": BridgeErrorResponse}},
    )
    async def capture_study_area(
        project_id: str,
        request: StudyAreaCaptureRequest,
        x_urban_design_session_token: str | None = Header(default=None, alias=BRIDGE_SESSION_HEADER),
    ):
        _authorized(x_urban_design_session_token)
        return bridge.capture(project_id, request)

    return app


def main(argv: Sequence[str] | None = None) -> int:
    """Run the loopback FastAPI bridge from the project-local launcher."""

    parser = argparse.ArgumentParser(description="Urban Design M2-A02 StudyArea bridge")
    parser.add_argument("--host", default=os.environ.get("URBAN_DESIGN_BRIDGE_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=os.environ.get("URBAN_DESIGN_BRIDGE_PORT", str(DEFAULT_BRIDGE_PORT)),
    )
    parser.add_argument("--database", default=os.environ.get("URBAN_DESIGN_DB_PATH", "state.sqlite3"))
    parser.add_argument(
        "--artifact-root",
        default=os.environ.get("URBAN_DESIGN_ARTIFACT_ROOT", "artifacts/study-area-bridge"),
    )
    parser.add_argument("--instance", default=os.environ.get("URBAN_DESIGN_INSTANCE", "urban-design-local"))
    parser.add_argument("--session-token", default=os.environ.get("URBAN_DESIGN_SESSION_TOKEN"))
    parser.add_argument("--qgis-host", default=os.environ.get("QGIS_MCP_HOST", "localhost"))
    parser.add_argument("--qgis-port", type=int, default=int(os.environ.get("QGIS_MCP_PORT", "9876")))
    parser.add_argument(
        "--project-id",
        default=os.environ.get("URBAN_DESIGN_PROJECT_ID", "rotterdam-m4h-pilot-project"),
    )
    parser.add_argument(
        "--anchor-config",
        default=os.environ.get("URBAN_DESIGN_ANCHOR_CONFIG"),
    )
    parser.add_argument(
        "--anchor-root",
        default=os.environ.get("URBAN_DESIGN_ANCHOR_ROOT"),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        args.port = validate_bridge_port(args.port)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        ensure_bridge_port_available(args.host, args.port)
    except ValueError as exc:
        parser.error(str(exc))
    if not isinstance(args.session_token, str) or not args.session_token.strip():
        parser.error("--session-token or URBAN_DESIGN_SESSION_TOKEN is required")
    app = create_app(
        database_path=args.database,
        artifact_root=args.artifact_root,
        qgis_host=args.qgis_host,
        qgis_port=args.qgis_port,
        qgis_token=args.session_token,
        qgis_server_version=QGIS_MCP_VERSION,
        instance_id=args.instance,
        session_token=args.session_token,
        initialize_project=True,
        default_project_id=args.project_id,
        anchor_config_path=args.anchor_config,
        anchor_root=args.anchor_root,
    )
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised by an incomplete launcher runtime
        raise RuntimeError("uvicorn is required to run the local bridge") from exc
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


__all__ = [
    "BRIDGE_SESSION_HEADER",
    "CAPTURE_OPERATION",
    "IntegrationStatusResponse",
    "ProjectAnchorError",
    "ProjectGeographicAnchor",
    "LadybugReadiness",
    "QGIS_MCP_VERSION",
    "QgisMCPPostDispatchError",
    "QgisMCPPreDispatchError",
    "QgisReadiness",
    "ReadinessStatus",
    "SocketQgisMCPTransport",
    "STUDY_AREA_CRS",
    "STUDY_AREA_LAYER_NAME",
    "STUDY_AREA_UNITS",
    "StudyAreaBridge",
    "StudyAreaCaptureRequest",
    "StudyAreaCaptureResponse",
    "BridgeErrorResponse",
    "DEFAULT_BRIDGE_PORT",
    "HERMES_RESERVED_PORT",
    "create_app",
    "ensure_bridge_port_available",
    "main",
    "validate_bridge_port",
]


if __name__ == "__main__":  # pragma: no cover - exercised by the launcher
    raise SystemExit(main())
