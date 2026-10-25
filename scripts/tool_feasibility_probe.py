"""Bounded Milestone 1 environment and tool feasibility probes.

This module deliberately does not expose QGIS arbitrary execution.  It inventories
the installed QGIS surface, rejects requests outside the future urban facade, and
attempts only the fixed Ladybug and Honeybee-Radiance smoke fixtures.  A package
import or a generated-but-empty file is never promoted to a successful simulation.
"""

from __future__ import annotations

import argparse
import asyncio
import configparser
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
from urban_design.gates import M1_GATE_DEFINITIONS, REVIEWER_ID, build_m1_gate_manifest
from urban_design.probe_contracts import ProbeSourceReport, validate_probe_report
from urban_design.qgis_facade import DEFAULT_ALLOWED_OPERATIONS, FORBIDDEN_OPERATIONS

FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "climate_smoke.json"
QGIS_APP = Path("/Applications/QGIS-LTR.app")
QGIS_BINARY = QGIS_APP / "Contents" / "MacOS" / "QGIS"
QGIS_PROCESS = QGIS_APP / "Contents" / "MacOS" / "bin" / "qgis_process"
QGIS_PROFILE = Path("/private/tmp/qgis-isolated/profiles/m1")
QGIS_PLUGIN_ROOT = QGIS_PROFILE / "python" / "plugins"

ALLOWED_QGIS_OPERATIONS = DEFAULT_ALLOWED_OPERATIONS
FORBIDDEN_QGIS_OPERATIONS = FORBIDDEN_OPERATIONS


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def manifest_for_directory(root: Path) -> list[dict[str, Any]]:
    """Return hashes for all regular files below an explicit output root."""
    root = root.resolve()
    if not root.exists():
        return []
    records = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        records.append(
            {
                "path": str(path.relative_to(root)),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def _new_run_root(base_root: Path) -> Path:
    """Create a never-reused run directory below the caller's evidence root."""
    import uuid

    base_root = base_root.expanduser().resolve()
    base_root.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        candidate = base_root / f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("could not allocate a unique probe run directory")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")


def _write_source_report(path: Path, *, source_kind: str, payload: dict[str, Any]) -> ProbeSourceReport:
    record = ProbeSourceReport(
        source_kind=source_kind,
        created_at=datetime.now(timezone.utc),
        status=str(payload.get("status", "BLOCKED")).upper(),
        payload=payload,
    )
    _write_json(path, record.model_dump(mode="json"))
    return record


def _parse_radiance_values(path: Path) -> list[float]:
    """Parse finite numeric values from an ASCII Radiance matrix."""
    values: list[float] = []
    data_started = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("FORMAT="):
            data_started = True
            continue
        if not data_started or not line or line.startswith("#") or "=" in line:
            continue
        for token in line.split():
            try:
                value = float(token)
            except ValueError:
                continue
            if not math.isfinite(value) or value < 0:
                raise ValueError("incident radiation matrix contains invalid values")
            values.append(value)
    if not values:
        raise ValueError("incident radiation matrix contains no numeric values")
    return values


def _run_fixed_command(command: list[str], *, cwd: Path | None = None, timeout: int = 30) -> dict[str, Any]:
    """Run a fixed, locally resolved command and retain bounded diagnostics."""
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
            "timeout": True,
        }
    except OSError as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
        }


def _pytest_node_from_case(case: ET.Element) -> str | None:
    file_name = case.attrib.get("file")
    name = case.attrib.get("name")
    if not name:
        return None
    if file_name:
        file_path = Path(file_name)
        if file_path.is_absolute():
            try:
                file_name = str(file_path.resolve().relative_to(PROJECT_ROOT))
            except ValueError:
                file_name = str(file_path)
        return f"{file_name}::{name}"
    return f"::{name}"


def run_m1_gate_tests(run_root: Path) -> dict[str, Any]:
    """Run only the explicit M1 mapped nodes once and persist per-node outcomes.

    Collection is checked separately, and JUnit XML supplies the actual result
    for every node.  This runner never invokes ``run_probe`` or another gate
    runner, so certification cannot pass through pytest recursion.
    """
    node_ids = sorted({node for definition in M1_GATE_DEFINITIONS.values() for node in definition["tests"]})
    gates_dir = run_root / "raw" / "gates"
    gates_dir.mkdir(parents=True, exist_ok=True)
    collect_command = [sys.executable, "-m", "pytest", "--collect-only", "-q", *node_ids]
    collect = _run_fixed_command(collect_command, cwd=PROJECT_ROOT, timeout=120)
    collect_text = f"{collect.get('stdout', '')}\n{collect.get('stderr', '')}"
    match = re.search(r"(\d+)\s+tests?\s+collected", collect_text)
    collected_count = int(match.group(1)) if match else 0
    junit_path = gates_dir / "pytest-junit.xml"
    command = [sys.executable, "-m", "pytest", "-q", "--disable-warnings", f"--junitxml={junit_path}", *node_ids]
    execution = _run_fixed_command(command, cwd=PROJECT_ROOT, timeout=180)
    cases: dict[str, ET.Element] = {}
    if junit_path.is_file():
        try:
            root = ET.parse(junit_path).getroot()
            for case in root.iter("testcase"):
                node_id = _pytest_node_from_case(case)
                if node_id:
                    cases[node_id] = case
        except (ET.ParseError, OSError):
            cases = {}
    results = []
    for node_id in node_ids:
        case = cases.get(node_id)
        if case is None:
            suffix = node_id.split("::")[-1]
            case = next((candidate for key, candidate in cases.items() if key.endswith(f"::{suffix}")), None)
        if case is None:
            outcome = "NOT_COLLECTED"
            collected = False
        elif case.find("failure") is not None:
            outcome, collected = "FAIL", True
        elif case.find("error") is not None:
            outcome, collected = "ERROR", True
        elif case.find("skipped") is not None:
            outcome, collected = "SKIPPED", True
        else:
            outcome, collected = "PASS", True
        results.append({"node_id": node_id, "outcome": outcome, "collected": collected})
    result = {
        "run_id": f"{run_root.name}-pytest",
        "reviewer": REVIEWER_ID,
        "collect_command": collect_command,
        "command": command,
        "collect_returncode": collect.get("returncode"),
        "returncode": execution.get("returncode"),
        "collected_count": collected_count,
        "node_results": results,
        "junit_path": str(junit_path.relative_to(run_root)),
        "collect_stdout": collect.get("stdout", ""),
        "collect_stderr": collect.get("stderr", ""),
        "stdout": execution.get("stdout", ""),
        "stderr": execution.get("stderr", ""),
    }
    _write_json(gates_dir / "pytest-gate-run.json", result)
    return result


def validate_qgis_probe_request(
    operation: str,
    *,
    output_path: Path | None = None,
    controlled_root: Path | None = None,
    approved_input_roots: tuple[Path, ...] | None = None,
    run_output_root: Path | None = None,
) -> dict[str, Any]:
    """Validate a future facade request without dispatching external code.

    The probe intentionally treats every operation outside the documented facade as
    forbidden, including aliases that would provide arbitrary Python, SQL, or batch
    execution.  Output paths are restricted to an explicit controlled root.
    """
    if operation in FORBIDDEN_QGIS_OPERATIONS or operation not in ALLOWED_QGIS_OPERATIONS:
        raise PermissionError(f"QGIS operation denied by default facade: {operation}")
    if output_path is not None:
        output_root = run_output_root or controlled_root
        if output_root is None:
            raise PermissionError("QGIS output requires an explicit controlled root")
        root = output_root.resolve()
        target = output_path.resolve()
        if target != root and root not in target.parents:
            raise PermissionError("QGIS output path is outside the run output root")
    return {"operation": operation, "allowed": True, "dispatched": False}


def _run_qgis_facade_geometry_smoke(run_output_root: Path) -> dict[str, Any]:
    """Dispatch the fixed buffer operation through the product policy facade.

    The injected transport is a tiny adapter to the qgis-mcp socket client. It
    has one fixed algorithm and no pass-through command field. This helper is
    only invoked when the disposable QGIS MCP instance is reachable.
    """
    from urban_design.qgis_facade import QgisFacadePolicy, QgisMCPFacade
    from urban_design.store import EntityNotFoundError, ProjectStateStore

    approved_input_root = (PROJECT_ROOT / "tests" / "fixtures").resolve()
    run_output_root = run_output_root.resolve()
    run_output_root.mkdir(parents=True, exist_ok=True)
    output_path = run_output_root / "m1_facade_buffer.gpkg"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = {
        "input_path": str((PROJECT_ROOT / "tests" / "fixtures" / "qgis_point.geojson").resolve()),
        "output_path": str(output_path),
        "distance_m": 10,
        "segments": 4,
    }
    client = None
    audit_records = []
    try:
        def dispatch(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            if client is None:
                raise ConnectionError("QGIS client is not connected")
            if operation != "urban.buffer_fixture":
                raise PermissionError(f"unregistered live operation: {operation}")
            point = client.add_vector_layer(payload["input_path"], "m1_facade_point", "ogr")
            if point.get("status") != "success":
                raise RuntimeError(f"point layer failed: {point}")
            point_id = point["result"]["id"]
            buffered = client.execute_processing(
                "native:buffer",
                {
                    "INPUT": point_id,
                    "DISTANCE": payload["distance_m"],
                    "SEGMENTS": payload["segments"],
                    "END_CAP_STYLE": 0,
                    "JOIN_STYLE": 0,
                    "MITER_LIMIT": 2,
                    "DISSOLVE": False,
                    "OUTPUT": payload["output_path"],
                },
            )
            if buffered.get("status") != "success":
                raise RuntimeError(f"buffer failed: {buffered}")
            loaded = client.add_vector_layer(payload["output_path"], "m1_facade_buffer", "ogr")
            if loaded.get("status") != "success":
                raise RuntimeError(f"buffer reload failed: {loaded}")
            features = client.get_layer_features(loaded["result"]["id"], include_geometry=True)
            return {"processing": buffered, "features": features}

        facade = QgisMCPFacade(
            QgisFacadePolicy(approved_input_roots=(approved_input_root,), run_output_root=run_output_root),
            dispatch,
            audit_sink=audit_records.append,
        )
        try:
            facade.execute(
                "execute_code",
                {"output_path": str(output_path)},
                request_id="qgis-m1-denied-execute-code",
            )
        except PermissionError:
            pass
        from qgis_mcp.client import QgisMCPClient

        client = QgisMCPClient()
        if not client.connect():
            return {"status": "BLOCKED", "reason": f"QGIS socket unavailable: {client.last_error}"}
        result = facade.execute("urban.buffer_fixture", request, request_id="qgis-m1-facade-buffer")
        if result.status != "SUCCEEDED" or not output_path.is_file() or output_path.stat().st_size == 0:
            return {"status": result.status, "result": result.as_dict()}

        artifact_hash = sha256_file(output_path)
        state_path = run_output_root / "state.sqlite3"
        with ProjectStateStore(state_path) as state:
            try:
                state.current("qgis-m1-project")
            except EntityNotFoundError:
                state.create_project({"name": "Milestone 1 QGIS facade smoke"}, project_id="qgis-m1-project", actor="probe")
            payload = {
                "project_id": "qgis-m1-project",
                "scenario_id": None,
                "tool": "qgis-mcp",
                "tool_version": "0.14.0",
                "input_refs": ["tests/fixtures/qgis_point.geojson"],
                "output_artifact_refs": [str(output_path.relative_to(run_output_root))],
                "output_artifact_hashes": [artifact_hash],
                "parameters": {"distance_m": 10, "segments": 4, "algorithm": "native:buffer"},
                "status": "SUCCEEDED",
                "idempotency_key": "qgis-m1-facade-buffer",
            }
            try:
                state.current("qgis-m1-toolrun")
                state.update("qgis-m1-toolrun", payload, actor="probe", action="Rerun", reason="refresh smoke artifact")
            except EntityNotFoundError:
                state.create("ToolExecution", payload, entity_id="qgis-m1-toolrun", project_id="qgis-m1-project", actor="probe")
            ledger = state.ledger("qgis-m1-project")
        audit_path = run_output_root / "qgis-audit.json"
        _write_json(audit_path, [record.model_dump(mode="json") for record in audit_records])
        return {
            "status": "PASS",
            "operation": "urban.buffer_fixture",
            "artifact": str(output_path),
            "artifact_sha256": artifact_hash,
            "artifact_size_bytes": output_path.stat().st_size,
            "ledger_event_count": len(ledger),
            "ledger_state_linked": any(event.target_id == "qgis-m1-toolrun" for event in ledger),
            "transport": result.as_dict(),
            "audit_artifact": str(audit_path),
            "audit_artifact_sha256": sha256_file(audit_path),
            "denied_requests_recorded": sum(1 for record in audit_records if record.status == "REJECTED"),
        }
    except Exception as exc:
        return {"status": "BLOCKED", "failure_type": type(exc).__name__, "reason": str(exc)}
    finally:
        try:
            _write_json(run_output_root / "qgis-audit.json", [record.model_dump(mode="json") for record in audit_records])
        except Exception:
            pass
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass


def _version_from_qgis_output(text: str) -> str | None:
    match = re.search(r"^QGIS ([^\n]+)", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _which_candidates(names: tuple[str, ...]) -> dict[str, str | None]:
    return {name: shutil.which(name) for name in names}


def _mcp_result_data(result: Any) -> Any:
    """Extract structured MCP data while keeping the probe client-version tolerant."""
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    content = getattr(result, "content", None) or []
    for item in content:
        text = getattr(item, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return None


async def _qgis_mcp_async_probe(server_path: Path) -> dict[str, Any]:
    """Use only read-only MCP calls against the disposable QGIS smoke layers.

    The raw QGIS MCP server exposes many privileged tools. This function has a
    deliberately tiny call surface: initialize, list tools, ping, diagnose,
    list layers, and read geometry from the two disposable ``m1_*`` layers.
    It never sends execute_code, SQL, processing, edit, or delete requests.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = os.environ.copy()
    env.update(
        {
            "QGIS_MCP_LOG_FILE": "",
            "QGIS_MCP_LOG_LEVEL": "WARNING",
            "QGIS_MCP_HOST": "127.0.0.1",
            "QGIS_MCP_PORT": "9876",
            "QGIS_MCP_TRANSPORT": "stdio",
        }
    )
    params = StdioServerParameters(command=str(server_path), args=[], env=env, cwd=str(PROJECT_ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialize = await asyncio.wait_for(session.initialize(), timeout=10)
            listed = await asyncio.wait_for(session.list_tools(), timeout=10)
            ping = _mcp_result_data(await asyncio.wait_for(session.call_tool("ping", arguments={}), timeout=10))
            diagnose = _mcp_result_data(
                await asyncio.wait_for(session.call_tool("diagnose", arguments={}), timeout=10)
            )
            layers_result = _mcp_result_data(
                await asyncio.wait_for(
                    session.call_tool("get_layers", arguments={"limit": 50, "offset": 0}), timeout=10
                )
            )
            layers = (layers_result or {}).get("layers", []) if isinstance(layers_result, dict) else []
            by_name = {layer.get("name"): layer for layer in layers if isinstance(layer, dict)}
            expected_names = {
                "m1_point": ("m1_point", "m1_facade_point"),
                "m1_buffer": ("m1_buffer", "m1_facade_buffer"),
            }
            geometry_results: dict[str, Any] = {}
            for canonical_name, aliases in expected_names.items():
                layer = next((by_name.get(alias) for alias in aliases if by_name.get(alias)), None)
                if not layer or not layer.get("id"):
                    geometry_results[canonical_name] = {"status": "BLOCKED", "reason": "Disposable layer is missing."}
                    continue
                geometry_results[canonical_name] = _mcp_result_data(
                    await asyncio.wait_for(
                        session.call_tool(
                            "get_layer_features",
                            arguments={
                                "layer_id": layer["id"],
                                "limit": 10,
                                "offset": 0,
                                "include_geometry": True,
                            },
                        ),
                        timeout=10,
                    )
                )

            point_data = geometry_results.get("m1_point") or {}
            buffer_data = geometry_results.get("m1_buffer") or {}
            point_features = point_data.get("features", []) if isinstance(point_data, dict) else []
            buffer_features = buffer_data.get("features", []) if isinstance(buffer_data, dict) else []
            point_geometry = point_features[0].get("_geometry", {}) if point_features else {}
            buffer_geometry = buffer_features[0].get("_geometry", {}) if buffer_features else {}
            point_wkt = point_geometry.get("wkt") or point_geometry.get("wkt_summary")
            checks = {
                "m1_point_is_point_at_origin": point_wkt == "Point (0 0)",
                "m1_buffer_bbox_is_controlled": buffer_geometry.get("bbox") == [-10.0, -10.0, 10.0, 10.0],
            }
            return {
                "status": "PASS" if all(checks.values()) else "BLOCKED",
                "connection_method": "MCP stdio client -> QGIS MCP TCP socket 127.0.0.1:9876",
                "server_path": str(server_path),
                "server_name": getattr(getattr(initialize, "server_info", None), "name", None),
                "server_version": importlib.metadata.version("qgis-mcp"),
                "tool_count": len(listed.tools),
                "read_only_calls": ["ping", "diagnose", "get_layers", "get_layer_features"],
                "ping": ping,
                "diagnose_status": diagnose.get("status") if isinstance(diagnose, dict) else None,
                "diagnose": diagnose,
                "layer_inventory": layers,
                "geometry_operation": "get_layer_features(include_geometry=True)",
                "geometry_results": geometry_results,
                "checks": checks,
                "privileged_calls_dispatched": [],
            }


def _probe_qgis_mcp_route(server_path: Path) -> dict[str, Any]:
    """Run the bounded MCP probe, preserving sandbox/connection failures exactly."""
    if not server_path.is_file():
        return {"status": "BLOCKED", "reason": "qgis-mcp-server executable is absent."}
    try:
        return asyncio.run(asyncio.wait_for(_qgis_mcp_async_probe(server_path), timeout=45))
    except Exception as exc:  # connection and sandbox failures are gate evidence
        return {
            "status": "BLOCKED",
            "failure_type": type(exc).__name__,
            "failure": str(exc),
            "reason": "MCP route could not complete the bounded read-only probe.",
        }


def _qgis_plugin_metadata(plugin_path: Path) -> dict[str, Any]:
    metadata_path = plugin_path / "metadata.txt"
    parser = configparser.ConfigParser()
    if not metadata_path.is_file():
        return {}
    parser.read(metadata_path, encoding="utf-8")
    if not parser.has_section("general"):
        return {}
    general = parser["general"]
    return {
        key: general.get(key)
        for key in ("name", "version", "qgisminimumversion", "qgismaximumversion", "license", "repository")
        if general.get(key) is not None
    }


def probe_qgis_environment(run_root: Path | None = None) -> dict[str, Any]:
    """Inventory QGIS and execute one bounded read-only MCP geometry smoke."""
    plugin_path = QGIS_PLUGIN_ROOT / "qgis_mcp_plugin"
    server_path = PROJECT_ROOT / ".venv" / "bin" / "qgis-mcp-server"
    result: dict[str, Any] = {
        "app_path": str(QGIS_APP),
        "app_present": QGIS_APP.is_dir(),
        "qgis_binary_path": str(QGIS_BINARY),
        "qgis_binary_present": QGIS_BINARY.is_file(),
        "process_path": str(QGIS_PROCESS),
        "process_present": QGIS_PROCESS.is_file(),
        "host_architecture": platform.machine(),
        "host_os": platform.platform(),
        "qgis_binary_architecture": None,
        "qgis_version": None,
        "qgis_process_version_probe": None,
        "profile_path": str(QGIS_PROFILE),
        "plugin_root": str(QGIS_PLUGIN_ROOT),
        "profile_plugins": [],
        "mcp_plugin_detected": False,
        "mcp_server_candidates": {},
        "plugin_metadata": {},
        "connection_method": "unavailable: no MCP client/server/plugin discovered",
        "facade_smoke": {
            "status": "BLOCKED",
            "reason": "No bounded QGIS MCP geometry operation completed.",
        },
    }
    if QGIS_BINARY.is_file():
        file_probe = _run_fixed_command(["/usr/bin/file", str(QGIS_BINARY)])
        result["qgis_binary_architecture"] = file_probe["stdout"].strip() or file_probe["stderr"].strip()
    if QGIS_PROCESS.is_file():
        result["qgis_process_version_probe"] = _run_fixed_command([str(QGIS_PROCESS), "--version"], timeout=30)
        version_text = "\n".join(
            [
                result["qgis_process_version_probe"].get("stdout", ""),
                result["qgis_process_version_probe"].get("stderr", ""),
            ]
        )
        result["qgis_version"] = _version_from_qgis_output(version_text)

    if QGIS_PLUGIN_ROOT.is_dir():
        result["profile_plugins"] = sorted(
            path.name for path in QGIS_PLUGIN_ROOT.iterdir() if path.is_dir()
        )
    result["mcp_plugin_detected"] = any("mcp" in name.lower() for name in result["profile_plugins"])
    if plugin_path.is_dir():
        result["plugin_metadata"] = _qgis_plugin_metadata(plugin_path)
    result["mcp_server_candidates"] = _which_candidates(
        ("qgis-mcp", "qgis_mcp", "qgis-mcp-server", "qgis_mcp_server")
    )
    if server_path.is_file():
        # The project-local venv is intentionally recorded even when its bin
        # directory is not on the caller's PATH.
        result["mcp_server_candidates"]["qgis-mcp-server"] = str(server_path)
    result["mcp_server_present"] = any(result["mcp_server_candidates"].values())
    result["mcp_server_path"] = str(server_path)
    try:
        result["mcp_server_version"] = importlib.metadata.version("qgis-mcp")
    except importlib.metadata.PackageNotFoundError:
        result["mcp_server_version"] = None
    socket_probe = _run_fixed_command(
        [
            str(PROJECT_ROOT / ".venv" / "bin" / "python"),
            "-c",
            "import socket; s=socket.create_connection(('127.0.0.1',9876),2); s.close(); print('connected')",
        ],
        cwd=PROJECT_ROOT,
        timeout=5,
    )
    result["socket_probe"] = socket_probe
    facade_output_root = (run_root or PROJECT_ROOT / ".milestone1-r02-runs" / "unbound-qgis").resolve() / "raw" / "qgis" / "outputs"
    result["facade_dispatch"] = _run_qgis_facade_geometry_smoke(facade_output_root)
    result["mcp_route"] = _probe_qgis_mcp_route(server_path)
    if result["facade_dispatch"].get("status") == "PASS":
        result["connection_method"] = "QgisMCPFacade -> qgis_mcp.client TCP socket 127.0.0.1:9876"
        result["facade_smoke"] = {
            "status": "PASS",
            "operation": "urban.buffer_fixture",
            "reason": "Fixed native:buffer geometry operation completed through the product policy facade with a linked state/ledger record.",
            "artifact": result["facade_dispatch"].get("artifact"),
            "artifact_sha256": result["facade_dispatch"].get("artifact_sha256"),
            "ledger_state_linked": result["facade_dispatch"].get("ledger_state_linked"),
        }
    elif result["mcp_route"].get("status") == "PASS":
        result["connection_method"] = result["mcp_route"]["connection_method"]
        result["facade_smoke"] = {
            "status": "PASS",
            "operation": result["mcp_route"]["geometry_operation"],
            "reason": "Read-only geometry returned from the controlled disposable m1_* layers through the live MCP route.",
            "boundary": "This verifies transport and deterministic geometry response; the product facade dispatch did not complete.",
        }
    elif result["mcp_plugin_detected"] and result["mcp_server_present"]:
        result["connection_method"] = "QGIS MCP plugin + qgis-mcp-server discovered; bounded route probe blocked"
    return result


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


def _fixture_geometry(fixture: dict[str, Any], offset: float) -> tuple[Any, Any, Any]:
    """Create the identical controlled sensor/context geometry for both tiers."""
    from ladybug_geometry.geometry3d import Mesh3D
    from ladybug_geometry.geometry3d.pointvector import Point3D

    sensor_data = fixture["sensor"]
    sensor = Mesh3D(
        tuple(Point3D(*point) for point in sensor_data["vertices"]),
        tuple(tuple(face) for face in sensor_data["faces"]),
    )
    building = fixture["building"]
    ox, oy, oz = building["origin_m"]
    ox += offset
    width, depth, height = building["width_m"], building["depth_m"], building["height_m"]
    vertices = (
        (ox, oy, oz),
        (ox + width, oy, oz),
        (ox + width, oy + depth, oz),
        (ox, oy + depth, oz),
        (ox, oy, oz + height),
        (ox + width, oy, oz + height),
        (ox + width, oy + depth, oz + height),
        (ox, oy + depth, oz + height),
    )
    context = Mesh3D(
        tuple(Point3D(*point) for point in vertices),
        ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)),
    )
    return sensor, context, Point3D(ox, oy, oz)


def _make_wea(fixture: dict[str, Any]) -> Any:
    from ladybug.wea import Wea

    weather = fixture["weather"]
    return Wea.from_dict(
        {
            "type": "Wea",
            "location": {
                "city": weather["city"],
                "country": weather["country"],
                "latitude": weather["latitude"],
                "longitude": weather["longitude"],
                "time_zone": weather["time_zone"],
                "elevation": weather["elevation_m"],
                "source": weather["source"],
            },
            "direct_normal_irradiance": weather["direct_normal_irradiance_W_m2"],
            "diffuse_horizontal_irradiance": weather["diffuse_horizontal_irradiance_W_m2"],
            "timestep": 1,
            "is_leap_year": False,
            "datetimes": weather["datetimes"],
        }
    )


def _package_versions() -> dict[str, str | None]:
    names = (
        "ladybug-core",
        "ladybug-geometry",
        "ladybug-radiance",
        "honeybee-core",
        "honeybee-radiance",
        "honeybee-schema",
        "honeybee-energy",
    )
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _radiance_inventory() -> dict[str, Any]:
    from honeybee_radiance.config import folders as honeybee_folders
    from ladybug_radiance.config import folders as ladybug_folders

    commands = ("rad", "gendaymtx", "rtrace", "rfluxmtx", "oconv", "rmtxop")
    command_paths = _which_candidates(commands)
    version_probe = None
    rtrace_path = command_paths.get("rtrace")
    if rtrace_path:
        version_probe = _run_fixed_command([rtrace_path, "-version"], timeout=10)
    return {
        "commands": command_paths,
        "environment": {
            "BINPATH": os.environ.get("BINPATH"),
            "RAYPATH": os.environ.get("RAYPATH"),
        },
        "rtrace_version_probe": version_probe,
        "ladybug_radbin_path": ladybug_folders.radbin_path,
        "honeybee_radbin_path": honeybee_folders.radbin_path,
        "ladybug_radiance_path": ladybug_folders.radiance_path,
        "honeybee_radiance_path": honeybee_folders.radiance_path,
    }


def run_ladybug_smoke(output_root: Path, fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    """Attempt the Ladybug screening fixture for baseline and two offsets."""
    fixture = fixture or _load_fixture()
    from ladybug_radiance.skymatrix import SkyMatrix
    from ladybug_radiance.study.radiation import RadiationStudy

    fixture_hash = sha256_file(FIXTURE_PATH)
    runs = []
    for offset in fixture["offsets_m"]:
        run_id = f"offset_{offset:+g}m".replace("+", "plus").replace("-", "minus")
        run_dir = output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        wea = _make_wea(fixture)
        wea_path = Path(wea.write(str(run_dir / "weather")))
        sensor, context, _ = _fixture_geometry(fixture, float(offset))
        record: dict[str, Any] = {
            "run_id": run_id,
            "offset_m": offset,
            "axis": fixture["offset_axis"],
            "status": "BLOCKED",
            "method": "Ladybug/ladybug-radiance RadiationStudy",
            "units": {"geometry": "m", "weather": "W/m2", "result": "kWh/m2"},
            "geometry": {"sensor_area_m2": sensor.area, "sensor_outside_context": True},
            "weather_path": str(wea_path.relative_to(output_root)),
            "weather_sha256": sha256_file(wea_path),
            "fixture_sha256": fixture_hash,
        }
        try:
            sky = SkyMatrix(
                wea,
                north=fixture["north_degrees"],
                high_density=False,
                ground_reflectance=0.2,
            )
            sky.folder = str(run_dir)
            study = RadiationStudy(
                sky,
                sensor,
                [context],
                offset_distance=0.01,
                by_vertex=False,
                sim_folder=str(run_dir),
            )
            values = study.radiation_values
            record.update(
                {
                    "status": "SUCCEEDED",
                    "radiation_values": values,
                    "area_weighted_total_kwh_m2": study.total_radiation(),
                }
            )
        except Exception as exc:  # the exact failure is evidence for the gate
            record.update(
                {
                    "status": "BLOCKED" if "No Radiance installation" in str(exc) else "TOOL_FAILED",
                    "failure_type": type(exc).__name__,
                    "failure": str(exc),
                }
            )
        record["artifacts"] = manifest_for_directory(run_dir)
        runs.append(record)
    return {
        "tier": "screening",
        "package_versions": _package_versions(),
        "radiance_inventory": _radiance_inventory(),
        "runs": runs,
        "status": "PASS" if all(run["status"] == "SUCCEEDED" for run in runs) else "BLOCKED",
    }


def _honeybee_model(fixture: dict[str, Any], offset: float) -> tuple[Any, Any]:
    from honeybee.model import Model
    from honeybee.room import Room
    from honeybee_radiance.sensorgrid import SensorGrid
    from ladybug_geometry.geometry3d import Mesh3D
    from ladybug_geometry.geometry3d.pointvector import Point3D

    building = fixture["building"]
    ox, oy, oz = building["origin_m"]
    room = Room.from_box(
        "building_000",
        building["width_m"],
        building["depth_m"],
        building["height_m"],
        origin=Point3D(ox + offset, oy, oz),
    )
    sensor_data = fixture["sensor"]
    sensor_mesh = Mesh3D(
        tuple(Point3D(*point) for point in sensor_data["vertices"]),
        tuple(tuple(face) for face in sensor_data["faces"]),
    )
    model = Model("hb_smoke", [room])
    model.properties.radiance.add_sensor_grid(SensorGrid.from_mesh3d("public_sensor", sensor_mesh))
    return model, sensor_mesh


def run_honeybee_smoke(output_root: Path, fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the real Honeybee-Radiance incident-radiation calculation.

    Translation, sky generation, and octree creation are prerequisites only.
    CLM-002 succeeds only when ``dc scoeff`` produces finite incident values and
    a spatial sensor artifact for every offset.
    """
    fixture = fixture or _load_fixture()
    fixture_hash = sha256_file(FIXTURE_PATH)
    executable = PROJECT_ROOT / ".venv" / "bin" / "honeybee-radiance"
    runs = []
    for offset in fixture["offsets_m"]:
        run_id = f"offset_{offset:+g}m".replace("+", "plus").replace("-", "minus")
        run_dir = output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        wea = _make_wea(fixture)
        wea_path = Path(wea.write(str(run_dir / "weather")))
        model, sensor = _honeybee_model(fixture, float(offset))
        hbjson_path = Path(model.to_hbjson("model", str(run_dir)))
        rad_folder = run_dir / "radiance"
        translation = _run_fixed_command(
            [
                str(executable),
                "translate",
                "model-to-rad-folder",
                str(hbjson_path),
                "--folder",
                str(rad_folder),
                "--grid-check",
                "--no-view-check",
            ],
            cwd=PROJECT_ROOT,
        )
        model_folder = rad_folder / "model"
        sky_dir = run_dir / "sky"
        sky = _run_fixed_command(
            [
                str(executable),
                "sky",
                "mtx",
                str(wea_path),
                "--folder",
                str(sky_dir),
                "--name",
                "summer_smoke",
                "--solar",
                "--cumulative",
            ],
            cwd=PROJECT_ROOT,
        )
        octree_path = run_dir / "scene.oct"
        octree = _run_fixed_command(
            [
                str(executable),
                "octree",
                "from-folder",
                str(model_folder),
                "--output",
                str(octree_path),
            ],
            cwd=PROJECT_ROOT,
        )
        sky_dome_dir = run_dir / "sky_dome"
        sky_dome = _run_fixed_command(
            [
                str(executable),
                "sky",
                "skydome",
                "--sky-density",
                "1",
                "--folder",
                str(sky_dome_dir),
                "--name",
                "summer_dome",
            ],
            cwd=PROJECT_ROOT,
        )
        sky_artifact = sky_dir / "summer_smoke.mtx"
        sky_valid = sky_artifact.is_file() and sky_artifact.stat().st_size > 0
        octree_valid = octree_path.is_file() and octree_path.stat().st_size > 0
        sky_dome_path = sky_dome_dir / "summer_dome"
        if not sky_dome_path.is_file():
            candidates = sorted(path for path in sky_dome_dir.glob("summer_dome*") if path.is_file())
            sky_dome_path = candidates[0] if candidates else sky_dome_path
        sky_dome_valid = sky_dome_path.is_file() and sky_dome_path.stat().st_size > 0
        sensor_paths = sorted(model_folder.rglob("public_sensor.pts"))
        sensor_path = sensor_paths[0] if sensor_paths else model_folder / "grid" / "public_sensor.pts"
        sensor_valid = sensor_path.is_file() and sensor_path.stat().st_size > 0
        sensor_count = sum(1 for line in sensor_path.read_text(encoding="utf-8").splitlines() if line.strip()) if sensor_valid else 0
        incident_path = run_dir / "incident_radiation.mtx"
        incident = _run_fixed_command(
            [
                str(executable),
                "dc",
                "scoeff",
                str(octree_path),
                str(sensor_path),
                str(sky_dome_path),
                str(sky_artifact),
                "--sensor-count",
                str(sensor_count),
                "--output-format",
                "a",
                "--conversion",
                "47.4 119.9 11.6",
                "--order-by-sensor",
                "--output",
                str(incident_path),
            ],
            cwd=PROJECT_ROOT,
            timeout=120,
        )
        incident_valid = incident_path.is_file() and incident_path.stat().st_size > 0
        raw_values: list[float] = []
        incident_failure: str | None = None
        if incident_valid:
            try:
                raw_values = _parse_radiance_values(incident_path)
            except ValueError as exc:
                incident_failure = str(exc)
        if len(raw_values) != sensor_count:
            incident_failure = incident_failure or f"expected {sensor_count} sensor values, found {len(raw_values)}"
        normalized_values = [value / 1000.0 for value in raw_values]
        spatial_path = run_dir / "incident_radiation_spatial.json"
        spatial_payload: dict[str, Any] | None = None
        if incident_failure is None and sensor_valid:
            points = []
            for line in sensor_path.read_text(encoding="utf-8").splitlines():
                tokens = line.split()
                if len(tokens) >= 3:
                    points.append([float(tokens[0]), float(tokens[1]), float(tokens[2])])
            spatial_payload = {
                "type": "SensorGridRadiation",
                "unit": "kWh/m2",
                "raw_unit": "Wh/m2",
                "source_matrix": str(incident_path.name),
                "sensor_count": sensor_count,
                "sensors": [
                    {"sensor_id": f"public_sensor_{index:04d}", "point_m": point, "incident_radiation_kwh_m2": value}
                    for index, (point, value) in enumerate(zip(points, normalized_values))
                ],
            }
            _write_json(spatial_path, spatial_payload)
        spatial_valid = spatial_path.is_file() and spatial_path.stat().st_size > 0
        prerequisites_valid = (
            translation["returncode"] == 0
            and sky_valid
            and octree_valid
            and octree["returncode"] == 0
            and sky_dome_valid
            and sky_dome["returncode"] == 0
            and sensor_valid
        )
        status = "SUCCEEDED" if prerequisites_valid and incident["returncode"] == 0 and incident_valid and incident_failure is None and spatial_valid else "BLOCKED"
        spatial_record = None
        if spatial_valid:
            spatial_record = {
                "path": str(spatial_path.relative_to(run_dir)),
                "size_bytes": spatial_path.stat().st_size,
                "sha256": sha256_file(spatial_path),
            }
        runs.append(
            {
                "run_id": run_id,
                "offset_m": offset,
                "axis": fixture["offset_axis"],
                "status": status,
                "method": "Honeybee-Radiance verification",
                "units": {"geometry": "m", "weather": "W/m2", "incident_raw": "Wh/m2", "result": "kWh/m2"},
                "geometry": {"sensor_area_m2": sensor.area, "sensor_outside_building": True},
                "weather_path": str(wea_path.relative_to(output_root.parent)),
                "weather_sha256": sha256_file(wea_path),
                "fixture_sha256": fixture_hash,
                "translation": translation,
                "sky_matrix": {"command": sky, "artifact_nonempty": sky_valid},
                "octree": {"command": octree, "artifact_nonempty": octree_valid},
                "sky_dome": {
                    "command": sky_dome,
                    "artifact": str(sky_dome_path),
                    "artifact_nonempty": sky_dome_valid,
                },
                "incident_radiation": {
                    "command": incident,
                    "artifact": str(incident_path),
                    "artifact_nonempty": incident_valid,
                    "values_wh_m2": raw_values,
                    "values_kwh_m2": normalized_values,
                    "result_unit": "kWh/m2",
                    "raw_result_unit": "Wh/m2",
                    "failure": incident_failure,
                },
                "incident_radiation_values": normalized_values,
                "spatial_artifact": spatial_record,
                "sensor_artifact": {
                    "path": str(sensor_path),
                    "sha256": sha256_file(sensor_path) if sensor_valid else None,
                    "sensor_count": sensor_count,
                },
                "artifacts": manifest_for_directory(run_dir),
            }
        )
    return {
        "tier": "verification",
        "package_versions": _package_versions(),
        "radiance_inventory": _radiance_inventory(),
        "runs": runs,
        "status": "PASS" if all(run["status"] == "SUCCEEDED" for run in runs) else "BLOCKED",
    }


def reconcile_outcome(
    *,
    dispatch_status: str,
    expected_artifact: Path,
    expected_sha256: str | None,
    observed_project_revision: str | None,
    expected_project_revision: str,
    ledger_record_present: bool,
) -> dict[str, Any]:
    """Resolve an uncertain external run only from matching independent evidence."""
    if dispatch_status != "OUTCOME_UNKNOWN":
        return {"status": dispatch_status, "retry_allowed": False, "reason": "No reconciliation needed."}
    if expected_artifact.is_file() and expected_sha256 and sha256_file(expected_artifact) == expected_sha256:
        if observed_project_revision == expected_project_revision and ledger_record_present:
            return {
                "status": "SUCCEEDED",
                "retry_allowed": False,
                "reason": "Artifact hash, project revision, and ledger record reconcile.",
            }
        return {
            "status": "OUTCOME_UNKNOWN",
            "retry_allowed": False,
            "reason": "Artifact exists but project revision or ledger evidence is insufficient.",
        }
    if expected_artifact.exists():
        return {
            "status": "TOOL_FAILED",
            "retry_allowed": False,
            "reason": "Expected artifact exists but its hash does not reconcile.",
        }
    return {
        "status": "OUTCOME_UNKNOWN",
        "retry_allowed": False,
        "reason": "No reconciled artifact; do not blindly retry a post-dispatch request.",
    }


def run_probe(output_root: Path) -> dict[str, Any]:
    """Run one probe in a fresh directory and persist only validated records."""
    output_root = _new_run_root(output_root)
    fixture = _load_fixture()
    raw_qgis_dir = output_root / "raw" / "qgis"
    raw_climate_dir = output_root / "raw" / "climate"
    qgis_payload = probe_qgis_environment(output_root)
    climate_payload = {
        "ladybug": run_ladybug_smoke(raw_climate_dir / "ladybug", fixture),
        "honeybee_radiance": run_honeybee_smoke(raw_climate_dir / "honeybee_radiance", fixture),
    }
    qgis_source_path = raw_qgis_dir / "qgis-report.json"
    climate_source_path = raw_climate_dir / "climate-report.json"
    qgis_source_payload = {"status": qgis_payload.get("facade_smoke", {}).get("status", "BLOCKED"), **qgis_payload}
    _write_source_report(qgis_source_path, source_kind="qgis", payload=qgis_source_payload)
    climate_status = "PASS" if all(item.get("status") == "PASS" for item in climate_payload.values()) else "BLOCKED"
    _write_source_report(climate_source_path, source_kind="climate", payload={"status": climate_status, **climate_payload})
    pytest_run = run_m1_gate_tests(output_root)
    pytest_run_path = output_root / "raw" / "gates" / "pytest-gate-run.json"
    _write_json(pytest_run_path, pytest_run)
    run_id = output_root.name
    report = {
        "probe_id": "milestone1-tool-feasibility-v2",
        "run_id": run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "python": sys.version.replace("\n", " "),
            "executable": sys.executable,
            "architecture": platform.machine(),
            "os": platform.platform(),
        },
        "fixture": {
            "path": str(FIXTURE_PATH),
            "sha256": sha256_file(FIXTURE_PATH),
            "units": fixture["units"],
            "coordinate_system": fixture["coordinate_system"],
            "offsets_m": fixture["offsets_m"],
            "sensor_area_m2": fixture["sensor"]["area_m2"],
        },
        "qgis": qgis_payload,
        "climate": climate_payload,
        "output_root": str(output_root),
        "source_reports": {
            "qgis": {
                "path": str(qgis_source_path.relative_to(output_root)),
                "sha256": sha256_file(qgis_source_path),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": qgis_payload.get("facade_smoke", {}).get("status", "BLOCKED"),
            },
            "climate": {
                "path": str(climate_source_path.relative_to(output_root)),
                "sha256": sha256_file(climate_source_path),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": climate_status,
            },
        },
    }
    output_file = output_root / "composite" / "probe-report.json"
    gate_manifest = build_m1_gate_manifest(
        report,
        report_root=output_root,
        report_path=str(output_file),
        pytest_run=pytest_run,
        run_id=run_id,
    )
    report["gate_manifest"] = {
        key: value for key, value in gate_manifest.items() if key != "report_path"
    }
    report["gate_manifest"]["manifest_path"] = "m1-gate-manifest.json"
    validated = validate_probe_report(report)
    _write_json(output_file, validated.model_dump(mode="json"))
    manifest_path = output_root / "m1-gate-manifest.json"
    _write_json(manifest_path, gate_manifest)
    report = validated.model_dump(mode="json")
    report["report_path"] = str(output_file)
    report["gate_manifest_path"] = str(manifest_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / ".milestone1-r02-runs",
        help="Evidence base directory; every invocation creates a unique run child.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report to stdout.")
    args = parser.parse_args()
    result = run_probe(args.output_dir)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=_json_default))
    else:
        print(f"probe report: {result['report_path']}")
        print(f"QGIS facade smoke: {result['qgis']['facade_smoke']['status']}")
        print(f"Ladybug tier: {result['climate']['ladybug']['status']}")
        print(f"Honeybee-Radiance tier: {result['climate']['honeybee_radiance']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
