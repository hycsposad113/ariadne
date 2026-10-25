#!/usr/bin/env python3
"""Capture real, isolated Week 6 ribbon layout evidence.

Run against an already-running isolated app on loopback ports 8940-8949.
The runner never starts or stops a server and routes page HTTP/WebSocket
traffic only to that allowlist. Each run requires a new output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import SplitResult, urlsplit, urlunsplit

LANGUAGES = ("en", "zh-TW")
WIDTHS = (1280, 1440)
VIEWPORT_HEIGHT = 1000
PHASES = ("before", "on", "off")
ALLOWED_HOSTS = {"localhost", "127.0.0.1"}
ALLOWED_PORTS = frozenset(range(8940, 8950))
CHROME_EXECUTABLE = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_SECRET_FIELD_NAMES = (
    r"authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|"
    r"cookie|set-cookie|credential|body|request[_-]?body|response[_-]?body|payload|post[_-]?data|response"
)
_SECRET_FIELD = re.compile(rf"^(?:{_SECRET_FIELD_NAMES})$", re.IGNORECASE)
_BODY_FIELD_NAMES = r"body|request[_-]?body|response[_-]?body|payload|post[_-]?data|response"
_BODY_FIELD_TOKEN = rf'''(?:"(?:{_BODY_FIELD_NAMES})"|'(?:{_BODY_FIELD_NAMES})'|(?:{_BODY_FIELD_NAMES}))'''
_BODY_ASSIGNMENT = re.compile(rf"(?i)(?P<prefix>{_BODY_FIELD_TOKEN}\s*[:=]\s*).*$")
_SECRET_FIELD_TOKEN = rf"""(?:"(?:{_SECRET_FIELD_NAMES})"|'(?:{_SECRET_FIELD_NAMES})'|(?:{_SECRET_FIELD_NAMES}))"""
_SECRET_ASSIGNMENT = re.compile(
    rf"(?i)(?P<prefix>{_SECRET_FIELD_TOKEN}\s*[:=]\s*)(?:(?:bearer|basic)\s+)?"
    r'''(?P<value>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;&}\]]+)'''
)
_BEARER = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/-]+=*")
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"']+")


class RunnerBlocked(RuntimeError):
    """A required local browser capability is unavailable before the case can run."""


def validate_target(raw_url: str) -> SplitResult:
    """Accept only credential-free HTTP(S) targets on the temporary loopback ports."""
    try:
        target = urlsplit(raw_url)
        port = target.port
    except ValueError as exc:
        raise ValueError("target URL is malformed") from exc
    if target.scheme not in {"http", "https"}:
        raise ValueError("target scheme must be HTTP or HTTPS")
    if target.hostname not in ALLOWED_HOSTS:
        raise ValueError("target host is outside the loopback allowlist")
    if target.username is not None or target.password is not None:
        raise ValueError("target URL must not contain credentials")
    if port not in ALLOWED_PORTS:
        raise ValueError("target port is outside 8940-8949")
    return target


def websocket_is_allowed(raw_url: str) -> bool:
    """Check a WebSocket URL against the same host and port allowlist."""
    try:
        target = urlsplit(raw_url)
        if target.scheme not in {"ws", "wss"}:
            return False
        http_scheme = "https" if target.scheme == "wss" else "http"
        validate_target(urlunsplit((http_scheme, target.netloc, target.path, target.query, "")))
        return True
    except ValueError:
        return False


def sanitize_url(raw_url: str) -> str:
    """Remove userinfo, query values, and fragments before URLs enter evidence logs."""
    try:
        target = urlsplit(raw_url)
        host = target.hostname
        if not host:
            return "<invalid-url>"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = target.port
        netloc = f"{host}:{port}" if port is not None else host
        query = "REDACTED" if target.query else ""
        return urlunsplit((target.scheme, netloc, target.path, query, ""))
    except ValueError:
        return "<invalid-url>"


def _redact_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SECRET_FIELD.fullmatch(str(key)) else _redact_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_json_value(item) for item in value]
    if isinstance(value, str):
        return _redact_plain_text(value)
    return value


def _redact_plain_text(value: str) -> str:
    text = _URL_IN_TEXT.sub(lambda match: sanitize_url(match.group(0)), value)
    text = _BODY_ASSIGNMENT.sub(lambda match: match.group("prefix") + "[REDACTED]", text)

    def redact_assignment(match: re.Match[str]) -> str:
        original = match.group("value")
        if original.startswith('"'):
            replacement = '"[REDACTED]"'
        elif original.startswith("'"):
            replacement = "'[REDACTED]'"
        else:
            replacement = "[REDACTED]"
        return match.group("prefix") + replacement

    text = _SECRET_ASSIGNMENT.sub(redact_assignment, text)
    return _BEARER.sub("Bearer [REDACTED]", text)


def redact_text(value: str) -> str:
    """Redact URL queries, quoted JSON secrets, bodies, and credential assignments."""
    text = str(value)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return _redact_plain_text(text)[:4000]
    return json.dumps(_redact_json_value(parsed), ensure_ascii=False, separators=(",", ":"))[:4000]


def new_run_record(display_url: str) -> dict[str, Any]:
    """Create a truthful all-NOT_RUN evidence template for the required matrix."""
    cases: list[dict[str, Any]] = []
    for language in LANGUAGES:
        for width in WIDTHS:
            cases.append(
                {
                    "case_id": f"{language}-{width}x{VIEWPORT_HEIGHT}",
                    "language": language,
                    "width": width,
                    "height": VIEWPORT_HEIGHT,
                    "status": "NOT_RUN",
                    "language_verification": {
                        "status": "NOT_RUN",
                        "observed_lang": None,
                        "aria_label": None,
                        "visible_text": None,
                    },
                    "readiness": {
                        "status": "NOT_RUN",
                        "binding_source": None,
                        "identity": None,
                        "checks": None,
                        "source_counts": None,
                        "rendered_projection": None,
                    },
                    "api_requests": [],
                    "phases": {
                        phase: {
                            "status": "NOT_RUN",
                            "measurements": None,
                            "checks": None,
                            "screenshot": None,
                            "interaction": None,
                        }
                        for phase in PHASES
                    },
                    "screenshots": [],
                    "failures": [],
                    "unauthorized_requests": [],
                }
            )
    return {
        "record_format": "q5-week6-ribbon-layout-run-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_target": sanitize_url(display_url),
        "overall_status": "NOT_RUN",
        "cases": cases,
        "run_failures": [],
        "diagnostics_file": "diagnostics.jsonl",
    }


def assess_snapshot(
    snapshot: Mapping[str, Any],
    *,
    baseline: Mapping[str, Any] | None = None,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> dict[str, Any]:
    """Apply existing >1px overlap gate and expose strict-zero overlap separately."""
    document_scroll = _finite_number(snapshot.get("document_scroll_width"))
    document_client = _finite_number(snapshot.get("document_client_width"))
    ribbon_scroll = _finite_number(snapshot.get("ribbon_scroll_width"))
    ribbon_client = _finite_number(snapshot.get("ribbon_client_width"))
    viewport_width = _finite_number(snapshot.get("viewport_inner_width"))
    viewport_height = _finite_number(snapshot.get("viewport_inner_height"))
    legacy_overlaps = _finite_number(snapshot.get("legacy_peer_overlap_count"))
    original_head_overlaps = _finite_number(snapshot.get("original_head_full_button_pair_overlap_count"))
    strict_overlaps = _finite_number(snapshot.get("strict_peer_overlap_count"))
    button_overflow = _finite_number(snapshot.get("button_overflow_count"))

    checks: dict[str, bool | None] = {
        "document_horizontal_fit": (
            document_scroll <= document_client
            if document_scroll is not None and document_client is not None
            else False
        ),
        "ribbon_content_fit": (
            ribbon_scroll <= ribbon_client
            if ribbon_scroll is not None and ribbon_client is not None
            else False
        ),
        "legacy_overlap_gate_clear": legacy_overlaps == 0 if legacy_overlaps is not None else False,
        "original_head_all_button_overlap_gate_clear": (
            original_head_overlaps == 0 if original_head_overlaps is not None else False
        ),
        "ribbon_buttons_within_viewport": button_overflow == 0 if button_overflow is not None else False,
        "shell_present": snapshot.get("shell") is not None,
        "view_present": snapshot.get("view") is not None,
        "viewport_matches_request": (
            viewport_width == expected_width and viewport_height == expected_height
            if expected_width is not None and expected_height is not None
            else None
        ),
        "shell_view_geometry_unchanged": (
            snapshot.get("shell") == baseline.get("shell")
            and snapshot.get("view") == baseline.get("view")
            if baseline is not None
            else None
        ),
    }
    diagnostics = {
        "legacy_peer_overlap_count_over_1px": legacy_overlaps,
        "original_head_full_button_pair_overlap_count_over_1px": original_head_overlaps,
        "strict_peer_overlap_count_any_positive_intersection": strict_overlaps,
        "strict_zero_overlap_diagnostic": strict_overlaps == 0 if strict_overlaps is not None else None,
        "viewport_inner_width": viewport_width,
        "document_client_width": document_client,
        "viewport_inner_height": viewport_height,
    }
    passed = all(value is not False for value in checks.values()) and all(
        value is True for name, value in checks.items() if name != "viewport_matches_request" and value is not None
    )
    return {"passed": passed, "checks": checks, "diagnostics": diagnostics}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


_PLACEHOLDER_IDENTITIES = {
    "", "—", "-", "unavailable", "not loaded", "unknown", "none", "null",
    "undefined", "loading", "無法取得", "尚未載入", "載入中",
}


def _usable_identity(value: Any) -> bool:
    return isinstance(value, str) and value.strip().casefold() not in _PLACEHOLDER_IDENTITIES


def _integer_value(value: Any) -> int | None:
    number = _finite_number(value)
    return int(number) if number is not None and number.is_integer() else None


def _coordinate_position_count(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    if (
        len(value) >= 2
        and all(_finite_number(item) is not None for item in value[:2])
    ):
        return 1
    return sum(_coordinate_position_count(item) for item in value)


def _source_projection_expectation(source_context: Any, language: str) -> dict[str, Any] | None:
    if not isinstance(source_context, Mapping) or language not in LANGUAGES:
        return None
    area = source_context.get("study_area")
    workspace = source_context.get("current_workspace")
    area = area if isinstance(area, Mapping) else {}
    workspace = workspace if isinstance(workspace, Mapping) else {}
    geometry = area.get("geometry")
    geometry = geometry if isinstance(geometry, Mapping) else {}
    evidence_cards = source_context.get("evidence_cards")
    buildings = source_context.get("buildings")
    roads = source_context.get("roads")
    project_id = source_context.get("project_id")
    study_area_id = area.get("id")
    workspace_id = workspace.get("workspace_id")
    revision = _integer_value(workspace.get("revision"))
    area_revision = _integer_value(area.get("revision"))
    evidence_count = len(evidence_cards) if isinstance(evidence_cards, list) else None
    building_count = len(buildings) if isinstance(buildings, list) else None
    road_count = len(roads) if isinstance(roads, list) else None
    if not all((
        source_context.get("source_integrity_status") == "VERIFIED",
        _usable_identity(project_id),
        _usable_identity(study_area_id),
        _usable_identity(workspace_id),
        area.get("status") == "CONFIRMED_FOR_EXPLORATION",
        area_revision is not None and area_revision > 0,
        geometry.get("type") in {"Polygon", "MultiPolygon"},
        _coordinate_position_count(geometry.get("coordinates")) >= 4,
        workspace.get("project_id") == project_id,
        workspace.get("study_area_id") == study_area_id,
        revision is not None and revision >= 0,
        evidence_count is not None and evidence_count > 0,
        building_count is not None and road_count is not None and building_count + road_count > 0,
    )):
        return None
    return {
        "language": language,
        "project_id": project_id,
        "study_area_id": study_area_id,
        "source_study_area_status": area.get("status"),
        "workspace_revision": revision,
        "evidence_count": evidence_count,
        "building_count": building_count,
        "road_count": road_count,
    }


def _wait_for_site_context_completion(page: Any, api_tracker: Mapping[str, Any]) -> dict[str, Any]:
    for _ in range(50):
        request = api_tracker.get("site_context_request")
        if isinstance(request, Mapping):
            if request.get("failed") is True:
                return {"status": "FAILED", "request_finished": False}
            if request.get("finished") is True:
                return {"status": "FINISHED", "request_finished": True}
        page.wait_for_timeout(100)
    request = api_tracker.get("site_context_request")
    return {
        "status": "TIMEOUT" if isinstance(request, Mapping) else "NOT_OBSERVED",
        "request_finished": False,
    }


def _wait_for_source_bound_projection(page: Any, expectation: Mapping[str, Any]) -> str | None:
    try:
        page.wait_for_function(
            """expected => {
              const shell = document.querySelector('.design-shell');
              if (shell?.getAttribute('lang') !== expected.language) return false;
              const footer = [...document.querySelectorAll('.shell-statusbar > span')]
                .map(el => (el.innerText || el.textContent || '').trim());
              const labelValue = value => {
                const text = String(value || '');
                const colon = Math.max(text.lastIndexOf(':'), text.lastIndexOf('：'));
                return colon >= 0 ? text.slice(colon + 1).trim() : '';
              };
              const revisionFrom = value => {
                const match = String(value || '').match(/([0-9]+) *$/);
                return match ? Number(match[1]) : null;
              };
              const authorityValue = labelValue(footer[3]);
              if (authorityValue !== 'READY' && authorityValue !== '就緒') return false;
              const projectId = document.querySelector('#header-project-id')?.getAttribute('title')?.trim()
                || labelValue(footer[0]);
              const studyAreaId = document.querySelector('#header-study-area-id')?.getAttribute('title')?.trim()
                || labelValue(footer[1]);
              const workspaceRevision = revisionFrom(document.querySelector('#badge-revision')?.textContent)
                ?? revisionFrom(footer[2]);
              const statusBadge = document.querySelector('#badge-study-area-status');
              const countFrom = value => {
                const match = String(value || '').match(/([0-9]+)[^0-9]*$/);
                return match ? Number(match[1]) : null;
              };
              const factsCount = countFrom(document.querySelector('.site-facts-panel__heading h2')?.textContent);
              const propertyCounts = {building_count: null, road_count: null};
              for (const term of document.querySelectorAll('.shell-properties .shell-property-content dt')) {
                const label = (term.textContent || '').trim();
                const value = Number((term.nextElementSibling?.textContent || '').trim());
                if ((label === 'Buildings' || label === '建築') && Number.isInteger(value)) propertyCounts.building_count = value;
                if ((label === 'Roads' || label === '道路') && Number.isInteger(value)) propertyCounts.road_count = value;
              }
              const canvas = document.querySelector('#canvas-viewport-2d');
              if (!canvas || !canvas.getClientRects().length || canvas.width < 1 || canvas.height < 1) return false;
              let outlinePresent = false;
              try {
                const pixels = canvas.getContext('2d')?.getImageData(0, 0, canvas.width, canvas.height).data;
                if (pixels) for (let index = 0; index < pixels.length; index += 4) {
                  const red = pixels[index], green = pixels[index + 1], blue = pixels[index + 2], alpha = pixels[index + 3];
                  if (alpha > 0 && red >= 40 && red <= 75 && green >= 160 && green <= 215 && blue >= 220) {
                    outlinePresent = true;
                    break;
                  }
                }
              } catch {}
              return expected.source_study_area_status === 'CONFIRMED_FOR_EXPLORATION' &&
                statusBadge === null &&
                projectId === expected.project_id && studyAreaId === expected.study_area_id &&
                workspaceRevision === expected.workspace_revision &&
                factsCount === expected.evidence_count &&
                propertyCounts.building_count === expected.building_count &&
                propertyCounts.road_count === expected.road_count && outlinePresent;
            }""",
            arg=dict(expectation),
            timeout=10000,
            polling=250,
        )
        return None
    except Exception as exc:
        return redact_text(str(exc))


def assess_ui_readiness(
    *,
    request_lifecycle: Mapping[str, Any],
    source_context: Mapping[str, Any] | None,
    ui_projection: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind completed read-only site-context data to the visible app projection."""
    source = source_context if isinstance(source_context, Mapping) else {}
    area = source.get("study_area")
    area = area if isinstance(area, Mapping) else {}
    workspace = source.get("current_workspace")
    workspace = workspace if isinstance(workspace, Mapping) else {}
    geometry = area.get("geometry")
    geometry = geometry if isinstance(geometry, Mapping) else {}
    evidence_cards = source.get("evidence_cards")
    buildings = source.get("buildings")
    roads = source.get("roads")
    evidence_count = len(evidence_cards) if isinstance(evidence_cards, list) else None
    building_count = len(buildings) if isinstance(buildings, list) else None
    road_count = len(roads) if isinstance(roads, list) else None
    source_project_id = source.get("project_id")
    source_area_id = area.get("id")
    source_area_status = area.get("status")
    source_area_revision = _integer_value(area.get("revision"))
    source_workspace_id = workspace.get("workspace_id")
    source_workspace_project_id = workspace.get("project_id")
    source_workspace_area_id = workspace.get("study_area_id")
    source_workspace_revision = _integer_value(workspace.get("revision"))
    ui_revision = _integer_value(ui_projection.get("workspace_revision"))
    request_status = _integer_value(request_lifecycle.get("status_code"))
    geometry_type = geometry.get("type")
    geometry_positions = _coordinate_position_count(geometry.get("coordinates"))
    canvas_width = _finite_number(ui_projection.get("map_canvas_width"))
    canvas_height = _finite_number(ui_projection.get("map_canvas_height"))
    outline_pixels = _integer_value(ui_projection.get("study_area_outline_pixel_count"))
    ui_evidence_count = _integer_value(ui_projection.get("site_facts_count"))
    ui_building_count = _integer_value(ui_projection.get("building_count"))
    ui_road_count = _integer_value(ui_projection.get("road_count"))

    checks = {
        "site_context_endpoint_matches": request_lifecycle.get("endpoint") == "site-context",
        "site_context_method_readonly": request_lifecycle.get("method") == "GET",
        "site_context_request_started": request_lifecycle.get("started") is True,
        "site_context_request_finished": (
            request_lifecycle.get("finished") is True
            and request_lifecycle.get("failed") is False
        ),
        "site_context_response_ok": request_status == 200,
        "site_context_body_json_valid": request_lifecycle.get("body_json_valid") is True,
        "source_catalog_verified": source.get("source_integrity_status") == "VERIFIED",
        "source_project_identity_present": _usable_identity(source_project_id),
        "source_study_area_identity_present": _usable_identity(source_area_id),
        "source_study_area_confirmed": source_area_status == "CONFIRMED_FOR_EXPLORATION",
        "source_study_area_revision_persisted": source_area_revision is not None and source_area_revision > 0,
        "source_study_area_geometry_present": (
            geometry_type in {"Polygon", "MultiPolygon"} and geometry_positions >= 4
        ),
        "source_workspace_identity_present": _usable_identity(source_workspace_id),
        "source_workspace_revision_persisted": source_workspace_revision is not None and source_workspace_revision >= 0,
        "source_workspace_project_matches_study_context": (
            _usable_identity(source_project_id)
            and source_workspace_project_id == source_project_id
        ),
        "source_workspace_study_area_matches": (
            _usable_identity(source_area_id)
            and source_workspace_area_id == source_area_id
        ),
        "source_evidence_nonempty": evidence_count is not None and evidence_count > 0,
        "source_features_nonempty": (
            building_count is not None and road_count is not None
            and building_count + road_count > 0
        ),
        "authority_ready": ui_projection.get("authority_state") == "READY",
        "source_projection_wait_matched": ui_projection.get("source_projection_wait_matched") is True,
        "rendered_project_identity_matches_source": (
            _usable_identity(ui_projection.get("project_id"))
            and ui_projection.get("project_id") == source_project_id
        ),
        "rendered_study_area_identity_matches_source": (
            _usable_identity(ui_projection.get("study_area_id"))
            and ui_projection.get("study_area_id") == source_area_id
        ),
        "rendered_workspace_revision_matches_source": (
            ui_revision is not None and ui_revision == source_workspace_revision
        ),
        "source_workspace_identity_matches_rendered_projection": (
            _usable_identity(source_workspace_id)
            and source_workspace_project_id == source_project_id
            and source_workspace_area_id == source_area_id
            and ui_projection.get("project_id") == source_project_id
            and ui_projection.get("study_area_id") == source_area_id
            and ui_revision is not None and ui_revision == source_workspace_revision
        ),
        "rendered_study_area_status_not_displayed": (
            ui_projection.get("study_area_status_display_state") == "NOT_DISPLAYED"
            and ui_projection.get("study_area_status") is None
        ),
        "rendered_site_facts_match_nonempty_source": (
            evidence_count is not None and evidence_count > 0
            and ui_evidence_count == evidence_count
        ),
        "rendered_feature_counts_match_source": (
            building_count is not None and road_count is not None
            and ui_building_count == building_count
            and ui_road_count == road_count
            and building_count + road_count > 0
        ),
        "map_canvas_visible": (
            ui_projection.get("map_canvas_visible") is True
            and canvas_width is not None and canvas_width > 0
            and canvas_height is not None and canvas_height > 0
        ),
        "rendered_study_area_outline_present": outline_pixels is not None and outline_pixels > 0,
    }
    source_identity = {
        "project_id": source_project_id if _usable_identity(source_project_id) else None,
        "source_integrity_status": source.get("source_integrity_status"),
        "source_package_id": source.get("source_package_id"),
        "source_package_revision": source.get("source_package_revision"),
        "study_area_id": source_area_id if _usable_identity(source_area_id) else None,
        "study_area_revision": source_area_revision,
        "study_area_status": source_area_status,
        "workspace_id": source_workspace_id if _usable_identity(source_workspace_id) else None,
        "workspace_project_id": source_workspace_project_id,
        "workspace_study_area_id": source_workspace_area_id,
        "workspace_revision": source_workspace_revision,
    }
    rendered_identity = {
        "project_id": ui_projection.get("project_id"),
        "study_area_id": ui_projection.get("study_area_id"),
        "study_area_status": ui_projection.get("study_area_status"),
        "study_area_status_display_state": ui_projection.get("study_area_status_display_state"),
        "workspace_revision": ui_revision,
    }
    authority = ui_projection.get("authority_state")
    if (
        request_lifecycle.get("started") is not True
        or request_lifecycle.get("failed") is True
        or request_lifecycle.get("finished") is not True
        or authority in (None, "", "LOADING")
    ):
        status = "BLOCKED"
    else:
        status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "status": status,
        "binding_source": (
            "completed browser GET site-context JSON from the allowlisted API, "
            "matched to the rendered project, StudyArea, workspace revision, properties, Site Facts, and 2D boundary; status badge is NOT_DISPLAYED"
        ),
        "identity": {"source": source_identity, "rendered": rendered_identity},
        "source_counts": {
            "evidence_cards": evidence_count,
            "buildings": building_count,
            "roads": road_count,
            "study_area_geometry_type": geometry_type,
            "study_area_coordinate_positions": geometry_positions,
        },
        "rendered_projection": {
            "site_facts_count": ui_evidence_count,
            "building_count": ui_building_count,
            "road_count": ui_road_count,
            "map_canvas_visible": ui_projection.get("map_canvas_visible") is True,
            "map_canvas_width": canvas_width,
            "map_canvas_height": canvas_height,
            "study_area_outline_pixel_count": outline_pixels,
            "authority_state": authority,
            "study_area_status": ui_projection.get("study_area_status"),
            "study_area_status_display_state": ui_projection.get("study_area_status_display_state"),
            "source_projection_wait_matched": ui_projection.get("source_projection_wait_matched") is True,
        },
        "checks": checks,
    }


def _readiness_evidence_complete(readiness: Mapping[str, Any]) -> bool:
    checks = readiness.get("checks")
    identity = readiness.get("identity")
    source = identity.get("source") if isinstance(identity, Mapping) else None
    rendered = identity.get("rendered") if isinstance(identity, Mapping) else None
    source_counts = readiness.get("source_counts")
    projection = readiness.get("rendered_projection")
    if not all(isinstance(item, Mapping) for item in (checks, source, rendered, source_counts, projection)):
        return False
    required_checks = {
        "site_context_endpoint_matches", "site_context_method_readonly",
        "site_context_request_started", "site_context_request_finished",
        "site_context_response_ok", "site_context_body_json_valid",
        "source_catalog_verified", "source_project_identity_present",
        "source_study_area_identity_present", "source_study_area_confirmed",
        "source_study_area_revision_persisted", "source_study_area_geometry_present",
        "source_workspace_identity_present", "source_workspace_revision_persisted",
        "source_workspace_project_matches_study_context", "source_workspace_study_area_matches",
        "source_evidence_nonempty", "source_features_nonempty", "authority_ready",
        "source_projection_wait_matched",
        "rendered_project_identity_matches_source", "rendered_study_area_identity_matches_source",
        "rendered_workspace_revision_matches_source", "source_workspace_identity_matches_rendered_projection",
        "rendered_study_area_status_not_displayed", "rendered_site_facts_match_nonempty_source",
        "rendered_feature_counts_match_source", "map_canvas_visible",
        "rendered_study_area_outline_present",
    }
    if (
        readiness.get("status") != "PASS"
        or not isinstance(readiness.get("binding_source"), str)
        or not readiness["binding_source"].strip()
        or not required_checks.issubset(checks)
        or any(value is not True for value in checks.values())
    ):
        return False
    source_area = source.get("study_area_id")
    source_project = source.get("project_id")
    source_workspace_id = source.get("workspace_id")
    revision = _integer_value(source.get("workspace_revision"))
    area_revision = _integer_value(source.get("study_area_revision"))
    evidence_count = _integer_value(source_counts.get("evidence_cards"))
    building_count = _integer_value(source_counts.get("buildings"))
    road_count = _integer_value(source_counts.get("roads"))
    outline_pixels = _integer_value(projection.get("study_area_outline_pixel_count"))
    return all((
        _usable_identity(source_area),
        _usable_identity(source_project),
        _usable_identity(source_workspace_id),
        source.get("source_integrity_status") == "VERIFIED",
        source.get("workspace_project_id") == source_project,
        source.get("workspace_study_area_id") == source_area,
        source.get("study_area_status") == "CONFIRMED_FOR_EXPLORATION",
        area_revision is not None and area_revision > 0,
        revision is not None and revision >= 0,
        source_counts.get("study_area_geometry_type") in {"Polygon", "MultiPolygon"},
        _integer_value(source_counts.get("study_area_coordinate_positions")) is not None
        and _integer_value(source_counts.get("study_area_coordinate_positions")) >= 4,
        rendered.get("project_id") == source_project,
        rendered.get("study_area_id") == source_area,
        rendered.get("study_area_status") is None,
        rendered.get("study_area_status_display_state") == "NOT_DISPLAYED",
        rendered.get("workspace_revision") == revision,
        evidence_count is not None and evidence_count > 0,
        building_count is not None and road_count is not None and building_count + road_count > 0,
        _integer_value(projection.get("site_facts_count")) == evidence_count,
        _integer_value(projection.get("building_count")) == building_count,
        _integer_value(projection.get("road_count")) == road_count,
        projection.get("map_canvas_visible") is True,
        (_finite_number(projection.get("map_canvas_width")) or 0) > 0,
        (_finite_number(projection.get("map_canvas_height")) or 0) > 0,
        outline_pixels is not None and outline_pixels > 0,
        projection.get("authority_state") == "READY",
        projection.get("source_projection_wait_matched") is True,
    ))


def _derive_overall_status(record: Mapping[str, Any]) -> str:
    cases = record.get("cases", [])
    if not cases:
        return "NOT_RUN"
    statuses = [case.get("status") for case in cases]
    run_failures = record.get("run_failures", [])
    failure_statuses = [item.get("status") for item in run_failures]
    allowed = {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}
    if any(status not in allowed for status in statuses + failure_statuses):
        return "FAIL"
    if "FAIL" in failure_statuses or "FAIL" in statuses:
        return "FAIL"
    if "BLOCKED" in failure_statuses or "BLOCKED" in statuses:
        return "BLOCKED"
    if any(status != "PASS" for status in statuses + failure_statuses):
        return "NOT_RUN"
    if any(_case_status(case) != "PASS" for case in cases):
        return "NOT_RUN"
    return "PASS"


def _checkpoint(output_dir: Path, record: dict[str, Any]) -> None:
    record["overall_status"] = _derive_overall_status(record)
    temporary = output_dir / "result.json.tmp"
    destination = output_dir / "result.json"
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)


class DiagnosticLog:
    """Append-only, fsynced JSONL diagnostics with URL and credential redaction."""

    def __init__(self, path: Path) -> None:
        self._stream = path.open("x", encoding="utf-8")

    def __enter__(self) -> "DiagnosticLog":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def emit(self, event: Mapping[str, Any]) -> None:
        safe = _redact_value(dict(event))
        safe.setdefault("at_utc", datetime.now(timezone.utc).isoformat())
        self._stream.write(json.dumps(safe, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
        self._stream.flush()
        os.fsync(self._stream.fileno())

    def close(self) -> None:
        self._stream.close()


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SECRET_FIELD.fullmatch(str(key)) else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


def _write_png_exclusive(path: Path, image: bytes) -> dict[str, Any]:
    if not image or not image.startswith(PNG_SIGNATURE):
        raise RuntimeError("browser did not return a nonempty PNG screenshot")
    with path.open("xb") as stream:
        stream.write(image)
        stream.flush()
        os.fsync(stream.fileno())
    saved = path.read_bytes()
    if not saved or not saved.startswith(PNG_SIGNATURE):
        raise RuntimeError("saved screenshot is not a nonempty PNG")
    return {"size_bytes": len(saved), "sha256": hashlib.sha256(saved).hexdigest()}


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    encoded = (json.dumps(_redact_value(dict(value)), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    saved = path.read_bytes()
    return {"file": path.name, "size_bytes": len(saved), "sha256": hashlib.sha256(saved).hexdigest()}


def _capture_screenshot(
    page: Any,
    output_dir: Path,
    case: dict[str, Any],
    phase: str,
    diagnostics: DiagnosticLog,
) -> dict[str, Any]:
    safe_language = case["language"].replace("/", "-")
    filename = f"{safe_language}-{case['width']}x{case['height']}-{phase}.png"
    path = output_dir / filename
    image = page.screenshot(full_page=False, animations="disabled", timeout=15000)
    saved = _write_png_exclusive(path, image)
    artifact = {"phase": phase, "file": filename, **saved}
    case["screenshots"].append(artifact)
    if phase in case["phases"]:
        case["phases"][phase]["screenshot"] = artifact
    diagnostics.emit({"type": "screenshot_saved", "case_id": case["case_id"], **artifact})
    return artifact


def _capture_readiness_diagnostics(
    page: Any,
    output_dir: Path,
    case: dict[str, Any],
    diagnostics: DiagnosticLog,
) -> None:
    snapshot = _snapshot(page)
    dom_name = f"{case['language']}-{case['width']}x{case['height']}-readiness-dom.json"
    try:
        dom_artifact = _write_json_exclusive(output_dir / dom_name, snapshot)
        case["readiness"]["diagnostic_dom"] = dom_artifact
        diagnostics.emit({
            "type": "readiness_dom_saved",
            "case_id": case["case_id"],
            **dom_artifact,
        })
    except Exception as exc:
        diagnostics.emit({
            "type": "readiness_dom_save_failure",
            "case_id": case["case_id"],
            "message": redact_text(str(exc)),
        })
    try:
        case["readiness"]["diagnostic_screenshot"] = _capture_screenshot(
            page, output_dir, case, "readiness", diagnostics
        )
    except Exception as exc:
        diagnostics.emit({
            "type": "readiness_screenshot_failure",
            "case_id": case["case_id"],
            "message": redact_text(str(exc)),
        })


def _record_failure(
    case: dict[str, Any],
    diagnostics: DiagnosticLog,
    checkpoint: Any,
    message: str,
    *,
    status: str = "FAIL",
    phase: str | None = None,
) -> None:
    detail = {"status": status, "phase": phase, "message": redact_text(message)}
    case["failures"].append(detail)
    if phase in case["phases"]:
        case["phases"][phase]["status"] = "FAIL" if status == "FAIL" else status
        case["phases"][phase].setdefault("failures", []).append(detail)
    if status == "FAIL" or case["status"] == "NOT_RUN":
        case["status"] = status
    diagnostics.emit({"type": "case_failure", "case_id": case["case_id"], **detail})
    checkpoint()


def _mark_pending_blocked(
    record: dict[str, Any], diagnostics: DiagnosticLog, checkpoint: Any, reason: str
) -> None:
    for case in record["cases"]:
        if case["status"] == "NOT_RUN":
            case["status"] = "BLOCKED"
            case["failures"].append({"status": "BLOCKED", "phase": None, "message": redact_text(reason)})
    record["run_failures"].append({"status": "BLOCKED", "message": redact_text(reason)})
    diagnostics.emit({"type": "runner_blocked", "message": reason})
    checkpoint()


def _snapshot(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const rect = el => {
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {x: r.x, y: r.y, width: r.width, height: r.height};
          };
          const visible = el => {
            const style = getComputedStyle(el);
            if (!el.getClientRects().length || style.display === 'none' ||
                style.visibility === 'hidden' || style.visibility === 'collapse' ||
                Number(style.opacity) === 0) return false;
            for (let parent = el.parentElement; parent; parent = parent.parentElement) {
              if (Number(getComputedStyle(parent).opacity) === 0) return false;
            }
            return true;
          };
          const allButtons = [...document.querySelectorAll('.shell-ribbon button')]
            .map(el => ({el, ...rect(el)}));
          let originalHeadFullButtonPairOverlapCount = 0;
          for (let i = 0; i < allButtons.length; i++) {
            for (let j = i + 1; j < allButtons.length; j++) {
              const a = allButtons[i];
              const b = allButtons[j];
              const width = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
              const height = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
              if (width > 1 && height > 1) originalHeadFullButtonPairOverlapCount++;
            }
          }
          const controls = allButtons.filter(({el}) => visible(el));
          let legacyOverlapCount = 0;
          let strictOverlapCount = 0;
          for (let i = 0; i < controls.length; i++) {
            for (let j = i + 1; j < controls.length; j++) {
              const a = controls[i];
              const b = controls[j];
              if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
              const width = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
              const height = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
              if (width > 0 && height > 0) strictOverlapCount++;
              if (width > 1 && height > 1) legacyOverlapCount++;
            }
          }
          const ribbon = document.querySelector('.shell-ribbon');
          const shell = document.querySelector('.design-shell');
          const view = document.querySelector('.shell-view-content');
          const footer = [...document.querySelectorAll('.shell-statusbar > span')]
            .map(el => (el.innerText || el.textContent || '').trim());
          const labelValue = value => {
            const text = String(value || '');
            const colon = Math.max(text.lastIndexOf(':'), text.lastIndexOf('：'));
            return colon >= 0 ? text.slice(colon + 1).trim() : '';
          };
          const revisionFrom = value => {
            const match = String(value || '').match(/([0-9]+) *$/);
            return match ? Number(match[1]) : null;
          };
          const countFrom = value => {
            const match = String(value || '').match(/([0-9]+)[^0-9]*$/);
            return match ? Number(match[1]) : null;
          };
          const authorityText = footer[3] || '';
          const authorityState = authorityText.includes('READY') || authorityText.includes('就緒') ? 'READY'
            : authorityText.includes('ERROR') || authorityText.includes('錯誤') ? 'ERROR'
              : authorityText.includes('LOADING') || authorityText.includes('載入中') ? 'LOADING' : null;
          const studyAreaStatusBadge = document.querySelector('#badge-study-area-status');
          const studyAreaStatusText = studyAreaStatusBadge?.textContent ?? null;
          const factsHeading = document.querySelector('.site-facts-panel__heading h2')?.textContent || '';
          const propertyCounts = {building_count: null, road_count: null};
          for (const term of document.querySelectorAll('.shell-properties .shell-property-content dt')) {
            const label = (term.textContent || '').trim();
            const value = Number((term.nextElementSibling?.textContent || '').trim());
            if ((label === 'Buildings' || label === '建築') && Number.isInteger(value)) {
              propertyCounts.building_count = value;
            }
            if ((label === 'Roads' || label === '道路') && Number.isInteger(value)) {
              propertyCounts.road_count = value;
            }
          }
          const mapCanvas = document.querySelector('#canvas-viewport-2d');
          let studyAreaOutlinePixelCount = 0;
          if (mapCanvas && mapCanvas.width > 0 && mapCanvas.height > 0) {
            try {
              const pixels = mapCanvas.getContext('2d')?.getImageData(0, 0, mapCanvas.width, mapCanvas.height).data;
              if (pixels) {
                for (let index = 0; index < pixels.length; index += 4) {
                  const red = pixels[index], green = pixels[index + 1];
                  const blue = pixels[index + 2], alpha = pixels[index + 3];
                  if (alpha > 0 && red >= 40 && red <= 75 && green >= 160 && green <= 215 && blue >= 220) {
                    studyAreaOutlinePixelCount++;
                  }
                }
              }
            } catch {}
          }
          const renderedProjection = {
            authority_state: authorityState,
            project_id: document.querySelector('#header-project-id')?.getAttribute('title') || labelValue(footer[0]),
            study_area_id: document.querySelector('#header-study-area-id')?.getAttribute('title') || labelValue(footer[1]),
            study_area_status: null,
            study_area_status_display_state: studyAreaStatusBadge === null ? 'NOT_DISPLAYED' : 'DISPLAYED',
            study_area_status_text: studyAreaStatusText,
            workspace_revision: revisionFrom(document.querySelector('#badge-revision')?.textContent)
              ?? revisionFrom(footer[2]),
            site_facts_count: countFrom(factsHeading),
            ...propertyCounts,
            map_canvas_visible: visible(mapCanvas),
            map_canvas_width: mapCanvas?.width ?? null,
            map_canvas_height: mapCanvas?.height ?? null,
            study_area_outline_pixel_count: studyAreaOutlinePixelCount,
          };
          return {
            document_scroll_width: document.documentElement.scrollWidth,
            document_client_width: document.documentElement.clientWidth,
            viewport_inner_width: window.innerWidth,
            viewport_inner_height: window.innerHeight,
            ribbon_scroll_width: ribbon?.scrollWidth ?? null,
            ribbon_client_width: ribbon?.clientWidth ?? null,
            visible_peer_control_count: controls.length,
            legacy_peer_overlap_count: legacyOverlapCount,
            original_head_full_button_pair_overlap_count: originalHeadFullButtonPairOverlapCount,
            strict_peer_overlap_count: strictOverlapCount,
            button_overflow_count: controls.filter(r => r.x < 0 || r.x + r.width > window.innerWidth).length,
            shell: rect(shell),
            view: rect(view),
            language: shell?.getAttribute('lang') ?? null,
            measurement_pressed: document.querySelector('#btn-measure-distance')?.getAttribute('aria-pressed') ?? null,
            readiness_projection: renderedProjection,
            statusbar_text: footer,
          };
        }"""
    )
    projection = result.get("readiness_projection") if isinstance(result, dict) else None
    return result


def _connection_refused(error: BaseException) -> bool:
    message = str(error).upper()
    return any(
        marker in message
        for marker in (
            "ERR_CONNECTION_REFUSED",
            "ERR_CONNECTION_TIMED_OUT",
            "ERR_ADDRESS_UNREACHABLE",
        )
    )


def _verify_language(page: Any, case: dict[str, Any], diagnostics: DiagnosticLog, checkpoint: Any) -> bool:
    expected = case["language"]
    shell = page.locator(".design-shell")
    shell.wait_for(state="visible", timeout=15000)
    toggle = page.locator("#language-toggle")
    toggle.wait_for(state="visible", timeout=5000)
    actual = shell.get_attribute("lang")
    if actual not in LANGUAGES:
        raise AssertionError(f"UI declared unsupported language {actual!r}")
    if actual != expected:
        toggle.click(timeout=5000)
        page.wait_for_function(
            "expected => document.querySelector('.design-shell')?.getAttribute('lang') === expected",
            arg=expected,
            timeout=5000,
        )
        actual = shell.get_attribute("lang")
    aria_label = toggle.get_attribute("aria-label")
    visible_text = toggle.inner_text().strip()
    expected_aria = {
        "en": "Current language: English; click to switch language",
        "zh-TW": "目前語言：繁體中文；點擊切換語言",
    }[expected]
    expected_visible_text = {"en": "English ▾", "zh-TW": "中文 ▾"}[expected]
    if actual != expected or aria_label != expected_aria or visible_text != expected_visible_text:
        case["language_verification"] = {
            "status": "FAIL",
            "expected_lang": expected,
            "observed_lang": actual,
            "aria_label": aria_label,
            "visible_text": visible_text,
        }
        _record_failure(
            case,
            diagnostics,
            checkpoint,
            f"language UI verification failed for {expected}: lang/aria-label/text did not match",
        )
        return False
    case["language_verification"] = {
        "status": "PASS",
        "expected_lang": expected,
        "observed_lang": actual,
        "aria_label": aria_label,
        "visible_text": visible_text,
        "control_selector": "#language-toggle",
    }
    diagnostics.emit(
        {
            "type": "language_verified",
            "case_id": case["case_id"],
            "language": actual,
            "selector": "#language-toggle",
            "aria_label": aria_label,
            "visible_text": visible_text,
        }
    )
    checkpoint()
    return True


def _phase_evidence_complete(phase: str, phase_record: Mapping[str, Any]) -> bool:
    measurements = phase_record.get("measurements")
    screenshot = phase_record.get("screenshot")
    checks = phase_record.get("checks")
    required_measurements = {
        "document_scroll_width", "document_client_width", "viewport_inner_width", "viewport_inner_height",
        "ribbon_scroll_width", "ribbon_client_width", "visible_peer_control_count",
        "legacy_peer_overlap_count", "original_head_full_button_pair_overlap_count",
        "strict_peer_overlap_count", "button_overflow_count", "shell", "view", "language",
        "measurement_pressed", "readiness_projection",
    }
    if not isinstance(measurements, Mapping) or not required_measurements.issubset(measurements):
        return False
    if not isinstance(screenshot, Mapping):
        return False
    filename = screenshot.get("file")
    if screenshot.get("phase") != phase or not isinstance(filename, str) or not filename or Path(filename).name != filename:
        return False
    size_bytes = screenshot.get("size_bytes")
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes <= 0:
        return False
    if not isinstance(screenshot.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", screenshot["sha256"]):
        return False
    if not isinstance(checks, Mapping):
        return False
    required_checks = {
        "document_horizontal_fit", "ribbon_content_fit", "legacy_overlap_gate_clear",
        "original_head_all_button_overlap_gate_clear", "ribbon_buttons_within_viewport",
        "shell_present", "view_present", "viewport_matches_request", "shell_view_geometry_unchanged",
        "language_matches_case", "measurement_toggle_state", "actual_screenshot_saved",
        "source_bound_readiness",
    }
    if phase != "before":
        required_checks.add("baseline_measurement_available")
    if not required_checks.issubset(checks):
        return False
    return all(
        value is True or (phase == "before" and key == "shell_view_geometry_unchanged" and value is None)
        for key, value in checks.items()
    )


def _case_status(case: Mapping[str, Any]) -> str:
    failures = case.get("failures", [])
    failure_statuses = [failure.get("status") for failure in failures]
    if any(status not in {"PASS", "FAIL", "BLOCKED", "NOT_RUN"} for status in failure_statuses):
        return "FAIL"
    if "FAIL" in failure_statuses:
        return "FAIL"
    if "BLOCKED" in failure_statuses:
        return "BLOCKED"
    language_status = case.get("language_verification", {}).get("status")
    if language_status not in {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}:
        return "FAIL"
    if language_status == "FAIL":
        return "FAIL"
    if language_status == "BLOCKED":
        return "BLOCKED"
    if language_status != "PASS":
        return "NOT_RUN"
    readiness = case.get("readiness")
    if readiness is None:
        return "NOT_RUN"
    if not isinstance(readiness, Mapping):
        return "FAIL"
    readiness_status = readiness.get("status", "NOT_RUN")
    if readiness_status not in {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}:
        return "FAIL"
    if readiness_status == "FAIL":
        return "FAIL"
    if readiness_status == "BLOCKED":
        return "BLOCKED"
    if readiness_status != "PASS":
        return "NOT_RUN"
    if not _readiness_evidence_complete(readiness):
        return "FAIL"
    phase_records = case.get("phases", {})
    phase_statuses = [phase_records.get(phase, {}).get("status") for phase in PHASES]
    if any(status not in {"PASS", "FAIL", "BLOCKED", "NOT_RUN"} for status in phase_statuses):
        return "FAIL"
    if "FAIL" in phase_statuses:
        return "FAIL"
    if "BLOCKED" in phase_statuses:
        return "BLOCKED"
    if any(status != "PASS" for status in phase_statuses):
        return "NOT_RUN"
    if any(not _phase_evidence_complete(phase, phase_records[phase]) for phase in PHASES):
        return "NOT_RUN"
    return "PASS"


def measurement_phase_action(phase: str, language: str) -> dict[str, str]:
    """Describe the actual localized control for each measurement phase."""
    if language not in LANGUAGES:
        raise ValueError(f"unsupported UI language: {language}")
    if phase == "before":
        return {"kind": "observe", "selector": "#btn-measure-distance", "expected_pressed": "false"}
    if phase == "on":
        return {"kind": "start", "selector": "#btn-measure-distance", "expected_pressed": "true"}
    if phase == "off":
        return {
            "kind": "cancel",
            "region_label": {"en": "Measurement controls", "zh-TW": "量測控制"}[language],
            "accessible_name": {"en": "Cancel measurement", "zh-TW": "取消量測"}[language],
            "expected_pressed": "false",
        }
    raise ValueError(f"unsupported measurement phase: {phase}")


def _transition_measurement(page: Any, phase: str, language: str) -> None:
    action = measurement_phase_action(phase, language)
    if action["kind"] == "observe":
        return
    if action["kind"] == "start":
        page.locator(action["selector"]).click(timeout=5000)
    else:
        region = page.get_by_role("region", name=action["region_label"], exact=True)
        cancel = region.get_by_role("button", name=action["accessible_name"], exact=True)
        cancel.wait_for(state="visible", timeout=5000)
        cancel.click(timeout=5000)
        cancel.wait_for(state="hidden", timeout=5000)
    page.wait_for_function(
        "expected => document.querySelector('#btn-measure-distance')?.getAttribute('aria-pressed') === expected",
        arg=action["expected_pressed"],
        timeout=5000,
    )


def _route_websocket(socket_route: Any, unauthorized_request: Any) -> None:
    raw_url = socket_route.url
    if not websocket_is_allowed(raw_url):
        unauthorized_request(raw_url, "websocket")
        socket_route.close()
        return
    connect = getattr(socket_route, "connect_to_server", None)
    if not callable(connect):
        raise RunnerBlocked("Playwright WebSocketRoute.connect_to_server is unavailable")
    connect()


def _attach_page_diagnostics(
    page: Any,
    case: dict[str, Any],
    active_phase: Mapping[str, str],
    diagnostics: DiagnosticLog,
    checkpoint: Any,
    api_tracker: dict[str, Any],
) -> None:
    def find_live_request(request: Any) -> dict[str, Any] | None:
        for pair in reversed(api_tracker["live_requests"]):
            entry = pair["entry"]
            if pair["request"] is request and not entry["finished"] and not entry["failed"]:
                return pair
        for pair in api_tracker["live_requests"]:
            original = pair["request"]
            entry = pair["entry"]
            if (
                original.method == request.method
                and original.url == request.url
                and not entry["finished"]
                and not entry["failed"]
            ):
                return pair
        return None

    def on_api_request(request: Any) -> None:
        endpoint = _api_endpoint_kind(request.url)
        diagnostics.emit({
            "type": "request",
            "case_id": case["case_id"],
            "phase": active_phase["name"],
            "method": request.method,
            "resource_type": request.resource_type,
            "endpoint": endpoint,
        })
        if endpoint is None:
            return
        entry = {
            "endpoint": endpoint,
            "method": request.method,
            "started": True,
            "response_received": False,
            "status_code": None,
            "finished": False,
            "failed": False,
            "failure": None,
            "body_json_valid": False if endpoint == "site-context" else None,
        }
        case["api_requests"].append(entry)
        api_tracker["live_requests"].append({"request": request, "entry": entry})
        if endpoint == "site-context":
            api_tracker["site_context_request"] = entry
            api_tracker["site_context_payload"] = None
        diagnostics.emit({
            "type": "api_request_started",
            "case_id": case["case_id"],
            "endpoint": endpoint,
            "method": request.method,
        })
        checkpoint()

    page.on(
        "response",
        lambda response: diagnostics.emit({
                "type": "response",
                "case_id": case["case_id"],
                "phase": active_phase["name"],
                "status_code": response.status,
                "resource_type": response.request.resource_type,
                "url": sanitize_url(response.url),
            }),
    )
    def on_api_response(response: Any) -> None:
        pair = find_live_request(response.request)
        if pair is None:
            return
        entry = pair["entry"]
        entry["response_received"] = True
        entry["status_code"] = response.status
        api_tracker["responses"][id(entry)] = response
        diagnostics.emit({
            "type": "api_response_received",
            "case_id": case["case_id"],
            "endpoint": entry["endpoint"],
            "method": entry["method"],
            "status_code": response.status,
        })
        checkpoint()

    def on_request_finished(request: Any) -> None:
        pair = find_live_request(request)
        if pair is None:
            return
        entry = pair["entry"]
        entry["finished"] = True
        response = api_tracker["responses"].pop(id(entry), None)
        if response is None:
            try:
                response = request.response()
            except Exception:
                response = None
        if entry["endpoint"] == "site-context" and response is not None and response.status == 200:
            try:
                payload = response.json()
                entry["body_json_valid"] = isinstance(payload, Mapping)
                if entry is api_tracker.get("site_context_request") and entry["body_json_valid"]:
                    api_tracker["site_context_payload"] = payload
            except Exception as exc:
                entry["body_json_valid"] = False
                entry["failure"] = redact_text(str(exc))
        identity = _safe_context_identity(api_tracker.get("site_context_payload")) if entry["endpoint"] == "site-context" else None
        diagnostics.emit({
            "type": "api_request_finished",
            "case_id": case["case_id"],
            "endpoint": entry["endpoint"],
            "method": entry["method"],
            "status_code": entry["status_code"],
            "request_finished": True,
            "request_failed": False,
            "body_json_valid": entry["body_json_valid"],
            "source_identity": identity,
        })
        checkpoint()

    def on_request_failed(request: Any) -> None:
        pair = find_live_request(request)
        if pair is None:
            return
        entry = pair["entry"]
        entry["failed"] = True
        entry["failure"] = redact_text(str(request.failure or "unknown"))
        diagnostics.emit({
            "type": "api_request_failed",
            "case_id": case["case_id"],
            "endpoint": entry["endpoint"],
            "method": entry["method"],
            "status_code": entry["status_code"],
            "request_finished": False,
            "request_failed": True,
            "failure": entry["failure"],
        })
        checkpoint()

    page.on("request", on_api_request)
    page.on("response", on_api_response)
    page.on("requestfinished", on_request_finished)
    page.on("requestfailed", on_request_failed)
    page.on(
        "requestfailed",
        lambda request: diagnostics.emit(
            {
                "type": "request_failed",
                "case_id": case["case_id"],
                "phase": active_phase["name"],
                "resource_type": request.resource_type,
                "url": sanitize_url(request.url),
                "failure": redact_text(str(request.failure or "unknown")),
            }
        ),
    )
    page.on(
        "console",
        lambda message: diagnostics.emit(
            {
                "type": "console",
                "case_id": case["case_id"],
                "phase": active_phase["name"],
                "level": message.type,
                "message": redact_text(message.text),
            }
        ),
    )
    page.on(
        "pageerror",
        lambda error: _record_failure(
            case,
            diagnostics,
            checkpoint,
            f"uncaught page error: {redact_text(str(error))}",
            phase=active_phase["name"] if active_phase["name"] in case["phases"] else None,
        ),
    )
    page.on(
        "websocket",
        lambda socket: diagnostics.emit(
            {
                "type": "websocket",
                "case_id": case["case_id"],
                "phase": active_phase["name"],
                "url": sanitize_url(socket.url),
            }
        ),
    )


def _api_endpoint_kind(raw_url: str) -> str | None:
    try:
        path = urlsplit(raw_url).path.rstrip("/")
    except ValueError:
        return None
    if re.fullmatch(r"/api/v1/projects/[^/]+/site-context", path):
        return "site-context"
    if re.fullmatch(r"/api/v1/projects/[^/]+/site-intelligence", path):
        return "site-intelligence"
    return None


def _safe_context_identity(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    area = payload.get("study_area")
    area = area if isinstance(area, Mapping) else {}
    workspace = payload.get("current_workspace")
    workspace = workspace if isinstance(workspace, Mapping) else {}
    return {
        "project_id": payload.get("project_id") if _usable_identity(payload.get("project_id")) else None,
        "source_integrity_status": payload.get("source_integrity_status"),
        "study_area_id": area.get("id") if _usable_identity(area.get("id")) else None,
        "study_area_revision": _integer_value(area.get("revision")),
        "study_area_status": area.get("status"),
        "workspace_id": workspace.get("workspace_id") if _usable_identity(workspace.get("workspace_id")) else None,
        "workspace_project_id": workspace.get("project_id"),
        "workspace_study_area_id": workspace.get("study_area_id"),
        "workspace_revision": _integer_value(workspace.get("revision")),
    }


def _run_case(
    browser: Any,
    target_url: str,
    output_dir: Path,
    case: dict[str, Any],
    diagnostics: DiagnosticLog,
    checkpoint: Any,
) -> None:
    context = None
    page = None
    active_phase = {"name": "navigation"}
    api_tracker: dict[str, Any] = {
        "live_requests": [],
        "responses": {},
        "site_context_request": None,
        "site_context_payload": None,
    }

    def unauthorized_request(raw_url: str, kind: str) -> None:
        entry = {"kind": kind, "url": sanitize_url(raw_url)}
        case["unauthorized_requests"].append(entry)
        _record_failure(
            case,
            diagnostics,
            checkpoint,
            f"page attempted request outside loopback 8940-8949 allowlist ({kind}): {entry['url']}",
            phase=active_phase["name"] if active_phase["name"] in case["phases"] else None,
        )

    try:
        context = browser.new_context(
            viewport={"width": case["width"], "height": case["height"]},
            service_workers="block",
        )
        context.set_default_timeout(8000)
        context.route("**/*", lambda route: _route_request(route, unauthorized_request))
        route_web_socket = getattr(context, "route_web_socket", None)
        if not callable(route_web_socket):
            raise RunnerBlocked("Playwright BrowserContext.route_web_socket is required to enforce the network allowlist")

        route_web_socket("**/*", lambda socket_route: _route_websocket(socket_route, unauthorized_request))
        context.on(
            "page",
            lambda candidate: _attach_page_diagnostics(
                candidate, case, active_phase, diagnostics, checkpoint, api_tracker
            ),
        )
        page = context.new_page()

        try:
            response = page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
        except Exception as exc:
            blocked = _connection_refused(exc) and not case["unauthorized_requests"]
            _record_failure(
                case,
                diagnostics,
                checkpoint,
                f"application navigation failed: {redact_text(str(exc))}",
                status="BLOCKED" if blocked else "FAIL",
            )
            _try_diagnostic_screenshot(page, output_dir, case, "navigation-failure", diagnostics)
            return
        if response is not None and response.status >= 400:
            _record_failure(
                case,
                diagnostics,
                checkpoint,
                f"application returned HTTP {response.status} for the local page",
            )
            _try_diagnostic_screenshot(page, output_dir, case, "http-failure", diagnostics)
            return

        try:
            page.locator(".design-shell").wait_for(state="visible", timeout=15000)
        except Exception as exc:
            _record_failure(case, diagnostics, checkpoint, f"application shell did not become visible: {exc}")
            _try_diagnostic_screenshot(page, output_dir, case, "shell-not-ready", diagnostics)
            return

        if not _verify_language(page, case, diagnostics, checkpoint):
            _try_diagnostic_screenshot(page, output_dir, case, "language-failure", diagnostics)
            return

        active_phase["name"] = "readiness"
        site_tab = page.locator("#stage-site")
        try:
            site_tab.wait_for(state="visible", timeout=8000)
            if site_tab.get_attribute("aria-current") != "step":
                site_tab.click(timeout=5000)
                page.wait_for_function(
                    "() => document.querySelector('#stage-site')?.getAttribute('aria-current') === 'step'",
                    timeout=5000,
                )
        except Exception as exc:
            diagnostics.emit({
                "type": "readiness_site_stage_error",
                "case_id": case["case_id"],
                "message": redact_text(str(exc)),
            })
        try:
            view_2d = page.locator("#shell-view-2d")
            view_2d.wait_for(state="visible", timeout=8000)
            if view_2d.get_attribute("aria-pressed") != "true":
                view_2d.click(timeout=5000)
                page.wait_for_function(
                    "() => document.querySelector('#shell-view-2d')?.getAttribute('aria-pressed') === 'true'",
                    timeout=5000,
                )
        except Exception as exc:
            diagnostics.emit({
                "type": "readiness_2d_view_error",
                "case_id": case["case_id"],
                "message": redact_text(str(exc)),
            })

        completion_observation = _wait_for_site_context_completion(page, api_tracker)

        terminal_wait_error = None
        try:
            page.wait_for_function(
                """() => {
                  const text = document.querySelector('.shell-statusbar > span:nth-child(4)')?.textContent || '';
                  return /READY|ERROR|就緒|錯誤/u.test(text);
                }""",
                timeout=20000,
            )
        except Exception as exc:
            terminal_wait_error = redact_text(str(exc))
        source_context = api_tracker.get("site_context_payload")
        projection_expectation = _source_projection_expectation(source_context, case["language"])
        if projection_expectation is None:
            source_projection_wait = {"status": "NOT_APPLICABLE", "error": None}
        else:
            projection_wait_error = _wait_for_source_bound_projection(page, projection_expectation)
            source_projection_wait = {
                "status": "TIMEOUT" if projection_wait_error else "MATCHED",
                "error": projection_wait_error,
            }

        measured_readiness = _snapshot(page)
        readiness_projection = measured_readiness.get("readiness_projection")
        if not isinstance(readiness_projection, Mapping):
            readiness_projection = {}
        readiness_projection = dict(readiness_projection)
        readiness_projection["source_projection_wait_matched"] = source_projection_wait["status"] == "MATCHED"
        context_request = api_tracker.get("site_context_request")
        lifecycle = context_request if isinstance(context_request, Mapping) else {}
        readiness = assess_ui_readiness(
            request_lifecycle=lifecycle,
            source_context=source_context,
            ui_projection=readiness_projection,
        )
        readiness["terminal_state_wait_error"] = terminal_wait_error
        readiness["request_completion_observation"] = completion_observation
        readiness["source_projection_wait"] = source_projection_wait
        case["readiness"] = readiness
        diagnostics.emit({
            "type": "ui_readiness_assessed",
            "case_id": case["case_id"],
            "status": readiness["status"],
            "binding_source": readiness["binding_source"],
            "identity": readiness["identity"],
            "source_counts": readiness["source_counts"],
            "rendered_projection": readiness["rendered_projection"],
            "checks": readiness["checks"],
            "site_context_request": lifecycle,
            "request_completion_observation": completion_observation,
            "source_projection_wait": source_projection_wait,
            "terminal_state_wait_error": terminal_wait_error,
        })
        checkpoint()
        if readiness["status"] != "PASS":
            failed_checks = [name for name, passed in readiness["checks"].items() if not passed]
            _record_failure(
                case,
                diagnostics,
                checkpoint,
                f"read-only site-context projection did not reach source-bound readiness: {', '.join(failed_checks) or 'authority wait incomplete'}",
                status=readiness["status"],
            )
            _capture_readiness_diagnostics(page, output_dir, case, diagnostics)
            for phase_record in case["phases"].values():
                phase_record["status"] = readiness["status"]
                phase_record.setdefault("failures", []).append({
                    "status": readiness["status"],
                    "phase": None,
                    "message": "measurement phase did not run because source-bound readiness failed",
                })
            case["status"] = readiness["status"]
            diagnostics.emit({
                "type": "case_completed",
                "case_id": case["case_id"],
                "status": case["status"],
                "readiness_status": readiness["status"],
                "measurement_phases": "NOT_RUN",
            })
            checkpoint()
            return

        active_phase["name"] = "before"
        measurement_toggle = page.locator("#btn-measure-distance")
        try:
            measurement_toggle.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            _record_failure(case, diagnostics, checkpoint, f"measure-distance control was unavailable: {exc}")
            _try_diagnostic_screenshot(page, output_dir, case, "measure-control-missing", diagnostics)
            return

        baseline: Mapping[str, Any] | None = None
        expected_pressed = {"before": "false", "on": "true", "off": "false"}
        for phase in PHASES:
            active_phase["name"] = phase
            phase_record = case["phases"][phase]
            expected = expected_pressed[phase]
            try:
                action = measurement_phase_action(phase, case["language"])
                phase_record["interaction"] = action
                observed = measurement_toggle.get_attribute("aria-pressed")
                if phase == "before" and observed != expected:
                    _record_failure(
                        case,
                        diagnostics,
                        checkpoint,
                        f"initial measure toggle state was {observed!r}, expected {expected!r}",
                        phase=phase,
                    )
                elif phase == "off" and observed != "true":
                    _record_failure(
                        case,
                        diagnostics,
                        checkpoint,
                        f"active measurement was not open before Cancel control: state was {observed!r}",
                        phase=phase,
                    )
                elif phase != "before" and observed != expected:
                    _transition_measurement(page, phase, case["language"])
            except Exception as exc:
                _record_failure(
                    case,
                    diagnostics,
                    checkpoint,
                    f"measure toggle did not reach {phase} state: {exc}",
                    phase=phase,
                )

            screenshot = None
            try:
                screenshot = _capture_screenshot(page, output_dir, case, phase, diagnostics)
            except Exception as exc:
                _record_failure(
                    case,
                    diagnostics,
                    checkpoint,
                    f"{phase} screenshot could not be saved as an actual PNG: {exc}",
                    phase=phase,
                )

            try:
                measured = _snapshot(page)
                phase_record["measurements"] = measured
                if phase == "before":
                    baseline = measured
                assessment = assess_snapshot(
                    measured,
                    baseline=None if phase == "before" else baseline,
                    expected_width=case["width"],
                    expected_height=case["height"],
                )
                checks = dict(assessment["checks"])
                checks["language_matches_case"] = measured.get("language") == case["language"]
                checks["measurement_toggle_state"] = measured.get("measurement_pressed") == expected
                checks["actual_screenshot_saved"] = screenshot is not None
                checks["source_bound_readiness"] = case.get("readiness", {}).get("status") == "PASS"
                if phase != "before":
                    checks["baseline_measurement_available"] = baseline is not None
                phase_record["checks"] = checks
                diagnostics.emit(
                    {
                        "type": "phase_measurement",
                        "case_id": case["case_id"],
                        "phase": phase,
                        "measurements": measured,
                        "gate_checks": checks,
                        "diagnostics": assessment["diagnostics"],
                    }
                )
                if all(value is not False for value in checks.values()) and all(
                    value is True for key, value in checks.items() if key != "viewport_matches_request" and value is not None
                ):
                    if phase_record["status"] != "FAIL":
                        phase_record["status"] = "PASS"
                else:
                    phase_record["status"] = "FAIL"
                    failed_checks = [key for key, value in checks.items() if value is False]
                    _record_failure(
                        case,
                        diagnostics,
                        checkpoint,
                        f"{phase} gate checks failed: {', '.join(failed_checks)}",
                        phase=phase,
                    )
            except Exception as exc:
                _record_failure(
                    case,
                    diagnostics,
                    checkpoint,
                    f"{phase} measurement failed: {exc}",
                    phase=phase,
                )
            checkpoint()
        case["status"] = _case_status(case)
        diagnostics.emit({"type": "case_completed", "case_id": case["case_id"], "status": case["status"]})
        checkpoint()
    except RunnerBlocked as exc:
        _record_failure(case, diagnostics, checkpoint, str(exc), status="BLOCKED")
        _try_diagnostic_screenshot(page, output_dir, case, "runner-blocked", diagnostics)
    except Exception as exc:
        _record_failure(case, diagnostics, checkpoint, f"unexpected runner failure: {exc}")
        _try_diagnostic_screenshot(page, output_dir, case, "runner-failure", diagnostics)
    finally:
        if context is not None:
            try:
                context.close()
            except Exception as exc:
                diagnostics.emit(
                    {"type": "context_close_failure", "case_id": case["case_id"], "message": redact_text(str(exc))}
                )
        case["status"] = _case_status(case)
        checkpoint()


def _route_request(route: Any, unauthorized_request: Any) -> None:
    raw_url = route.request.url
    try:
        validate_target(raw_url)
    except ValueError:
        unauthorized_request(raw_url, "http")
        route.abort("blockedbyclient")
        return
    if str(route.request.method).upper() not in {"GET", "HEAD", "OPTIONS"}:
        unauthorized_request(raw_url, "http_method")
        route.abort("blockedbyclient")
        return
    route.continue_()


def _try_diagnostic_screenshot(
    page: Any, output_dir: Path, case: dict[str, Any], name: str, diagnostics: DiagnosticLog
) -> None:
    if page is None:
        return
    try:
        _capture_screenshot(page, output_dir, case, name, diagnostics)
    except Exception as exc:
        diagnostics.emit(
            {
                "type": "diagnostic_screenshot_failure",
                "case_id": case["case_id"],
                "phase": name,
                "message": redact_text(str(exc)),
            }
        )


def _create_output_directory(path: Path) -> Path:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=False)
    return destination


def _mark_browser_blocked(record: dict[str, Any], diagnostics: DiagnosticLog, checkpoint: Any, reason: str) -> None:
    _mark_pending_blocked(record, diagnostics, checkpoint, reason)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="already-running local app URL on ports 8940-8949")
    parser.add_argument("--output", required=True, type=Path, help="new, exclusive evidence directory")
    args = parser.parse_args(argv)

    try:
        output_dir = _create_output_directory(args.output)
    except FileExistsError:
        parser.error("output directory already exists; preserve prior evidence and choose a new path")
    except OSError as exc:
        parser.error(f"cannot create exclusive output directory: {redact_text(str(exc))}")

    record = new_run_record(args.url)
    diagnostics = DiagnosticLog(output_dir / "diagnostics.jsonl")
    checkpoint = lambda: _checkpoint(output_dir, record)
    checkpoint()
    diagnostics.emit(
        {
            "type": "run_started",
            "record_format": record["record_format"],
            "requested_target": record["requested_target"],
            "required_case_ids": [case["case_id"] for case in record["cases"]],
        }
    )
    try:
        try:
            validate_target(args.url)
        except ValueError as exc:
            record["run_failures"].append({"status": "FAIL", "message": redact_text(str(exc))})
            diagnostics.emit({"type": "target_rejected", "status": "FAIL", "message": str(exc)})
            checkpoint()
            return 1

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            _mark_browser_blocked(
                record,
                diagnostics,
                checkpoint,
                f"Playwright runtime is unavailable: {redact_text(str(exc))}",
            )
            return 1

        try:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch(
                        headless=True,
                        executable_path=CHROME_EXECUTABLE,
                        args=[
                            "--no-sandbox",
                            "--disable-background-networking",
                            "--disable-component-update",
                            "--disable-sync",
                            "--disable-default-apps",
                            "--disable-extensions",
                            "--no-first-run",
                        ],
                    )
                except Exception as exc:
                    _mark_browser_blocked(
                        record,
                        diagnostics,
                        checkpoint,
                        f"local Chromium runtime could not launch: {redact_text(str(exc))}",
                    )
                    return 1
                try:
                    for case in record["cases"]:
                        _run_case(browser, args.url, output_dir, case, diagnostics, checkpoint)
                finally:
                    try:
                        browser.close()
                    except Exception as exc:
                        record["run_failures"].append(
                            {"status": "FAIL", "message": f"browser close failed: {redact_text(str(exc))}"}
                        )
                        diagnostics.emit(
                            {"type": "browser_close_failure", "message": redact_text(str(exc))}
                        )
        except Exception as exc:
            record["run_failures"].append(
                {"status": "FAIL", "message": f"browser session failed: {redact_text(str(exc))}"}
            )
            diagnostics.emit(
                {"type": "browser_session_failure", "status": "FAIL", "message": redact_text(str(exc))}
            )
            for case in record["cases"]:
                if case["status"] == "NOT_RUN":
                    case["status"] = "BLOCKED"
                    case["failures"].append(
                        {"status": "BLOCKED", "phase": None, "message": "browser session ended before case ran"}
                    )
            checkpoint()
            return 1
    finally:
        diagnostics.close()
        record["diagnostics_sha256"] = _sha256_file(output_dir / "diagnostics.jsonl")
        record["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        checkpoint()

    return 0 if all(case["status"] == "PASS" for case in record["cases"]) and not record["run_failures"] else 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
