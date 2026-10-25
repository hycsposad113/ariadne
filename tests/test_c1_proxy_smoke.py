from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from qgis_plugin.urban_design_study_area.helpers import (
    build_platform_sync_payload,
    create_pending_platform_sync,
)
from scripts.c1_proxy_smoke import (
    AUTHORITY_DB,
    PROTECTED_PORTS,
    RECEIPT_FIELDS,
    assert_disposable_database,
    assert_disposable_port,
    require_receipt_fields,
)

ROOT = Path(__file__).resolve().parents[1]


def test_proxy_refuses_protected_ports_and_the_authority_database(tmp_path: Path) -> None:
    for port in (8788, 9876, 8789, 8795):
        with pytest.raises(ValueError, match="protected port"):
            assert_disposable_port(port)
    assert 8788 in PROTECTED_PORTS and 9876 in PROTECTED_PORTS
    with pytest.raises(ValueError, match="authority"):
        assert_disposable_database(AUTHORITY_DB)
    copy = tmp_path / "state.sqlite3"
    copy.write_bytes(b"not-the-authority")
    assert_disposable_database(copy)


def test_builder_payload_freezes_the_actor_fields_the_api_requires() -> None:
    feature = {
        "id": "bag:0599100000035095",
        "feature_kind": "building",
        "lineage_status": "VERIFIED",
        "source_artifact_id": "artifact-bag-normalized",
        "source_snapshot_id": "snapshot-bag",
        "source_feature_id": "0599100000035095",
    }
    payload = build_platform_sync_payload(
        project_id="rotterdam-m4h-pilot-project",
        study_area_id="study-area-v5",
        expected_workspace_revision=8,
        actor_session_id="c1-proxy-simulation",
        source_snapshot_ids=["snapshot-bag"],
        selected_features=[feature],
        current_workspace=None,
        request_key="c1-proxy-test",
    )
    pending = create_pending_platform_sync("http://127.0.0.1:8891", payload)

    assert pending["request_body"] == payload
    assert pending["request_body"]["actor_kind"] == "QGIS_PLUGIN"
    with pytest.raises(ValueError, match="typed sync request"):
        create_pending_platform_sync("http://127.0.0.1:8891", {key: value for key, value in payload.items() if key != "actor_kind"})


def test_script_launch_imports_plugin_helpers_without_a_preseeded_worktree_path() -> None:
    code = r"""
import importlib.util
import sys
from pathlib import Path
root = Path.cwd().resolve()
sys.path = [item for item in sys.path if item and Path(item).resolve() != root]
sys.path.insert(0, str(root / "scripts"))
spec = importlib.util.spec_from_file_location("c1_as_script", root / "scripts" / "c1_proxy_smoke.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
helpers = module._plugin_helpers()
assert helpers[0].__name__ == "build_platform_sync_payload"
print("ok")
"""
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = "src"
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout


def test_headless_smoke_calls_exit_qgis_before_returning() -> None:
    source = (ROOT / "scripts/qgis_headless_exit_smoke.py").read_text()
    finally_at = source.index("finally:")
    exit_at = source.index("app.exitQgis()", finally_at)
    leave_at = source.index('os._exit(0 if result.get("ok") else 1)', exit_at)
    assert finally_at < exit_at < leave_at


def test_receipt_contract_lists_the_runbook_fields() -> None:
    receipt = {name: None for name in RECEIPT_FIELDS}
    receipt.update({
        "acceptance": "NOT_ACCEPTANCE",
        "status": "DRAFT",
        "live_mcp_contacted": False,
        "live_bridge_contacted": False,
        "screenshots": {"before_sync_sha256": None, "after_sync_sha256": None, "status": "NOT_CAPTURED_PROXY_SIMULATION"},
    })
    require_receipt_fields(receipt)
    incomplete = dict(receipt)
    incomplete.pop("payload_digest")
    with pytest.raises(ValueError, match="payload_digest"):
        require_receipt_fields(incomplete)
