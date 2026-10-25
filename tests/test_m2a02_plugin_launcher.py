"""Static contract tests for the M2-A02 QGIS companion and launcher."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import stat
import subprocess

import pytest

from urban_design.bridge import (
    DEFAULT_BRIDGE_PORT,
    HERMES_RESERVED_PORT,
    _ALLOWED_QGIS_COMMANDS,
    main,
    validate_bridge_port,
)
from qgis_plugin.urban_design_study_area.helpers import (
    DEFAULT_BRIDGE_URL,
    DEFAULT_PLATFORM_API_URL,
    capture_payload,
    capture_result_kind,
    build_platform_sync_payload,
    create_pending_platform_sync,
    matching_pending_sync_revision,
    parse_pending_platform_sync,
    serialize_pending_platform_sync,
    validate_pending_sync_revision,
    format_status,
    platform_api_base_url,
    qgis_source_feature_reference,
    bridge_url,
    response_error_text,
)


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "Open Urban Design QGIS.command"
PLUGIN = ROOT / "qgis_plugin" / "urban_design_study_area" / "plugin.py"
METADATA = ROOT / "qgis_plugin" / "urban_design_study_area" / "metadata.txt"


def test_launcher_is_executable_and_uses_only_project_local_profile():
    mode = LAUNCHER.stat().st_mode
    assert mode & stat.S_IXUSR
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'QGIS_PROFILE_NAME="urban-design"' in source
    assert 'QGIS_PROFILES_ROOT="$RUNTIME_ROOT/qgis-profiles"' in source
    assert 'QGIS_PROFILE_PATH="$QGIS_PROFILES_ROOT/profiles/$QGIS_PROFILE_NAME"' in source
    assert 'COMPANION_DEST="$QGIS_PROFILE_PATH/python/plugins/urban_design_study_area"' in source
    assert 'qgis_mcp_plugin=true' in source
    assert 'urban_design_study_area=true' in source
    assert "--profile \"$QGIS_PROFILE_NAME\"" in source
    assert "--profiles-path \"$QGIS_PROFILES_ROOT\"" in source
    assert "QGIS3/profiles/default" not in source
    assert ".local/share/QGIS" not in source
    assert "SiteProposal" not in source
    assert "DesignBoundary" not in source


def test_launcher_pins_and_authenticates_the_two_qgis_mcp_halves():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'QGIS_MCP_VERSION="0.14.0"' in source
    assert 'importlib.metadata.version("qgis-mcp")' in source
    assert 'QGIS_MCP_PLUGIN_SOURCE' in source
    assert 'MCP_PLUGIN_VERSION' in source
    assert 'export QGIS_MCP_TOKEN="$SESSION_TOKEN"' in source
    assert 'export URBAN_DESIGN_SESSION_TOKEN="$SESSION_TOKEN"' in source
    assert 'instance_id=os.environ["URBAN_DESIGN_INSTANCE"]' in source
    assert 'export URBAN_DESIGN_INSTANCE="$PROJECT_FILE"' in source


def test_companion_metadata_and_controls_are_present_without_climate_or_arbitrary_qgis_routes():
    metadata = METADATA.read_text(encoding="utf-8")
    source = PLUGIN.read_text(encoding="utf-8")
    assert "version=0.1.0" in metadata
    for label in ("Draw Study Area", "Use as Study Area", "Refresh connection status", "Sync to Platform"):
        assert label in source
    assert "Study Area Draft" in source
    assert "DRAFT_CRS_AUTHID" in source
    assert "QgsMapToolDigitizeFeature" in source
    assert "digitizingCompleted" in source
    assert "QNetworkAccessManager" in source
    assert "commitChanges" in source
    assert "execute_code" not in source
    assert "climate" not in source.casefold()


def test_plugin_capture_payload_has_exact_authority_boundary():
    payload = capture_payload(instance="qgis-instance", layer_id="draft", fid=7, actor="designer", request_id_value="r1")
    assert set(payload) == {
        "instance", "layer_id", "fid", "actor", "actor_kind", "actor_session_id", "request_id"
    }
    assert payload["fid"] == 7
    assert payload["actor_kind"] == "QGIS_PLUGIN"
    assert payload["actor_session_id"] == "qgis-instance"
    for forbidden in ("geometry", "expression", "filter_expression", "output_path", "target_crs"):
        assert forbidden not in payload


def test_plugin_capture_payload_rejects_non_integer_fids():
    for value in (True, 7.0, "7"):
        try:
            capture_payload(instance="qgis-instance", layer_id="draft", fid=value)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError("non-integer FID was accepted")


def test_status_formatter_keeps_three_integrations_separate():
    status = format_status(
        {
            "integrations": {
                "backend": {"status": "READY"},
                "qgis_mcp": {"status": "UNAVAILABLE"},
                "ladybug": {"status": "DEGRADED"},
            }
        }
    )
    assert status == "Backend: READY | QGIS MCP: UNAVAILABLE | Ladybug: DEGRADED"


def test_plugin_surfaces_typed_bridge_error_message():
    assert (
        response_error_text(
            {
                "code": "FID_MISMATCH",
                "message": "selected QGIS FID does not match the request",
                "status": "FAILED",
            }
        )
        == "selected QGIS FID does not match the request"
    )


def test_plugin_treats_http_503_outcome_unknown_as_non_retryable():
    payload = {
        "code": "OUTCOME_UNKNOWN",
        "message": "QGIS MCP connection lost after dispatch",
        "status": "OUTCOME_UNKNOWN",
        "retry_allowed": False,
        "dispatched": True,
    }
    assert capture_result_kind(payload, "HTTP 503: request failed") == "unknown"


def test_bridge_qgis_allowlist_excludes_arbitrary_and_batch_routes():
    assert "export_layer" in _ALLOWED_QGIS_COMMANDS
    assert "get_selection" in _ALLOWED_QGIS_COMMANDS
    assert not _ALLOWED_QGIS_COMMANDS.intersection(
        {"execute_code", "execute_processing", "execute_processing_batch", "run_sql", "batch"}
    )


def test_bridge_and_plugin_default_to_the_reserved_port_boundary(monkeypatch):
    monkeypatch.delenv("URBAN_DESIGN_BRIDGE_URL", raising=False)
    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert DEFAULT_BRIDGE_PORT == 8788
    assert HERMES_RESERVED_PORT == 8787
    assert DEFAULT_BRIDGE_URL == "http://127.0.0.1:8788"
    assert bridge_url() == DEFAULT_BRIDGE_URL
    assert validate_bridge_port(DEFAULT_BRIDGE_PORT) == DEFAULT_BRIDGE_PORT
    assert 'BRIDGE_PORT="${URBAN_DESIGN_BRIDGE_PORT:-8788}"' in launcher
    assert 'QGIS_MCP_PORT="9876"' in launcher
    assert 'export URBAN_DESIGN_BRIDGE_URL="http://127.0.0.1:$BRIDGE_PORT"' in launcher


def test_bridge_rejects_the_Hermes_reserved_port():
    with pytest.raises(ValueError, match="reserved for the Hermes Web UI"):
        validate_bridge_port(HERMES_RESERVED_PORT)


def test_bridge_cli_rejects_reserved_port_override(monkeypatch):
    monkeypatch.setenv("URBAN_DESIGN_BRIDGE_PORT", str(HERMES_RESERVED_PORT))
    with pytest.raises(SystemExit):
        main(["--session-token", "test-only-token"])


def test_bridge_cli_fails_safely_when_default_port_is_occupied(capsys, monkeypatch):
    import urban_design.bridge as bridge
    temporary_port = 8943
    monkeypatch.setattr(bridge, "DEFAULT_BRIDGE_PORT", temporary_port)
    monkeypatch.delenv("URBAN_DESIGN_BRIDGE_PORT", raising=False)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            listener.bind(("127.0.0.1", temporary_port))
            listener.listen(1)
        except OSError:
            listener.close()
            listener = None
        with pytest.raises(SystemExit):
            main(["--session-token", "test-only-token"])
        assert "already in use" in capsys.readouterr().err
    finally:
        if listener is not None:
            listener.close()


def test_launcher_rejects_8787_before_touching_runtime():
    env = os.environ.copy()
    env.update(
        {
            "URBAN_DESIGN_BRIDGE_PORT": "8787",
            "URBAN_DESIGN_QGIS_BIN": "/definitely/missing-qgis",
            "URBAN_DESIGN_BRIDGE_PYTHON": "/definitely/missing-python",
        }
    )
    result = subprocess.run(
        [str(LAUNCHER)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "reserved for the Hermes Web UI" in result.stderr
    assert "missing-qgis" not in result.stderr


def test_launcher_rejects_numeric_alias_of_8787_before_touching_runtime():
    env = os.environ.copy()
    env.update(
        {
            "URBAN_DESIGN_BRIDGE_PORT": "08787",
            "URBAN_DESIGN_QGIS_BIN": "/definitely/missing-qgis",
            "URBAN_DESIGN_BRIDGE_PYTHON": "/definitely/missing-python",
        }
    )
    result = subprocess.run(
        [str(LAUNCHER)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "reserved for the Hermes Web UI" in result.stderr
    assert "missing-qgis" not in result.stderr


def test_launcher_fails_before_children_when_an_existing_qgis_process_is_detected(tmp_path: Path):
    fake_ps = tmp_path / "ps"
    fake_ps.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' '59612 /Applications/QGIS-LTR.app/Contents/MacOS/QGIS'\n",
        encoding="utf-8",
    )
    fake_ps.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path}:{env['PATH']}",
            "URBAN_DESIGN_QGIS_BIN": "/definitely/missing-qgis",
            "URBAN_DESIGN_BRIDGE_PYTHON": "/definitely/missing-python",
        }
    )
    result = subprocess.run(
        [str(LAUNCHER)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "existing QGIS process prevents a safe dedicated GUI launch" in result.stderr
    assert "missing-qgis" not in result.stderr
    assert "missing-python" not in result.stderr


def test_launcher_fails_closed_when_process_listing_is_unavailable(tmp_path: Path):
    fake_ps = tmp_path / "ps"
    fake_ps.write_text("#!/bin/sh\nexit 73\n", encoding="utf-8")
    fake_ps.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path}:{env['PATH']}",
            "URBAN_DESIGN_QGIS_BIN": "/definitely/missing-qgis",
            "URBAN_DESIGN_BRIDGE_PYTHON": "/definitely/missing-python",
        }
    )
    result = subprocess.run(
        [str(LAUNCHER)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "cannot verify QGIS GUI ownership" in result.stderr
    assert "process listing failed" in result.stderr
    assert "missing-qgis" not in result.stderr
    assert "missing-python" not in result.stderr


def test_launcher_single_instance_preflight_is_before_profile_and_bridge_setup():
    source = LAUNCHER.read_text(encoding="utf-8")
    preflight = source.index('QGIS_RUNNING=')
    profile_setup = source.index('mkdir -p "$QGIS_PROFILE_PATH')
    token_generation = source.index('SESSION_TOKEN=')
    bridge_start = source.index('BRIDGE_PID=$!')
    assert preflight < profile_setup < token_generation < bridge_start
    assert "save and close every existing QGIS window" in source
    assert "open -n" not in source


def test_launcher_fails_safely_when_8788_is_already_listening(tmp_path):
    # Isolate the unrelated GUI process preflight. Occupancy still uses an
    # actual listener and the real lsof; the launcher must reach that guard.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    process_probe = bin_dir / "ps"
    process_probe.write_text("#!/bin/sh\nexit 0\n")
    process_probe.chmod(0o755)
    temporary_port = 8944
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        try:
            listener.bind(("127.0.0.1", temporary_port))
            listener.listen(1)
        except OSError:
            # A real listener (including an already-running Urban Design
            # launch) owns this port.  The launcher must still refuse to
            # start; do not disturb or probe that process further.
            listener.close()
            listener = None

        env = os.environ.copy()
        env.update(
            {
                "PATH": str(bin_dir) + os.pathsep + env.get("PATH", ""),
                "URBAN_DESIGN_BRIDGE_PORT": str(temporary_port),
                "URBAN_DESIGN_QGIS_BIN": "/definitely/missing-qgis",
                "URBAN_DESIGN_BRIDGE_PYTHON": "/definitely/missing-python",
            }
        )
        result = subprocess.run(
            [str(LAUNCHER)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
        if listener is not None:
            assert "already in use" in result.stderr
        assert "missing-qgis" not in result.stderr
    finally:
        if listener is not None:
            listener.close()


def test_launcher_cleanup_is_scoped_to_its_bridge_child_and_never_kills_Hermes():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'kill -TERM "$BRIDGE_PID"' in source
    assert "pkill" not in source
    assert "killall" not in source
    assert "HERMES_PID" not in source


def test_project_has_an_unambiguous_visible_identity():
    project = ROOT / ".urban_design_runtime/rotterdam-m4h-pilot-project.qgs"
    if not project.is_file():
        pytest.skip(
            "missing untracked runtime file .urban_design_runtime/rotterdam-m4h-pilot-project.qgs; "
            "this worktree does not carry the local QGIS project, so the visible identity cannot be checked"
        )
    source = project.read_text(encoding="utf-8")
    assert 'projectname="rotterdam-m4h-pilot-project"' in source
    assert "<title>rotterdam-m4h-pilot-project</title>" in source


def test_plugin_rejects_a_Hermes_reserved_bridge_url(monkeypatch):
    monkeypatch.setenv("URBAN_DESIGN_BRIDGE_URL", "http://127.0.0.1:8787")
    with pytest.raises(ValueError, match="reserved for the Hermes Web UI"):
        bridge_url()


def test_platform_api_defaults_to_8795_and_rejects_hermes_or_bridge_ports():
    assert DEFAULT_PLATFORM_API_URL == "http://127.0.0.1:8795"
    assert platform_api_base_url(environ={}) == DEFAULT_PLATFORM_API_URL
    for port in (8787, 8788, 8644):
        with pytest.raises(ValueError, match="reserved"):
            platform_api_base_url(environ={"URBAN_DESIGN_API_BASE_URL": f"http://127.0.0.1:{port}"})
    with pytest.raises(ValueError, match="loopback"):
        platform_api_base_url(environ={"URBAN_DESIGN_API_BASE_URL": "https://example.com"})


def test_qgis_platform_sync_payload_contains_only_verified_references_and_draft_state():
    reference = qgis_source_feature_reference(
        "BAG pand",
        {"identificatie": "0599100000035095"},
    )
    assert reference == {"feature_id": "bag:0599100000035095", "feature_kind": "building"}
    feature = {
        "id": reference["feature_id"],
        "feature_kind": "building",
        "lineage_status": "VERIFIED",
        "source_artifact_id": "artifact-bag-normalized",
        "source_snapshot_id": "snapshot-bag",
        "source_feature_id": "0599100000035095",
        "geometry": {"type": "Polygon", "coordinates": []},
    }
    payload = build_platform_sync_payload(
        project_id="rotterdam-m4h-pilot-project",
        study_area_id="study-area-v5",
        expected_workspace_revision=3,
        actor_session_id="qgis-project-instance",
        source_snapshot_ids=["snapshot-bag"],
        selected_features=[feature],
        current_workspace=None,
        request_key="browser-test-key",
    )
    assert payload["expected_workspace_revision"] == 3
    assert payload["actor_kind"] == "QGIS_PLUGIN"
    assert payload["actor_session_id"] == "qgis-project-instance"
    assert payload["feature_dispositions"] == [{
        "feature_id": "bag:0599100000035095",
        "feature_kind": "building",
        "disposition": "undecided",
        "source_artifact_id": "artifact-bag-normalized",
        "source_snapshot_id": "snapshot-bag",
        "source_feature_id": "0599100000035095",
    }]
    assert "geometry" not in payload["feature_dispositions"][0]
    assert payload["spatial_brief"] == {"zones": [], "status": "DRAFT_PENDING_HUMAN_DECISION"}


def _pending_sync_fixture():
    body = {
        "project_id": "rotterdam-m4h-pilot-project",
        "study_area_id": "study-area-v5",
        "expected_workspace_revision": 5,
        "source_snapshot_ids": ["snapshot-bag", "snapshot-osm"],
        "idempotency_key": "stable-retry-key",
        "actor_kind": "QGIS_PLUGIN",
        "actor_session_id": "qgis-test-session",
        "feature_dispositions": [],
        "spatial_brief": {"zones": [], "status": "DRAFT_PENDING_HUMAN_DECISION"},
    }
    return create_pending_platform_sync(DEFAULT_PLATFORM_API_URL, body)


def test_pending_platform_sync_round_trips_exact_body_and_rejects_unsafe_origin():
    pending = _pending_sync_fixture()
    restored = parse_pending_platform_sync(serialize_pending_platform_sync(pending))

    assert restored == pending
    assert restored["request_body"]["idempotency_key"] == "stable-retry-key"
    with pytest.raises(ValueError, match="reserved"):
        create_pending_platform_sync("http://127.0.0.1:8787", pending["request_body"])


def test_pending_sync_history_match_confirms_only_the_same_project_area_and_revision():
    pending = _pending_sync_fixture()
    revision = {
        "workspace_id": "workspace-rotterdam-m4h-pilot-project",
        "project_id": "rotterdam-m4h-pilot-project",
        "revision": 6,
        "study_area_id": "study-area-v5",
        "status": "DRAFT",
        "idempotency_key": "stable-retry-key",
        "payload_digest": "a" * 64,
    }

    assert matching_pending_sync_revision([revision], pending) == revision
    assert matching_pending_sync_revision([], pending) is None
    assert validate_pending_sync_revision(revision, pending) == 6

    wrong_area = {**revision, "study_area_id": "study-area-v4"}
    with pytest.raises(ValueError, match="does not match"):
        matching_pending_sync_revision([wrong_area], pending)


def test_pending_sync_rejects_duplicate_keys_and_invalid_saved_records():
    pending = _pending_sync_fixture()
    revision = {
        "workspace_id": "workspace-rotterdam-m4h-pilot-project",
        "project_id": "rotterdam-m4h-pilot-project",
        "revision": 6,
        "study_area_id": "study-area-v5",
        "status": "DRAFT",
        "idempotency_key": "stable-retry-key",
        "payload_digest": "a" * 64,
    }

    with pytest.raises(ValueError, match="multiple"):
        matching_pending_sync_revision([revision, revision], pending)
    with pytest.raises(ValueError, match="unreadable"):
        parse_pending_platform_sync("{broken")
    with pytest.raises(ValueError, match="does not match"):
        validate_pending_sync_revision({**revision, "revision": 7}, pending)


def test_plugin_persists_and_reconciles_pending_sync_without_creating_a_new_key():
    source = PLUGIN.read_text(encoding="utf-8")
    assert "QSettings" in source
    assert "}/history" in source
    assert "_handle_pending_platform_history_reply" in source
    assert "serialize_pending_platform_sync" in source
    assert "request_body" in source

def test_launcher_platform_origin_contract_without_launching():
    source = LAUNCHER.read_text()
    assert 'export URBAN_DESIGN_API_BASE_URL="${URBAN_DESIGN_API_BASE_URL-http://127.0.0.1:8795}"' in source
    assert source.index('PLATFORM_API_ORIGIN_PATTERN=') < source.index('mkdir -p')
    assert 'fail "invalid platform API URL' in source
    assert platform_api_base_url(environ={'URBAN_DESIGN_API_BASE_URL': 'http://localhost:8999'}) == 'http://localhost:8999'


@pytest.mark.parametrize('value,expected', [
    (None, 'http://127.0.0.1:8795'),
    ('http://localhost:8999', 'http://localhost:8999'),
    ('http://127.0.0.1:8787', None),
    ('http://localhost:8644', None),
    ('http://127.0.0.1:08787', None),
    ('https://example.com', None),
    ('', None),
])
def test_platform_origin_preflight_fragment_only(value, expected):
    # Execute only the exact origin guard; never execute the launcher or QGIS.
    source = LAUNCHER.read_text()
    fragment = source[source.index('export URBAN_DESIGN_API_BASE_URL='):source.index('# QGIS-LTR')]
    env = os.environ.copy()
    env.pop('URBAN_DESIGN_API_BASE_URL', None)
    if value is not None:
        env['URBAN_DESIGN_API_BASE_URL'] = value
    result = subprocess.run(['/bin/zsh', '-c', 'set -euo pipefail\nfail() { print -u2 "$*"; exit 1; }\n' + fragment + '\nprint -r -- "$URBAN_DESIGN_API_BASE_URL"'],env=env,text=True,capture_output=True)
    if expected is None:
        assert result.returncode != 0
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected
