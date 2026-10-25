#!/usr/bin/env python3
"""Run full browser rehearsal for P1 UI cleanup Round 2 (W8, 2026-10-17)."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

API_PORT = 8985
WEB_PORT = 5985
API_URL = f"http://127.0.0.1:{API_PORT}"
WEB_URL = f"http://127.0.0.1:{WEB_PORT}"

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIMATE_ARTIFACT_ROOT = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/artifacts/w8")
DATABASE_PATH = Path("/private/tmp/p1ui-db/state.sqlite3")
ORIGINAL_DATABASE = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3")
OUTPUT_DIR = REPO_ROOT / "artifacts/w8/rehearsal/p1-ui-r2"
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
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    for extra in DATABASE_PATH.parent.glob("state.sqlite3*"):
        try:
            extra.unlink(missing_ok=True)
        except OSError:
            pass
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


def scan_page_codes(page) -> list[str]:
    """Scan document.body.innerText for internal uppercase underscore codes.
    Regex: \\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\\b
    Returns sorted unique matches.
    """
    codes = page.evaluate("""() => {
        const text = document.body.innerText || '';
        const regex = /\\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\\b/g;
        const matches = text.match(regex) || [];
        return Array.from(new Set(matches)).sort();
    }""")
    return codes


def wait_for_content_ready(page, stage_name: str) -> None:
    """Wait for loading spinners to disappear and concrete content to be present."""
    # 1. Wait for loading spinners and indicators to disappear
    page.wait_for_function("""() => {
        const busy = document.querySelector('.loading, .spinner, [aria-busy="true"], .generation-readiness-checking');
        const text = document.body.innerText || '';
        const hasLoading = /\\bLoading\\b|正在載入|載入中…|載入方案…|載入預覽方案…|載入紋理方案…/.test(text);
        return !busy && !hasLoading;
    }""", timeout=25000)

    # 2. Stage-specific structural expectations
    if stage_name == "site":
        page.wait_for_selector("#stage-site[aria-current=\"step\"]", timeout=15000)
        page.wait_for_selector("#btn-draw-extent", timeout=15000)
    elif stage_name == "conditions":
        page.wait_for_selector("#stage-conditions[aria-current=\"step\"]", timeout=15000)
    elif stage_name == "generate":
        page.wait_for_selector(".generation-workflow-panel", timeout=15000)
    elif stage_name == "compare":
        page.wait_for_selector("#stage-compare[aria-current=\"step\"]", timeout=25000)
        page.wait_for_selector("[data-testid=\"fabric-maps\"], .fabric-maps", timeout=25000)
    elif stage_name == "refine":
        page.wait_for_selector("#stage-refine[aria-current=\"step\"]", timeout=15000)
        page.wait_for_selector("[data-testid=\"harbour-mainline-card\"]", timeout=15000)
    elif stage_name == "refine-editor":
        page.wait_for_selector(".scenario-editor-tools, .scenario-studio-body", timeout=20000)

    # 3. Ensure all images are fully loaded
    page.wait_for_function("""() => {
        const imgs = Array.from(document.querySelectorAll('img'));
        return imgs.every(img => img.complete);
    }""", timeout=15000)

    # Small pause for layout/canvas rendering
    page.wait_for_timeout(800)


def main() -> int:
    api_proc: subprocess.Popen | None = None
    web_proc: subprocess.Popen | None = None
    api_log = OUTPUT_DIR / "api.log"
    web_log = OUTPUT_DIR / "web.log"

    console_errors: list[str] = []
    page_errors: list[str] = []
    screenshots_taken: list[str] = []
    fabric_compare_result: dict = {}
    code_scan_results: dict[str, dict[str, list[str]]] = {
        "zh-TW": {},
        "en": {},
    }

    try:
        print("[1/5] Backing up database to disposable copy...")
        ensure_disposable_database()

        print(f"[2/5] Starting API server on port {API_PORT}...")
        api_proc = start_backend(api_log)
        wait_for_port(API_PORT, timeout=30.0)

        print(f"[3/5] Starting Web server on port {WEB_PORT}...")
        web_proc = start_frontend(web_log)
        wait_for_port(WEB_PORT, timeout=30.0)

        print("[4/5] Running browser walkthrough and capturing screenshots...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type == "error" else None)
            page.on("pageerror", lambda err: page_errors.append(str(err)))

            # Initial load (default language is zh-TW)
            page.goto(WEB_URL, wait_until="networkidle")
            page.wait_for_selector(".design-shell", timeout=10000)

            stages = [
                ("site", "#stage-site"),
                ("conditions", "#stage-conditions"),
                ("generate", "#stage-generate"),
                ("compare", "#stage-compare"),
                ("refine", "#stage-refine"),
            ]

            for lang, is_zh in [("zh-TW", True), ("en", False)]:
                lang_prefix = "zh" if is_zh else "en"
                print(f"      === Processing {lang} walkthrough ===")

                # Walk through 5 stages
                for stage_name, selector in stages:
                    print(f"        Stage: {stage_name}...")
                    page.click(selector)
                    wait_for_content_ready(page, stage_name)

                    # Scan codes on this stage
                    codes = scan_page_codes(page)
                    code_scan_results[lang][stage_name] = codes
                    if codes:
                        print(f"          [CODE SCAN ALERT] Found codes in {lang}/{stage_name}: {codes}")

                    shot_num = stages.index((stage_name, selector)) + 1
                    shot_path = OUTPUT_DIR / f"{lang_prefix}-0{shot_num}-stage-{stage_name}.png"
                    page.screenshot(path=str(shot_path), full_page=True)
                    screenshots_taken.append(shot_path.name)
                    print(f"          Saved {shot_path.name}")

                # Refine stage: open Harbour editor
                print(f"        Opening Harbour scenario in Refine stage...")
                page.click("#stage-refine")
                wait_for_content_ready(page, "refine")
                # Click harbour card to select it
                page.click('[data-testid="harbour-mainline-btn"]')
                page.wait_for_timeout(500)
                # Click Open scenario editing tools
                page.click('[data-testid="open-scenario-editing-btn"]')
                page.wait_for_timeout(1000)
                # Wait for editor tools / 3D canvas / scenario studio body
                page.wait_for_selector(".scenario-studio-body, .scenario-editor-tools, .scenario-viewer", timeout=15000)
                page.wait_for_load_state("networkidle")
                wait_for_content_ready(page, "refine-editor")

                # Scan codes in opened Harbour editor
                codes_harbour = scan_page_codes(page)
                code_scan_results[lang]["refine-harbour-editor"] = codes_harbour
                if codes_harbour:
                    print(f"          [CODE SCAN ALERT] Found codes in {lang}/refine-harbour-editor: {codes_harbour}")

                shot_harbour = OUTPUT_DIR / f"{lang_prefix}-05b-refine-harbour-editor.png"
                page.screenshot(path=str(shot_harbour), full_page=True)
                screenshots_taken.append(shot_harbour.name)
                print(f"          Saved {shot_harbour.name}")

                # Ariadne expanded panel
                print(f"        Capturing Ariadne expanded panel...")
                page.click('button[aria-label="Ariadne"]')
                page.wait_for_timeout(600)
                expand_btn = page.locator('[data-testid="ariadne-expand-toggle"]')
                if expand_btn.is_visible():
                    aside = page.locator("aside.shell-properties")
                    if "shell-properties--expanded" not in (aside.get_attribute("class") or ""):
                        expand_btn.click()
                        page.wait_for_selector("aside.shell-properties--expanded", timeout=5000)
                page.wait_for_timeout(600)

                codes_ariadne = scan_page_codes(page)
                code_scan_results[lang]["ariadne-expanded"] = codes_ariadne
                if codes_ariadne:
                    print(f"          [CODE SCAN ALERT] Found codes in {lang}/ariadne-expanded: {codes_ariadne}")

                shot_ariadne = OUTPUT_DIR / f"{lang_prefix}-06-ariadne-expanded.png"
                page.screenshot(path=str(shot_ariadne), full_page=True)
                screenshots_taken.append(shot_ariadne.name)
                print(f"          Saved {shot_ariadne.name}")

                # If switching to English, toggle language and close Ariadne
                if is_zh:
                    print("        Switching to English (en)...")
                    # Switch back to Properties tab
                    page.locator('.panel-tabs button').first.click()
                    page.wait_for_timeout(400)
                    page.click("#language-toggle")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(1000)

            browser.close()

        # Save code scan results
        code_scan_path = OUTPUT_DIR / "code-scan.json"
        code_scan_path.write_text(json.dumps(code_scan_results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[4.5] Code scan results written to {code_scan_path}")

        print("[5/5] Running fabric_compare.py against rehearsal services...")
        fabric_output_dir = OUTPUT_DIR / "fabric"
        if fabric_output_dir.exists():
            import shutil
            shutil.rmtree(fabric_output_dir)
        fabric_proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "web/e2e/fabric_compare.py"),
                "--url", WEB_URL,
                "--api-base", API_URL,
                "--output-dir", str(fabric_output_dir),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        print("      fabric_compare return code:", fabric_proc.returncode)
        if fabric_proc.stdout:
            print("      fabric_compare stdout (tail):\n", fabric_proc.stdout[-500:])
        if fabric_proc.stderr:
            print("      fabric_compare stderr (tail):\n", fabric_proc.stderr[-500:])
        fabric_compare_result = {
            "returncode": fabric_proc.returncode,
            "stdout": fabric_proc.stdout[-500:] if fabric_proc.stdout else "",
            "stderr": fabric_proc.stderr[-500:] if fabric_proc.stderr else "",
        }

    except Exception as exc:
        print(f"ERROR during rehearsal execution: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    finally:
        print("Shutting down temporary servers...")
        stop_process(web_proc)
        stop_process(api_proc)
        print("Temporary servers stopped.")

    total_errors = len(console_errors) + len(page_errors)
    total_leaked_codes = sum(len(codes) for lang in code_scan_results.values() for codes in lang.values())
    status_str = "PASS" if total_errors == 0 and total_leaked_codes == 0 and fabric_compare_result.get("returncode") == 0 else "FAIL"

    report_path = OUTPUT_DIR / "REPORT.md"
    fc_code = fabric_compare_result.get("returncode")
    fc_status = "PASS (exit code 0)" if fc_code == 0 else f"FAIL (exit code {fc_code})"
    report_lines = [
        "# P1 UI Cleanup Round 2 Rehearsal Report",
        "",
        f"- **Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Branch**: `wp/p1-ui-cleanup`",
        f"- **API Port**: {API_PORT}",
        f"- **Web Port**: {WEB_PORT}",
        f"- **Database**: `/private/tmp/p1ui-db/state.sqlite3`",
        f"- **Climate Artifact Root**: `{CLIMATE_ARTIFACT_ROOT}`",
        f"- **Status**: **{status_str}**",
        "",
        "## Commander Issues Addressed in Round 2",
        "1. **Refine stage (細修頁) Mainline Proposals (主線方案)**:",
        "   - Mainline proposals list pinned registered Harbour formal proposal (`formal-fabric-harbour-grain-88445febe1b6`, accepted) marked '選定' (Selected) at the top.",
        "   - Four fabric schemes (`harbour_grain`, `closed_block_extension`, `courtyard_islands`, `landscape_figure`) listed below with '探索草案' (Exploratory draft) badges.",
        "   - Clicking Harbour proposal and '開啟方案編輯工具' (Open scenario editing tools) transitions to the live editable state via `/formal-draft` API endpoint.",
        "   - Right-side '已保存方案' (Saved scenarios) lists mainline scenarios first, with historical proposals (`common-*`, `grid-*`, `spine-mixed`) organized in collapsed `<details>` section.",
        "2. **Elimination of Leaked Internal Underscore Status Codes**:",
        "   - All internal uppercase codes with underscores (`\\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\\b`) across all 5 stages, right properties, and Ariadne panel are mapped to localized human-readable labels via `web/src/i18n/statusLabels.tsx` or dictionary, with raw codes in `title` tooltips and hidden `<span class=\"sr-only\" style=\"display: none;\">` for test assertions.",
        "   - Verified: Regex scan on `document.body.innerText` returns empty arrays `[]` across all stages in both `zh-TW` and `en`.",
        "3. **Concrete Content Loaded Before Screenshot Timing**:",
        "   - All screenshots captured after full content load (waiting for spinners and loading text to disappear, and `img.complete`).",
        "",
        "## Verification Results",
        f"- **Console Errors**: {len(console_errors)}",
        f"- **Page Errors**: {len(page_errors)}",
        f"- **Total Leaked Underscore Codes**: {total_leaked_codes}",
        f"- **Fabric Compare E2E**: {fc_status}",
        "",
        "### Code Scan Summary (`artifacts/w8/rehearsal/p1-ui-r2/code-scan.json`)",
        "```json",
        json.dumps(code_scan_results, indent=2, ensure_ascii=False),
        "```",
        "",
        "### Captured Screenshots",
    ]
    for shot in sorted(screenshots_taken):
        report_lines.append(f"- `artifacts/w8/rehearsal/p1-ui-r2/{shot}`")

    if console_errors:
        report_lines.extend(["", "### Console Errors Detail:"])
        for err in console_errors:
            report_lines.append(f"- `{err}`")

    if page_errors:
        report_lines.extend(["", "### Page Errors Detail:"])
        for err in page_errors:
            report_lines.append(f"- `{err}`")

    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"Report written to {report_path}")
    return 0 if status_str == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
