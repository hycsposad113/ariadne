from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urban_design.api import create_workspace_app
from urban_design.store import ProjectStateStore
from test_preview_catalog import make_bundle


def test_workspace_app_unconfigured_preview_is_disabled() -> None:
    store = ProjectStateStore(":memory:")
    app = create_workspace_app(store)
    client = TestClient(app)

    response = client.get("/api/v1/morphology/previews")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "DISABLED"
    assert payload["count"] == 0
    assert payload["previews"] == []


def test_workspace_app_single_parameter_fails_startup() -> None:
    store = ProjectStateStore(":memory:")

    with pytest.raises(ValueError, match="configured together"):
        create_workspace_app(store, morphology_preview_root="/some/path")

    with pytest.raises(ValueError, match="configured together"):
        create_workspace_app(store, morphology_preview_manifest_sha256="a" * 64)


def test_workspace_app_rejects_blank_preview_root_or_pin_before_startup() -> None:
    store = ProjectStateStore(":memory:")

    with pytest.raises(ValueError, match="must not be blank"):
        create_workspace_app(
            store,
            morphology_preview_root="",
            morphology_preview_manifest_sha256="a" * 64,
        )
    with pytest.raises(ValueError, match="must not be blank"):
        create_workspace_app(
            store,
            morphology_preview_root="/some/path",
            morphology_preview_manifest_sha256="",
        )


def test_run_workspace_server_cli_single_parameter_exits_with_error() -> None:
    script_env = {**os.environ, "PYTHONPATH": str(Path("src").resolve()), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_workspace_server.py",
            "--morphology-preview-root",
            "/some/path",
        ],
        capture_output=True,
        text=True,
        env=script_env,
    )
    assert result.returncode == 2
    assert "must be specified together or both omitted" in result.stderr

    result2 = subprocess.run(
        [
            sys.executable,
            "scripts/run_workspace_server.py",
            "--morphology-preview-manifest-sha256",
            "a" * 64,
        ],
        capture_output=True,
        text=True,
        env=script_env,
    )
    assert result2.returncode == 2
    assert "must be specified together or both omitted" in result2.stderr


def test_run_workspace_server_cli_rejects_blank_preview_arguments_before_serving() -> None:
    script_env = {**os.environ, "PYTHONPATH": str(Path("src").resolve()), "PYTHONDONTWRITEBYTECODE": "1"}
    for option in ("--morphology-preview-root", "--morphology-preview-manifest-sha256"):
        result = subprocess.run(
            [sys.executable, "scripts/run_workspace_server.py", option, ""],
            capture_output=True,
            text=True,
            env=script_env,
            timeout=10,
        )
        assert result.returncode == 2
        assert "must not be blank" in result.stderr


def test_workspace_app_hash_mismatch_returns_503_with_category(tmp_path: Path) -> None:
    root, _pin = make_bundle(tmp_path / "bundle")
    store = ProjectStateStore(":memory:")
    app = create_workspace_app(
        store,
        morphology_preview_root=root,
        morphology_preview_manifest_sha256="0" * 64,
    )
    client = TestClient(app)

    response = client.get("/api/v1/morphology/previews")

    assert response.status_code == 503
    assert "hash_mismatch" in response.json()["detail"]


def test_workspace_app_path_traversal_returns_404(tmp_path: Path) -> None:
    root, pin = make_bundle(tmp_path / "bundle")
    store = ProjectStateStore(":memory:")
    app = create_workspace_app(
        store,
        morphology_preview_root=root,
        morphology_preview_manifest_sha256=pin,
    )
    client = TestClient(app)

    assert client.get("/api/v1/morphology/previews/A/..%2F..%2Fetc/assets/plan").status_code == 404
    assert client.get("/api/v1/morphology/previews/A/perimeter_block_city/assets/..%2Fplan").status_code == 404
    assert client.get("/api/v1/morphology/previews/A/perimeter_block_city/assets/plan%2F..").status_code == 404
    assert client.get("/api/v1/morphology/previews/..%2F/assets/plan").status_code == 404
    assert client.get("/api/v1/morphology/previews/A/non_existent").status_code == 404


def test_workspace_app_get_requests_leave_store_entities_and_ledger_unchanged(tmp_path: Path) -> None:
    root, pin = make_bundle(tmp_path / "bundle")
    store = ProjectStateStore(tmp_path / "disposable.sqlite3")

    # Seed an entity and ledger event in the store to ensure it is active
    store.create(
        entity_type="Project",
        payload={"name": "Test Project"},
        entity_id="project-test",
        actor="test-actor",
        action="Create",
    )

    count_heads_before = store.connection.execute("SELECT count(*) FROM state_heads").fetchone()[0]
    count_versions_before = store.connection.execute("SELECT count(*) FROM state_versions").fetchone()[0]
    count_ledger_before = store.connection.execute("SELECT count(*) FROM ledger_events").fetchone()[0]

    assert count_heads_before > 0
    assert count_versions_before > 0
    assert count_ledger_before > 0

    app = create_workspace_app(
        store,
        morphology_preview_root=root,
        morphology_preview_manifest_sha256=pin,
    )
    client = TestClient(app)

    # Perform multiple preview GET operations
    res_list = client.get("/api/v1/morphology/previews")
    assert res_list.status_code == 200

    res_detail = client.get("/api/v1/morphology/previews/A/perimeter_block_city")
    assert res_detail.status_code == 200

    res_plan = client.get("/api/v1/morphology/previews/A/perimeter_block_city/assets/plan")
    assert res_plan.status_code == 200

    res_axon = client.get("/api/v1/morphology/previews/A/perimeter_block_city/assets/axonometric")
    assert res_axon.status_code == 200

    res_geom = client.get("/api/v1/morphology/previews/A/perimeter_block_city/assets/geometry")
    assert res_geom.status_code == 200

    count_heads_after = store.connection.execute("SELECT count(*) FROM state_heads").fetchone()[0]
    count_versions_after = store.connection.execute("SELECT count(*) FROM state_versions").fetchone()[0]
    count_ledger_after = store.connection.execute("SELECT count(*) FROM ledger_events").fetchone()[0]

    assert count_heads_after == count_heads_before
    assert count_versions_after == count_versions_before
    assert count_ledger_after == count_ledger_before

    store.close()

def test_real_source_smoke_uses_free_loopback_ports_and_exclusive_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import smoke_test_real_source

    choose_ports = getattr(smoke_test_real_source, "choose_loopback_ports", None)
    write_receipt = getattr(smoke_test_real_source, "write_receipt_exclusive", None)
    assert callable(choose_ports), "smoke verifier must choose dynamic loopback ports"
    assert callable(write_receipt), "smoke verifier must create receipts exclusively"

    available_ports = iter([5195, 8787, 45001, 45002])

    class FakeSocket:
        def __enter__(self):
            self.port = next(available_ports)
            return self

        def __exit__(self, *_args):
            return False

        def bind(self, address):
            assert address == ("127.0.0.1", 0)

        def getsockname(self):
            return ("127.0.0.1", self.port)

    monkeypatch.setattr(smoke_test_real_source.socket, "socket", lambda *_args: FakeSocket())
    api_port, vite_port = choose_ports()
    assert (api_port, vite_port) == (45001, 45002)
    assert {api_port, vite_port}.isdisjoint({5195, 8787, 8788, 8789})

    receipt = tmp_path / "fresh-receipt.json"
    write_receipt(receipt, {"status": "PASS"})
    assert '"status": "PASS"' in receipt.read_text()
    with pytest.raises(FileExistsError):
        write_receipt(receipt, {"status": "OVERWRITE"})
    assert '"status": "PASS"' in receipt.read_text()


def test_real_source_smoke_detects_asset_byte_or_etag_mismatch(tmp_path: Path) -> None:
    from scripts import smoke_test_real_source

    verify_asset = getattr(smoke_test_real_source, "verify_asset_bytes", None)
    assert callable(verify_asset), "smoke verifier must compare source bytes and response ETag"
    source = tmp_path / "plan.png"
    source_bytes = b"pinned image bytes"
    source.write_bytes(source_bytes)
    import hashlib
    digest = hashlib.sha256(source_bytes).hexdigest()
    assert verify_asset(source, source_bytes, '"' + digest + '"') == digest
    with pytest.raises(AssertionError):
        verify_asset(source, b"tampered image bytes", '"' + digest + '"')
    with pytest.raises(AssertionError):
        verify_asset(source, source_bytes, '"' + "0" * 64 + '"')

def test_smoke_cleanup_records_permission_error_and_attempts_each_owned_process() -> None:
    from scripts import smoke_test_real_source

    cleanup = getattr(smoke_test_real_source, "cleanup_owned_processes", None)
    assert callable(cleanup), "smoke cleanup must independently record every owned child outcome"

    class FakeProcess:
        def __init__(self, pid: int, args: list[str]) -> None:
            self.pid = pid
            self.args = args

    api = FakeProcess(12341, ["python", "api.py"])
    vite = FakeProcess(12342, ["npm", "run", "dev"])
    attempted: list[str] = []

    def stop_one(proc: FakeProcess, name: str) -> dict[str, object]:
        attempted.append(name)
        if name == "API":
            raise PermissionError("simulated process-group probe denial")
        return {"status": "STOPPED", "pid": proc.pid}

    result = cleanup([("API", api), ("Vite", vite)], stopper=stop_one)

    assert attempted == ["API", "Vite"]
    assert result["overall"] == "OUTCOME_UNKNOWN"
    assert result["processes"][0]["status"] == "OUTCOME_UNKNOWN"
    assert result["processes"][0]["pid"] == 12341
    assert result["processes"][0]["pgid"] == 12341
    assert result["processes"][0]["command"] == ["python", "api.py"]
    assert result["processes"][0]["error_type"] == "PermissionError"
    assert result["processes"][1]["status"] == "STOPPED"



def test_stop_owned_process_permission_failure_reports_unknown() -> None:
    from scripts import smoke_test_real_source

    class FakeProcess:
        pid = 12343
        args = ["node", "vite.js"]

        def poll(self):
            return None

        def terminate(self):
            raise PermissionError("simulated direct-child signal denial")

    result = smoke_test_real_source.stop_owned_process(FakeProcess(), "Vite")

    assert result["status"] == "OUTCOME_UNKNOWN"
    assert result["pid"] == 12343
    assert result["pgid"] == 12343
    assert result["command"] == ["node", "vite.js"]
    assert result["error_type"] == "PermissionError"


def test_stop_owned_process_stops_only_direct_child() -> None:
    from scripts import smoke_test_real_source

    class FakeProcess:
        pid = 12344
        args = ["node", "vite.js"]

        def __init__(self) -> None:
            self.returncode = None
            self.terminated = False
            self.killed = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self, timeout=None):
            if self.returncode is None:
                raise subprocess.TimeoutExpired(self.args, timeout)
            return self.returncode

    proc = FakeProcess()
    result = smoke_test_real_source.stop_owned_process(proc, "Vite")

    assert result["status"] == "STOPPED"
    assert result["pid"] == 12344
    assert result["command"] == ["node", "vite.js"]
    assert proc.terminated
    assert not proc.killed


def test_smoke_finalizer_writes_outcome_unknown_receipt_after_cleanup_denial(tmp_path: Path) -> None:
    import json
    from scripts import smoke_test_real_source

    finalize = getattr(smoke_test_real_source, "finalize_smoke_run", None)
    assert callable(finalize), "smoke runner must centralize cleanup and exclusive receipt writing"

    class FakeProcess:
        def __init__(self, pid: int, args: list[str]) -> None:
            self.pid = pid
            self.args = args

    api = FakeProcess(12345, ["python", "api.py"])
    vite = FakeProcess(12346, ["node", "vite.js"])
    attempted: list[str] = []

    def stop_one(proc: FakeProcess, name: str) -> dict[str, object]:
        attempted.append(name)
        if name == "API":
            raise PermissionError("simulated cleanup denial")
        return {"status": "STOPPED", "return_code": 0}

    receipt = tmp_path / "smoke-receipt.json"
    results: dict[str, object] = {"overall": "PASS", "checks": [{"status": "PASS"}]}
    finalized = finalize(
        results,
        receipt,
        [("API", api), ("Vite", vite)],
        stopper=stop_one,
    )

    assert finalized["receipt_written"] is True
    assert attempted == ["API", "Vite"]
    saved = json.loads(receipt.read_text())
    assert saved["overall"] == "OUTCOME_UNKNOWN"
    assert saved["process_cleanup"]["processes"][0]["pid"] == 12345
    assert saved["process_cleanup"]["processes"][0]["pgid"] == 12345
    assert saved["process_cleanup"]["processes"][0]["command"] == ["python", "api.py"]
    duplicate = finalize({"overall": "PASS"}, receipt, [], stopper=stop_one)
    assert duplicate["receipt_written"] is False
    assert duplicate["overall"] == "OUTCOME_UNKNOWN"
    assert json.loads(receipt.read_text())["overall"] == "OUTCOME_UNKNOWN"


def test_real_source_smoke_rejects_urban_design_runtime_paths(tmp_path: Path) -> None:
    from scripts import smoke_test_real_source

    is_runtime_path = getattr(smoke_test_real_source, "is_urban_design_runtime_path", None)
    assert callable(is_runtime_path), "smoke verifier must identify protected runtime paths"
    assert is_runtime_path(tmp_path / ".urban_design_runtime" / "state.sqlite3") is True
    assert is_runtime_path(tmp_path / "disposable" / "state-copy.sqlite3") is False


def test_real_source_smoke_rejects_authoritative_database_symlink_and_hardlink(tmp_path: Path) -> None:
    from scripts import smoke_test_real_source

    validate_database = getattr(smoke_test_real_source, "ensure_disposable_database", None)
    assert callable(validate_database), "smoke verifier must compare resolved path and inode identity"
    authority = tmp_path / ".urban_design_runtime" / "state.sqlite3"
    authority.parent.mkdir()
    authority.write_bytes(b"test authority database")

    symlink = tmp_path / "authority-symlink.sqlite3"
    symlink.symlink_to(authority)
    hardlink = tmp_path / "authority-hardlink.sqlite3"
    hardlink.hardlink_to(authority)

    for alias in (symlink, hardlink):
        with pytest.raises(ValueError, match="authoritative database"):
            validate_database(alias, authority)
