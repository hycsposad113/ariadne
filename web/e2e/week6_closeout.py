#!/usr/bin/env python3
"""Week 6 closeout drill on a disposable database copy and temporary ports.

The script refuses protected ports, backs up the source database with the
SQLite backup API in read-only mode, reads one workspace from the copy, and
runs the fault matrix through the shipped job, artifact, decision-key,
live-AI, and Radiance functions. It does not merge to main, write the
authority database, create a HumanDecision, read Keychain, or call a live model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from urban_design.decision_key import initialize_decision_key, verify_decision_key_strict
from urban_design.e2e_outputs import resolve_e2e_output_directory
from urban_design.e2e_ports import RESERVED_LOOPBACK_PORTS
from urban_design.environment.radiation import (
    E2_WEATHER_PAUSE_ACTIVE,
    RadiationInputReferences,
    refuse_formal_e2,
)
from urban_design.environment.sunlight import verify_radiance_runtime
from urban_design.generation.formal_persistence import persist_results
from urban_design.generation.job_runner import GenerationJobRunner
from urban_design.generation.job_store import GenerationJobStore, JobStatus
from urban_design.model_profiles import load_model_provider_config
from urban_design.model_provider import CriticRequest, ModelProviderRouter, create_profile_provider
from urban_design.store import ProjectStateStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_DATABASE = Path(
    "/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3"
)
PROTECTED_PORTS = {
    5173,
    5195,
    8644,
    8787,
    8788,
    8789,
    8795,
    9876,
}
API_PORTS = set(range(8880, 8890))
WEB_PORTS = set(range(5280, 5290))
BIND_HOST = "127.0.0.1"
_TEST_KEY = "closeout-test-key-not-a-passphrase"
_WRONG_KEY = "closeout-wrong-key-not-a-passphrase"
_FIXTURE_KEY = "fixture-key-not-live"


class CloseoutRefusal(RuntimeError):
    """The drill refused a port, path, or authority write before any service started."""


def assert_drill_port(port: int, *, kind: str) -> None:
    """Refuse protected, out-of-range, and already-listening ports."""

    if kind not in {"api", "web"}:
        raise CloseoutRefusal(f"unknown port kind {kind}")
    if port in PROTECTED_PORTS or port in RESERVED_LOOPBACK_PORTS:
        raise CloseoutRefusal(
            f"requested port {port} is protected; refusing to launch or stop its owner"
        )
    allowed = API_PORTS if kind == "api" else WEB_PORTS
    if port not in allowed:
        raise CloseoutRefusal(
            f"requested {kind} port {port} is outside the temporary drill range"
        )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        try:
            probe.connect((BIND_HOST, port))
        except ConnectionRefusedError:
            return
        except OSError as exc:
            raise CloseoutRefusal(f"requested port {port} probe failed: {exc}") from exc
    raise CloseoutRefusal(
        f"requested port {port} is occupied; refusing to reuse or stop its owner"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def isolated_backup(source: Path, destination: Path) -> str:
    """Copy ``source`` with the SQLite backup API. The source is opened read-only."""

    source = source.resolve(strict=True)
    destination = destination.expanduser()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"backup destination already exists: {destination}")
    resolved_destination = destination.resolve()
    if resolved_destination == AUTHORITY_DATABASE.resolve():
        raise CloseoutRefusal("refusing to write the authority database")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb"):
        pass
    source_uri = source.as_uri() + "?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("BACKUP_QUICK_CHECK_FAILED")
    return sha256_file(destination)


def discover_workspace(database: Path) -> dict[str, Any]:
    uri = database.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """SELECT entity_id, project_id, current_revision
               FROM state_heads WHERE entity_type = 'WorkspaceRevision'
               ORDER BY entity_id"""
        ).fetchone()
        if row is None:
            raise RuntimeError("database copy has no WorkspaceRevision")
        decisions = connection.execute(
            "SELECT COUNT(*) FROM state_heads WHERE entity_type = 'HumanDecision'"
        ).fetchone()[0]
        scenarios = connection.execute(
            "SELECT COUNT(*) FROM state_heads WHERE entity_type = 'DesignScenario'"
        ).fetchone()[0]
        quick = connection.execute("PRAGMA quick_check").fetchone()[0]
    return {
        "workspace_id": row["entity_id"],
        "project_id": row["project_id"],
        "revision": int(row["current_revision"]),
        "human_decision_count": int(decisions),
        "design_scenario_count": int(scenarios),
        "quick_check": quick,
    }


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def boot_workspace_read(
    *,
    database: Path,
    api_port: int,
    workspace_id: str,
    log_path: Path,
) -> dict[str, Any]:
    """Start the shipped workspace server on the copy and read one workspace."""

    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_workspace_server.py"),
        "--host",
        BIND_HOST,
        "--port",
        str(api_port),
        "--database",
        str(database),
    ]
    env = os.environ.copy()
    env["PROJECT_AI_AUTHORIZED"] = "0"
    env.pop("ARIADNE_LIVE", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    log_handle = log_path.open("wb")
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    url = f"http://{BIND_HOST}:{api_port}/api/v1/workspaces/{workspace_id}"
    body: dict[str, Any] | None = None
    status_code: int | None = None
    deadline = time.monotonic() + 45
    last_error = "server did not answer"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            last_error = f"server exited {process.returncode}"
            break
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                status_code = int(response.status)
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = str(exc)
            time.sleep(0.4)
            continue
        if not isinstance(payload, dict) or not payload.get("project_id") or not payload.get("workspace_id"):
            _stop_process_group(process)
            log_handle.close()
            raise RuntimeError("workspace response has no project payload")
        body = payload
        break
    if body is None or status_code is None:
        _stop_process_group(process)
        log_handle.close()
        raise RuntimeError(last_error)
    return {
        "http_status": status_code,
        "workspace_id": body["workspace_id"],
        "project_id": body["project_id"],
        "revision": body["revision"],
        "study_area_id": body["study_area_id"],
        "status": body["status"],
        "server_pid": process.pid,
        "body": body,
        "_process": process,
        "_log": log_handle,
    }


def recover_after_dead_owner(
    database: Path,
    owner_pid: int,
    *,
    output_root: Path,
    before_recover,
) -> dict[str, str]:
    """Claim a RUNNING job, let the caller kill that owner, then reconcile it.

    ``before_recover`` must make ``owner_pid`` dead. The handler must not rerun.
    """

    calls: list[str] = []

    def handler(_job, _path, _token):
        calls.append("handler")
        raise AssertionError("recovery must not rerun a killed job")

    store = GenerationJobStore(database)
    job, created = store.enqueue(
        project_id="closeout-drill",
        idempotency_key="api-killed-mid-job",
        stage="closeout-drill",
        request={"drill": "api-killed-mid-job"},
        input_refs=[
            {
                "id": "ref-closeout",
                "sha256": "sha256:" + ("ab" * 32),
                "kind": "artifact",
            }
        ],
    )
    if not created:
        raise RuntimeError("closeout job idempotency key already existed")
    claimed_at = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(timespec="microseconds")
    owner = uuid.uuid4().hex
    if not store.claim(job.job_id, owner, owner_pid, now=claimed_at):
        raise RuntimeError("closeout job was not claimed")
    before_recover()
    runner = GenerationJobRunner(
        store,
        staging_root=output_root / "job-staging",
        output_root=output_root / "job-output",
    )
    runner.register_handler("closeout-drill", "g14", handler, external=False)
    recovered = runner.recover(job.job_id)
    reopened = GenerationJobStore(database)
    again = reopened.get(job.job_id)
    actual = recovered.status.value
    recovery = again.status.value
    if calls:
        recovery = "HANDLER_RERAN"
    return {
        "expected": JobStatus.INTERRUPTED.value,
        "actual": actual,
        "recovery": recovery if recovery == JobStatus.INTERRUPTED.value else recovery,
        "error_code": again.error_code or "",
    }


def fault_tampered_database_hash(backup: Path, destination: Path) -> dict[str, str]:
    recorded = sha256_file(backup)
    destination.write_bytes(backup.read_bytes())
    blob = bytearray(destination.read_bytes())
    index = 100 if len(blob) > 120 else len(blob) - 1
    blob[index] ^= 0x01
    destination.write_bytes(blob)
    tampered = sha256_file(destination)
    original = sha256_file(backup)
    with sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True) as connection:
        quick = connection.execute("PRAGMA quick_check").fetchone()[0]
    actual = "HASH_MISMATCH" if tampered != recorded else "HASH_UNCHANGED"
    recovery = "BACKUP_HASH_RETAINED" if original == recorded and quick == "ok" else "BACKUP_DRIFT"
    return {"expected": "HASH_MISMATCH", "actual": actual, "recovery": recovery}


def fault_tampered_artifact(output: Path) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    recipe = "tamper-recipe"
    path = output / f"{recipe}.geojson"
    original = '{"tampered":true}\n'
    path.write_text(original, encoding="utf-8")
    report = {
        "candidates": [
            {
                "recipe_id": recipe,
                "geometry": {"type": "FeatureCollection", "features": []},
                "stages": {"steps": []},
            }
        ]
    }
    try:
        persist_results(report, output / "unused.sqlite3", output, dry_run=True)
    except ValueError as exc:
        message = str(exc)
    else:
        message = "NO_ERROR"
    retained = path.read_text(encoding="utf-8") == original
    actual = "OUTCOME_UNKNOWN" if message.startswith("OUTCOME_UNKNOWN") else message
    recovery = "ORIGINAL_BYTES_RETAINED" if retained else "BYTES_CHANGED"
    return {"expected": "OUTCOME_UNKNOWN", "actual": actual, "recovery": recovery}


def fault_wrong_passphrase(key_path: Path) -> dict[str, str]:
    """Verify a disposable test key. The report must not contain either secret."""

    prompts = iter((_TEST_KEY, _TEST_KEY))
    initialize_decision_key(path=key_path, password_prompt=lambda _label: next(prompts))
    rejected = verify_decision_key_strict(_WRONG_KEY, path=key_path)
    accepted = verify_decision_key_strict(_TEST_KEY, path=key_path)
    actual = "REJECTED" if rejected is False else "ACCEPTED"
    recovery = "TEST_KEY_STILL_ACCEPTED" if accepted is True else "TEST_KEY_LOST"
    return {"expected": "REJECTED", "actual": actual, "recovery": recovery}


def _install_live_network_block():
    import urban_design.model_provider as model_provider

    original_urlopen = model_provider.urlopen
    original_run = model_provider.subprocess.run

    def blocked_urlopen(*_args, **_kwargs):
        raise AssertionError("closeout must not open a live HTTP socket")

    def blocked_run(command, *_args, **_kwargs):
        text = " ".join(command) if isinstance(command, (list, tuple)) else str(command)
        if "find-generic-password" in text or "security" in text.split():
            raise AssertionError("closeout must not read Keychain")
        raise AssertionError(f"unexpected subprocess during live-AI fault: {text}")

    model_provider.urlopen = blocked_urlopen
    model_provider.subprocess.run = blocked_run
    return model_provider, original_urlopen, original_run


def fault_live_ai(database: Path, *, http_status: int) -> dict[str, str]:
    """Drive the shipped router with a fake transport. No socket and no Keychain."""

    previous_gate = os.environ.get("PROJECT_AI_AUTHORIZED")
    # The API child stays at 0. This process sets the gate only so the shipped
    # router will reach the injected fake transport; urlopen and Keychain stay blocked.
    os.environ["PROJECT_AI_AUTHORIZED"] = "1"
    os.environ.pop("PROJECT_OPENAI_AUTHORIZED", None)
    model_provider, original_urlopen, original_run = _install_live_network_block()
    calls: list[str] = []

    def model_list(_url, headers, _timeout):
        calls.append("models")
        if headers.get("Authorization") != f"Bearer {_FIXTURE_KEY}":
            raise AssertionError("fixture transport received an unexpected credential")
        return 200, {"data": [{"id": "gpt-4o"}]}

    def transport(_url, headers, _body, _timeout):
        calls.append("chat")
        if headers.get("Authorization") != f"Bearer {_FIXTURE_KEY}":
            raise AssertionError("fixture transport received an unexpected credential")
        return http_status, {"error": "withheld"}

    profile = next(item for item in load_model_provider_config().profiles if item.id == "openai-gpt-4o")
    provider = create_profile_provider(
        profile,
        api_key=_FIXTURE_KEY,
        transport=transport,
        model_list_transport=model_list,
        request_id_factory=lambda: "request-closeout-fixed",
    )
    store = ProjectStateStore(database)
    router = ModelProviderRouter(
        providers={"openai-gpt-4o": provider},
        fallback_order=["openai-gpt-4o"],
        store=store,
        project_id="closeout-live-ai",
        weekly_call_limit=200,
    )
    try:
        result = router.generate_criticism(
            CriticRequest(
                study_area_id="study-area-rotterdam-m4h-pilot-project-v5",
                evidence_bundle=[],
                query="Explain this scheme using only the evidence bundle.",
            )
        )
    finally:
        store.close()
        model_provider.urlopen = original_urlopen
        model_provider.subprocess.run = original_run
        if previous_gate is None:
            os.environ.pop("PROJECT_AI_AUTHORIZED", None)
        else:
            os.environ["PROJECT_AI_AUTHORIZED"] = previous_gate
    observed = int(result.get("provider_metadata", {}).get("http_status") or 0)
    actual = f"HTTP_{observed}" if observed else str(result.get("provider_status"))
    recovery = "NO_SOCKET" if calls and "security" not in json.dumps(result) else "UNEXPECTED_CALL"
    return {"expected": f"HTTP_{http_status}", "actual": actual, "recovery": recovery}


def fault_radiance_unavailable(empty_runtime: Path) -> dict[str, str]:
    empty_runtime.mkdir(parents=True, exist_ok=True)
    status = verify_radiance_runtime(custom_path=empty_runtime)
    actual = "UNAVAILABLE" if status.available is False and status.reason and "RADIANCE_RUNTIME_INCOMPLETE" in status.reason else "AVAILABLE"
    manifest = PROJECT_ROOT / "config" / "runtimes" / "radiance-6.0.2-arm64.json"
    recovery = "PINNED_MANIFEST_PRESENT" if manifest.is_file() else "MANIFEST_MISSING"
    return {"expected": "UNAVAILABLE", "actual": actual, "recovery": recovery}


def fault_formal_e2_refusal() -> dict[str, str]:
    refusal = refuse_formal_e2(RadiationInputReferences())
    actual = refusal.status if refusal.dispatch_allowed is False and refusal.e2_dispatch_attempted is False else "DISPATCHED"
    recovery = refusal.gate if E2_WEATHER_PAUSE_ACTIVE is True else "PAUSE_CHANGED"
    return {"expected": "BLOCKED", "actual": actual, "recovery": recovery}


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        for secret in (_TEST_KEY, _WRONG_KEY, _FIXTURE_KEY):
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    return value


def _fault_line(name: str, row: Mapping[str, str]) -> str:
    return (
        f"FAULT {name} expected={row['expected']} actual={row['actual']} recovery={row['recovery']}"
    )


def run_drill(source_database: Path, output_root: Path, api_port: int, web_port: int) -> dict[str, Any]:
    assert_drill_port(api_port, kind="api")
    assert_drill_port(web_port, kind="web")
    if source_database.resolve() != AUTHORITY_DATABASE.resolve() and not source_database.is_file():
        raise CloseoutRefusal("source database is missing")
    target, described = resolve_e2e_output_directory(output_root, project_root=PROJECT_ROOT)
    target.mkdir(parents=True)
    authority_before = sha256_file(AUTHORITY_DATABASE)
    backup = target / "state.sqlite3"
    backup_hash = isolated_backup(source_database, backup)
    authority_after = sha256_file(AUTHORITY_DATABASE)
    if authority_before != authority_after:
        raise RuntimeError("authority database changed during the read-only backup")
    source_inventory = discover_workspace(source_database)
    inventory = discover_workspace(backup)
    if source_inventory != inventory:
        raise RuntimeError("database copy does not match the read-only source inventory")
    log_path = target / "api-server.log"
    booted = boot_workspace_read(
        database=backup,
        api_port=api_port,
        workspace_id=inventory["workspace_id"],
        log_path=log_path,
    )
    process = booted.pop("_process")
    log_handle = booted.pop("_log")
    body = booted.pop("body")
    (target / "api-launch.json").write_text(json.dumps(body, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    server_pid = int(process.pid)
    job_db = target / "jobs.sqlite3"

    def _kill_api() -> None:
        _stop_process_group(process)
        if not log_handle.closed:
            log_handle.close()

    killed = recover_after_dead_owner(
        job_db,
        server_pid,
        output_root=target / "killed-job",
        before_recover=_kill_api,
    )
    faults = {
        "api-killed-mid-job": killed,
        "tampered-db-copy-hash": fault_tampered_database_hash(backup, target / "tampered-state.sqlite3"),
        "tampered-artifact": fault_tampered_artifact(target / "tampered-artifact"),
        "wrong-passphrase": fault_wrong_passphrase(target / "decision-key"),
        "live-ai-401": fault_live_ai(target / "live-ai-401.sqlite3", http_status=401),
        "live-ai-429": fault_live_ai(target / "live-ai-429.sqlite3", http_status=429),
        "radiance-unavailable": fault_radiance_unavailable(target / "empty-radiance"),
        "formal-e2-refusal": fault_formal_e2_refusal(),
    }
    packet = PROJECT_ROOT / "docs" / "w6" / "road-access-golive-packet-20261004T2230Z.md"
    packet_text = packet.read_text(encoding="utf-8") if packet.is_file() else ""
    report = {
        "bind_host": BIND_HOST,
        "api_port": api_port,
        "web_port": web_port,
        "web_server": "NOT_STARTED",
        "output": described,
        "backup_sha256": backup_hash,
        "authority_sha256": authority_after,
        "authority_written": False,
        "project_ai_authorized": "0",
        "ariadne_live": False,
        "workspace": {
            "http_status": booted["http_status"],
            "workspace_id": booted["workspace_id"],
            "project_id": booted["project_id"],
            "revision": booted["revision"],
            "study_area_id": booted["study_area_id"],
            "status": booted["status"],
            "human_decision_count": inventory["human_decision_count"],
            "design_scenario_count": inventory["design_scenario_count"],
        },
        "r4_tradeoff_label_present": "ACCEPTED_TRADEOFF_FOUNDER_2026-10-04" in packet_text,
        "faults": faults,
        "gates": {
            "LIVE_AI_GATE": "READY_FOR_FOUNDER",
            "WEATHER_METHOD_GATE": "READY_FOR_FOUNDER",
            "E2_EXECUTION_GATE": "BLOCKED",
            "DECISION_3": "NEEDS_FOUNDER",
            "VISUAL_SELF_CHECK": "INCOMPLETE",
            "G3_PERSIST_MEASURE": "PARTIAL",
            "C1_FOUNDER_SYNC": "NEEDS_FOUNDER",
            "FIVE_SCHEME_REGENERATION": "NEEDS_FOUNDER",
        },
    }
    redacted = _redact(report)
    encoded = json.dumps(redacted)
    for secret in (_TEST_KEY, _WRONG_KEY, _FIXTURE_KEY):
        if secret in encoded:
            raise RuntimeError("closeout report would contain a secret")
    (target / "closeout-report.json").write_text(
        json.dumps(redacted, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [_fault_line(name, row) for name, row in faults.items()]
    (target / "faults.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for line in lines:
        print(line)
    mismatched = [name for name, row in faults.items() if row["actual"] != row["expected"]]
    if mismatched:
        raise RuntimeError("fault actual status diverged: " + ", ".join(mismatched))
    return redacted


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-database", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--api-port", type=int, required=True)
    parser.add_argument("--web-port", type=int, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run_drill(args.source_database, args.output_root, args.api_port, args.web_port)
    except Exception as exc:
        print(f"CLOSEOUT_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("CLOSEOUT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
