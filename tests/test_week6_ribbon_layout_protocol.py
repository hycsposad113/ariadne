import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


RUNNER = Path(__file__).resolve().parents[1] / "web" / "e2e" / "week6_ribbon_layout.py"
_SPEC = importlib.util.spec_from_file_location("week6_ribbon_layout", RUNNER)
assert _SPEC is not None and _SPEC.loader is not None
_RIBBON = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RIBBON)


def test_help_does_not_require_browser_runtime() -> None:
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--url" in result.stdout
    assert "--output" in result.stdout


def test_import_does_not_parse_cli_or_start_a_run() -> None:
    loader = (
        "import importlib.util, sys; "
        "spec = importlib.util.spec_from_file_location('ribbon_runner', sys.argv[1]); "
        "module = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(module)"
    )
    result = subprocess.run(
        [sys.executable, "-c", loader, str(RUNNER)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_target_validation_is_limited_to_the_loopback_port_allowlist() -> None:
    target = _RIBBON.validate_target("http://127.0.0.1:8943/app")
    assert target.hostname == "127.0.0.1"
    assert target.port == 8943

    for unsafe in (
        "http://example.com:8943/",
        "http://127.0.0.1:8939/",
        "http://user:password@localhost:8943/",
    ):
        with pytest.raises(ValueError):
            _RIBBON.validate_target(unsafe)


def test_readiness_source_endpoint_recognition_never_logs_query_values() -> None:
    assert _RIBBON._api_endpoint_kind(
        "http://127.0.0.1:8940/api/v1/projects/pilot/site-context?token=private"
    ) == "site-context"
    assert _RIBBON._api_endpoint_kind(
        "http://127.0.0.1:8940/api/v1/projects/pilot/site-intelligence"
    ) == "site-intelligence"
    assert _RIBBON._api_endpoint_kind("http://127.0.0.1:8940/api/v1/decisions") is None


def test_logged_urls_redact_userinfo_query_values_and_fragments() -> None:
    assert _RIBBON.sanitize_url(
        "http://user:password@localhost:8943/app?token=secret&mode=quiet#private"
    ) == "http://localhost:8943/app?REDACTED"


def test_snapshot_gate_uses_horizontal_client_width_and_keeps_strict_overlap_diagnostic_separate() -> None:
    snapshot = {
        "document_scroll_width": 1264,
        "document_client_width": 1264,
        "viewport_inner_width": 1280,
        "ribbon_scroll_width": 900,
        "ribbon_client_width": 900,
        "legacy_peer_overlap_count": 0,
        "original_head_full_button_pair_overlap_count": 0,
        "strict_peer_overlap_count": 1,
        "button_overflow_count": 0,
        "shell": {"x": 0, "y": 0, "width": 1280, "height": 100},
        "view": {"x": 0, "y": 100, "width": 1280, "height": 900},
    }

    result = _RIBBON.assess_snapshot(snapshot, baseline=snapshot)

    assert result["passed"] is True
    assert result["checks"]["document_horizontal_fit"] is True
    assert result["diagnostics"]["strict_zero_overlap_diagnostic"] is False

    overflowing = {**snapshot, "document_scroll_width": 1265}
    assert _RIBBON.assess_snapshot(overflowing, baseline=snapshot)["passed"] is False


def test_initial_run_record_marks_all_required_cases_not_run_without_fake_measurements() -> None:
    record = _RIBBON.new_run_record("http://127.0.0.1:8943/")

    assert record["overall_status"] == "NOT_RUN"
    assert {(case["language"], case["width"]) for case in record["cases"]} == {
        ("en", 1280),
        ("en", 1440),
        ("zh-TW", 1280),
        ("zh-TW", 1440),
    }
    for case in record["cases"]:
        assert case["status"] == "NOT_RUN"
        assert case["screenshots"] == []
        assert all(phase["status"] == "NOT_RUN" for phase in case["phases"].values())
        assert all(phase["measurements"] is None for phase in case["phases"].values())


def test_websocket_allowlist_uses_the_same_loopback_ports() -> None:
    assert _RIBBON.websocket_is_allowed("ws://localhost:8940/socket") is True
    assert _RIBBON.websocket_is_allowed("wss://127.0.0.1:8949/socket") is True
    assert _RIBBON.websocket_is_allowed("ws://example.com:8940/socket") is False
    assert _RIBBON.websocket_is_allowed("ws://127.0.0.1:8950/socket") is False


def test_console_redaction_masks_url_queries_and_authorization_values() -> None:
    message = (
        "fetch http://localhost:8943/api?token=query-secret "
        "Authorization: Bearer header-secret"
    )
    redacted = _RIBBON.redact_text(message)

    assert "query-secret" not in redacted
    assert "header-secret" not in redacted
    assert "?REDACTED" in redacted


def test_json_quoted_credentials_are_redacted_without_breaking_json() -> None:
    raw = '{"authorization":"Bearer header-secret","nested":{"password":"pw-secret","api_key":"key-secret"}}'
    safe = _RIBBON.redact_text(raw)

    assert all(secret not in safe for secret in ("header-secret", "pw-secret", "key-secret"))
    decoded = json.loads(safe)
    assert decoded["authorization"] == "[REDACTED]"
    assert decoded["nested"]["password"] == "[REDACTED]"


def test_body_text_and_json_response_body_are_redacted_as_a_whole() -> None:
    import json

    prose = _RIBBON.redact_text('response body: {"person":"private name"} trailing private words')
    parsed = json.loads(_RIBBON.redact_text('{"response_body":{"person":"private name","token":"api-secret"}}'))

    assert "private name" not in prose and "private words" not in prose
    assert parsed["response_body"] == "[REDACTED]"
    assert "api-secret" not in repr(parsed)


def test_structured_diagnostics_redact_sensitive_fields_in_nested_objects() -> None:
    safe = _RIBBON._redact_value({
        "request": {"Authorization": "Bearer top-secret", "body": {"data": "private-body"}},
        "url": "http://127.0.0.1:8941/api?token=query-secret",
    })

    assert safe["request"]["Authorization"] == "[REDACTED]"
    assert safe["request"]["body"] == "[REDACTED]"
    assert all(secret not in repr(safe) for secret in ("top-secret", "private-body", "query-secret"))


def test_off_phase_uses_localized_cancel_measurement_control() -> None:
    assert _RIBBON.measurement_phase_action("before", "en") == {
        "kind": "observe", "selector": "#btn-measure-distance", "expected_pressed": "false"
    }
    assert _RIBBON.measurement_phase_action("on", "en") == {
        "kind": "start", "selector": "#btn-measure-distance", "expected_pressed": "true"
    }
    assert _RIBBON.measurement_phase_action("off", "en") == {
        "kind": "cancel", "region_label": "Measurement controls",
        "accessible_name": "Cancel measurement", "expected_pressed": "false"
    }
    assert _RIBBON.measurement_phase_action("off", "zh-TW") == {
        "kind": "cancel", "region_label": "量測控制",
        "accessible_name": "取消量測", "expected_pressed": "false"
    }


def test_phase_transition_clicks_start_then_accessible_cancel_not_start_toggle() -> None:
    class FakeLocator:
        def __init__(self, page, kind, options=None):
            self.page, self.kind, self.options = page, kind, options

        def get_by_role(self, role, *, name, exact):
            self.page.calls.append(("nested_role", role, name, exact))
            return FakeLocator(self.page, "cancel", {"role": role, "name": name})

        def click(self, **kwargs):
            self.page.calls.append(("click", self.kind, self.options, kwargs))

        def wait_for(self, **kwargs):
            self.page.calls.append(("wait_for", self.kind, self.options, kwargs))

    class FakePage:
        def __init__(self): self.calls = []
        def locator(self, selector):
            self.calls.append(("locator", selector))
            return FakeLocator(self, "selector", {"selector": selector})
        def get_by_role(self, role, *, name, exact):
            self.calls.append(("role", role, name, exact))
            return FakeLocator(self, "region", {"role": role, "name": name})
        def wait_for_function(self, expression, *, arg, timeout):
            self.calls.append(("wait", arg, timeout))

    page = FakePage()
    _RIBBON._transition_measurement(page, "on", "en")
    _RIBBON._transition_measurement(page, "off", "zh-TW")

    assert ("click", "selector", {"selector": "#btn-measure-distance"}, {"timeout": 5000}) in page.calls
    assert ("role", "region", "量測控制", True) in page.calls
    assert ("nested_role", "button", "取消量測", True) in page.calls
    assert sum(call[0] == "click" and call[1] == "selector" for call in page.calls) == 1
    assert any(call[0] == "click" and call[1] == "cancel" for call in page.calls)
    assert page.calls[-1] == ("wait", "false", 5000)


def test_assessment_keeps_visible_and_original_head_all_button_overlap_gates() -> None:
    snapshot = {
        "document_scroll_width": 1264, "document_client_width": 1264,
        "viewport_inner_width": 1280, "viewport_inner_height": 1000,
        "ribbon_scroll_width": 900, "ribbon_client_width": 900,
        "legacy_peer_overlap_count": 0, "original_head_full_button_pair_overlap_count": 0,
        "strict_peer_overlap_count": 1, "button_overflow_count": 0,
        "shell": {"x": 0, "y": 0, "width": 1280, "height": 100},
        "view": {"x": 0, "y": 100, "width": 1280, "height": 900},
    }
    assert _RIBBON.assess_snapshot(snapshot, baseline=snapshot)["passed"] is True

    visible_overlap = {**snapshot, "legacy_peer_overlap_count": 1}
    full_overlap = {**snapshot, "original_head_full_button_pair_overlap_count": 1}
    assert _RIBBON.assess_snapshot(visible_overlap, baseline=snapshot)["checks"]["legacy_overlap_gate_clear"] is False
    assert _RIBBON.assess_snapshot(full_overlap, baseline=snapshot)["checks"]["original_head_all_button_overlap_gate_clear"] is False
    missing_full_count = {key: value for key, value in snapshot.items() if key != "original_head_full_button_pair_overlap_count"}
    assert _RIBBON.assess_snapshot(missing_full_count, baseline=snapshot)["passed"] is False


def test_screenshot_writer_requires_png_and_writes_exclusively_with_saved_file_hash(tmp_path: Path) -> None:
    import base64
    import hashlib

    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/pT8AAAAASUVORK5CYII=")
    destination = tmp_path / "phase.png"
    metadata = _RIBBON._write_png_exclusive(destination, png)

    saved = destination.read_bytes()
    assert saved.startswith(_RIBBON.PNG_SIGNATURE)
    assert metadata["size_bytes"] == len(saved) > 0
    assert metadata["sha256"] == hashlib.sha256(saved).hexdigest()
    with pytest.raises(FileExistsError):
        _RIBBON._write_png_exclusive(destination, png)
    assert destination.read_bytes() == saved
    with pytest.raises(RuntimeError, match="PNG"):
        _RIBBON._write_png_exclusive(tmp_path / "invalid.png", b"not png")


def test_failure_event_and_result_are_fsynced_before_return(tmp_path: Path) -> None:
    record = _RIBBON.new_run_record("http://127.0.0.1:8941/")
    case = record["cases"][0]
    output = tmp_path / "evidence"
    output.mkdir()
    diagnostics_path = output / "diagnostics.jsonl"
    with _RIBBON.DiagnosticLog(diagnostics_path) as diagnostics:
        _RIBBON._record_failure(
            case, diagnostics, lambda: _RIBBON._checkpoint(output, record),
            'browser error {"password":"flush-secret"}', phase="on"
        )
        persisted = json.loads((output / "result.json").read_text())
        events = [json.loads(line) for line in diagnostics_path.read_text().splitlines()]

    assert persisted["overall_status"] == "FAIL"
    assert persisted["cases"][0]["phases"]["on"]["status"] == "FAIL"
    assert events[-1]["status"] == "FAIL"
    assert "flush-secret" not in repr(persisted) + repr(events)


def test_case_and_overall_status_cannot_pass_with_placeholder_evidence() -> None:
    record = _RIBBON.new_run_record("http://127.0.0.1:8941/")
    case = record["cases"][0]
    case["status"] = "PASS"
    case["language_verification"]["status"] = "PASS"
    for phase in case["phases"].values():
        phase["status"] = "PASS"
        phase["checks"] = {"document_horizontal_fit": True}

    assert _RIBBON._case_status(case) == "NOT_RUN"
    assert _RIBBON._derive_overall_status(record) == "NOT_RUN"
    case["status"] = "ALIEN_STATUS"
    assert _RIBBON._derive_overall_status(record) == "FAIL"


def _ready_projection_fixture() -> tuple[dict, dict, dict]:
    source_context = {
        "project_id": "readonly-project-01",
        "source_integrity_status": "VERIFIED",
        "study_area": {
            "id": "readonly-study-area-01",
            "revision": 3,
            "status": "CONFIRMED_FOR_EXPLORATION",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
            },
        },
        "current_workspace": {
            "workspace_id": "readonly-workspace-01",
            "project_id": "readonly-project-01",
            "study_area_id": "readonly-study-area-01",
            "revision": 7,
        },
        "evidence_cards": [{"id": "evidence-01"}],
        "buildings": [{"id": "building-01"}],
        "roads": [{"id": "road-01"}],
    }
    request = {
        "endpoint": "site-context",
        "method": "GET",
        "started": True,
        "finished": True,
        "failed": False,
        "status_code": 200,
        "body_json_valid": True,
    }
    ui_projection = {
        "authority_state": "READY",
        "source_projection_wait_matched": True,
        "project_id": "readonly-project-01",
        "study_area_id": "readonly-study-area-01",
        "study_area_status": None,
        "study_area_status_display_state": "NOT_DISPLAYED",
        "workspace_revision": 7,
        "site_facts_count": 1,
        "building_count": 1,
        "road_count": 1,
        "map_canvas_visible": True,
        "map_canvas_width": 800,
        "map_canvas_height": 600,
        "study_area_outline_pixel_count": 12,
    }
    return request, source_context, ui_projection


def test_readiness_binds_completed_source_projection_to_rendered_identity_and_map() -> None:
    request, source, ui = _ready_projection_fixture()

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert result["status"] == "PASS"
    assert result["checks"]["site_context_request_finished"] is True
    assert result["checks"]["source_workspace_identity_matches_rendered_projection"] is True
    assert result["checks"]["rendered_study_area_outline_present"] is True
    assert result["identity"]["source"]["workspace_id"] == "readonly-workspace-01"
    assert result["identity"]["rendered"]["study_area_id"] == "readonly-study-area-01"
    assert _RIBBON._readiness_evidence_complete(result) is True


def test_readiness_requires_completed_source_projection_wait_before_pass() -> None:
    request, source, ui = _ready_projection_fixture()
    ui["source_projection_wait_matched"] = False

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["source_projection_wait_matched"] is False


def test_source_projection_wait_expectation_comes_from_persisted_context() -> None:
    _, source, _ = _ready_projection_fixture()

    assert _RIBBON._source_projection_expectation(source, "zh-TW") == {
        "language": "zh-TW",
        "project_id": "readonly-project-01",
        "study_area_id": "readonly-study-area-01",
        "source_study_area_status": "CONFIRMED_FOR_EXPLORATION",
        "workspace_revision": 7,
        "evidence_count": 1,
        "building_count": 1,
        "road_count": 1,
    }


def test_source_projection_wait_does_not_accept_placeholder_or_empty_source() -> None:
    _, source, _ = _ready_projection_fixture()
    source["current_workspace"]["workspace_id"] = "Unavailable"
    source["evidence_cards"] = []

    assert _RIBBON._source_projection_expectation(source, "en") is None


@pytest.mark.parametrize(
    ("field", "value", "failed_check"),
    [
        ("authority_state", "LOADING", "authority_ready"),
        ("study_area_id", "Unavailable", "rendered_study_area_identity_matches_source"),
        ("study_area_status_display_state", "DISPLAYED", "rendered_study_area_status_not_displayed"),
        ("study_area_status_display_state", "UNKNOWN", "rendered_study_area_status_not_displayed"),
        ("workspace_revision", None, "rendered_workspace_revision_matches_source"),
        ("site_facts_count", 0, "rendered_site_facts_match_nonempty_source"),
        ("study_area_outline_pixel_count", 0, "rendered_study_area_outline_present"),
    ],
)
def test_readiness_rejects_loading_and_placeholder_projection(
    field: str, value: object, failed_check: str
) -> None:
    request, source, ui = _ready_projection_fixture()
    ui[field] = value

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert result["status"] != "PASS"
    assert result["checks"][failed_check] is False


def test_http_200_without_finished_site_context_body_is_blocked() -> None:
    request, source, ui = _ready_projection_fixture()
    request["finished"] = False

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert result["status"] == "BLOCKED"
    assert result["checks"]["site_context_request_finished"] is False
    assert result["identity"]["source"]["workspace_id"] == "readonly-workspace-01"


def test_http_200_requestfailure_cancellation_cannot_pass_readiness() -> None:
    request, source, ui = _ready_projection_fixture()
    request["finished"] = False
    request["failed"] = True
    request["status_code"] = 200

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert result["status"] == "BLOCKED"
    assert result["checks"]["site_context_request_finished"] is False


@pytest.mark.parametrize(
    ("field", "value", "failed_check"),
    [
        ("endpoint", "site-intelligence", "site_context_endpoint_matches"),
        ("method", "POST", "site_context_method_readonly"),
    ],
)
def test_readiness_requires_the_actual_readonly_site_context_get(
    field: str, value: str, failed_check: str
) -> None:
    request, source, ui = _ready_projection_fixture()
    request[field] = value

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert result["status"] == "FAIL"
    assert result["checks"][failed_check] is False


def test_completed_non_200_site_context_response_is_a_readiness_failure() -> None:
    request, source, ui = _ready_projection_fixture()
    request["status_code"] = 503
    request["body_json_valid"] = False

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["site_context_response_ok"] is False


@pytest.mark.parametrize(
    ("field", "value", "failed_check"),
    [
        ("project_id", "another-project", "rendered_project_identity_matches_source"),
        ("study_area_id", "another-study-area", "rendered_study_area_identity_matches_source"),
        ("workspace_revision", 8, "rendered_workspace_revision_matches_source"),
    ],
)
def test_readiness_rejects_rendered_identity_mismatch(
    field: str, value: object, failed_check: str
) -> None:
    request, source, ui = _ready_projection_fixture()
    ui[field] = value

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert result["status"] == "FAIL"
    assert result["checks"][failed_check] is False


def test_readiness_rejects_missing_persisted_workspace_and_empty_source_features() -> None:
    request, source, ui = _ready_projection_fixture()
    source["current_workspace"] = None
    ui["workspace_revision"] = None
    source["buildings"] = []
    source["roads"] = []
    ui["building_count"] = 0
    ui["road_count"] = 0

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["source_workspace_identity_present"] is False
    assert result["checks"]["source_features_nonempty"] is False


def test_status_revalidation_rejects_forged_pass_with_placeholder_identity() -> None:
    request, source, ui = _ready_projection_fixture()
    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )
    result["identity"]["source"]["study_area_id"] = "Unavailable"

    assert _RIBBON._readiness_evidence_complete(result) is False


def test_status_revalidation_rejects_wait_claim_that_disagrees_with_projection() -> None:
    request, source, ui = _ready_projection_fixture()
    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )
    result["rendered_projection"]["source_projection_wait_matched"] = False

    assert _RIBBON._readiness_evidence_complete(result) is False


def test_case_status_rejects_readiness_pass_without_complete_source_binding() -> None:
    case = _RIBBON.new_run_record("http://127.0.0.1:8941/")["cases"][0]
    case["language_verification"]["status"] = "PASS"
    case["readiness"] = {"status": "PASS", "binding_source": "claimed"}

    assert _RIBBON._case_status(case) == "FAIL"


def test_http_router_aborts_external_and_mutating_requests_but_continues_local_get() -> None:
    class Request:
        def __init__(self, url, method="GET"):
            self.url, self.method = url, method
    class Route:
        def __init__(self, url, method="GET"):
            self.request = Request(url, method)
            self.action = None
        def abort(self, reason): self.action = ("abort", reason)
        def continue_(self): self.action = ("continue",)

    violations = []
    local = Route("http://127.0.0.1:8941/api/read", "GET")
    outside = Route("https://example.com/collect", "GET")
    mutation = Route("http://127.0.0.1:8940/api/write", "POST")
    for route in (local, outside, mutation):
        _RIBBON._route_request(route, lambda url, kind: violations.append((url, kind)))

    assert local.action == ("continue",)
    assert outside.action == ("abort", "blockedbyclient")
    assert mutation.action == ("abort", "blockedbyclient")
    assert [kind for _url, kind in violations] == ["http", "http_method"]


def test_websocket_router_closes_external_and_connects_allowlisted_only() -> None:
    class SocketRoute:
        def __init__(self, url): self.url, self.actions = url, []
        def close(self): self.actions.append("close")
        def connect_to_server(self): self.actions.append("connect")

    violations = []
    local = SocketRoute("ws://127.0.0.1:8940/socket")
    outside = SocketRoute("wss://example.com:8940/socket")
    _RIBBON._route_websocket(local, lambda url, kind: violations.append((url, kind)))
    _RIBBON._route_websocket(outside, lambda url, kind: violations.append((url, kind)))

    assert local.actions == ["connect"]
    assert outside.actions == ["close"]
    assert violations == [(outside.url, "websocket")]


def test_output_directory_creation_refuses_overwrite(tmp_path: Path) -> None:
    existing = tmp_path / "evidence"
    existing.mkdir()
    marker = existing / "keep.txt"
    marker.write_text("immutable")
    with pytest.raises(FileExistsError):
        _RIBBON._create_output_directory(existing)
    assert marker.read_text() == "immutable"


def test_readiness_accepts_confirmed_api_status_when_badge_is_not_displayed() -> None:
    request, source, ui = _ready_projection_fixture()
    ui["study_area_status"] = None
    ui["study_area_status_display_state"] = "NOT_DISPLAYED"

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert source["study_area"]["status"] == "CONFIRMED_FOR_EXPLORATION"
    assert result["status"] == "PASS"
    assert result["checks"]["source_study_area_confirmed"] is True
    assert result["checks"]["rendered_study_area_status_not_displayed"] is True
    assert result["identity"]["rendered"]["study_area_status"] is None
    assert result["identity"]["rendered"]["study_area_status_display_state"] == "NOT_DISPLAYED"
    assert _RIBBON._readiness_evidence_complete(result) is True


def test_readiness_rejects_wrong_source_status_even_when_rendered_shell_matches() -> None:
    request, source, ui = _ready_projection_fixture()
    source["study_area"]["status"] = "LOADING"
    ui["study_area_status"] = None
    ui["study_area_status_display_state"] = "NOT_DISPLAYED"

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["source_study_area_confirmed"] is False


def test_readiness_does_not_treat_displayed_status_as_api_confirmation() -> None:
    request, source, ui = _ready_projection_fixture()
    ui["study_area_status"] = "CONFIRMED_FOR_EXPLORATION"
    ui["study_area_status_display_state"] = "DISPLAYED"

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["rendered_study_area_status_not_displayed"] is False


@pytest.mark.parametrize("authority_state", ["LOADING", "CHECKING_AUTHORITY", "Unavailable", None])
def test_readiness_fails_closed_for_loading_or_placeholder_authority(
    authority_state: str | None,
) -> None:
    request, source, ui = _ready_projection_fixture()
    ui["authority_state"] = authority_state
    ui["study_area_status"] = None
    ui["study_area_status_display_state"] = "NOT_DISPLAYED"

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert result["status"] != "PASS"
    assert result["checks"]["authority_ready"] is False



def test_readiness_rejects_broken_source_workspace_relationship() -> None:
    request, source, ui = _ready_projection_fixture()
    source["current_workspace"]["project_id"] = "another-project"

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=source, ui_projection=ui
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["source_workspace_project_matches_study_context"] is False
    assert result["checks"]["source_workspace_identity_matches_rendered_projection"] is False


def test_readiness_rejects_completed_http_200_without_valid_source_body() -> None:
    request, source, ui = _ready_projection_fixture()
    request["body_json_valid"] = False

    result = _RIBBON.assess_ui_readiness(
        request_lifecycle=request, source_context=None, ui_projection=ui
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["site_context_response_ok"] is True
    assert result["checks"]["site_context_body_json_valid"] is False
    assert result["checks"]["source_study_area_confirmed"] is False
