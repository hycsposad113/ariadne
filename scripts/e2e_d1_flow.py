#!/usr/bin/env python3
"""Browser E2E test for Week 5 Day 1 Human Decision workflow.

Runs against an isolated database copy and temporary decision key.
Captures screenshots into artifacts/week5-d1-flow-evidence/.
"""

import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import urllib.request
import uuid

# Ensure urban_design is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from urban_design.decision_key import initialize_decision_key
from urban_design.e2e_ports import resolve_e2e_ports

LIVE_DATABASE = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3")
VENV_PYTHON = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python")
PYENV_PYTHON = Path("/Users/jackhsieh/.pyenv/shims/python3")
EVIDENCE_DIR = PROJECT_ROOT / "artifacts" / "week5-d1-flow-evidence"


def wait_for_url(url: str, timeout_sec: float = 20.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def run_e2e():
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="w5_d1_e2e_"))
    temp_db = temp_dir / "test_state.sqlite3"
    temp_key = temp_dir / "test_decision_key"
    test_secret = "Test-Decision-Key-2026-D1!"

    api_proc = None
    vite_proc = None

    try:
        print(f"[E2E] Preparing isolated DB copy from {LIVE_DATABASE}...")
        with sqlite3.connect(f"file:{LIVE_DATABASE}?mode=ro", uri=True) as src:
            src.execute("PRAGMA query_only=ON")
            with sqlite3.connect(temp_db) as dst:
                src.backup(dst)

        print("[E2E] Initializing temporary test decision key...")
        initialize_decision_key(path=temp_key, password_prompt=lambda _: test_secret)

        api_port, web_port = resolve_e2e_ports()
        print(f"[E2E] Selected ephemeral ports: API={api_port}, Web={web_port}")

        api_env = os.environ.copy()
        api_env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        api_env["PYTHONDONTWRITEBYTECODE"] = "1"

        print(f"[E2E] Launching API server on port {api_port}...")
        api_cmd = [
            str(VENV_PYTHON),
            str(PROJECT_ROOT / "scripts" / "run_workspace_server.py"),
            "--host", "127.0.0.1",
            "--port", str(api_port),
            "--database", str(temp_db),
            "--decision-key-path", str(temp_key),
        ]
        api_proc = subprocess.Popen(
            api_cmd,
            cwd=str(PROJECT_ROOT),
            env=api_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        api_health_url = f"http://127.0.0.1:{api_port}/health"
        if not wait_for_url(api_health_url, timeout_sec=15.0):
            raise RuntimeError(f"API server failed to start on {api_health_url}")
        print("[E2E] API server is healthy.")

        print(f"[E2E] Launching Vite dev server on port {web_port}...")
        vite_env = os.environ.copy()
        vite_env["VITE_API_BASE"] = f"http://127.0.0.1:{api_port}"
        vite_cmd = [
            "npm", "--prefix", "web", "run", "dev", "--",
            "--host", "127.0.0.1",
            "--port", str(web_port),
        ]
        vite_proc = subprocess.Popen(
            vite_cmd,
            cwd=str(PROJECT_ROOT),
            env=vite_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )

        web_url = f"http://127.0.0.1:{web_port}"
        if not wait_for_url(web_url, timeout_sec=20.0):
            raise RuntimeError(f"Vite dev server failed to start on {web_url}")
        print(f"[E2E] Web server is up at {web_url}.")

        # Execute browser steps with Playwright
        print("[E2E] Starting Playwright browser...")
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1600, "height": 960})
            page = context.new_page()

            page.on("console", lambda msg: print(f"[Browser Console] {msg.text}"))
            page.on("pageerror", lambda err: print(f"[Browser Error] {err}"))
            page.on("requestfailed", lambda req: print(f"[Req Failed] {req.method} {req.url} - {req.failure}"))
            page.on("response", lambda res: print(f"[Response {res.status}] {res.url}") if res.status >= 400 else None)

            print(f"[E2E] Navigating to {web_url}...")
            page.goto(web_url)

            # Wait for header identity to load
            page.wait_for_selector("#header-project-id", timeout=30000)
            page.wait_for_selector("#status-authority", timeout=30000)
            for _ in range(40):
                text = page.inner_text("#status-authority")
                if "In Sync (Server Authority)" in text:
                    print(f"[E2E] Authority in sync: '{text}'")
                    break
                print(f"[E2E] Waiting for sync, current #status-authority: '{text}'")
                time.sleep(1.0)
            else:
                raise RuntimeError(f"Timeout waiting for In Sync (Server Authority), current text: {page.inner_text('#status-authority')}")
            time.sleep(1.0)  # stabilize render

            screenshot1 = EVIDENCE_DIR / "d1_01_workspace_loaded.png"
            page.screenshot(path=str(screenshot1), full_page=False)
            print(f"[E2E] Captured screenshot 1: {screenshot1}")

            # Verify initial decision badge is DRAFT / unconfirmed
            d1_badge = page.wait_for_selector("#badge-d1-decision")
            badge_text = d1_badge.inner_text()
            print(f"[E2E] Initial D1 badge text: {badge_text}")
            assert "未確認" in badge_text or "DRAFT" in badge_text

            # Click Confirm D1 Decision button
            confirm_btn = page.wait_for_selector("#btn-confirm-d1-decision")
            assert confirm_btn.is_enabled()
            print("[E2E] Clicking #btn-confirm-d1-decision...")
            confirm_btn.click()

            # Wait for dialog modal
            page.wait_for_selector('[role="dialog"]', timeout=8000)
            print("[E2E] [role='dialog'] appeared!")
            time.sleep(1.0)

            # Wait for HumanDecisionDialog and summary to appear
            page.wait_for_selector('[data-testid="d1-dialog-summary"]', timeout=8000)
            page.wait_for_selector('[data-testid="d1-dialog-eda-card"]', timeout=5000)
            page.wait_for_selector('[data-testid="d1-dialog-buildings-summary"]', timeout=5000)
            page.wait_for_selector('[data-testid="d1-dialog-roads-summary"]', timeout=5000)

            # Expand details for preserve buildings
            details_elem = page.query_selector('[data-testid="details-buildings-preserve"] > summary')
            if details_elem:
                details_elem.click()
                time.sleep(0.3)

            screenshot2 = EVIDENCE_DIR / "d1_02_decision_dialog_summary.png"
            page.screenshot(path=str(screenshot2), full_page=False)
            print(f"[E2E] Captured screenshot 2: {screenshot2}")

            # Input decision key and submit
            key_input = page.wait_for_selector('input[type="password"]')
            key_input.fill(test_secret)

            submit_btn = page.wait_for_selector('[data-testid="d1-dialog-submit-btn"]')
            assert submit_btn.is_enabled()
            submit_btn.click()

            # Wait for dialog to close
            page.wait_for_selector('[role="dialog"]', state="detached", timeout=10000)
            print("[E2E] Decision submitted, dialog closed.")

            # Wait for badge to update to approved
            page.wait_for_selector('#badge-d1-decision:has-text("approved")', timeout=10000)
            approved_badge_text = page.inner_text("#badge-d1-decision")
            print(f"[E2E] Approved D1 badge text: {approved_badge_text}")
            assert "approved" in approved_badge_text

            # Switch to Spatial Brief and verify callout
            page.wait_for_selector("#sidebar-tab-brief")
            page.evaluate("document.getElementById('sidebar-tab-brief').click()")
            page.wait_for_selector("#brief-decision-callout", timeout=10000)
            callout_text = page.inner_text("#brief-decision-callout")
            print(f"[E2E] Brief callout text: {callout_text}")
            assert "決策已確認" in callout_text

            page.evaluate("window.scrollTo(0, 0); document.documentElement.scrollTop = 0; document.documentElement.scrollLeft = 0;")
            time.sleep(0.5)
            screenshot3 = EVIDENCE_DIR / "d1_03_decision_approved.png"
            page.screenshot(path=str(screenshot3), full_page=False)
            print(f"[E2E] Captured screenshot 3: {screenshot3}")

            # Advance workspace revision on server to simulate further editing
            print("[E2E] Advancing workspace revision to test stale version detection...")
            ws_get_req = urllib.request.Request(f"http://127.0.0.1:{api_port}/api/v1/workspaces/workspace-rotterdam-m4h-pilot-project")
            with urllib.request.urlopen(ws_get_req) as resp:
                current_ws = json.loads(resp.read().decode("utf-8"))
            confirmed_rev = current_ws["revision"]
            print(f"[E2E] Current workspace revision confirmed by decision: {confirmed_rev}")

            sync_req = urllib.request.Request(
                f"http://127.0.0.1:{api_port}/api/v1/workspaces/sync",
                data=json.dumps({
                    "project_id": "rotterdam-m4h-pilot-project",
                    "study_area_id": current_ws["study_area_id"],
                    "expected_workspace_revision": confirmed_rev,
                    "source_snapshot_ids": current_ws["source_snapshot_ids"],
                    "idempotency_key": f"e2e-rev-advance-{uuid.uuid4().hex[:8]}",
                    "actor_kind": "HUMAN_UI",
                    "actor_session_id": "e2e-session",
                    "feature_dispositions": current_ws.get("feature_dispositions", []),
                    "spatial_brief": {
                        "zones": [],
                        "status": "DRAFT_PENDING_HUMAN_DECISION",
                    },
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(sync_req) as resp:
                assert resp.status in (200, 201)
                sync_result = json.loads(resp.read().decode("utf-8"))
                new_rev = sync_result["workspace_revision"]["revision"]
                print(f"[E2E] Successfully advanced workspace revision to: {new_rev}")

            # Click Reload button on page
            page.wait_for_selector("#btn-reload-workspace")
            page.evaluate("document.getElementById('btn-reload-workspace').click()")
            time.sleep(1.0)

            # Wait for badge to report stale prior revision
            page.wait_for_selector('#badge-d1-decision:has-text("對應舊版本")', timeout=10000)
            stale_badge_text = page.inner_text("#badge-d1-decision")
            print(f"[E2E] Stale D1 badge text: {stale_badge_text}")
            assert f"對應舊版本 rev {confirmed_rev}" in stale_badge_text

            # Verify callout reports stale prior revision
            stale_callout_text = page.inner_text("#brief-decision-callout")
            print(f"[E2E] Stale callout text: {stale_callout_text}")
            assert "對應舊版本" in stale_callout_text

            page.evaluate("window.scrollTo(0, 0); document.documentElement.scrollTop = 0; document.documentElement.scrollLeft = 0;")
            time.sleep(0.5)
            screenshot4 = EVIDENCE_DIR / "d1_04_decision_stale_prior_rev.png"
            page.screenshot(path=str(screenshot4), full_page=False)
            print(f"[E2E] Captured screenshot 4: {screenshot4}")

            browser.close()

        print("\n[E2E] All browser steps succeeded!")
        print("[E2E] Evidence screenshots:")
        for p in sorted(EVIDENCE_DIR.glob("d1_*.png")):
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            size = p.stat().st_size
            print(f"  - {p.name}: {size:,} bytes | sha256:{sha}")

    finally:
        print("[E2E] Cleaning up processes...")
        if vite_proc:
            try:
                os.killpg(os.getpgid(vite_proc.pid), signal.SIGTERM)
            except Exception:
                vite_proc.kill()
        if api_proc:
            try:
                api_proc.terminate()
                api_proc.wait(timeout=3)
            except Exception:
                api_proc.kill()
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        print("[E2E] Cleanup finished.")


if __name__ == "__main__":
    run_e2e()
