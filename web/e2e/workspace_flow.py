"""Real-browser Week 4 workspace flow against an isolated SQLite copy."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import struct
import sys
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from datetime import datetime, timezone
import hashlib
import argparse
import sys

from playwright.sync_api import sync_playwright
from shapely.geometry import Polygon, box as shapely_box, shape


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from urban_design.e2e_ports import resolve_e2e_ports
from urban_design.e2e_outputs import describe_output_path, require_new_report_path, resolve_e2e_output_directory

PROJECT_ID = "rotterdam-m4h-pilot-project"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
DEFAULT_OUTPUT_ROOT = ROOT / "artifacts/week4-repair-r04/browser"


def request_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=4) as response:
        return json.load(response)


def database_summary(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"disposable SQLite backup was not created: {path}")
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA query_only=ON")
    try:
        return {
            "ledger_event_count": connection.execute("SELECT count(*) FROM ledger_events").fetchone()[0],
            "state_version_count": connection.execute("SELECT count(*) FROM state_versions").fetchone()[0],
            "workspace_revisions": connection.execute(
                "SELECT entity_id,current_revision FROM state_heads WHERE entity_type='WorkspaceRevision' ORDER BY entity_id"
            ).fetchall(),
        }
    finally:
        connection.close()


def wait_for(url: str, process: subprocess.Popen, log_path: Path, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited ({process.returncode}): {log_path.read_text(errors='replace')}")
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    raise TimeoutError(f"timed out waiting for {url}: {log_path.read_text(errors='replace')}")


def point_in_ring(point: tuple[float, float], ring: list[list[float]]) -> bool:
    x, y = point
    inside = False
    for i, current in enumerate(ring):
        previous = ring[i - 1]
        if (current[1] > y) != (previous[1] > y):
            crossing_x = (previous[0] - current[0]) * (y - current[1]) / (previous[1] - current[1]) + current[0]
            if x < crossing_x:
                inside = not inside
    return inside


def choose_test_polygon(geometry: dict) -> list[tuple[float, float]]:
    geometry_shape = shape(geometry)
    parts = list(geometry_shape.geoms) if geometry_shape.geom_type == "MultiPolygon" else [geometry_shape]
    for part in parts:
        for half_side in (40, 25, 12, 8, 5, 3, 1):
            interior = part.buffer(-(half_side + 10)).representative_point()
            cx, cy = interior.x, interior.y
            points = [
                (cx - half_side, cy - half_side),
                (cx + half_side, cy - half_side),
                (cx + half_side, cy + half_side),
                (cx - half_side, cy + half_side),
            ]
            rounded = [(round(x), round(y)) for x, y in points]
            if geometry_shape.covers(Polygon(rounded)):
                return rounded
    raise AssertionError("could not find a bounded non-default polygon inside the active StudyArea")


def choose_boundary_crossing_test_polygon(
    geometry: dict, *, zoom: float, canvas_width: float, canvas_height: float
) -> list[tuple[float, float]]:
    """Find a visible rectangle that crosses the true edge but fits the legacy fallback bounds."""
    study_area = shape(geometry)
    parts = list(study_area.geoms) if study_area.geom_type == "MultiPolygon" else [study_area]
    legacy_bounds = (88000.0, 91000.0, 435000.0, 438000.0)
    for part in parts:
        coordinates = list(part.exterior.coords)
        for first, second in zip(coordinates, coordinates[1:]):
            dx = second[0] - first[0]
            dy = second[1] - first[1]
            length = (dx * dx + dy * dy) ** 0.5
            if length == 0:
                continue
            midpoint = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
            for nx, ny in ((dy / length, -dx / length), (-dy / length, dx / length)):
                for offset in (2, 5, 10):
                    cx = midpoint[0] + nx * offset
                    cy = midpoint[1] + ny * offset
                    for half_side in (55, 65, 75):
                        candidate = shapely_box(cx - half_side, cy - half_side, cx + half_side, cy + half_side)
                        min_x, min_y, max_x, max_y = candidate.bounds
                        if not study_area.intersects(candidate) or study_area.covers(candidate):
                            continue
                        if not (
                            legacy_bounds[0] <= min_x <= max_x <= legacy_bounds[1]
                            and legacy_bounds[2] <= min_y <= max_y <= legacy_bounds[3]
                        ):
                            continue
                        points = [
                            (min_x, min_y),
                            (max_x, min_y),
                            (max_x, max_y),
                            (min_x, max_y),
                        ]
                        screen_points = [
                            (420 + (x - 89100.0) * zoom, 380 - (y - 435900.0) * zoom)
                            for x, y in points
                        ]
                        if all(5 <= x <= canvas_width - 5 and 5 <= y <= canvas_height - 5 for x, y in screen_points):
                            return points
    raise AssertionError("could not find a visible StudyArea-edge crossing inside the legacy rectangle")


def choose_single_building_selection_box(
    buildings: list[dict], *, zoom: float, canvas_width: float, canvas_height: float, excluded_ids: set[str]
) -> dict:
    """Choose a visible EPSG:28992 rectangle intersecting exactly one source building."""
    visible = []
    for building in buildings:
        geometry = shape(building["geometry"])
        point = geometry.representative_point()
        screen_x = 420 + (point.x - 89100.0) * zoom
        screen_y = 380 - (point.y - 435900.0) * zoom
        if 0 <= screen_x <= canvas_width and 0 <= screen_y <= canvas_height:
            visible.append((abs(screen_x - 420) + abs(screen_y - 380), building, point))

    for _, building, point in sorted(visible, key=lambda item: item[0]):
        if building["id"] in excluded_ids:
            continue
        for radius in (30, 20, 15, 12, 10.5):
            extent = shapely_box(point.x - radius, point.y - radius, point.x + radius, point.y + radius)
            matches = [candidate["id"] for candidate in buildings if shape(candidate["geometry"]).intersects(extent)]
            if matches != [building["id"]]:
                continue
            start_x = 420 + (extent.bounds[0] - 89100.0) * zoom
            end_x = 420 + (extent.bounds[2] - 89100.0) * zoom
            start_y = 380 - (extent.bounds[3] - 435900.0) * zoom
            end_y = 380 - (extent.bounds[1] - 435900.0) * zoom
            drag_distance = ((end_x - start_x) ** 2 + (end_y - start_y) ** 2) ** 0.5
            if drag_distance < 5 or start_x < 5 or start_y < 5 or end_x > canvas_width - 5 or end_y > canvas_height - 5:
                continue
            return {
                "feature_id": building["id"],
                "extent": extent.bounds,
                "screen_start": (start_x, start_y),
                "screen_end": (end_x, end_y),
            }
    raise AssertionError("could not find a visible map rectangle selecting exactly one BAG building")


def project_building_point_to_3d_screen(
    geometry: dict,
    *,
    canvas_width: float,
    canvas_height: float,
    origin_x: float = 89100.0,
    origin_y: float = 435900.0,
) -> tuple[float, float]:
    """Project an interior point with the 3D viewport's initial camera pose."""
    building_shape = shape(geometry)
    # Viewport3D currently extrudes the first polygon component from a
    # MultiPolygon; choose a point from that same visible component.
    if building_shape.geom_type == "MultiPolygon":
        building_shape = building_shape.geoms[0]
    point = building_shape.representative_point()
    local_x = point.x - origin_x
    local_y = point.y - origin_y
    local_z = 7.0
    radius = 750.0
    phi = math.pi / 3.5
    sin_phi = math.sin(phi)
    cos_phi = math.cos(phi)
    camera_depth = radius + local_y * sin_phi - local_z * cos_phi
    if camera_depth <= 0:
        raise AssertionError("building interior point is behind the initial 3D camera")

    tangent = math.tan(math.radians(45.0 / 2.0))
    aspect = canvas_width / canvas_height
    screen_x = canvas_width / 2.0 + local_x / (camera_depth * tangent * aspect) * canvas_width / 2.0
    screen_y = canvas_height / 2.0 - (local_y * cos_phi + local_z * sin_phi) / (camera_depth * tangent) * canvas_height / 2.0
    if not (0 <= screen_x <= canvas_width and 0 <= screen_y <= canvas_height):
        raise AssertionError("building interior point projects outside the visible 3D viewport")
    return screen_x, screen_y


def project_3d_point_to_screen(
    point: tuple[float, float],
    *,
    z: float,
    canvas_width: float,
    canvas_height: float,
    camera_radius: float = 750.0,
    ensure_visible: bool = True,
    origin_x: float = 89100.0,
    origin_y: float = 435900.0,
) -> tuple[float, float]:
    """Project an EPSG:28992 point using Viewport3D's initial camera pose."""
    local_x = point[0] - origin_x
    local_y = point[1] - origin_y
    phi = math.pi / 3.5
    sin_phi = math.sin(phi)
    cos_phi = math.cos(phi)
    camera_depth = camera_radius + local_y * sin_phi - z * cos_phi
    if camera_depth <= 0:
        raise AssertionError("3D point is behind the initial camera")

    tangent = math.tan(math.radians(45.0 / 2.0))
    aspect = canvas_width / canvas_height
    screen_x = canvas_width / 2.0 + local_x / (camera_depth * tangent * aspect) * canvas_width / 2.0
    screen_y = canvas_height / 2.0 - (local_y * cos_phi + z * sin_phi) / (camera_depth * tangent) * canvas_height / 2.0
    if ensure_visible and not (0 <= screen_x <= canvas_width and 0 <= screen_y <= canvas_height):
        raise AssertionError("3D point projects outside the visible viewport")
    return screen_x, screen_y


def choose_visible_road_selection(
    roads: list[dict],
    buildings: list[dict],
    *,
    canvas_width: float,
    canvas_height: float,
    camera_radius: float = 750.0,
) -> dict:
    """Choose a visible rendered road point with a unique projected ray."""
    building_shapes = [shape(item["geometry"]) for item in buildings]
    rendered_roads = roads[:500]
    road_parts: list[tuple[dict, list]] = []
    projected_parts: list[list[list[tuple[float, float]]]] = []
    for road in rendered_roads:
        road_shape = shape(road["geometry"])
        if road_shape.geom_type not in {"LineString", "MultiLineString"} or road_shape.is_empty or road_shape.length <= 0:
            continue
        lines = list(road_shape.geoms) if road_shape.geom_type == "MultiLineString" else [road_shape]
        projected_lines: list[list[tuple[float, float]]] = []
        for line in lines:
            projected_lines.append([
                project_3d_point_to_screen(
                    (x, y),
                    z=0.5,
                    canvas_width=canvas_width,
                    canvas_height=canvas_height,
                    camera_radius=camera_radius,
                    ensure_visible=False,
                )
                for x, y in line.coords
            ])
        road_parts.append((road, lines))
        projected_parts.append(projected_lines)

    def point_to_projected_segment_distance(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        if dx == 0 and dy == 0:
            return math.hypot(point[0] - start[0], point[1] - start[1])
        t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)))
        return math.hypot(point[0] - (start[0] + t * dx), point[1] - (start[1] + t * dy))

    candidates: list[tuple[float, float, dict, tuple[float, float], tuple[float, float]]] = []
    for road_index, (road, lines) in enumerate(road_parts):
        for line in lines:
            for fraction in (0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95):
                point = line.interpolate(line.length * fraction)
                point_xy = (point.x, point.y)
                if any(building.distance(point) <= 0.75 for building in building_shapes):
                    continue
                try:
                    screen = project_3d_point_to_screen(
                        point_xy,
                        z=0.5,
                        canvas_width=canvas_width,
                        canvas_height=canvas_height,
                        camera_radius=camera_radius,
                    )
                except AssertionError:
                    continue
                if not (0 <= screen[0] <= canvas_width and 0 <= screen[1] <= canvas_height):
                    continue
                nearest_other_road = float("inf")
                for other_index, other_lines in enumerate(projected_parts):
                    if other_index == road_index:
                        continue
                    for projected_line in other_lines:
                        for start, end in zip(projected_line, projected_line[1:]):
                            nearest_other_road = min(
                                nearest_other_road,
                                point_to_projected_segment_distance(screen, start, end),
                            )
                if nearest_other_road < 20:
                    continue
                center_distance = abs(screen[0] - canvas_width / 2.0) + abs(screen[1] - canvas_height / 2.0)
                candidates.append((nearest_other_road, center_distance, road, point_xy, screen))

    if not candidates:
        raise AssertionError("could not find a visible rendered source road point with a unique projected ray")
    _, _, road, point, screen = max(candidates, key=lambda item: (item[0], -item[1]))
    return {"feature_id": road["id"], "point": point, "screen": screen}


def click_feature_action(page, button_id: str) -> None:
    locator = page.locator(f'[id="{button_id}"]')
    locator.scroll_into_view_if_needed()
    locator.click()


def run(
    *,
    api_port: int | None = None,
    web_port: int | None = None,
    output_dir: Path | None = None,
    database_path: Path | None = None,
    source_db_path: Path | None = None,
    source_package_root: Path | None = None,
    python_executable: Path | None = None,
    drop_first_sync_response: bool = False,
    drop_first_sync_before_commit: bool = False,
) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    if drop_first_sync_response and drop_first_sync_before_commit:
        raise ValueError("select only one first-sync response-loss mode")
    inject_sync_response_loss = drop_first_sync_response or drop_first_sync_before_commit
    outside_zone_rejection: dict[str, object] | None = None
    dirty_figure_export_guard = {
        "map_disabled_with_unsaved_changes": False,
        "schematic_3d_disabled_with_unsaved_changes": False,
    }
    fresh_browser_reload_verified = False
    zone_edit_verified = False
    zone_edit_record: dict[str, Any] | None = None
    cross_view_building_selection_verified = False
    cross_view_road_selection_verified = False
    zoomed_3d_road_selection_verified = False
    measurement_record: dict[str, Any] | None = None
    if not CHROME.is_file():
        raise RuntimeError(f"Google Chrome executable is missing: {CHROME}")
    if database_path is not None and source_db_path is not None:
        if database_path.expanduser().resolve() != source_db_path.expanduser().resolve():
            raise ValueError("database_path and source_db_path must identify the same SQLite seed")
    source_db = (source_db_path or database_path or ROOT / ".urban_design_runtime/state.sqlite3").expanduser().resolve()
    if not source_db.is_file():
        raise RuntimeError(f"SQLite seed database is missing: {source_db}")
    server_python = (python_executable or (ROOT / ".venv/bin/python")).expanduser().resolve()
    if not server_python.is_file():
        raise RuntimeError(f"workspace server Python executable is missing: {server_python}")
    source_package = (source_package_root or (
        ROOT / "artifacts/milestone2-analysis-inputs-rotterdam-m4h/"
        "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01"
    )).expanduser().resolve()
    if not source_package.is_dir():
        raise RuntimeError(f"verified source package directory is missing: {source_package}")

    api_port, web_port = resolve_e2e_ports(api_port, web_port)
    api_base = f"http://127.0.0.1:{api_port}"
    web_base = f"http://127.0.0.1:{web_port}"
    if output_dir is None:
        run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output_dir = DEFAULT_OUTPUT_ROOT / f"run-{run_stamp}"
    output_dir, output_descriptor = resolve_e2e_output_directory(output_dir, project_root=ROOT)
    output_dir.mkdir(parents=True, exist_ok=False)
    live_db_hash_before = hashlib.sha256(source_db.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="week4-r03-e2e-", dir="/private/tmp") as temporary:
        screenshot_dir = output_dir
        tmp = Path(temporary)
        db_path = tmp / "state.sqlite3"
        readonly = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
        disposable = sqlite3.connect(db_path)
        try:
            readonly.backup(disposable)
        finally:
            disposable.close()
            readonly.close()
        disposable_before = database_summary(db_path)

        api_log = tmp / "api.log"
        web_log = tmp / "web.log"
        api_output = api_log.open("w")
        web_output = web_log.open("w")
        environment = os.environ.copy()
        environment.update({
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT / "src"),
        })
        api_process = subprocess.Popen(
            [str(server_python), str(ROOT / "scripts/run_workspace_server.py"),
             "--host", "127.0.0.1", "--port", str(api_port), "--database", str(db_path),
             "--source-package-root", str(source_package)],
            cwd=ROOT, env=environment, stdout=api_output, stderr=subprocess.STDOUT,
        )
        web_environment = environment.copy()
        web_environment.update({
            "VITE_API_BASE": api_base,
            "VITE_PROJECT_ID": PROJECT_ID,
            "VITE_URBAN_DESIGN_ACTOR_KIND": "AGENT_AUTOMATION",
        })
        web_process = None
        browser = None
        try:
            wait_for(f"{api_base}/health", api_process, api_log)
            web_process = subprocess.Popen(
                ["npm", "--prefix", str(ROOT / "web"), "run", "dev", "--", "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"],
                cwd=ROOT, env=web_environment, stdout=web_output, stderr=subprocess.STDOUT,
            )
            wait_for(web_base, web_process, web_log)
            context = request_json(f"{api_base}/api/v1/projects/{PROJECT_ID}/site-context")
            if context.get("source_integrity_status") != "VERIFIED":
                raise AssertionError("API did not report verified spatial-r01 source integrity")
            if context.get("evidence_cards_status") != "VERIFIED_SOURCE_RESULT_ALIGNMENT":
                raise AssertionError("API did not report same-version source-aligned Evidence Cards")
            if len(context.get("evidence_cards", [])) < 4:
                raise AssertionError("API returned fewer than four verified observational cards")
            if not all(card.get("source_artifact_ids") and card.get("dataset_snapshot_ids") for card in context["evidence_cards"]):
                raise AssertionError("an Evidence Card has no verified Artifact or DatasetSnapshot parents")
            road_card = next(
                (card for card in context["evidence_cards"] if card.get("metric_key") == "osm_highway_unique_centerline_length"),
                None,
            )
            if road_card is None:
                raise AssertionError("site-context did not return the R04 unique-centerline Evidence Card")
            usage_card = next(
                (card for card in context["evidence_cards"] if card.get("metric_key") == "bag_registered_gebruiksdoel_features"),
                None,
            )
            residual_card = next(
                (card for card in context["evidence_cards"] if card.get("metric_key") == "unclassified_surface_residual_area"),
                None,
            )
            if usage_card is None or residual_card is None:
                raise AssertionError("site-context omitted one or more source-scoped site analysis cards")
            if usage_card.get("value") != 31 or usage_card.get("unit") != "features":
                raise AssertionError("BAG registered-use summary differs from the verified current R04 API result")
            if not all(usage_card.get(key) for key in ("source_artifact_ids", "dataset_snapshot_ids", "input_sha256", "output_sha256")):
                raise AssertionError("BAG registered-use summary lacks its provenance/hash contract")
            if not any("not a complete land-use inventory" in str(item).lower() for item in usage_card.get("limitations", [])):
                raise AssertionError("BAG registered-use summary does not state its inventory limitation")
            residual_limitations = " ".join(str(item).lower() for item in residual_card.get("limitations", []))
            if not all(phrase in residual_limitations for phrase in ("not open space", "does not establish public access", "legal buildability")):
                raise AssertionError("surface residual limitations do not prevent open-space, access, and buildability overclaims")
            if residual_card.get("unit") != "m²" or not all(
                residual_card.get(key) for key in ("source_artifact_ids", "dataset_snapshot_ids", "input_sha256", "output_sha256")
            ):
                raise AssertionError("surface residual summary lacks its unit or provenance/hash contract")
            if context.get("syntax_layers_status") != "EXPLORATORY_CANDIDATE":
                raise AssertionError("API did not report the persisted Syntax candidate status")
            computed_syntax = context.get("syntax_layers", [])
            planned_syntax = context.get("syntax_layer_plan", [])
            if len(computed_syntax) != 6 or any(layer.get("formal_result_eligible") is not False for layer in computed_syntax):
                raise AssertionError("API must return all six planned layers without formal-result eligibility")
            computed_radii = {layer.get("radius_m") for layer in computed_syntax if layer.get("calculation_status") == "COMPUTED"}
            if computed_radii != {800, 2000}:
                raise AssertionError(f"expected computed 800 m and 2 km results, found radii {sorted(computed_radii)}")
            withheld = [layer for layer in computed_syntax if layer.get("calculation_status") == "NOT_COMPUTED_RUNTIME_BUDGET"]
            if len(withheld) != 2 or any(layer.get("radius_m") != 10000 or layer.get("segment_values") for layer in withheld):
                raise AssertionError("10 km layers must be withheld with no metric values")
            if any(layer.get("statistics") is not None for layer in withheld):
                raise AssertionError("10 km layers must not expose zero-valued statistics")
            if not context.get("source_snapshot_ids"):
                raise AssertionError("site-context returned no verified source snapshots")
            if not context.get("buildings") or not context.get("roads"):
                raise AssertionError("site-context returned no source-backed building or road features")

            history_url = f"{api_base}/api/v1/workspaces/workspace-{PROJECT_ID}/history"
            initial_history = request_json(history_url)
            initial_history_by_revision = {item["revision"]: item for item in initial_history}

            building_id = context["buildings"][0]["id"]
            undecided_building_id = context["buildings"][1]["id"]
            road_id = context["roads"][0]["id"]
            initial_revision = (context.get("current_workspace") or {}).get("revision", 0)
            initial_zone_count = len(((context.get("current_workspace") or {}).get("spatial_brief") or {}).get("zones", []))
            polygon = choose_test_polygon(context["study_area"]["geometry"])
            browser_version = ""
            page_errors: list[str] = []
            sidebar_tab_clicks: list[str] = []
            preserved_unlock_confirmation_verified = False
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME), args=["--no-sandbox"])
                browser_version = browser.version
                page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                blocked_external_requests: list[str] = []
                non_local_font_requests: list[str] = []
                browser_api_targets: list[str] = []
                unexpected_browser_api_targets: list[str] = []
                browser_api_responses: list[dict[str, Any]] = []
                browser_request_failures: list[dict[str, str | None]] = []
                browser_console_errors: list[str] = []
                sync_dispatches: list[dict[str, Any]] = []
                dropped_sync_response: dict[str, Any] | None = None

                def local_only(route) -> None:
                    nonlocal dropped_sync_response
                    parsed_url = urlsplit(route.request.url)
                    hostname = parsed_url.hostname
                    if hostname not in {"127.0.0.1", "localhost"}:
                        blocked_external_requests.append(route.request.url)
                        if route.request.resource_type == "font":
                            non_local_font_requests.append(route.request.url)
                        route.abort()
                    elif parsed_url.path.startswith("/api/"):
                        default_port = 443 if parsed_url.scheme == "https" else 80
                        target_port = parsed_url.port or default_port
                        target = f"{parsed_url.scheme}://{hostname}:{target_port}{parsed_url.path}"
                        browser_api_targets.append(target)
                        if parsed_url.port != api_port:
                            unexpected_browser_api_targets.append(target)
                            route.abort()
                        elif parsed_url.path == "/api/v1/workspaces/sync" and route.request.method == "POST":
                            payload = json.loads(route.request.post_data or "{}")
                            if payload.get("actor_kind") != "AGENT_AUTOMATION" or not payload.get("actor_session_id"):
                                raise AssertionError("browser sync did not identify agent automation provenance")
                            key = payload.get("idempotency_key")
                            sync_dispatches.append({
                                "ordinal": len(sync_dispatches) + 1,
                                "idempotency_key_sha256": hashlib.sha256(str(key).encode()).hexdigest(),
                                "actor_kind": payload["actor_kind"],
                            })
                            if inject_sync_response_loss and len(sync_dispatches) == 1:
                                if drop_first_sync_before_commit:
                                    dropped_sync_response = {"status": None, "body": None}
                                else:
                                    server_response = route.fetch()
                                    dropped_sync_response = {
                                        "status": server_response.status,
                                        "body": server_response.json(),
                                    }
                                route.abort(error_code="failed")
                            else:
                                route.continue_()
                        else:
                            route.continue_()
                    else:
                        route.continue_()

                page.route("**/*", local_only)
                page.on(
                    "response",
                    lambda response: browser_api_responses.append({
                        "url": response.url,
                        "status": response.status,
                        **({"failure_body": response.text()} if response.status >= 400 else {}),
                    })
                    if urlsplit(response.url).path.startswith("/api/") else None,
                )
                page.on(
                    "requestfailed",
                    lambda request: browser_request_failures.append({
                        "url": request.url,
                        "failure": request.failure,
                    }),
                )
                page.on("console", lambda message: browser_console_errors.append(message.text) if message.type == "error" else None)
                page.goto(web_base, wait_until="networkidle")
                if unexpected_browser_api_targets:
                    raise AssertionError(
                        f"browser called an API outside this launch-scoped server on port {api_port}: {unexpected_browser_api_targets}"
                    )
                if non_local_font_requests:
                    raise AssertionError(f"browser attempted non-local font requests: {non_local_font_requests}")
                try:
                    page.locator("#badge-study-area-status").get_by_text("CONFIRMED_FOR_EXPLORATION").wait_for(timeout=15_000)
                except Exception:
                    print(json.dumps({
                        "browser_load_diagnostics": {
                            "api_port": api_port,
                            "api_targets": browser_api_targets,
                            "unexpected_api_targets": unexpected_browser_api_targets,
                            "api_responses": browser_api_responses,
                            "request_failures": browser_request_failures,
                            "console_errors": browser_console_errors,
                            "page_errors": page_errors,
                        },
                    }, sort_keys=True, indent=2))
                    raise
                rendered_usage_card = page.locator(f'[id="card-{usage_card["card_id"]}"]')
                rendered_residual_card = page.locator(f'[id="card-{residual_card["card_id"]}"]')
                rendered_usage_card.wait_for(state="visible")
                rendered_residual_card.wait_for(state="visible")
                usage_rendered_value = page.evaluate("value => value.toLocaleString()", usage_card["value"])
                residual_rendered_value = page.evaluate("value => value.toLocaleString()", residual_card["value"])
                usage_card_text = rendered_usage_card.inner_text()
                residual_card_text = rendered_residual_card.inner_text()
                if usage_card["metric_name"] not in usage_card_text or usage_rendered_value not in usage_card_text:
                    raise AssertionError("browser did not render the BAG registered-use Evidence Card and value")
                if "not a complete land-use inventory" not in usage_card_text.lower():
                    raise AssertionError("browser omitted the BAG registered-use inventory limitation")
                if residual_rendered_value not in residual_card_text or "not open space" not in residual_card_text.lower():
                    raise AssertionError("browser did not render the bounded surface residual and its limitation")
                if "does not establish public access" not in residual_card_text.lower():
                    raise AssertionError("browser omitted the surface residual access limitation")
                if not page.locator("#status-authority").get_by_text("In Sync", exact=False).count() and initial_revision:
                    raise AssertionError("existing server workspace did not display authoritative status")

                canvas = page.locator("#canvas-viewport-2d")
                canvas_box = canvas.bounding_box()
                if canvas_box is None:
                    raise AssertionError("2D map canvas is not visible")
                zoom = 0.9
                pan_x = 420.0
                pan_y = 380.0
                easting_anchor = 89100.0
                northing_anchor = 435900.0
                measurable_roads: list[tuple[int, float, dict[str, Any], list[list[float]], list[tuple[float, float]]]] = []
                for candidate_road in context["roads"]:
                    coordinates = candidate_road.get("geometry", {}).get("coordinates", [])
                    if len(coordinates) < 2:
                        continue
                    screen_points = [
                        (
                            pan_x + (float(point[0]) - easting_anchor) * zoom,
                            pan_y - (float(point[1]) - northing_anchor) * zoom,
                        )
                        for point in coordinates
                    ]
                    if not all(
                        24 <= x <= canvas_box["width"] - 250
                        and 88 <= y <= canvas_box["height"] - 70
                        for x, y in screen_points
                    ):
                        continue
                    geometry_length = math.fsum(
                        math.hypot(
                            float(coordinates[index][0]) - float(coordinates[index - 1][0]),
                            float(coordinates[index][1]) - float(coordinates[index - 1][1]),
                        )
                        for index in range(1, len(coordinates))
                    )
                    backend_length = candidate_road.get("length_m")
                    if not isinstance(backend_length, (int, float)) or abs(geometry_length - float(backend_length)) > 0.01:
                        continue
                    measurable_roads.append((len(coordinates), geometry_length, candidate_road, coordinates, screen_points))
                if not measurable_roads:
                    raise AssertionError("no source road with a backend-consistent visible EPSG:28992 geometry is available for the browser measurement check")
                _, measured_road_length, measured_road, measured_road_coordinates, measured_road_screen_points = min(
                    measurable_roads,
                    key=lambda item: (item[0], -item[1]),
                )
                page.get_by_role("button", name="Measure distance").click()
                for screen_x, screen_y in measured_road_screen_points:
                    page.mouse.click(canvas_box["x"] + screen_x, canvas_box["y"] + screen_y)
                page.get_by_role("button", name="Finish measurement").click()
                measurement_status = page.get_by_role("status", name="Measurement result")
                measurement_status.wait_for(state="visible")
                rendered_measurement = measurement_status.inner_text()
                rendered_length_text = rendered_measurement.split("Length:", 1)[1].split("m", 1)[0].strip()
                rendered_measurement_length = float(rendered_length_text.replace(",", ""))
                if abs(rendered_measurement_length - measured_road_length) > 0.01:
                    raise AssertionError(
                        f"2D measurement differs from the backend EPSG:28992 road length: UI={rendered_measurement_length}, backend={measured_road_length}"
                    )
                if page.locator("#canvas-viewport-2d").get_attribute("role") != "img":
                    raise AssertionError("2D map viewport is not exposed as an accessible image")
                scale_bar = page.get_by_test_id("scale-bar")
                scale_bar.wait_for(state="visible")
                scale_meters_per_pixel = float(scale_bar.get_attribute("data-meters-per-pixel") or "nan")
                if abs(scale_meters_per_pixel - (1.0 / zoom)) > 1e-6:
                    raise AssertionError("2D scale bar meters-per-pixel does not match the current projected transform")
                if page.get_by_label("Grid north indicator").count() != 1:
                    raise AssertionError("2D map does not show its projected grid-north indicator")
                measurement_record = {
                    "status": "PASS",
                    "source_road_id": measured_road["id"],
                    "geometry_length_m": measured_road_length,
                    "backend_length_m": float(measured_road["length_m"]),
                    "rendered_length_m": rendered_measurement_length,
                    "vertex_count": len(measured_road_coordinates),
                    "meters_per_pixel": scale_meters_per_pixel,
                    "north_reference": "EPSG:28992 grid north",
                    "measurement_is_evidence": False,
                    "measurement_persisted": False,
                }
                page.screenshot(path=str(screenshot_dir / "01a_measurement_against_source_road.png"), full_page=True)
                page.get_by_role("button", name="Clear measurement").click()
                for _ in range(7):
                    page.get_by_title("Zoom Out").click()
                    zoom = max(0.2, zoom * 0.8)
                box_selection = choose_single_building_selection_box(
                    context["buildings"],
                    zoom=zoom,
                    canvas_width=canvas_box["width"],
                    canvas_height=canvas_box["height"],
                    excluded_ids={building_id, undecided_building_id},
                )
                page.locator("#btn-toggle-box-select").click()
                start_x, start_y = box_selection["screen_start"]
                end_x, end_y = box_selection["screen_end"]
                page.mouse.move(canvas_box["x"] + start_x, canvas_box["y"] + start_y)
                page.mouse.down()
                page.mouse.move(canvas_box["x"] + end_x, canvas_box["y"] + end_y, steps=5)
                page.mouse.up()
                page.locator("#selected-disposition-count").get_by_text("1 building feature selected", exact=True).wait_for()
                page.locator("#selected-feature-2d").get_by_text(box_selection["feature_id"], exact=True).wait_for()
                page.locator("#btn-selected-editable-building").click()
                page.locator("#filter-disp-editable").click()
                page.locator(f'[id="disp-item-{box_selection["feature_id"]}"]').wait_for()
                page.locator("#filter-disp-all").click()
                page.screenshot(path=str(screenshot_dir / "00_box_selection.png"), full_page=True)

                click_feature_action(page, f"btn-preserve-{building_id}")
                click_feature_action(page, f"btn-undecided-{undecided_building_id}")
                annotation_text = "Local access note for browser verification; draft only."
                page.locator(f'[id="disp-item-{box_selection["feature_id"]}"]').click()
                page.get_by_label(f'Annotation for {box_selection["feature_id"]}').fill(annotation_text)
                page.locator("#tab-disp-roads").click()
                click_feature_action(page, f"btn-editable-{road_id}")

                first_card = context["evidence_cards"][0]
                page.locator(f'[id="card-{first_card["card_id"]}"]').click()
                page.locator("#evidence-gaps").get_by_text("UNKNOWN: land use and occupancy", exact=False).wait_for()
                page.locator(f'[id="card-{first_card["card_id"]}"] details summary').click()
                page.locator(f'[id="card-{first_card["card_id"]}"]').get_by_text(first_card["input_sha256"], exact=False).wait_for()
                rendered_road_card = page.locator(f'[id="card-{road_card["card_id"]}"]')
                rendered_road_text = rendered_road_card.inner_text()
                rendered_road_value = page.evaluate("value => value.toLocaleString()", road_card["value"])
                if rendered_road_value not in rendered_road_text:
                    raise AssertionError(
                        f"UI road card does not show current API value {rendered_road_value!r}: {rendered_road_text!r}"
                    )

                page.locator("#sidebar-tab-brief").click()
                page.locator("#input-zone-name").fill("R02 browser test zone")
                page.locator("#input-zone-notes").fill("Non-default polygon drawn in the active StudyArea for browser synchronization verification.")
                program_demands = ["Mixed-Use Innovation Hub", "Fabrication workshops", "Shared tool library"]
                open_space_demands = ["Public waterfront path", "Shaded courtyard"]
                draft_constraints = ["Preserve quay access", "Keep service access open"]
                draft_preferences = ["Reuse existing warehouse shells", "Active ground floors"]
                page.locator("#input-zone-program-demands").fill(", ".join(program_demands[1:]))
                page.locator("#input-zone-open-space-demands").fill(", ".join(open_space_demands))
                page.locator("#input-zone-constraints").fill(", ".join(draft_constraints))
                page.locator("#input-zone-preferences").fill(", ".join(draft_preferences))
                page.locator("#input-zone-far").fill("1.2")
                page.locator("#input-zone-height").fill("18")
                page.locator("#input-zone-name").fill("R02 rejected outside zone")
                page.locator("#btn-start-draw-zone").click()
                outside_polygon = choose_boundary_crossing_test_polygon(
                    context["study_area"]["geometry"],
                    zoom=zoom,
                    canvas_width=canvas_box["width"],
                    canvas_height=canvas_box["height"],
                )
                for x, y in outside_polygon:
                    sx = 420 + (x - 89100.0) * zoom
                    sy = 380 - (y - 435900.0) * zoom
                    page.mouse.click(canvas_box["x"] + sx, canvas_box["y"] + sy)
                page.locator("#btn-finish-drawing").click()
                page.locator("#btn-add-zone").click()
                rejection_message = page.locator("#brief-validation-error").get_by_text(
                    "Polygon must be fully within one polygon component of the active StudyArea",
                    exact=False,
                )
                rejection_message.wait_for()
                rejected_zone_count = page.locator('[id^="brief-zone-card-"]').count()
                if rejected_zone_count != initial_zone_count:
                    raise AssertionError("an outside StudyArea draft was added by the browser UI")
                outside_zone_rejection = {
                    "status": "REJECTED_BEFORE_LOCAL_DRAFT_APPEND",
                    "message": rejection_message.inner_text(),
                    "zone_count_before": initial_zone_count,
                    "zone_count_after": rejected_zone_count,
                    "candidate_bounds_epsg28992": list(shapely_box(*outside_polygon[0], *outside_polygon[2]).bounds),
                }
                page.screenshot(path=str(screenshot_dir / "00b_outside_zone_rejected.png"), full_page=True)
                page.locator("#btn-clear-drawn-polygon").click()
                page.locator("#input-zone-name").fill("R02 browser test zone")
                page.locator("#btn-start-draw-zone").click()
                # The initial renderer centers EPSG:28992 at (89100, 435900);
                # the earlier zoom-out steps bring the active area into view.
                box = canvas_box
                # Three separated points leave the UI's explicit Finish control available;
                # a fourth point near the first can intentionally auto-close small polygons.
                for x, y in polygon[:3]:
                    sx = 420 + (x - 89100.0) * zoom
                    sy = 380 - (y - 435900.0) * zoom
                    if not (5 <= sx <= box["width"] - 5 and 5 <= sy <= box["height"] - 5):
                        raise AssertionError(f"test polygon screen coordinate is outside canvas: {(sx, sy)}")
                    page.mouse.click(box["x"] + sx, box["y"] + sy)
                page.locator("#btn-finish-drawing").click()
                page.locator("#btn-add-zone").click()
                zone_cards = page.locator('[id^="brief-zone-card-"]')
                if zone_cards.count() != initial_zone_count + 1:
                    raise AssertionError(f"expected one appended zone, found {zone_cards.count()} total; prior DRAFT zones={initial_zone_count}")

                # Test both exporters while authored changes are still unsaved. Keep this
                # after geometry interactions because switching views remounts the canvas.
                page.locator("#status-authority").get_by_text("Unsaved Draft Changes", exact=True).wait_for()
                map_export_button = page.locator("#btn-export-map-figure")
                map_export_button.wait_for(state="visible")
                if not map_export_button.is_disabled():
                    raise AssertionError("map figure export stayed enabled while workspace edits were unsaved")
                dirty_figure_export_guard["map_disabled_with_unsaved_changes"] = True
                page.locator("#btn-view-3d").click()
                page.get_by_text("SCHEMATIC 3D VOLUME PREVIEW", exact=True).wait_for()
                page.locator("#viewport-3d-container canvas").wait_for(state="visible")
                schematic_export_button = page.locator("#btn-export-3d-figure")
                schematic_export_button.wait_for(state="visible")
                if not schematic_export_button.is_disabled():
                    raise AssertionError("schematic 3D figure export stayed enabled while workspace edits were unsaved")
                dirty_figure_export_guard["schematic_3d_disabled_with_unsaved_changes"] = True
                page.locator("#btn-view-2d").click()
                page.locator("#canvas-viewport-2d").wait_for(state="visible")

                if inject_sync_response_loss:
                    page.locator("#btn-sync-workspace").click()
                    page.locator("#btn-confirm-sync-modal").click()
                    expected_reconciliation = (
                        f"Reconciled: no matching revision is present. Draft retained; review before syncing again."
                        if drop_first_sync_before_commit
                        else f"Reconciled: request is persisted as revision {initial_revision + 1}."
                    )
                    page.locator("#sync-reconciliation-status").get_by_text(expected_reconciliation, exact=True).wait_for(timeout=15_000)
                    expected_authority = "Unsaved Draft Changes" if drop_first_sync_before_commit else "In Sync (Server Authority)"
                    page.locator("#status-authority").get_by_text(expected_authority, exact=True).wait_for()
                    page.locator("#btn-confirm-sync-modal").wait_for(state="detached", timeout=15_000)
                    page.locator("#sync-error-banner").wait_for(state="detached", timeout=15_000)
                    if len(sync_dispatches) != 1:
                        raise AssertionError(f"browser automatically retried after the response was lost: {len(sync_dispatches)} sync POSTs")
                    failed_sync_requests = [
                        item for item in browser_request_failures
                        if urlsplit(item["url"]).path == "/api/v1/workspaces/sync"
                    ]
                    if len(failed_sync_requests) != 1:
                        raise AssertionError(f"expected one lost sync response, observed {len(failed_sync_requests)} failed sync requests")
                    if drop_first_sync_before_commit:
                        if dropped_sync_response is None or dropped_sync_response["status"] is not None:
                            raise AssertionError("pre-commit fault unexpectedly reached or captured a server response")
                        with page.expect_response(
                            lambda response: response.url.endswith("/api/v1/workspaces/sync") and response.request.method == "POST"
                        ) as explicit_retry_info:
                            page.locator("#btn-sync-workspace").click()
                            page.locator("#btn-confirm-sync-modal").click()
                        explicit_retry = explicit_retry_info.value
                        if explicit_retry.status not in (200, 201):
                            raise AssertionError(f"explicit post-reconciliation sync failed: HTTP {explicit_retry.status}")
                        response_body = explicit_retry.json()
                    else:
                        if dropped_sync_response is None or dropped_sync_response["status"] not in (200, 201):
                            raise AssertionError("the test proxy did not capture one successful server commit before dropping its response")
                        response_body = dropped_sync_response["body"]
                        committed_key = response_body.get("workspace_revision", {}).get("idempotency_key")
                        committed_key_hash = hashlib.sha256(str(committed_key).encode()).hexdigest()
                        if committed_key_hash != sync_dispatches[0]["idempotency_key_sha256"]:
                            raise AssertionError("reconciled server revision does not match the single dispatched idempotency key")
                else:
                    with page.expect_response(
                        lambda response: response.url.endswith("/api/v1/workspaces/sync") and response.request.method == "POST"
                    ) as first_response_info:
                        page.locator("#btn-sync-workspace").click()
                        page.locator("#btn-confirm-sync-modal").click()
                    response = first_response_info.value
                    if response.status not in (200, 201):
                        posted = json.loads(response.request.post_data or "{}")
                        posted_zones = ((posted.get("spatial_brief") or {}).get("zones") or [])
                        actual = posted_zones[-1]["geometry"]["coordinates"][0] if posted_zones else []
                        print(json.dumps({
                            "expected_test_points": polygon[:3],
                            "posted_test_geometry": actual,
                            "server_detail": response.text(),
                            "expected_coverage": shape(context["study_area"]["geometry"]).covers(Polygon(actual[:-1] if actual and actual[0] == actual[-1] else actual)),
                        }, indent=2))
                        raise AssertionError(f"first browser sync failed with HTTP {response.status}: {response.text()}")
                    response_body = response.json()
                persisted_first = response_body["workspace_revision"]
                if persisted_first["revision"] != initial_revision + 1:
                    raise AssertionError("first browser sync did not append exactly one workspace revision")
                first_dispositions = {
                    item["feature_id"]: item["disposition"]
                    for item in persisted_first.get("feature_dispositions", [])
                }
                if (
                    first_dispositions.get(building_id) != "preserve"
                    or first_dispositions.get(undecided_building_id) != "undecided"
                    or first_dispositions.get(road_id) != "editable"
                ):
                    raise AssertionError("first saved revision did not preserve the selected preserve/editable/undecided feature IDs")
                expected_box_selection_status = (
                    "preserve" if box_selection["feature_id"] == building_id
                    else "undecided" if box_selection["feature_id"] == undecided_building_id
                    else "editable"
                )
                if first_dispositions.get(box_selection["feature_id"]) != expected_box_selection_status:
                    raise AssertionError("box-selected BAG feature disposition did not persist under its exact source feature ID")
                first_annotations = {
                    item["feature_id"]: item.get("annotation", "")
                    for item in persisted_first.get("feature_dispositions", [])
                }
                if first_annotations.get(box_selection["feature_id"]) != annotation_text:
                    raise AssertionError("local feature annotation did not persist on the first workspace revision")
                page.locator("#badge-revision").get_by_text(f"rev {persisted_first['revision']}").wait_for()
                page.screenshot(path=str(screenshot_dir / "01_after_revision_one.png"), full_page=True)

                page.locator("#sidebar-tab-dispositions").click()
                click_feature_action(page, f"btn-editable-{building_id}")
                unlock_dialog = page.get_by_role("alertdialog", name="Unlock preserved feature?")
                unlock_dialog.wait_for(state="visible")
                page.screenshot(path=str(screenshot_dir / "00a_preserved_unlock_confirmation.png"), full_page=True)
                unlock_dialog.get_by_role("button", name="Unlock and set Editable").click()
                preserved_unlock_confirmation_verified = True
                with page.expect_response(
                    lambda response: response.url.endswith("/api/v1/workspaces/sync") and response.request.method == "POST"
                ) as second_response_info:
                    page.locator("#btn-sync-workspace").click()
                    page.locator("#btn-confirm-sync-modal").click()
                second_response = second_response_info.value
                if second_response.status not in (200, 201):
                    raise AssertionError(f"second browser sync failed with HTTP {second_response.status}: {second_response.text()}")
                persisted_second = second_response.json()["workspace_revision"]
                if persisted_second["revision"] != persisted_first["revision"] + 1:
                    raise AssertionError("second browser sync did not append exactly one revision")

                page.locator("#btn-reload-workspace").click()
                page.locator("#badge-revision").get_by_text(f"rev {persisted_second['revision']}").wait_for()
                # React does not await this async click handler; revision text can render
                # before loadData finishes reconciling server authority.
                page.locator("#status-authority").get_by_text("In Sync (Server Authority)", exact=True).wait_for(timeout=15_000)
                # A hard page reload exercises fresh application bootstrap from the
                # persisted server revision, independently of the in-app reload above.
                page.reload(wait_until="networkidle")
                page.locator("#badge-revision").get_by_text(f"rev {persisted_second['revision']}").wait_for(timeout=15_000)
                page.locator("#status-authority").get_by_text("In Sync (Server Authority)", exact=True).wait_for(timeout=15_000)
                page.locator("#sidebar-tab-dispositions").click()
                page.locator(f'[id="disp-item-{box_selection["feature_id"]}"]').click()
                reloaded_annotation = page.get_by_label(f'Annotation for {box_selection["feature_id"]}')
                reloaded_annotation.wait_for(state="visible")
                if reloaded_annotation.input_value() != annotation_text:
                    raise AssertionError("fresh browser bootstrap did not restore the saved feature annotation")
                editable_button = page.locator(f'[id="btn-editable-{box_selection["feature_id"]}"]')
                disposition_button_colors = page.locator(
                    f'[id^="btn-"][id$="-{box_selection["feature_id"]}"]'
                ).evaluate_all("elements => elements.map(element => ({id: element.id, background: getComputedStyle(element).backgroundColor}))")
                if editable_button.evaluate("element => getComputedStyle(element).backgroundColor") != "rgba(56, 189, 248, 0.25)":
                    raise AssertionError(
                        "fresh browser bootstrap did not render the box-selected feature disposition as active: "
                        f"{json.dumps(disposition_button_colors)}"
                    )
                page.locator("#sidebar-tab-brief").click()
                freshly_reloaded_zone = page.locator('[id^="brief-zone-card-"]').filter(has_text="R02 browser test zone")
                freshly_reloaded_zone.wait_for(state="visible")
                if "Fabrication workshops" not in freshly_reloaded_zone.inner_text():
                    raise AssertionError("fresh browser bootstrap did not restore the saved draft brief")

                saved_zone_before_edit = next(
                    zone for zone in persisted_second.get("spatial_brief", {}).get("zones", [])
                    if zone.get("name") == "R02 browser test zone"
                )
                saved_zone_geometry = json.dumps(
                    saved_zone_before_edit.get("geometry"), sort_keys=True, separators=(",", ":")
                )
                page.locator(f'[id="btn-edit-zone-{saved_zone_before_edit["zone_id"]}"]').click()
                page.locator("#input-zone-name").wait_for()
                if page.locator("#input-zone-name").input_value() != "R02 browser test zone":
                    raise AssertionError("saved zone editor did not restore its current name")
                if page.locator("#input-zone-far").input_value() != "1.2":
                    raise AssertionError("saved zone editor did not restore FAR from the API numeric value object")
                if page.locator("#input-zone-height").input_value() != "18":
                    raise AssertionError("saved zone editor did not restore height from the API numeric value object")
                page.locator("#input-zone-name").fill("R02 browser test zone edited")
                page.locator("#input-zone-program-demands").fill(", ".join([*program_demands[1:], "Community kitchen"]))
                page.locator("#input-zone-far").fill("1.8")
                page.locator("#input-zone-height").fill("21")
                page.screenshot(path=str(screenshot_dir / "04a_edit_saved_draft_zone.png"), full_page=True)
                page.get_by_role("button", name="Save Draft Zone").click()
                page.locator("#status-authority").get_by_text("Unsaved Draft Changes", exact=True).wait_for()
                with page.expect_response(
                    lambda response: response.url.endswith("/api/v1/workspaces/sync") and response.request.method == "POST"
                ) as zone_edit_response_info:
                    page.locator("#btn-sync-workspace").click()
                    page.locator("#btn-confirm-sync-modal").click()
                zone_edit_response = zone_edit_response_info.value
                if zone_edit_response.status not in (200, 201):
                    raise AssertionError(f"saved zone edit sync failed with HTTP {zone_edit_response.status}: {zone_edit_response.text()}")
                persisted_zone_edit = zone_edit_response.json()["workspace_revision"]
                if persisted_zone_edit["revision"] != persisted_second["revision"] + 1:
                    raise AssertionError("editing one saved zone did not append exactly one workspace revision")
                saved_zone_after_edit = next(
                    zone for zone in persisted_zone_edit.get("spatial_brief", {}).get("zones", [])
                    if zone.get("zone_id") == saved_zone_before_edit["zone_id"]
                )
                edited_geometry = json.dumps(saved_zone_after_edit.get("geometry"), sort_keys=True, separators=(",", ":"))
                if edited_geometry != saved_zone_geometry:
                    raise AssertionError("editing saved brief text or parameters changed the zone's polygon geometry")
                if saved_zone_after_edit.get("status") != "DRAFT_PENDING_HUMAN_DECISION":
                    raise AssertionError("editing a zone activated its draft constraints without a Human Decision")
                if saved_zone_after_edit.get("name") != "R02 browser test zone edited":
                    raise AssertionError("edited zone name was not saved under the existing zone identity")
                if saved_zone_after_edit.get("program_demands") != [*program_demands, "Community kitchen"]:
                    raise AssertionError("editing a saved zone duplicated or lost program demands")
                zone_edit_record = {
                    "zone_id": saved_zone_after_edit["zone_id"],
                    "revision_before": persisted_second["revision"],
                    "revision_after": persisted_zone_edit["revision"],
                    "geometry_sha256_before": hashlib.sha256(saved_zone_geometry.encode("utf-8")).hexdigest(),
                    "geometry_sha256_after": hashlib.sha256(edited_geometry.encode("utf-8")).hexdigest(),
                    "status": saved_zone_after_edit["status"],
                    "far": saved_zone_after_edit.get("target_far"),
                    "height": saved_zone_after_edit.get("target_height_m"),
                }
                page.locator("#badge-revision").get_by_text(f"rev {persisted_zone_edit['revision']}").wait_for()
                page.locator("#btn-reload-workspace").click()
                page.locator("#badge-revision").get_by_text(f"rev {persisted_zone_edit['revision']}").wait_for()
                page.locator("#status-authority").get_by_text("In Sync (Server Authority)", exact=True).wait_for(timeout=15_000)
                page.reload(wait_until="networkidle")
                page.locator("#badge-revision").get_by_text(f"rev {persisted_zone_edit['revision']}").wait_for(timeout=15_000)
                page.locator("#status-authority").get_by_text("In Sync (Server Authority)", exact=True).wait_for(timeout=15_000)
                page.locator("#sidebar-tab-brief").click()
                edited_zone_card = page.locator(f'[id="brief-zone-card-{saved_zone_after_edit["zone_id"]}"]')
                edited_zone_card.get_by_text("R02 browser test zone edited", exact=True).wait_for()
                if "Community kitchen" not in edited_zone_card.inner_text():
                    raise AssertionError("fresh browser bootstrap did not restore the edited zone demand")
                if "FAR: 1.8 | H: 21m" not in edited_zone_card.inner_text():
                    raise AssertionError("fresh browser bootstrap did not restore the edited FAR and height values")
                page.screenshot(path=str(screenshot_dir / "04b_edited_draft_zone_reloaded.png"), full_page=True)
                zone_edit_verified = True
                page.locator("#sidebar-tab-dispositions").click()
                fresh_browser_reload_verified = True
                tab_diagnostics: list[dict[str, Any]] = []

                def capture_tab_state(label: str) -> None:
                    state = page.evaluate("""() => {
                      const ids = ['dispositions', 'brief', 'syntax'];
                      const tabs = Object.fromEntries(ids.map(name => {
                        const element = document.querySelector(`#sidebar-tab-${name}`);
                        if (!element) return [name, null];
                        const style = getComputedStyle(element);
                        return [name, {
                          border: style.borderBottomColor,
                          text: style.color,
                          background: style.backgroundColor,
                          connected: element.isConnected,
                        }];
                      }));
                      return {
                        tabs,
                        briefCards: [...document.querySelectorAll('[id^="brief-zone-card-"]')]
                          .map(element => ({id: element.id, visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length)})),
                        activeElement: document.activeElement?.id ?? null,
                        visible2dCanvas: [...document.querySelectorAll('canvas')].some(element => {
                          const rect = element.getBoundingClientRect();
                          return rect.width > 0 && rect.height > 0 && getComputedStyle(element).visibility !== 'hidden';
                        }),
                      };
                    }""")
                    tab_diagnostics.append({"label": label, **state})

                page.evaluate("""() => {
                  window.__week4SidebarClicks = [];
                  document.addEventListener('click', event => {
                    const target = event.target instanceof Element ? event.target.closest('[id^="sidebar-tab-"]') : null;
                    if (target) window.__week4SidebarClicks.push(target.id);
                  }, true);
                }""")
                page.locator("#btn-view-3d").click()
                page.get_by_text("SCHEMATIC 3D VOLUME PREVIEW", exact=True).wait_for()
                canvas_3d = page.locator("#viewport-3d-container canvas")
                canvas_3d.wait_for(state="visible")
                canvas_3d_box = canvas_3d.bounding_box()
                if canvas_3d_box is None:
                    raise AssertionError("3D canvas has no visible bounding box")
                canvas_3d.evaluate(
                    "element => element.setAttribute('data-week4-canvas-identity', 'retained-through-selection')"
                )
                road_selection = choose_visible_road_selection(
                    context["roads"],
                    context["buildings"],
                    canvas_width=canvas_3d_box["width"],
                    canvas_height=canvas_3d_box["height"],
                )
                road_pick_x, road_pick_y = road_selection["screen"]
                page.mouse.click(canvas_3d_box["x"] + road_pick_x, canvas_3d_box["y"] + road_pick_y)
                page.locator("#selected-feature-3d").get_by_text(road_selection["feature_id"], exact=True).wait_for()
                page.screenshot(path=str(screenshot_dir / "03a_3d_road_selection.png"), full_page=True)
                page.locator("#btn-view-2d").click()
                page.locator("#canvas-viewport-2d").wait_for(state="visible")
                page.locator("#selected-feature-2d").get_by_text(road_selection["feature_id"], exact=True).wait_for()
                page.screenshot(path=str(screenshot_dir / "03b_2d_road_selection.png"), full_page=True)
                cross_view_road_selection_verified = True
                page.locator("#btn-view-3d").click()
                page.get_by_text("SCHEMATIC 3D VOLUME PREVIEW", exact=True).wait_for()
                canvas_3d = page.locator("#viewport-3d-container canvas")
                canvas_3d.wait_for(state="visible")
                canvas_3d_box = canvas_3d.bounding_box()
                if canvas_3d_box is None:
                    raise AssertionError("3D canvas disappeared after preserving the road selection")
                canvas_3d.evaluate(
                    "element => element.setAttribute('data-week4-canvas-identity', 'retained-through-selection')"
                )
                page.mouse.move(
                    canvas_3d_box["x"] + canvas_3d_box["width"] / 2,
                    canvas_3d_box["y"] + canvas_3d_box["height"] / 2,
                )
                zoom_events = 3
                for _ in range(zoom_events):
                    page.mouse.wheel(0, -100)
                page.wait_for_timeout(200)
                zoomed_camera_radius = 750.0 * (0.9 ** zoom_events)
                zoomed_road_pick = project_3d_point_to_screen(
                    road_selection["point"],
                    z=0.5,
                    canvas_width=canvas_3d_box["width"],
                    canvas_height=canvas_3d_box["height"],
                    camera_radius=zoomed_camera_radius,
                )
                page.mouse.click(
                    canvas_3d_box["x"] + zoomed_road_pick[0],
                    canvas_3d_box["y"] + zoomed_road_pick[1],
                )
                page.locator("#selected-feature-3d").get_by_text(road_selection["feature_id"], exact=True).wait_for()
                page.screenshot(path=str(screenshot_dir / "03c_3d_road_selection_zoomed.png"), full_page=True)
                zoomed_3d_road_selection_verified = True
                page.locator("#btn-view-2d").click()
                page.locator("#canvas-viewport-2d").wait_for(state="visible")
                page.locator("#selected-feature-2d").get_by_text(road_selection["feature_id"], exact=True).wait_for()
                page.locator("#btn-view-3d").click()
                page.get_by_text("SCHEMATIC 3D VOLUME PREVIEW", exact=True).wait_for()
                canvas_3d = page.locator("#viewport-3d-container canvas")
                canvas_3d.wait_for(state="visible")
                canvas_3d_box = canvas_3d.bounding_box()
                if canvas_3d_box is None:
                    raise AssertionError("3D canvas disappeared after zoomed road selection")
                canvas_3d.evaluate(
                    "element => element.setAttribute('data-week4-canvas-identity', 'retained-through-selection')"
                )
                page.locator(f'[id="disp-item-{building_id}"]').click()
                page.wait_for_function(
                    """() => document.querySelector(
                      '#viewport-3d-container canvas[data-week4-canvas-identity="retained-through-selection"]'
                    ) !== null""",
                    timeout=5_000,
                )
                page.locator("#selected-feature-3d").get_by_text(building_id, exact=True).wait_for()
                selected_building_geometry = next(
                    building["geometry"] for building in context["buildings"]
                    if building["id"] == box_selection["feature_id"]
                )
                pick_x, pick_y = project_building_point_to_3d_screen(
                    selected_building_geometry,
                    canvas_width=canvas_3d_box["width"],
                    canvas_height=canvas_3d_box["height"],
                )
                page.mouse.click(canvas_3d_box["x"] + pick_x, canvas_3d_box["y"] + pick_y)
                page.wait_for_function(
                    """() => document.querySelector(
                      '#viewport-3d-container canvas[data-week4-canvas-identity="retained-through-selection"]'
                    ) !== null""",
                    timeout=5_000,
                )
                page.locator("#selected-feature-3d").get_by_text(box_selection["feature_id"], exact=True).wait_for()
                page.locator("#btn-view-2d").click()
                page.locator("#selected-feature-2d").get_by_text(box_selection["feature_id"], exact=True).wait_for()
                cross_view_building_selection_verified = True
                page.locator("#btn-view-3d").click()
                page.locator("#selected-feature-3d").get_by_text(box_selection["feature_id"], exact=True).wait_for()
                capture_tab_state("3d_loaded")
                page.screenshot(path=str(screenshot_dir / "03_3d_schematic_preview.png"), full_page=True)
                export_button = page.get_by_role("button", name="Export 3D figure (PNG)")
                export_button.wait_for(state="visible")
                if export_button.is_disabled():
                    raise AssertionError("provenance-linked 3D figure export is disabled after the saved workspace reload")
                with page.expect_download() as figure_download_info:
                    export_button.click()
                figure_download = figure_download_info.value
                figure_path = screenshot_dir / "05_schematic_3d_figure.png"
                figure_download.save_as(figure_path)
                figure_bytes = figure_path.read_bytes()
                if len(figure_bytes) < 2_000 or figure_bytes[:8] != b"\x89PNG\r\n\x1a\n":
                    raise AssertionError("downloaded schematic 3D figure is missing, too small, or not a PNG")
                if figure_bytes[12:16] != b"IHDR":
                    raise AssertionError("downloaded schematic 3D figure has no PNG IHDR")
                figure_width, figure_height = struct.unpack(">II", figure_bytes[16:24])
                if figure_width < 1_400 or figure_height < 700:
                    raise AssertionError(f"downloaded figure dimensions are too small: {figure_width}x{figure_height}")
                page.locator("#status-3d-figure-export").get_by_text("PNG downloaded", exact=False).wait_for()
                page.screenshot(path=str(screenshot_dir / "05_3d_figure_export_complete.png"), full_page=True)
                page.locator("#btn-view-2d").click()
                page.locator("#canvas-viewport-2d").wait_for(state="visible")
                capture_tab_state("2d_restored_before_brief_click")
                map_export_button = page.get_by_role("button", name="Export analysis map figure (PNG)")
                map_export_button.wait_for(state="visible")
                page.locator("#btn-toggle-box-select").click()
                if not map_export_button.is_disabled():
                    raise AssertionError("map figure export stayed enabled while a transient box-selection tool was active")
                page.locator("#btn-toggle-box-select").click()
                if map_export_button.is_disabled():
                    raise AssertionError("provenance-linked map export is disabled after returning to a saved, idle 2D view")
                with page.expect_download() as map_figure_download_info:
                    map_export_button.click()
                map_figure_download = map_figure_download_info.value
                map_figure_path = screenshot_dir / "06_analysis_map_figure.png"
                map_figure_download.save_as(map_figure_path)
                map_figure_bytes = map_figure_path.read_bytes()
                if len(map_figure_bytes) < 2_000 or map_figure_bytes[:8] != b"\x89PNG\r\n\x1a\n":
                    raise AssertionError("downloaded analysis map figure is missing, too small, or not a PNG")
                if map_figure_bytes[12:16] != b"IHDR":
                    raise AssertionError("downloaded analysis map figure has no PNG IHDR")
                map_figure_width, map_figure_height = struct.unpack(">II", map_figure_bytes[16:24])
                if map_figure_width < 1_400 or map_figure_height < 1_000:
                    raise AssertionError(f"downloaded analysis map figure dimensions are too small: {map_figure_width}x{map_figure_height}")
                map_figure_status = page.locator("#status-map-figure-export").inner_text()
                if "PNG downloaded" not in map_figure_status or "COMPUTED_EXPLORATORY" not in map_figure_status:
                    raise AssertionError(f"map export status does not expose the saved revision and exploratory analysis state: {map_figure_status}")
                page.screenshot(path=str(screenshot_dir / "06_analysis_map_export_complete.png"), full_page=True)
                page.locator("#sidebar-tab-brief").click()
                capture_tab_state("immediately_after_brief_click")
                reloaded_brief_card = page.locator('[id^="brief-zone-card-"]').filter(has_text="R02 browser test zone")
                reloaded_brief_card.wait_for(state="visible")
                try:
                    page.wait_for_function(
                        """() => {
                          const tab = document.querySelector('#sidebar-tab-brief');
                          const probe = document.createElement('span');
                          probe.style.color = 'var(--accent-cyan)';
                          document.body.appendChild(probe);
                          const expectedColor = getComputedStyle(probe).color;
                          probe.remove();
                          return getComputedStyle(tab).borderBottomColor === expectedColor;
                        }""",
                        timeout=2_000,
                    )
                except Exception as exc:
                    clicks = page.evaluate("window.__week4SidebarClicks")
                    capture_tab_state("brief_selection_timeout")
                    raise AssertionError(
                        f"Brief tab did not become selected; clicks={clicks}; diagnostics={json.dumps(tab_diagnostics)}"
                    ) from exc
                capture_tab_state("brief_selection_committed")
                brief_tab_border_color = page.locator("#sidebar-tab-brief").evaluate("element => getComputedStyle(element).borderBottomColor")
                if brief_tab_border_color in ("transparent", "rgba(0, 0, 0, 0)"):
                    raise AssertionError(f"Brief tab border remained inactive: {json.dumps(tab_diagnostics)}")
                reloaded_brief_text = reloaded_brief_card.inner_text()
                for field_text in (
                    "Program demands (draft):",
                    "Fabrication workshops",
                    "Open-space demands (draft):",
                    "Public waterfront path",
                    "Hard constraints (draft; inactive)",
                    "Preserve quay access",
                    "Preferences (non-binding draft)",
                    "Reuse existing warehouse shells",
                ):
                    if field_text not in reloaded_brief_text:
                        raise AssertionError(f"reloaded brief panel omits saved field text: {field_text}")
                page.screenshot(path=str(screenshot_dir / "04_reloaded_draft_brief.png"), full_page=True)
                page.locator("#sidebar-tab-syntax").click()
                page.locator("#syntax-exploratory-warning").get_by_text("EXPLORATORY ONLY", exact=False).wait_for()
                page.locator("#layer-syntax_local_800m_integration").get_by_text("Computed summary covers 514 segments.", exact=True).wait_for()
                page.get_by_text(
                    "Historical R02 geometry noding predates source OSM node identity and is not topology-validated.",
                    exact=False,
                ).wait_for()
                plan_rows = page.locator("#syntax-layer-plan [role='listitem']")
                if plan_rows.count() != 6:
                    raise AssertionError(f"Syntax panel should render all six planned metric/radius rows, found {plan_rows.count()}")
                plan_row_texts = [
                    plan_rows.nth(index).inner_text().replace("2,000 m", "2000 m").replace("10,000 m", "10000 m")
                    for index in range(plan_rows.count())
                ]
                expected_plan_rows = (
                    ("800 m · Angular integration (NAIN)", "Computed · exploratory", "BLOCKED_BOUNDARY_STABILITY_UNASSESSED"),
                    ("800 m · Angular choice (NACH)", "Computed · exploratory", "BLOCKED_BOUNDARY_STABILITY_UNASSESSED"),
                    ("2000 m · Angular integration (NAIN)", "Computed · exploratory", "EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY"),
                    ("2000 m · Angular choice (NACH)", "Computed · exploratory", "EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY"),
                    ("10000 m · Angular integration (NAIN)", "Not computed · runtime budget", "BLOCKED_RUNTIME_BUDGET_ESTIMATE"),
                    ("10000 m · Angular choice (NACH)", "Not computed · runtime budget", "BLOCKED_RUNTIME_BUDGET_ESTIMATE"),
                )
                for row_text, expected in zip(plan_row_texts, expected_plan_rows, strict=True):
                    if any(part not in row_text for part in expected):
                        raise AssertionError(f"Syntax readiness row does not match its planned calculation state: expected={expected}; actual={row_text}")
                syntax_legend = page.locator('[aria-label^="Metric legend for "]')
                syntax_legend.wait_for(state="visible")
                visible_legend_text = syntax_legend.inner_text()
                integration_result = next(layer for layer in computed_syntax if layer.get("metric_key") == "nain" and layer.get("radius_m") == 800)
                for label, key in (("Min", "min"), ("Mean", "mean"), ("Max", "max")):
                    value = integration_result.get("statistics", {}).get(key)
                    if not isinstance(value, (int, float)) or f"{label}: {value:.2f}" not in visible_legend_text:
                        raise AssertionError(f"Syntax legend does not display the API result's deterministic {label} value")
                if "Classifier breaks unavailable." in visible_legend_text:
                    raise AssertionError("Syntax legend omitted classifier break values present in the API result")
                if not all(f"{value:.2f}" in visible_legend_text for value in integration_result.get("legend_breaks", [])):
                    raise AssertionError("Syntax legend classifier break labels differ from the verified API layer")
                download_url = context.get("syntax_figure_downloads", {}).get("svg")
                if not download_url:
                    raise AssertionError("API did not expose a verified R03 exploratory figure download")
                link_href = page.locator("#syntax-exploratory-download").get_attribute("href")
                if link_href != f"{api_base}{download_url}":
                    raise AssertionError(f"exploratory figure link does not resolve to the API download route: {link_href}")
                with page.expect_download() as download_info:
                    page.locator("#syntax-exploratory-download").click()
                downloaded = download_info.value
                downloaded_path = screenshot_dir / "04_downloaded_exploratory_800m.svg"
                downloaded.save_as(downloaded_path)
                downloaded_text = downloaded_path.read_text(encoding="utf-8")
                if "EXPLORATORY ONLY" not in downloaded_text or "SOURCE COVERAGE INSUFFICIENT" not in downloaded_text:
                    raise AssertionError("downloaded Syntax figure does not visibly carry its exploratory coverage warning")
                required_figure_counts = (
                    "Displayed linework: 1,328",
                    "With Syntax values: 1,272",
                    "Without Syntax values: 56",
                    "Source-mapped network: 1,355 segments",
                )
                missing_figure_counts = [label for label in required_figure_counts if label not in downloaded_text]
                if missing_figure_counts:
                    raise AssertionError(f"downloaded Syntax figure omits count distinctions: {missing_figure_counts}")
                if "Segments: 1,328" in downloaded_text or "1355 mapped segments" in downloaded_text:
                    raise AssertionError("downloaded Syntax figure still contains ambiguous legacy count labels")
                last_plan_row = plan_rows.nth(5)
                last_plan_row.scroll_into_view_if_needed()
                last_row_box = last_plan_row.bounding_box()
                legend_box = syntax_legend.bounding_box()
                viewport_height = page.evaluate("() => window.innerHeight")
                if not last_row_box or not legend_box:
                    raise AssertionError("Syntax readiness row or metric legend has no rendered bounds")
                if last_row_box["y"] + last_row_box["height"] > legend_box["y"]:
                    raise AssertionError("scrolling the planned rows hides or overlaps the persistent metric legend")
                if legend_box["y"] < 0 or legend_box["y"] + legend_box["height"] > viewport_height:
                    raise AssertionError("metric legend is outside the visible sidebar viewport")
                page.screenshot(path=str(screenshot_dir / "02_reload_syntax_readiness.png"), full_page=True)
                if page_errors:
                    raise AssertionError(f"browser runtime errors: {page_errors}")
                if blocked_external_requests:
                    raise AssertionError(f"browser attempted external requests: {blocked_external_requests}")
                if unexpected_browser_api_targets:
                    raise AssertionError(f"browser called an API outside this launch-scoped server: {unexpected_browser_api_targets}")
                if inject_sync_response_loss:
                    unexpected_console_errors = [
                        error for error in browser_console_errors if "net::ERR_FAILED" not in error
                    ]
                    if unexpected_console_errors:
                        raise AssertionError(f"unexpected browser console errors: {unexpected_console_errors}")
                    expected_dispatches = 4 if drop_first_sync_before_commit else 3
                    if len(sync_dispatches) != expected_dispatches:
                        raise AssertionError(f"expected {expected_dispatches} explicit/request dispatches in this scenario, observed {len(sync_dispatches)}")
                    if len({item["idempotency_key_sha256"] for item in sync_dispatches}) != len(sync_dispatches):
                        raise AssertionError("subsequent user-triggered syncs must use distinct idempotency keys")
                sidebar_tab_clicks = page.evaluate("window.__week4SidebarClicks")

            final_context = request_json(f"{api_base}/api/v1/projects/{PROJECT_ID}/site-context")
            final_workspace = final_context["current_workspace"]
            if final_workspace["revision"] != initial_revision + 3:
                raise AssertionError("disposable DB does not contain exactly three newly appended revisions")
            if final_workspace["feature_dispositions"] is None:
                raise AssertionError("workspace has no persisted feature dispositions")
            dispositions = {d["feature_id"]: d["disposition"] for d in final_workspace["feature_dispositions"]}
            annotations = {d["feature_id"]: d.get("annotation", "") for d in final_workspace["feature_dispositions"]}
            if (
                dispositions.get(building_id) != "editable"
                or dispositions.get(undecided_building_id) != "undecided"
                or dispositions.get(road_id) != "editable"
                or dispositions.get(box_selection["feature_id"]) != "editable"
            ):
                raise AssertionError("reloaded feature dispositions do not match the saved browser values")
            if annotations.get(box_selection["feature_id"]) != annotation_text:
                raise AssertionError("local feature annotation did not survive the second save and site-context reload")
            zones = final_workspace.get("spatial_brief", {}).get("zones", [])
            test_zone = next((zone for zone in zones if zone["name"] == "R02 browser test zone edited"), None)
            if len(zones) != initial_zone_count + 1 or test_zone is None:
                raise AssertionError("reloaded spatial brief does not match the drawn zone")
            first_revision_zones = persisted_first.get("spatial_brief", {}).get("zones", [])
            first_revision_zone = next(
                (zone for zone in first_revision_zones if zone.get("zone_id") == test_zone.get("zone_id")),
                None,
            )
            if first_revision_zone is None or not isinstance(first_revision_zone.get("geometry"), dict):
                raise AssertionError("first saved workspace revision does not contain the drawn zone geometry")
            canonical_first_geometry = json.dumps(
                first_revision_zone["geometry"], sort_keys=True, separators=(",", ":")
            )
            canonical_reloaded_geometry = json.dumps(
                test_zone.get("geometry"), sort_keys=True, separators=(",", ":")
            )
            if canonical_reloaded_geometry != canonical_first_geometry:
                raise AssertionError("fresh browser reload changed the first saved spatial zone geometry")
            zone_geometry_sha256 = hashlib.sha256(canonical_reloaded_geometry.encode("utf-8")).hexdigest()
            expected_draft_fields = {
                "program_demands": [*program_demands, "Community kitchen"],
                "open_space_demands": open_space_demands,
                "draft_constraints": draft_constraints,
                "draft_preferences": draft_preferences,
            }
            for field, expected_values in expected_draft_fields.items():
                if test_zone.get(field) != expected_values:
                    raise AssertionError(f"reloaded draft zone {field} do not match the designer's input")
            if test_zone.get("status") != "DRAFT_PENDING_HUMAN_DECISION":
                raise AssertionError("brief input became active without a Human Decision")
            if not zone_edit_verified or zone_edit_record is None:
                raise AssertionError("saved zone edit and fresh reload were not verified")
            if zone_edit_record["zone_id"] != test_zone.get("zone_id"):
                raise AssertionError("saved zone edit changed the zone identity")
            if zone_edit_record["geometry_sha256_before"] != zone_edit_record["geometry_sha256_after"]:
                raise AssertionError("saved zone edit changed geometry bytes")
            if test_zone.get("target_far") != {"value": 1.8, "unit": "ratio", "status": "DRAFT_PENDING_HUMAN_DECISION"}:
                raise AssertionError("saved zone edit did not persist the typed FAR draft value")
            if test_zone.get("target_height_m") != {"value": 21.0, "unit": "m", "status": "DRAFT_PENDING_HUMAN_DECISION"}:
                raise AssertionError("saved zone edit did not persist the typed height draft value")
            history = request_json(history_url)
            history_by_revision = {item["revision"]: item for item in history}
            for revision, prior_record in initial_history_by_revision.items():
                if history_by_revision.get(revision) != prior_record:
                    raise AssertionError(f"append-only sync modified pre-existing workspace revision {revision}")
            first_history_revision = next((item for item in history if item.get("revision") == persisted_first["revision"]), None)
            first_history_dispositions = {
                item["feature_id"]: item["disposition"]
                for item in (first_history_revision or {}).get("feature_dispositions", [])
            }
            if first_history_dispositions != first_dispositions:
                raise AssertionError("later sync modified the earlier revision's feature disposition history")
            if test_zone["geometry"]["coordinates"][0][0] != test_zone["geometry"]["coordinates"][0][-1]:
                raise AssertionError("persisted polygon ring is not closed")
            disposable_after = database_summary(db_path)
            live_db_hash_after = hashlib.sha256(source_db.read_bytes()).hexdigest()
            if live_db_hash_after != live_db_hash_before:
                raise AssertionError("authoritative SQLite changed during browser E2E")
            screenshots = [
                screenshot_dir / "00_box_selection.png",
                screenshot_dir / "00b_outside_zone_rejected.png",
                screenshot_dir / "00a_preserved_unlock_confirmation.png",
                screenshot_dir / "01_after_revision_one.png",
                screenshot_dir / "01a_measurement_against_source_road.png",
                screenshot_dir / "02_reload_syntax_readiness.png",
                screenshot_dir / "03_3d_schematic_preview.png",
                screenshot_dir / "03a_3d_road_selection.png",
                screenshot_dir / "03b_2d_road_selection.png",
                screenshot_dir / "03c_3d_road_selection_zoomed.png",
                screenshot_dir / "04_reloaded_draft_brief.png",
                screenshot_dir / "04a_edit_saved_draft_zone.png",
                screenshot_dir / "04b_edited_draft_zone_reloaded.png",
                screenshot_dir / "05_3d_figure_export_complete.png",
                screenshot_dir / "06_analysis_map_export_complete.png",
                figure_path,
                map_figure_path,
            ]
            return {
                "status": "PASS",
                "started_at_utc": started_at,
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "browser": f"Chromium {browser_version} (system Google Chrome)",
                "dirty_figure_export_guard": dirty_figure_export_guard,
                "fresh_browser_reload_verified": fresh_browser_reload_verified,
                "zone_edit_verified": zone_edit_verified,
                "cross_view_building_selection_verified": cross_view_building_selection_verified,
                "cross_view_road_selection_verified": cross_view_road_selection_verified,
                "zoomed_3d_road_selection_verified": zoomed_3d_road_selection_verified,
                "measurement_validation": measurement_record,
                "api_port": api_port,
                "web_port": web_port,
                "output_dir": output_descriptor,
                "api_process_pid": api_process.pid,
                "web_process_pid": web_process.pid if web_process else None,
                "source_package": context["source_package_id"],
                "source_package_revision": context["source_package_revision"],
                "study_area_id": context["study_area"]["id"],
                "schematic_3d_figure": {
                    "path": str(figure_path),
                    "sha256": hashlib.sha256(figure_bytes).hexdigest(),
                    "size_bytes": len(figure_bytes),
                    "dimensions_px": [figure_width, figure_height],
                    "mime_type": "image/png",
                    "download_name": figure_download.suggested_filename,
                    "source_package_revision": context["source_package_revision"],
                    "study_area_id": context["study_area"]["id"],
                    "workspace_revision": persisted_second["revision"],
                },
                "analysis_map_figure": {
                    "path": str(map_figure_path),
                    "sha256": hashlib.sha256(map_figure_bytes).hexdigest(),
                    "size_bytes": len(map_figure_bytes),
                    "dimensions_px": [map_figure_width, map_figure_height],
                    "mime_type": "image/png",
                    "download_name": map_figure_download.suggested_filename,
                    "figure_version": "week4-analysis-map-v1",
                    "analysis_status": "COMPUTED_EXPLORATORY",
                    "source_package_revision": context["source_package_revision"],
                    "study_area_id": context["study_area"]["id"],
                    "workspace_revision": persisted_second["revision"],
                    "scale_bar_unit": "m",
                    "north_arrow": "EPSG:28992 north",
                    "transient_box_selection_disables_export": True,
                },
                "building_id": building_id,
                "box_selected_building_id": box_selection["feature_id"],
                "box_selection_extent_epsg28992": list(box_selection["extent"]),
                "box_selection_disposition_after_reload": dispositions[box_selection["feature_id"]],
                "road_id": road_id,
                "road_selection": {
                    "feature_id": road_selection["feature_id"],
                    "pick_point_epsg28992": list(road_selection["point"]),
                    "canvas_point_px": list(road_selection["screen"]),
                    "status": "SELECTED_IN_3D_AND_PRESERVED_IN_2D",
                },
                "zoomed_road_selection": {
                    "feature_id": road_selection["feature_id"],
                    "camera_radius": zoomed_camera_radius,
                    "canvas_point_px": list(zoomed_road_pick),
                    "status": "SELECTED_IN_ZOOMED_3D_AND_PRESERVED_IN_2D",
                },
                "selection_scope": {
                    "status": "TRANSIENT_CROSS_VIEW_ONLY",
                    "selected_feature_id_persisted": False,
                    "limitation": "selectedFeatureId is UI-local and is not saved or restored; reload evidence covers saved dispositions, draft annotations, and draft zone geometry.",
                },
                "initial_revision": initial_revision,
                "created_revisions": [persisted_first["revision"], persisted_second["revision"], persisted_zone_edit["revision"]],
                "reloaded_dispositions": {
                    building_id: dispositions[building_id],
                    undecided_building_id: dispositions[undecided_building_id],
                    road_id: dispositions[road_id],
                },
                "reloaded_feature_annotation": {
                    "feature_id": box_selection["feature_id"],
                    "text": annotation_text,
                    "status": "DRAFT_ONLY",
                },
                "preserved_unlock_confirmation_verified": preserved_unlock_confirmation_verified,
                "zone": {
                    "name": test_zone["name"],
                    "ring_points": len(test_zone["geometry"]["coordinates"][0]),
                    "geometry_reload_status": "IDENTICAL_BEFORE_EDIT_AFTER_EDIT_AND_FRESH_RELOAD",
                    "geometry_sha256": zone_geometry_sha256,
                    "program_demands": test_zone.get("program_demands", []),
                    "open_space_demands": test_zone.get("open_space_demands", []),
                    "draft_constraints": test_zone.get("draft_constraints", []),
                    "draft_preferences": test_zone.get("draft_preferences", []),
                    "status": test_zone["status"],
                    "prior_draft_zones_preserved": initial_zone_count,
                    "saved_zone_edit": zone_edit_record,
                },
                "out_of_scope_zone_rejection": outside_zone_rejection,
                "preexisting_workspace_revisions_preserved": sorted(initial_history_by_revision),
                "syntax_state": "EXPLORATORY_800M_ONLY_SOURCE_COVERAGE_INSUFFICIENT",
                "evidence_cards_status": context["evidence_cards_status"],
                "evidence_bundle_sha256": context["evidence_bundle_sha256"],
                "selected_evidence_card_id": first_card["card_id"],
                "road_evidence_card": {
                    "card_id": road_card["card_id"],
                    "metric_key": road_card["metric_key"],
                    "api_value": road_card["value"],
                    "rendered_value": rendered_road_value,
                    "output_sha256": road_card["output_sha256"],
                },
                "site_analysis_evidence_cards": {
                    "bag_registered_gebruiksdoel_features": {
                        "card_id": usage_card["card_id"],
                        "value": usage_card["value"],
                        "rendered_value": usage_rendered_value,
                        "input_sha256": usage_card["input_sha256"],
                        "output_sha256": usage_card["output_sha256"],
                        "source_artifact_ids": usage_card["source_artifact_ids"],
                        "dataset_snapshot_ids": usage_card["dataset_snapshot_ids"],
                    },
                    "unclassified_surface_residual_area": {
                        "card_id": residual_card["card_id"],
                        "value": residual_card["value"],
                        "rendered_value": residual_rendered_value,
                        "input_sha256": residual_card["input_sha256"],
                        "output_sha256": residual_card["output_sha256"],
                        "source_artifact_ids": residual_card["source_artifact_ids"],
                        "dataset_snapshot_ids": residual_card["dataset_snapshot_ids"],
                    },
                },
                "syntax_computed_layer_ids": [layer["layer_id"] for layer in computed_syntax],
                "syntax_not_computed_layer_ids": [layer["layer_id"] for layer in planned_syntax if layer["calculation_status"] != "COMPUTED"],
                "downloaded_exploratory_figure": {
                    **describe_output_path(downloaded_path, project_root=ROOT),
                    "size_bytes": downloaded_path.stat().st_size,
                    "sha256": hashlib.sha256(downloaded_path.read_bytes()).hexdigest(),
                },
                "screenshots": [
                    {
                        **describe_output_path(item, project_root=ROOT),
                        "size_bytes": item.stat().st_size,
                        "sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
                    }
                    for item in screenshots
                ],
                "database": {
                    "disposable_copy": True,
                    "before": disposable_before,
                    "after": disposable_after,
                    "authoritative_live_db_hash_before": live_db_hash_before,
                    "authoritative_live_db_hash_after": live_db_hash_after,
                    "live_sqlite_written": False,
                },
                "outbound_model_requests": 0,
                "outbound_geodata_weather_requests": 0,
                "outbound_external_http_requests": 0,
                "blocked_external_request_attempts": blocked_external_requests,
                "non_local_font_requests": non_local_font_requests,
                "browser_api_targets": browser_api_targets,
                "unexpected_browser_api_targets": unexpected_browser_api_targets,
                "browser_api_responses": browser_api_responses,
                "browser_request_failures": browser_request_failures,
                "browser_console_errors": browser_console_errors,
                "sidebar_tab_diagnostics": tab_diagnostics,
                "sidebar_tab_clicks": sidebar_tab_clicks,
                "sync_dispatches": sync_dispatches,
                "first_sync_response_dropped_after_server_commit": drop_first_sync_response,
                "first_sync_request_failed_before_server_commit": drop_first_sync_before_commit,
                "dropped_sync_server_status": dropped_sync_response["status"] if dropped_sync_response else None,
            }
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            if web_process is not None:
                web_process.terminate()
                try:
                    web_process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    web_process.kill()
                    web_process.wait(timeout=3)
            api_process.terminate()
            try:
                api_process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                api_process.kill()
                api_process.wait(timeout=3)
            api_output.close()
            web_output.close()
            shutil.copy2(api_log, output_dir / "api-server.log")
            shutil.copy2(web_log, output_dir / "web-server.log")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the isolated Week 4 browser flow.")
    parser.add_argument("--api-port", type=int, default=None, help="unused loopback port; omitted selects one")
    parser.add_argument("--web-port", type=int, default=None, help="unused loopback port; omitted selects one")
    parser.add_argument("--output-dir", type=Path, default=None, help="fresh project-relative or absolute temporary output directory")
    parser.add_argument("--database", "--source-db", dest="source_db_path", type=Path, default=None, help="read-only SQLite seed copied into the disposable E2E database")
    parser.add_argument("--source-package", type=Path, default=None, help="verified spatial-r01 package directory used by the isolated API")
    parser.add_argument("--python-executable", type=Path, default=None, help="Python used to run the isolated workspace API")
    parser.add_argument(
        "--drop-first-sync-response",
        action="store_true",
        help="commit the first sync to the disposable API database, then drop the browser response to test reconciliation",
    )
    parser.add_argument(
        "--drop-first-sync-before-commit",
        action="store_true",
        help="abort the first sync before the API sees it, then verify reconciliation retains the draft for an explicit retry",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
    )
    arguments = parser.parse_args()
    if arguments.report is not None:
        try:
            require_new_report_path(arguments.report)
        except FileExistsError as exc:
            parser.error(str(exc))
    result = run(
        api_port=arguments.api_port,
        web_port=arguments.web_port,
        output_dir=arguments.output_dir,
        source_db_path=arguments.source_db_path,
        source_package_root=arguments.source_package,
        python_executable=arguments.python_executable,
        drop_first_sync_response=arguments.drop_first_sync_response,
        drop_first_sync_before_commit=arguments.drop_first_sync_before_commit,
    )
    output_record = result["output_dir"]
    output_dir = ROOT / output_record["path"] if output_record["kind"] == "project_relative" else Path(output_record["path"])
    report_path = require_new_report_path(arguments.report or output_dir / "report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as report_file:
        report_file.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True, indent=2))
