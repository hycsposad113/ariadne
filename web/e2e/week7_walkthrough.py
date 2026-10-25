#!/usr/bin/env python3
"""Week 7 reviewer drill on a sqlite backup and temporary ports.

Uses the already installed Google Chrome headless CDP endpoint. It does not
install Playwright, does not open the authority database for write, and does
not call a live model.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import signal
import socket
import sqlite3
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[2]
PYTHON = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python")
AUTHORITY = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3")
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
WORKSPACE = "ws-w7"
FORK_ID = "branch-b2"
REVISION = "rev-b2"

OPERATIONS = (
    ("inspect", "forged_calculation"),
    ("challenge", "rev-b2"),
    ("modify", "grants_acceptance"),
    ("rerun", "overwrote_baseline"),
    ("compare", "radius_family"),
    ("fork", FORK_ID),
    ("reject", "still_queryable"),
    ("override", "computed_value_unchanged"),
)


class ChromeStartError(RuntimeError):
    pass


class Cdp:
    def __init__(self, ws_url: str) -> None:
        host_path = ws_url.removeprefix("ws://")
        host, path = host_path.split("/", 1)
        hostname, port = host.rsplit(":", 1)
        self.sock = socket.create_connection((hostname, int(port)), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ChromeStartError("CDP handshake closed")
            buffer += chunk
        header, rest = buffer.split(b"\r\n\r\n", 1)
        if b" 101 " not in header.split(b"\r\n", 1)[0]:
            raise ChromeStartError(header.decode("utf-8", "replace")[:400])
        self.buffer = rest
        self.next_id = 1

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def call(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        message_id = self.next_id
        self.next_id += 1
        self._send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.sock.settimeout(max(0.1, deadline - time.monotonic()))
            payload = json.loads(self._recv())
            if payload.get("id") == message_id:
                if "error" in payload:
                    raise RuntimeError(json.dumps(payload["error"]))
                return payload.get("result") or {}
        raise TimeoutError(method)

    def _send(self, text: str) -> None:
        raw = text.encode()
        mask = os.urandom(4)
        header = bytearray([0x81])
        length = len(raw)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(raw))
        self.sock.sendall(bytes(header) + masked)

    def _read_exact(self, count: int) -> bytes:
        while len(self.buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ChromeStartError("CDP socket closed")
            self.buffer += chunk
        out, self.buffer = self.buffer[:count], self.buffer[count:]
        return out

    def _recv(self) -> str:
        while True:
            first, second = self._read_exact(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            if second & 0x80:
                mask = self._read_exact(4)
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(self._read_exact(length)))
            else:
                payload = self._read_exact(length)
            if opcode == 1:
                return payload.decode()
            if opcode == 8:
                raise ChromeStartError("CDP close frame")

    def evaluate(self, expression: str) -> object:
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        inner = result.get("result") or {}
        if inner.get("subtype") == "error" or "exceptionDetails" in result:
            raise RuntimeError(json.dumps(result)[:500])
        return inner.get("value")

    def screenshot(self, path: Path, *, full: bool = False) -> None:
        params: dict = {"format": "png"}
        if not full:
            params["clip"] = {"x": 0, "y": 0, "width": 1440, "height": 280, "scale": 1}
        payload = self.call("Page.captureScreenshot", params, timeout=60)
        path.write_bytes(base64.b64decode(payload["data"]))


def wait_http(url: str, timeout: float, expect: int | None = 200) -> tuple[int, str]:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                body = response.read().decode("utf-8", "replace")
                if expect is None or response.status == expect:
                    return response.status, body
                last = f"{response.status} {body[:200]}"
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if expect is not None and exc.code == expect:
                return exc.code, body
            last = f"{exc.code} {body[:200]}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = str(exc)
        time.sleep(0.4)
    raise TimeoutError(f"{url} not ready: {last}")


def start_api(database: Path, port: int, log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("ab")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = "src"
    env.pop("PROJECT_AI_AUTHORIZED", None)
    env.pop("ARIADNE_LIVE", None)
    proc = subprocess.Popen(
        [str(PYTHON), "scripts/run_workspace_server.py", "--host", "127.0.0.1", "--port", str(port), "--database", str(database)],
        cwd=WORKTREE,
        env=env,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
    return proc


def start_web(api_port: int, web_port: int, log_path: Path) -> subprocess.Popen:
    log = log_path.open("ab")
    env = os.environ.copy()
    env["VITE_API_BASE"] = f"http://127.0.0.1:{api_port}"
    env["BROWSER"] = "none"
    return subprocess.Popen(
        ["npx", "--no-install", "vite", "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"],
        cwd=WORKTREE / "web",
        env=env,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )


def stop(proc: subprocess.Popen | None) -> None:
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


def seed_database(destination: Path) -> None:
    if destination.exists():
        destination.rename(destination.with_name(destination.name + ".old-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())))
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = "src"
    script = f"""
from pathlib import Path
from urban_design.week7.service import Week7Service, copy_authority_database
from tests.week7_support import seed_pair
dest = Path({str(destination)!r})
copy_authority_database(dest, Path({str(AUTHORITY)!r}))
service = Week7Service(dest)
seed_pair(service, {WORKSPACE!r})
service.apply_change({WORKSPACE!r}, "floor_height")
print(service.view({WORKSPACE!r})["revision_label"])
service.close()
"""
    subprocess.run([str(PYTHON), "-c", script], cwd=WORKTREE, env=env, check=True)


def query(database: Path, sql: str, params: tuple = ()) -> list[dict]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()


def timed_request(method: str, url: str, body: dict | None = None) -> tuple[float, int, str]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read().decode()
        elapsed = time.perf_counter() - started
        return elapsed, response.status, payload


def open_chrome(cdp_port: int, profile: Path) -> subprocess.Popen:
    if not CHROME.is_file():
        raise ChromeStartError(f"CHROME_START_FAILED missing binary {CHROME}")
    profile.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={cdp_port}",
            "--window-size=1440,1100",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise ChromeStartError(f"CHROME_START_FAILED exit {proc.returncode}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version", timeout=1) as response:
                if response.status == 200:
                    return proc
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.3)
    raise ChromeStartError("CHROME_START_FAILED debugging port did not answer")


def new_page(cdp_port: int, url: str) -> dict:
    target = f"http://127.0.0.1:{cdp_port}/json/new?{url}"
    for method in ("PUT", "GET"):
        request = urllib.request.Request(target, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError:
            continue
    raise ChromeStartError("CHROME_START_FAILED json/new refused")


def wait_text(page: Cdp, needle: str, timeout: float = 25) -> str:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        last = str(page.evaluate("document.body ? document.body.innerText : ''") or "")
        if needle in last and "revision unavailable" not in last:
            return last
        time.sleep(0.4)
    raise RuntimeError(f"text {needle!r} not visible; saw {last[:400]!r}")


def click(page: Cdp, test_id: str) -> None:
    clicked = page.evaluate(
        f"""(() => {{
          const node = document.querySelector('[data-testid="{test_id}"]');
          if (!node) return 'missing';
          node.click();
          return 'clicked';
        }})()"""
    )
    if clicked != "clicked":
        raise RuntimeError(f"missing button {test_id}")


def run_browser(page_url: str, database: Path, evidence: Path, cdp_port: int) -> dict:
    profile = Path(f"/private/tmp/w7-chrome-{cdp_port}-{os.getpid()}")
    chrome = open_chrome(cdp_port, profile)
    page = None
    try:
        target = new_page(cdp_port, page_url)
        page = Cdp(target["webSocketDebuggerUrl"])
        page.call("Page.enable")
        page.call("Runtime.enable")
        text = wait_text(page, "revision rev-b2", timeout=90)
        for needle in (
            "STALE 結果已過時",
            "Authority: Ready",
            "map revision rev-b2 feature ",
            "dashboard revision rev-b2",
            "charts revision rev-b2",
            "ai revision rev-b2",
            "export revision rev-b2",
            "fixture sun B2",
        ):
            if needle not in text:
                raise RuntimeError(f"{needle} missing from the mounted shell")
        if "Authority: Loading…" in text or "StudyArea ID: Unavailable" in text:
            raise RuntimeError("footer stayed on LOADING or had no persisted study area")
        evidence.mkdir(parents=True, exist_ok=True)
        page.screenshot(evidence / "00-revision-stale.png", full=True)
        click(page, "week7-switch-B1")
        wait_text(page, "map revision rev-b1 feature ")
        page.call("Page.navigate", {"url": page_url})
        text = wait_text(page, "revision rev-b1", timeout=90)
        for needle in (
            "Authority: Ready",
            "map revision rev-b1 feature ",
            "dashboard revision rev-b1",
            "charts revision rev-b1",
            "ai revision rev-b1",
            "export revision rev-b1",
            "fixture sun B1",
        ):
            if needle not in text:
                raise RuntimeError(f"reload did not restore {needle}")
        if "map revision rev-b2" in text or "dashboard revision rev-b2" in text or "Authority: Loading…" in text:
            raise RuntimeError("B1 reload still showed B2 or LOADING")
        page.screenshot(evidence / "01-reload-b1.png")
        click(page, "week7-switch-B2")
        wait_text(page, "map revision rev-b2 feature ")
        saved = {}
        for kind, marker in OPERATIONS:
            click(page, f"week7-op-{kind}")
            seen = wait_text(page, marker)
            if marker not in seen:
                raise RuntimeError(f"{kind} marker missing")
            shot = evidence / f"op-{kind}.png"
            page.screenshot(shot)
            rows = query(
                database,
                "SELECT operation_id, kind, target_revision, payload_json FROM week7_operations WHERE kind = ? ORDER BY operation_id",
                (kind,),
            )
            (evidence / f"op-{kind}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
            saved[kind] = {"screenshot": str(shot), "rows": len(rows), "marker": marker}
        fork_rows = query(database, "SELECT branch_id, lineage_json FROM week7_forks")
        far_rows = query(
            database,
            "SELECT scenario_id, revision, value_json FROM week7_results WHERE kind = 'gfa_far' ORDER BY scenario_id, revision",
        )
        stage_shots = []
        compare_revision = "MISSING"
        for stage in ("site", "conditions", "generate", "compare", "refine"):
            exists = page.evaluate(f"Boolean(document.querySelector('#stage-{stage}'))")
            if exists:
                page.evaluate(f"document.querySelector('#stage-{stage}').click()")
                time.sleep(0.4)
                path = evidence / f"stage-{stage}.png"
                page.screenshot(path)
                stage_shots.append(str(path))
            if stage == "compare":
                compare_text = wait_text(page, "compare revision rev-b2")
                compare_revision = "rev-b2" if "compare revision rev-b2" in compare_text else "MISSING"
        visible = str(page.evaluate("document.body ? document.body.innerText : ''"))
        if "map revision rev-b1" in visible:
            map_revision = "MIXED"
        elif "map revision rev-b2 feature " in visible:
            map_revision = "rev-b2"
        else:
            map_revision = "MISSING"
        return {
            "revision": "rev-b2" if "revision rev-b2" in visible else "MISSING",
            "map_revision": map_revision,
            "authority": "READY" if "Authority: Ready" in visible and "Authority: Loading…" not in visible else "NOT_READY",
            "surfaces": {
                "dashboard": "rev-b2" if "dashboard revision rev-b2" in visible else "MISSING",
                "charts": "rev-b2" if "charts revision rev-b2" in visible else "MISSING",
                "ai": "rev-b2" if "ai revision rev-b2" in visible else "MISSING",
                "export": "rev-b2" if "export revision rev-b2" in visible else "MISSING",
                "compare": compare_revision,
            },
            "fork_id": fork_rows[0]["branch_id"] if fork_rows else "MISSING",
            "lineage": json.loads(fork_rows[0]["lineage_json"]) if fork_rows else [],
            "far_rows": far_rows,
            "operations": saved,
            "stage_screenshots": stage_shots,
            "blocked": {
                "decision_3": "NEEDS_FOUNDER",
                "e1_plan": "NEEDS_FOUNDER",
                "e2": "NEEDS_FOUNDER",
                "live_ai": "OFFLINE",
            },
        }
    finally:
        if page is not None:
            page.close()
        stop(chrome)


def figure_hashes(destination: Path) -> dict[str, str]:
    from urban_design.week7.figures import export_figure_set

    rows = export_figure_set(
        destination,
        revision=REVISION,
        unit="ratio",
        period="2026-06-21T08:00/18:00",
        schemes=[
            {"scenario_id": "B1", "value": 1.1, "extent_id": "shared-public-open-space"},
            {"scenario_id": "B2", "value": 2.2, "extent_id": "shared-public-open-space"},
        ],
    )
    return {row["kind"]: row["sha256"] for row in rows}


def measure(database: Path, api_port: int, perf_path: Path) -> None:
    view_url = f"http://127.0.0.1:{api_port}/api/v1/week7/workspaces/{WORKSPACE}/view"
    reads = [timed_request("GET", view_url)[0] for _ in range(5)]
    switch_body = {
        "project_id": "rotterdam-m4h-pilot-project",
        "scenario_id": "B1",
        "revision": "rev-b1",
        "results": [{"kind": "gfa_far", "value": 1.1, "unit": "ratio", "provenance": "FIXTURE_ONLY"}],
        "cards": [],
    }
    switch_seconds, switch_status, _ = timed_request(
        "POST",
        f"http://127.0.0.1:{api_port}/api/v1/week7/workspaces/{WORKSPACE}/switch",
        switch_body,
    )
    modify_seconds, modify_status, _ = timed_request(
        "POST",
        f"http://127.0.0.1:{api_port}/api/v1/week7/workspaces/{WORKSPACE}/operations/modify",
        {"kind": "modify", "payload": {"parameter": "storey_height_m", "proposed_value": 3.5}},
    )
    rss = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True, check=False)
    server_lines = subprocess.run(["lsof", "-nP", f"-iTCP:{api_port}", "-sTCP:LISTEN"], capture_output=True, text=True, check=False)
    pid = ""
    for line in server_lines.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) > 1 and parts[1].isdigit():
            pid = parts[1]
            break
    server_rss = ""
    if pid:
        server_rss = subprocess.run(["ps", "-o", "rss=", "-p", pid], capture_output=True, text=True, check=False).stdout.strip()
    report = {
        "scheme_switch_post_seconds": switch_seconds,
        "scheme_switch_http_status": switch_status,
        "modify_preview_post_seconds": modify_seconds,
        "modify_http_status": modify_status,
        "view_get_seconds_min": min(reads),
        "view_get_seconds_max": max(reads),
        "database_bytes": database.stat().st_size,
        "api_rss_kb": server_rss,
        "walker_rss_kb": rss.stdout.strip(),
        "drag_preview": "not_measured",
        "e1_duration": "not_measured",
        "e2_duration": "not_measured",
        "syntax_duration": "not_measured",
        "fps": "not_measured",
    }
    perf_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def boot_view(database: Path, port: int, log_path: Path) -> dict:
    proc = start_api(database, port, log_path)
    try:
        status, body = wait_http(f"http://127.0.0.1:{port}/api/v1/week7/workspaces/{WORKSPACE}/view", 90)
        if status != 200:
            raise RuntimeError(body[:400])
        if proc.poll() is not None:
            raise RuntimeError(f"api exited {proc.returncode}")
        return json.loads(body)
    finally:
        stop(proc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--launch-log", type=Path, required=True)
    parser.add_argument("--walkthrough-log", type=Path, required=True)
    parser.add_argument("--perf-log", type=Path, required=True)
    args = parser.parse_args()
    args.runtime.mkdir(parents=True, exist_ok=True)
    launch_db = args.runtime / "launch.sqlite3"
    seed_database(launch_db)
    first = boot_view(launch_db, 8901, args.runtime / "api-launch-1.log")
    second = boot_view(launch_db, 8901, args.runtime / "api-launch-2.log")
    launch_same = first == second
    args.launch_log.write_text(
        json.dumps({"same_persisted_body": launch_same, "first": first, "second": second}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if not launch_same:
        print("LAUNCH_MISMATCH")
        return 1
    perf_proc = start_api(launch_db, 8903, args.runtime / "api-perf.log")
    try:
        wait_http(f"http://127.0.0.1:8903/api/v1/week7/workspaces/{WORKSPACE}/view", 90)
        measure(launch_db, 8903, args.perf_log)
    finally:
        stop(perf_proc)
    runs = []
    try:
        for index, api_port, web_port, cdp_port in ((1, 8901, 5301, 8931), (2, 8902, 5302, 8932)):
            database = args.runtime / f"run-{index}.sqlite3"
            seed_database(database)
            evidence = args.evidence / f"run-{index}"
            api = start_api(database, api_port, args.runtime / f"api-run-{index}.log")
            web = start_web(api_port, web_port, args.runtime / f"web-run-{index}.log")
            try:
                wait_http(f"http://127.0.0.1:{api_port}/api/v1/week7/workspaces/{WORKSPACE}/view", 90)
                wait_http(f"http://127.0.0.1:{web_port}/?week7Workspace={WORKSPACE}&week7Fork={FORK_ID}", 90)
                browser = run_browser(
                    f"http://127.0.0.1:{web_port}/?week7Workspace={WORKSPACE}&week7Fork={FORK_ID}",
                    database,
                    evidence,
                    cdp_port,
                )
                figures = figure_hashes(evidence / "figures")
                browser["figure_hashes"] = figures
                runs.append(browser)
                (evidence / "result.json").write_text(json.dumps(browser, indent=2, ensure_ascii=False), encoding="utf-8")
            finally:
                stop(web)
                stop(api)
    except ChromeStartError as exc:
        args.walkthrough_log.write_text(str(exc) + "\n", encoding="utf-8")
        print(exc)
        return 0
    if len(runs) != 2:
        print("WALKTHROUGH_INCOMPLETE")
        return 1
    same = (
        runs[0]["revision"] == runs[1]["revision"] == REVISION
        and runs[0]["map_revision"] == runs[1]["map_revision"] == REVISION
        and runs[0]["authority"] == runs[1]["authority"] == "READY"
        and runs[0]["fork_id"] == runs[1]["fork_id"] == FORK_ID
        and runs[0]["surfaces"] == runs[1]["surfaces"] == {
            "dashboard": REVISION,
            "charts": REVISION,
            "ai": REVISION,
            "export": REVISION,
            "compare": REVISION,
        }
        and runs[0]["figure_hashes"] == runs[1]["figure_hashes"]
        and runs[0]["revision"] != "MISSING"
    )
    args.walkthrough_log.write_text(
        json.dumps({"same": same, "run1": runs[0], "run2": runs[1]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("WALKTHROUGH_SAME" if same else "WALKTHROUGH_MISMATCH")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
