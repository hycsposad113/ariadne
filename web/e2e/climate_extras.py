#!/usr/bin/env python3
"""E2E Playwright test for Climate Extras Read-Only Viewer (W8, 2026-10-17).

Runs against temporary ports:
  API: 8981
  Web: 5981
Database:
  Disposable copy at /private/tmp/climate-1017-db/state.sqlite3
Artifact Root:
  /Users/jackhsieh/Downloads/TUD/Q5/project/artifacts/w8
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

API_PORT = 8981
WEB_PORT = 5981
API_URL = f"http://127.0.0.1:{API_PORT}"
WEB_URL = f"http://127.0.0.1:{WEB_PORT}"

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIMATE_ARTIFACT_ROOT = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/artifacts/w8")
DATABASE_PATH = Path("/private/tmp/climate-1017-db/state.sqlite3")
ORIGINAL_DATABASE = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3")
OUTPUT_DIR = REPO_ROOT / "artifacts/w8/rehearsal/climate-extras-1017"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PYTHON_BIN = REPO_ROOT / ".venv/bin/python"


def stop_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            proc.kill()
        proc.wait(timeout=5)


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
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not ORIGINAL_DATABASE.is_file():
        raise FileNotFoundError(f"Original database not found: {ORIGINAL_DATABASE}")
    # Backup using sqlite3 tool to ensure clean atomic copy
    subprocess.run(
        ["sqlite3", str(ORIGINAL_DATABASE), f".backup {DATABASE_PATH}"],
        check=True,
    )
    if not DATABASE_PATH.is_file():
        raise RuntimeError(f"Failed to create disposable database copy: {DATABASE_PATH}")


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
        "--database", str(DATABASE_PATH),
        "--climate-artifact-root", str(CLIMATE_ARTIFACT_ROOT),
    ]

    log_file = log_path.open("wb")
    proc = subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
    )
    return proc


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
    proc = subprocess.Popen(
        cmd,
        cwd=REPO_ROOT / "web",
        env=env,
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
    )
    return proc


def main() -> int:
    api_proc: subprocess.Popen | None = None
    web_proc: subprocess.Popen | None = None
    api_log = OUTPUT_DIR / "api.log"
    web_log = OUTPUT_DIR / "web.log"

    console_errors: list[str] = []
    page_errors: list[str] = []
    missing_sections: list[str] = []
    ok_sections: list[str] = []

    try:
        print("[1/5] Creating disposable database copy...")
        ensure_disposable_database()

        print(f"[2/5] Starting API server on port {API_PORT}...")
        api_proc = start_backend(api_log)
        wait_for_port(API_PORT, timeout=30.0)

        # Check API response
        req = urllib.request.Request(f"{API_URL}/api/v1/environment/climate-extras")
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.load(resp)
            for sec in data:
                if sec.get("status") == "MISSING":
                    missing_sections.append(sec.get("id"))
                else:
                    ok_sections.append(sec.get("id"))
        print(f"      API responded: OK sections={ok_sections}, MISSING sections={missing_sections}")

        print(f"[3/5] Starting Web dev server on port {WEB_PORT}...")
        web_proc = start_frontend(web_log)
        wait_for_port(WEB_PORT, timeout=30.0)

        print("[4/5] Running Playwright browser tests and capturing screenshots...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1400})
            page = context.new_page()

            def on_console(msg):
                if msg.type == "error":
                    console_errors.append(msg.text)
                    print(f"      [Browser Console Error] {msg.text}")

            def on_pageerror(err):
                page_errors.append(str(err))
                print(f"      [Browser Page Error] {err}")

            page.on("console", on_console)
            page.on("pageerror", on_pageerror)

            # --- Chinese (zh-TW) run ---
            print("      Navigating in Traditional Chinese (zh-TW)...")
            page.add_init_script("localStorage.setItem('urban-design-language', 'zh-TW');")
            page.goto(f"{WEB_URL}/", wait_until="networkidle")

            # Click stage compare button
            page.wait_for_selector("#stage-compare", timeout=15000)
            page.click("#stage-compare")

            # Wait for climate extras panel to appear and load
            page.wait_for_selector('[data-testid="climate-extras-panel"]', timeout=15000)
            page.wait_for_selector('[data-testid="climate-section-e1-fabric"]', timeout=15000)

            # Scroll panel into view and capture screenshots
            panel = page.locator('[data-testid="climate-extras-panel"]')
            panel.scroll_into_view_if_needed()
            page.wait_for_timeout(1000)

            zh_screenshot_path = OUTPUT_DIR / "climate-extras-zh.png"
            page.screenshot(path=str(zh_screenshot_path), full_page=True)
            print(f"      Saved Chinese full-page screenshot: {zh_screenshot_path}")

            zh_panel_screenshot_path = OUTPUT_DIR / "climate-extras-panel-zh.png"
            panel.screenshot(path=str(zh_panel_screenshot_path))
            print(f"      Saved Chinese panel screenshot: {zh_panel_screenshot_path}")

            # Capture sections scrolled into view (Chinese)
            page.locator('[data-testid="climate-section-utci"]').scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUTPUT_DIR / "climate-extras-utci-zh.png"))

            page.locator('[data-testid="climate-section-e3-energy"]').scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUTPUT_DIR / "climate-extras-e3e4-zh.png"))

            page.locator('[data-testid="climate-section-e5-cfd"]').scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUTPUT_DIR / "climate-extras-e5-zh.png"))

            # --- English (en) run ---
            print("      Switching to English (en)...")
            page.click("#language-toggle")
            page.wait_for_timeout(1000)

            # Wait for English header title
            page.wait_for_selector("text=Additional Climate Simulations (Exploratory)", timeout=10000)
            panel.scroll_into_view_if_needed()
            page.wait_for_timeout(1500)

            en_screenshot_path = OUTPUT_DIR / "climate-extras-en.png"
            page.screenshot(path=str(en_screenshot_path), full_page=True)
            print(f"      Saved English full-page screenshot: {en_screenshot_path}")

            en_panel_screenshot_path = OUTPUT_DIR / "climate-extras-panel-en.png"
            panel.screenshot(path=str(en_panel_screenshot_path))
            print(f"      Saved English panel screenshot: {en_panel_screenshot_path}")

            # Capture sections scrolled into view (English)
            page.locator('[data-testid="climate-section-utci"]').scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUTPUT_DIR / "climate-extras-utci-en.png"))

            page.locator('[data-testid="climate-section-e3-energy"]').scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUTPUT_DIR / "climate-extras-e3e4-en.png"))

            page.locator('[data-testid="climate-section-e5-cfd"]').scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUTPUT_DIR / "climate-extras-e5-en.png"))

            browser.close()

    except Exception as exc:
        print(f"ERROR during e2e execution: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    finally:
        print("[5/5] Shutting down temporary servers...")
        stop_process(web_proc)
        stop_process(api_proc)
        print("      Servers stopped.")

    # Write report
    report_path = OUTPUT_DIR / "REPORT.md"
    total_errors = len(console_errors) + len(page_errors)
    status_str = "PASS" if total_errors == 0 else "FAIL"

    report_content = f"""# Climate Extras Viewer Rehearsal Report (W8, 2026-10-17)

- **Date**: 2026-10-17
- **API Port**: {API_PORT}
- **Web Port**: {WEB_PORT}
- **Database Copy**: `{DATABASE_PATH}`
- **Climate Artifact Root**: `{CLIMATE_ARTIFACT_ROOT}`
- **Result**: {status_str}
- **Console Errors**: {len(console_errors)}
- **Page Uncaught Exceptions**: {len(page_errors)}
- **OK Sections**: {', '.join(ok_sections) if ok_sections else 'None'}
- **MISSING Sections**: {', '.join(missing_sections) if missing_sections else 'None'}

## Screenshots
- Chinese (`zh-TW`): [`climate-extras-zh.png`](./climate-extras-zh.png)
- English (`en`): [`climate-extras-en.png`](./climate-extras-en.png)

## Console Error Log
{chr(10).join(f"- `{e}`" for e in console_errors) if console_errors else "Zero console errors."}

## Page Exceptions
{chr(10).join(f"- `{e}`" for e in page_errors) if page_errors else "Zero page exceptions."}
"""
    report_path.write_text(report_content, encoding="utf-8")
    print(f"Rehearsal report written to: {report_path}")

    if total_errors > 0:
        print(f"FAILURE: Detected {total_errors} errors in browser rehearsal!", file=sys.stderr)
        return 1

    print("SUCCESS: Browser rehearsal completed with 0 errors!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
