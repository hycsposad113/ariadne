"""Proxy walk of the C1 sync runbook on a disposable port and database copy.

This is not Founder acceptance and does not press Sync in the live QGIS session.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parents[1]
AUTHORITY_DB = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3")
PROTECTED_PORTS = frozenset({5195, 8644, 8787, 8788, 8789, 8795, 9876})
PROJECT_ID = "rotterdam-m4h-pilot-project"
QGIS_PYTHON = Path("/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3")
QGIS_PREFIX = "/Applications/QGIS-LTR.app/Contents/MacOS"
PROJ_LIB = "/Applications/QGIS-LTR.app/Contents/Resources/proj"
RECEIPT_FIELDS = (
    "recorded_at_utc",
    "timezone",
    "simulation",
    "acceptance",
    "qgis_version",
    "qgis_architecture",
    "qgis_mcp_server_version",
    "qgis_mcp_plugin_version",
    "live_mcp_contacted",
    "live_bridge_contacted",
    "project_id",
    "study_area_id",
    "expected_workspace_revision",
    "source_snapshot_ids",
    "selected_feature_ids",
    "actor_kind",
    "actor_session_id",
    "idempotency_key",
    "http_status",
    "workspace_id",
    "revision",
    "status",
    "feature_dispositions",
    "payload_digest",
    "idempotent_replay",
    "replay_http_status",
    "approve_event_count_before",
    "approve_event_count_after",
    "screenshots",
    "exit_qgis_called",
    "qgis_smoke_exit_code",
    "ports_started",
    "protected_listeners_unchanged",
)


def assert_disposable_port(port: int) -> None:
    if port in PROTECTED_PORTS:
        raise ValueError(f"refusing protected port {port}")
    if not 1 <= port <= 65535:
        raise ValueError("port must be within 1..65535")


def assert_disposable_database(path: Path) -> None:
    resolved = path.resolve()
    authority = AUTHORITY_DB.resolve()
    if resolved == authority:
        raise ValueError("refusing the authority database")
    if resolved.exists() and authority.exists():
        copy_stat = resolved.stat()
        authority_stat = authority.stat()
        if copy_stat.st_dev == authority_stat.st_dev and copy_stat.st_ino == authority_stat.st_ino:
            raise ValueError("refusing a link to the authority database")


def choose_ephemeral_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    assert_disposable_port(port)
    return port


def require_receipt_fields(receipt: dict[str, Any]) -> None:
    missing = [name for name in RECEIPT_FIELDS if name not in receipt]
    if missing:
        raise ValueError("receipt is missing " + ", ".join(missing))
    if receipt.get("acceptance") != "NOT_ACCEPTANCE":
        raise ValueError("proxy receipt must stay unmarked as acceptance")
    if receipt.get("status") != "DRAFT":
        raise ValueError("proxy sync revision must stay DRAFT")
    if receipt.get("live_mcp_contacted") is not False or receipt.get("live_bridge_contacted") is not False:
        raise ValueError("proxy simulation contacted a live QGIS service")
    screenshots = receipt.get("screenshots")
    if not isinstance(screenshots, dict) or screenshots.get("status") != "NOT_CAPTURED_PROXY_SIMULATION":
        raise ValueError("proxy simulation must not invent screenshot hashes")


def copy_authority_database(destination: Path) -> str:
    assert_disposable_database(destination)
    if destination.exists():
        raise ValueError("refusing to overwrite an existing database copy")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{AUTHORITY_DB}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    assert_disposable_database(destination)
    return _sha256(destination)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _approve_count(database: Path) -> int:
    """Count Approve events without writing.

    The authority file stays on a read-only URI. A fresh sqlite backup of that
    file can refuse the same URI, so a disposable copy is opened normally and
    then locked to query_only.
    """
    if database.resolve() == AUTHORITY_DB.resolve():
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(database)
        connection.execute("PRAGMA query_only=ON")
    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM ledger_events WHERE action = 'Approve'"
        ).fetchone()
    finally:
        connection.close()
    return int(row[0])


def _listeners(port: int) -> list[str]:
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]


def _request(method: str, url: str, body: dict[str, Any] | None = None, timeout: float = 180) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {"raw": raw.decode("utf-8", errors="replace")}
        return exc.code, payload


def _wait_for_health(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 30
    last_error = "health check did not run"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"workspace server exited {process.returncode} before health")
        try:
            status, payload = _request("GET", f"{base_url}/health", timeout=2)
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.2)
            continue
        if status == 200 and payload.get("status") == "ok":
            return
        last_error = f"HTTP {status} {payload}"
        time.sleep(0.2)
    raise RuntimeError(last_error)


def _selected_feature(site_context: dict[str, Any]) -> dict[str, Any]:
    for feature in list(site_context.get("buildings", [])) + list(site_context.get("roads", [])):
        if feature.get("lineage_status") == "VERIFIED" and feature.get("feature_kind") in {"building", "road"}:
            return feature
    raise ValueError("site-context has no verified building or road feature")


def run_qgis_exit_smoke(output_gpkg: Path) -> dict[str, Any]:
    if not QGIS_PYTHON.is_file():
        return {"exit_code": 127, "exit_qgis_called": False, "reason": "QGIS Python is not installed"}
    env = os.environ.copy()
    env["PROJ_LIB"] = PROJ_LIB
    env["QGIS_PREFIX_PATH"] = QGIS_PREFIX
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            ["/usr/bin/arch", "-x86_64", str(QGIS_PYTHON), str(WORKTREE / "scripts/qgis_headless_exit_smoke.py"), str(output_gpkg)],
            cwd=WORKTREE,
            env=env,
            text=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            check=False,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": None,
            "exit_qgis_called": False,
            "reason": "QGIS smoke exceeded 180s",
            "stdout_tail": (exc.stdout or "")[-1000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-1000:] if isinstance(exc.stderr, str) else "",
        }
    parsed: dict[str, Any] = {}
    for line in reversed(completed.stdout.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            parsed = payload
            break
    return {
        "exit_code": completed.returncode,
        "exit_qgis_called": parsed.get("exit_qgis_called") is True,
        "qgis_version": parsed.get("qgis_version"),
        "qgis_architecture": parsed.get("qgis_architecture"),
        "feature_count": parsed.get("feature_count"),
        "bbox": parsed.get("bbox"),
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
    }


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _incomplete_receipt(
    *,
    port: int,
    error: str,
    approve_before: int | None,
    approve_after: int | None,
    authority_before: str,
    authority_after: str,
    before_listeners: dict[int, list[str]],
    after_listeners: dict[int, list[str]],
    qgis: dict[str, Any],
    server_log_tail: str,
) -> dict[str, Any]:
    receipt = {name: None for name in RECEIPT_FIELDS}
    receipt.update({
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "timezone": "UTC",
        "simulation": "C1_PROXY",
        "acceptance": "NOT_ACCEPTANCE",
        "qgis_version": qgis.get("qgis_version"),
        "qgis_architecture": "x86_64",
        "qgis_mcp_server_version": "0.14.0",
        "qgis_mcp_plugin_version": "0.14.0",
        "qgis_mcp_version_source": "pinned manifest config/runtimes/qgis-3.40.5-ltr-x86_64-rosetta.json",
        "live_mcp_contacted": False,
        "live_bridge_contacted": False,
        "actor_kind": "QGIS_PLUGIN",
        "screenshots": {
            "before_sync_sha256": None,
            "after_sync_sha256": None,
            "status": "NOT_CAPTURED_PROXY_SIMULATION",
        },
        "exit_qgis_called": qgis.get("exit_qgis_called"),
        "qgis_smoke_exit_code": qgis.get("exit_code"),
        "qgis_smoke_feature_count": qgis.get("feature_count"),
        "qgis_smoke_bbox": qgis.get("bbox"),
        "qgis_stdout_tail": qgis.get("stdout_tail"),
        "qgis_stderr_tail": qgis.get("stderr_tail"),
        "ports_started": [port],
        "protected_listeners_unchanged": before_listeners == after_listeners,
        "approve_event_count_before": approve_before,
        "approve_event_count_after": approve_after,
        "authority_sha256_before": authority_before,
        "authority_sha256_after": authority_after,
        "proxy_status": "INCOMPLETE",
        "error": error,
        "server_log_tail": server_log_tail,
    })
    return receipt


def _plugin_helpers():
    """Import plugin helpers when this file is launched as a script.

    Script execution puts ``scripts/`` on ``sys.path``, not the worktree root.
    """
    root = str(WORKTREE)
    if root not in sys.path:
        sys.path.insert(0, root)
    from qgis_plugin.urban_design_study_area.helpers import (
        build_platform_sync_payload,
        create_pending_platform_sync,
        matching_pending_sync_revision,
        validate_pending_sync_revision,
    )
    return (
        build_platform_sync_payload,
        create_pending_platform_sync,
        matching_pending_sync_revision,
        validate_pending_sync_revision,
    )


def run_proxy(*, database: Path, port: int, receipt_path: Path, qgis_output: Path) -> dict[str, Any]:
    (
        build_platform_sync_payload,
        create_pending_platform_sync,
        matching_pending_sync_revision,
        validate_pending_sync_revision,
    ) = _plugin_helpers()

    assert_disposable_port(port)
    assert_disposable_database(database)
    before_listeners = {protected: _listeners(protected) for protected in (8788, 9876)}
    approve_before = _approve_count(database)
    authority_before = _sha256(AUTHORITY_DB)
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.pop("ARIADNE_LIVE", None)
    env.pop("PROJECT_AI_AUTHORIZED", None)
    env.pop("PROJECT_OPENAI_AUTHORIZED", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = "src"
    log_path = receipt_path.with_name(receipt_path.name + ".server.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8")
    process: subprocess.Popen[str] | None = None
    qgis_result: dict[str, Any] | None = None
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "scripts/run_workspace_server.py",
                "--host", "127.0.0.1",
                "--port", str(port),
                "--database", str(database),
            ],
            cwd=WORKTREE,
            env=env,
            text=True,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        _wait_for_health(base_url, process)
        status, site_context = _request(
            "GET",
            f"{base_url}/api/v1/projects/{PROJECT_ID}/site-context",
        )
        if status != 200:
            raise RuntimeError(f"site-context HTTP {status}: {site_context}")
        study_area = site_context.get("study_area") or {}
        if (
            site_context.get("project_id") != PROJECT_ID
            or site_context.get("source_integrity_status") != "VERIFIED"
            or study_area.get("status") != "CONFIRMED_FOR_EXPLORATION"
        ):
            raise RuntimeError("site-context did not match the runbook preflight")
        selected = _selected_feature(site_context)
        current = site_context.get("current_workspace") or {}
        request_body = build_platform_sync_payload(
            project_id=PROJECT_ID,
            study_area_id=str(study_area["id"]),
            expected_workspace_revision=int(current.get("revision", 0)),
            actor_session_id="c1-proxy-simulation",
            source_snapshot_ids=list(site_context.get("source_snapshot_ids") or []),
            selected_features=[selected],
            current_workspace=current,
            request_key="c1-proxy-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        )
        pending = create_pending_platform_sync(base_url, request_body)
        sync_status, sync_body = _request(
            "POST",
            f"{base_url}/api/v1/workspaces/sync",
            pending["request_body"],
        )
        if sync_status != 201:
            raise RuntimeError(f"sync HTTP {sync_status}: {sync_body}")
        revision = sync_body.get("workspace_revision")
        revision_number = validate_pending_sync_revision(revision, pending)
        history_status, history = _request(
            "GET",
            f"{base_url}/api/v1/workspaces/{pending['workspace_id']}/history",
        )
        if history_status != 200:
            raise RuntimeError(f"history HTTP {history_status}: {history}")
        matched = matching_pending_sync_revision(history, pending)
        if matched is None:
            raise RuntimeError("history did not retain the proxy sync")
        replay_status, replay_body = _request(
            "POST",
            f"{base_url}/api/v1/workspaces/sync",
            pending["request_body"],
        )
        qgis = run_qgis_exit_smoke(qgis_output)
        qgis_result = qgis
        approve_after = _approve_count(database)
        authority_after = _sha256(AUTHORITY_DB)
        after_listeners = {protected: _listeners(protected) for protected in (8788, 9876)}
        receipt = {
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "timezone": "UTC",
            "simulation": "C1_PROXY",
            "acceptance": "NOT_ACCEPTANCE",
            "qgis_version": qgis.get("qgis_version"),
            "qgis_architecture": qgis.get("qgis_architecture"),
            "qgis_mcp_server_version": "0.14.0",
            "qgis_mcp_plugin_version": "0.14.0",
            "qgis_version_source": "headless smoke" if qgis.get("qgis_version") else "not_observed",
            "qgis_mcp_version_source": "pinned manifest config/runtimes/qgis-3.40.5-ltr-x86_64-rosetta.json",
            "live_mcp_contacted": False,
            "live_bridge_contacted": False,
            "project_id": PROJECT_ID,
            "study_area_id": study_area.get("id"),
            "expected_workspace_revision": request_body["expected_workspace_revision"],
            "source_snapshot_ids": request_body["source_snapshot_ids"],
            "selected_feature_ids": [selected.get("id")],
            "actor_kind": request_body["actor_kind"],
            "actor_session_id": request_body["actor_session_id"],
            "idempotency_key": request_body["idempotency_key"],
            "http_status": sync_status,
            "workspace_id": revision.get("workspace_id"),
            "revision": revision_number,
            "status": revision.get("status"),
            "feature_dispositions": revision.get("feature_dispositions"),
            "payload_digest": revision.get("payload_digest"),
            "idempotent_replay": sync_body.get("idempotent_replay"),
            "replay_http_status": replay_status,
            "replay_idempotent": replay_body.get("idempotent_replay") if isinstance(replay_body, dict) else None,
            "approve_event_count_before": approve_before,
            "approve_event_count_after": approve_after,
            "screenshots": {
                "before_sync_sha256": None,
                "after_sync_sha256": None,
                "status": "NOT_CAPTURED_PROXY_SIMULATION",
            },
            "exit_qgis_called": qgis.get("exit_qgis_called"),
            "qgis_smoke_exit_code": qgis.get("exit_code"),
            "qgis_smoke_feature_count": qgis.get("feature_count"),
            "qgis_smoke_bbox": qgis.get("bbox"),
            "ports_started": [port],
            "protected_listeners_unchanged": before_listeners == after_listeners,
            "authority_sha256_before": authority_before,
            "authority_sha256_after": authority_after,
            "database_copy_sha256": _sha256(database),
            "qgis_stdout_tail": qgis.get("stdout_tail"),
            "qgis_stderr_tail": qgis.get("stderr_tail"),
        }
        require_receipt_fields(receipt)
        if (
            replay_status != 200
            or replay_body.get("idempotent_replay") is not True
            or approve_before != approve_after
            or authority_before != authority_after
            or receipt["protected_listeners_unchanged"] is not True
            or receipt["exit_qgis_called"] is not True
            or receipt["qgis_smoke_exit_code"] != 0
            or receipt["idempotent_replay"] is not False
        ):
            receipt["proxy_status"] = "INCOMPLETE"
        else:
            receipt["proxy_status"] = "SIMULATED"
        _write_receipt(receipt_path, receipt)
        return receipt
    except Exception as exc:
        log_handle.flush()
        if qgis_result is None:
            qgis_result = run_qgis_exit_smoke(qgis_output)
        try:
            approve_after_error = _approve_count(database)
        except sqlite3.Error:
            approve_after_error = None
        authority_after = _sha256(AUTHORITY_DB)
        after_listeners = {protected: _listeners(protected) for protected in (8788, 9876)}
        try:
            server_log_tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        except OSError as read_error:
            server_log_tail = f"unreadable server log: {read_error}"
        receipt = _incomplete_receipt(
            port=port,
            error=f"{type(exc).__name__}: {exc}",
            approve_before=approve_before,
            approve_after=approve_after_error,
            authority_before=authority_before,
            authority_after=authority_after,
            before_listeners=before_listeners,
            after_listeners=after_listeners,
            qgis=qgis_result,
            server_log_tail=server_log_tail,
        )
        _write_receipt(receipt_path, receipt)
        return receipt
    finally:
        log_handle.close()
        if process is not None and process.poll() is None:
            os.killpg(process.pid, 15)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, 9)
                process.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--qgis-output", type=Path, required=True)
    parser.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    port = args.port if args.port is not None else choose_ephemeral_port()
    receipt = run_proxy(
        database=args.database,
        port=port,
        receipt_path=args.receipt,
        qgis_output=args.qgis_output,
    )
    print(json.dumps({"proxy_status": receipt.get("proxy_status"), "port": port, "revision": receipt.get("revision")}))
    return 0 if receipt.get("proxy_status") == "SIMULATED" else 1


if __name__ == "__main__":
    sys.exit(main())
