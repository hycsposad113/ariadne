#!/usr/bin/env python3
"""P4b Playwright Browser Rehearsal Script.
Captures screenshots of E2 Workspace in Traditional Chinese and English on disposable DB copy.
Strict prohibitions enforced:
- NO passphrases entered or printed
- NO decisions submitted
- NO simulate calls dispatched
- Ports used: 8996 (backend), 5996 (frontend)
- Database: Read-only copy from authoritative runtime DB
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

API_PORT = 8996
WEB_PORT = 5996
API_URL = f"http://127.0.0.1:{API_PORT}"
WEB_URL = f"http://127.0.0.1:{WEB_PORT}"

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIMATE_ARTIFACT_ROOT = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/artifacts/w8")
ORIGINAL_STATE_DB = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3")
ORIGINAL_JOBS_DB = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/e2-jobs.sqlite3")

TMP_DB_DIR = Path("/private/tmp/p4b-db")
DISPOSABLE_STATE_DB = TMP_DB_DIR / "state.sqlite3"
DISPOSABLE_JOBS_DB = TMP_DB_DIR / "e2-jobs.sqlite3"

OUTPUT_DIR = REPO_ROOT / "artifacts/w8/rehearsal/p4b-e2-ui"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PYTHON_BIN = REPO_ROOT / ".venv/bin/python"


def stop_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, AttributeError):
        proc.terminate()
    try:
        proc.wait(timeout=6)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, AttributeError):
            proc.kill()
        proc.wait(timeout=4)


def wait_for_port(port: int, timeout: float = 30.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return
        except (OSError, ConnectionRefusedError):
            time.sleep(0.3)
    raise TimeoutError(f"Port {port} failed to become available within {timeout}s")


def ensure_disposable_database() -> None:
    TMP_DB_DIR.mkdir(parents=True, exist_ok=True)
    if not ORIGINAL_STATE_DB.is_file():
        raise FileNotFoundError(f"Original state database not found: {ORIGINAL_STATE_DB}")

    # Backup state.sqlite3 using SQLite URI mode=ro
    if DISPOSABLE_STATE_DB.exists():
        DISPOSABLE_STATE_DB.unlink()
    subprocess.run(
        ["sqlite3", f"file://{ORIGINAL_STATE_DB}?mode=ro", f".backup {DISPOSABLE_STATE_DB}"],
        check=True,
    )

    # Backup e2-jobs.sqlite3 if present
    if ORIGINAL_JOBS_DB.is_file():
        if DISPOSABLE_JOBS_DB.exists():
            DISPOSABLE_JOBS_DB.unlink()
        subprocess.run(
            ["sqlite3", f"file://{ORIGINAL_JOBS_DB}?mode=ro", f".backup {DISPOSABLE_JOBS_DB}"],
            check=True,
        )


def start_backend(log_path: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env.pop("PROJECT_AI_AUTHORIZED", None)
    env.pop("ARIADNE_LIVE", None)

    cmd = [
        str(PYTHON_BIN),
        "scripts/run_workspace_server.py",
        "--host", "127.0.0.1",
        "--port", str(API_PORT),
        "--database", str(DISPOSABLE_STATE_DB),
        "--climate-artifact-root", str(CLIMATE_ARTIFACT_ROOT),
    ]
    if DISPOSABLE_JOBS_DB.is_file():
        cmd.extend(["--e2-job-database", str(DISPOSABLE_JOBS_DB)])

    log_file = log_path.open("wb")
    return subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
    )


def start_frontend(log_path: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["VITE_API_BASE"] = API_URL
    env["BROWSER"] = "none"

    cmd = [
        "npx", "--no-install", "vite",
        "--host", "127.0.0.1",
        "--port", str(WEB_PORT),
        "--strictPort",
    ]

    log_file = log_path.open("wb")
    return subprocess.Popen(
        cmd,
        cwd=REPO_ROOT / "web",
        env=env,
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
    )


def main() -> int:
    backend_proc = None
    frontend_proc = None
    log_dir = OUTPUT_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    backend_log = log_dir / "backend.log"
    frontend_log = log_dir / "frontend.log"

    try:
        print("[1/5] Creating disposable database copy (mode=ro)...")
        ensure_disposable_database()

        print(f"[2/5] Starting backend on port {API_PORT}...")
        backend_proc = start_backend(backend_log)
        wait_for_port(API_PORT, timeout=25.0)
        print("Backend ready.")

        print(f"[3/5] Starting frontend on port {WEB_PORT}...")
        frontend_proc = start_frontend(frontend_log)
        wait_for_port(WEB_PORT, timeout=25.0)
        print("Frontend ready.")

        print("[4/5] Running Playwright browser rehearsal...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            page.on("console", lambda msg: print(f"[Browser {msg.type}] {msg.text}"))
            page.on("pageerror", lambda exc: print(f"[Browser Error] {exc}"))
            page.on("request", lambda req: print(f"[Req] {req.method} {req.url}") if "e2" in req.url else None)
            page.on("response", lambda resp: print(f"[Resp] {resp.status} {resp.url}") if "e2" in resp.url else None)
            page.on("requestfailed", lambda req: print(f"[ReqFailed] {req.method} {req.url}: {req.failure}"))

            # Navigate to platform
            page.goto(WEB_URL, wait_until="networkidle")
            page.wait_for_selector(".design-shell", timeout=15000)

            # Switch to Compare stage
            page.click("#stage-compare")
            page.wait_for_selector("#compare-climate-environment", timeout=15000)

            # Scroll into Climate & Environment section
            climate_section = page.locator("#compare-climate-environment")
            climate_section.scroll_into_view_if_needed()

            # Click E2 tab
            e2_tab_btn = page.locator('button[role="tab"]:has-text("E2 夏季輻射實驗"), button[role="tab"]:has-text("E2 Summer Radiation")')
            e2_tab_btn.first.click()
            page.wait_for_selector(".e2-workspace", timeout=15000)
            # Allow initial fetches to complete and pin responses to settle
            try:
                page.wait_for_response(lambda r: "common-mixed" in r.url and r.status == 200, timeout=25000)
            except Exception:
                pass
            try:
                page.wait_for_response(lambda r: "harbour" in r.url and r.status == 200, timeout=25000)
            except Exception:
                pass
            time.sleep(1)

            # Click view full table if available to show Step 6 comparisons table
            table_btn = page.locator('.e2-workspace button:has-text("查看完整結果表")').first
            if table_btn.is_visible():
                table_btn.click()
                time.sleep(1)

            # Switch comparison scenario to compact (which is unaccepted) to reveal decision button
            mod_select = page.locator('.e2-workspace select').nth(1)
            print("Initial modified scenario:", mod_select.input_value())
            with page.expect_response(lambda r: "common-compact" in r.url and r.status == 200, timeout=35000):
                mod_select.select_option("formal-dict-3da03eb0172d-common-compact-a1ff97864a21")
            print("After select option and response received:", mod_select.input_value())

            page.wait_for_selector('.e2-workspace button:has-text("接受此方案（需你的決策密語）")', timeout=5000)
            decision_btn = page.locator('.e2-workspace button:has-text("接受此方案（需你的決策密語）")').first
            decision_btn.click()
            page.wait_for_selector('[role="dialog"]', timeout=5000)
            dialog_zh_path = OUTPUT_DIR / "e2-decision-dialog-zh.png"
            page.locator('[role="dialog"]').screenshot(path=str(dialog_zh_path))
            print(f"Captured: {dialog_zh_path}")

            # Close dialog via Cancel button without submitting or entering key
            cancel_btn = page.locator('[role="dialog"] button:has-text("取消")').first
            cancel_btn.click()
            page.wait_for_selector('[role="dialog"]', state="detached", timeout=5000)
            time.sleep(0.5)

            # Switch back to harbour scenario
            with page.expect_response(lambda r: "harbour" in r.url and r.status == 200, timeout=25000):
                mod_select.select_option("formal-fabric-harbour-grain-88445febe1b6")
            time.sleep(0.5)

            # 1. Screenshot E2 Workspace (Traditional Chinese)
            e2_workspace = page.locator(".e2-workspace")
            e2_workspace.scroll_into_view_if_needed()
            zh_screenshot_path = OUTPUT_DIR / "e2-workspace-zh.png"
            e2_workspace.screenshot(path=str(zh_screenshot_path))
            print(f"Captured: {zh_screenshot_path}")

            # 2. Switch language to English
            page.click("#language-toggle")
            page.wait_for_selector('.e2-workspace:has-text("E2 Summer Incident Radiation Experiment")', timeout=5000)
            time.sleep(1)

            # In English: switch to compact to reveal English decision dialog
            mod_select_en = page.locator('.e2-workspace select').nth(1)
            with page.expect_response(lambda r: "common-compact" in r.url and r.status == 200, timeout=35000):
                mod_select_en.select_option("formal-dict-3da03eb0172d-common-compact-a1ff97864a21")
            print("After select option in English and response received")

            page.wait_for_selector('.e2-workspace button:has-text("Accept Scenario (requires your decision passphrase)")', timeout=5000)
            decision_btn_en = page.locator('.e2-workspace button:has-text("Accept Scenario (requires your decision passphrase)")').first
            decision_btn_en.click()
            page.wait_for_selector('[role="dialog"]', timeout=5000)
            dialog_en_path = OUTPUT_DIR / "e2-decision-dialog-en.png"
            page.locator('[role="dialog"]').screenshot(path=str(dialog_en_path))
            print(f"Captured: {dialog_en_path}")

            # Close dialog
            cancel_btn_en = page.locator('[role="dialog"] button:has-text("Cancel")').first
            cancel_btn_en.click()
            page.wait_for_selector('[role="dialog"]', state="detached", timeout=5000)
            time.sleep(0.5)

            # Switch back to harbour
            with page.expect_response(lambda r: "harbour" in r.url and r.status == 200, timeout=25000):
                mod_select_en.select_option("formal-fabric-harbour-grain-88445febe1b6")
            time.sleep(0.5)

            # Click view full table if available
            table_btn_en = page.locator('.e2-workspace button:has-text("View Full Table")').first
            if table_btn_en.is_visible():
                table_btn_en.click()
                time.sleep(1)

            # Screenshot E2 Workspace (English)
            en_screenshot_path = OUTPUT_DIR / "e2-workspace-en.png"
            e2_workspace.screenshot(path=str(en_screenshot_path))
            print(f"Captured: {en_screenshot_path}")

            browser.close()

        print("[5/5] Rehearsal completed successfully!")
        return 0

    except Exception as e:
        print(f"Rehearsal failed: {e}", file=sys.stderr)
        return 1

    finally:
        print("Cleaning up processes...")
        stop_process(frontend_proc)
        stop_process(backend_proc)
        print("Cleanup done.")


if __name__ == "__main__":
    sys.exit(main())
