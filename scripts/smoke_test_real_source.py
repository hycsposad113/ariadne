#!/usr/bin/env python3
"""Run a read-only real-source HTTP smoke test on dynamically selected loopback ports."""

import argparse
import hashlib
import json
import os
import socket
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


DEFAULT_PREVIEW_ROOT = Path("/Users/jackhsieh/Downloads/TUD/Q5/w6-dictionary-generator/out/dictionary-generator/run-01")
DEFAULT_MANIFEST_SHA256 = "14b2378ca16f79b84ce8fd60fbe6aa81ff11e7cccdec875034be5740e6b37452"
PROTECTED_PORTS = {5195, 8644, 8787, 8788, 8789, 8795, 9876}
ASSET_SOURCE_NAMES = {"plan": "plan.png", "axonometric": "axonometric.png", "geometry": "scenario.geojson"}


def choose_loopback_ports() -> tuple[int, int]:
    """Ask the OS for two currently free loopback ports, excluding protected services."""
    selected: list[int] = []
    while len(selected) < 2:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        if port not in PROTECTED_PORTS and port not in selected:
            selected.append(port)
    return selected[0], selected[1]


def write_receipt_exclusive(path: Path, results: dict) -> None:
    """Write a new receipt without replacing an earlier run."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(results, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def verify_asset_bytes(source_path: Path, content: bytes, etag: str | None) -> str:
    """Require response bytes to equal the pinned source and its SHA-256 ETag."""
    source_bytes = Path(source_path).read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if content != source_bytes:
        raise AssertionError(f"served asset bytes differ from pinned source: {source_path.name}")
    normalized_etag = (etag or "").strip().strip('"')
    if normalized_etag != digest:
        raise AssertionError(f"served asset ETag differs from byte hash: {source_path.name}")
    return digest


def is_urban_design_runtime_path(path: Path) -> bool:
    """Return true for lexical or resolved paths inside a protected runtime directory."""
    candidate = Path(path).expanduser()
    lexical = candidate.absolute()
    resolved = candidate.resolve(strict=False)
    return ".urban_design_runtime" in lexical.parts or ".urban_design_runtime" in resolved.parts


def ensure_disposable_database(database_path: Path, authoritative_database: Path) -> Path:
    """Reject protected runtime paths and aliases of the authoritative state database."""
    candidate = Path(database_path).expanduser()
    authority = Path(authoritative_database).expanduser()
    if not candidate.is_file():
        raise ValueError("database backup copy does not exist")

    resolved_candidate = candidate.resolve(strict=True)
    resolved_authority = authority.resolve(strict=False)
    same_path = resolved_candidate == resolved_authority
    same_inode = False
    try:
        candidate_stat = resolved_candidate.stat()
        authority_stat = resolved_authority.stat()
        same_inode = (candidate_stat.st_dev, candidate_stat.st_ino) == (authority_stat.st_dev, authority_stat.st_ino)
    except FileNotFoundError:
        pass
    if same_path or same_inode:
        raise ValueError("database backup must not be the authoritative database")
    if is_urban_design_runtime_path(candidate):
        raise ValueError("database paths under .urban_design_runtime are forbidden")
    return resolved_candidate


def _authoritative_database_path(root: Path) -> Path:
    project_root = root if root.name == "project" else root.parent / "project"
    if not project_root.is_dir():
        project_root = root
    return project_root / ".urban_design_runtime" / "state.sqlite3"


def _process_identity(proc: subprocess.Popen, name: str) -> dict:
    command = proc.args
    if isinstance(command, (str, bytes)):
        command = [str(command)]
    else:
        command = [str(part) for part in command]
    return {
        "name": name,
        "pid": proc.pid,
        "pgid": proc.pid if proc.pid is not None else None,
        "command": command,
    }


def stop_owned_process(proc: subprocess.Popen, name: str) -> dict:
    """Stop and wait for one directly spawned verifier-owned process."""
    identity = _process_identity(proc, name)
    try:
        return_code = proc.poll()
        if return_code is None:
            proc.terminate()
            try:
                return_code = proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                return_code = proc.wait(timeout=2.0)
        if return_code is None:
            return {**identity, "status": "OUTCOME_UNKNOWN", "error_type": "TimeoutExpired"}
        return {**identity, "status": "STOPPED", "return_code": return_code}
    except ProcessLookupError:
        try:
            return_code = proc.wait(timeout=1.0)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {
                **identity,
                "status": "OUTCOME_UNKNOWN",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        return {**identity, "status": "STOPPED", "return_code": return_code}
    except (PermissionError, OSError, subprocess.TimeoutExpired) as exc:
        return {
            **identity,
            "status": "OUTCOME_UNKNOWN",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def cleanup_owned_processes(processes: list[tuple[str, subprocess.Popen]], *, stopper=None) -> dict:
    """Attempt every verifier-owned child and retain each process identity and outcome."""
    stop_one = stopper or stop_owned_process
    results = []
    for name, proc in processes:
        identity = _process_identity(proc, name)
        try:
            result = stop_one(proc, name)
        except Exception as exc:
            result = {
                "status": "OUTCOME_UNKNOWN",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        if not isinstance(result, dict) or result.get("status") not in {"STOPPED", "OUTCOME_UNKNOWN"}:
            result = {
                "status": "OUTCOME_UNKNOWN",
                "error_type": "InvalidCleanupResult",
                "error": "process cleanup did not return a recognized status",
            }
        results.append({**identity, **result})
    overall = "STOPPED" if all(item["status"] == "STOPPED" for item in results) else "OUTCOME_UNKNOWN"
    return {"overall": overall, "processes": results}


def finalize_smoke_run(
    smoke_results: dict,
    receipt_path: Path,
    processes: list[tuple[str, subprocess.Popen]],
    *,
    log_streams: list[tuple[str, object]] | None = None,
    stopper=None,
) -> dict:
    """Stop every owned process and exclusively persist verification and cleanup outcomes."""
    smoke_results["verification_status_before_cleanup"] = smoke_results.get("overall", "FAIL")
    cleanup_result = cleanup_owned_processes(processes, stopper=stopper)
    smoke_results["process_cleanup"] = cleanup_result
    if cleanup_result["overall"] != "STOPPED":
        smoke_results["overall"] = "OUTCOME_UNKNOWN"

    for name, log_stream in log_streams or []:
        if log_stream is None:
            continue
        try:
            log_stream.close()
        except Exception as exc:
            smoke_results.setdefault("cleanup_errors", []).append({
                "name": name,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            smoke_results["overall"] = "OUTCOME_UNKNOWN"

    try:
        write_receipt_exclusive(receipt_path, smoke_results)
    except FileExistsError as exc:
        smoke_results["overall"] = "OUTCOME_UNKNOWN"
        smoke_results["receipt_error"] = {
            "type": type(exc).__name__,
            "message": "refusing to overwrite existing smoke receipt",
        }
        return {"receipt_written": False, "overall": smoke_results["overall"]}
    except OSError as exc:
        smoke_results["overall"] = "OUTCOME_UNKNOWN"
        smoke_results["receipt_error"] = {"type": type(exc).__name__, "message": str(exc)}
        return {"receipt_written": False, "overall": smoke_results["overall"]}
    return {"receipt_written": True, "overall": smoke_results["overall"]}


def wait_until_ready(url: str, timeout: float = 15.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Read-only smoke test for the pinned real morphology bundle.")
    parser.add_argument("--database", type=Path, required=True, help="Disposable SQLite backup copy used by the API.")
    parser.add_argument("--output", type=Path, required=True, help="New receipt path under out/ or /private/tmp.")
    parser.add_argument("--morphology-preview-root", type=Path, default=DEFAULT_PREVIEW_ROOT)
    parser.add_argument("--morphology-preview-manifest-sha256", default=DEFAULT_MANIFEST_SHA256)
    args = parser.parse_args(argv)

    try:
        db_copy = ensure_disposable_database(args.database, _authoritative_database_path(root))
    except ValueError as exc:
        parser.error(str(exc))
    original_db = (root / "out" / "state.sqlite3").resolve()
    if db_copy == original_db:
        parser.error("--database must name a disposable backup copy, not the retained out/state.sqlite3")

    out_path = args.output.expanduser().resolve()
    if is_urban_design_runtime_path(args.output):
        parser.error("--output must not be under .urban_design_runtime")
    allowed_output_roots = ((root / "out").resolve(), Path("/private/tmp").resolve())
    if not any(out_path.is_relative_to(allowed) for allowed in allowed_output_roots):
        parser.error("--output must be under this worktree's out/ directory or /private/tmp")
    if out_path.exists() or out_path.is_symlink():
        parser.error(f"refusing to overwrite existing evidence: {out_path}")

    preview_root = args.morphology_preview_root.expanduser().resolve()
    if is_urban_design_runtime_path(args.morphology_preview_root):
        parser.error("--morphology-preview-root must not be under .urban_design_runtime")
    manifest_sha256 = args.morphology_preview_manifest_sha256
    if not preview_root.is_dir():
        parser.error("configured morphology preview root does not exist")
    if not isinstance(manifest_sha256, str) or len(manifest_sha256) != 64:
        parser.error("configured morphology preview manifest SHA-256 must have 64 characters")

    try:
        from urban_design.morphology.preview_catalog import load_catalog

        loaded_catalog = load_catalog(preview_root, manifest_sha256)
        manifest_path = preview_root / "artifact-manifest.json"
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_file_count = len(manifest_data["files"])
        if manifest_file_count != 52 or len(loaded_catalog.records) != 10:
            raise AssertionError("pinned source must verify exactly 52 manifest files and 10 preview candidates")
    except Exception as exc:
        parser.error(f"pinned source verification failed ({type(exc).__name__})")

    api_port, vite_port = choose_loopback_ports()
    api_url = f"http://127.0.0.1:{api_port}"
    vite_url = f"http://127.0.0.1:{vite_port}"
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(root / "src"), env.get("PYTHONPATH", "")]))
    vite_env = os.environ.copy()
    vite_env["VITE_API_BASE"] = api_url

    api_cmd = [
        str(root / ".venv" / "bin" / "python"),
        str(root / "scripts" / "run_workspace_server.py"),
        "--host", "127.0.0.1",
        "--port", str(api_port),
        "--database", str(db_copy),
        "--morphology-preview-root", str(preview_root),
        "--morphology-preview-manifest-sha256", manifest_sha256,
    ]
    node_executable = shutil.which("node")
    vite_entry = root / "web" / "node_modules" / "vite" / "bin" / "vite.js"
    if node_executable is None or not vite_entry.is_file():
        parser.error("direct Node and the installed Vite entrypoint are required for verifiable process cleanup")
    vite_cmd = [
        node_executable, str(vite_entry), "--host", "127.0.0.1", "--port", str(vite_port), "--strictPort"
    ]

    smoke_results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "api_port": api_port,
        "vite_port": vite_port,
        "preview_root": str(preview_root),
        "manifest_sha256": manifest_sha256,
        "manifest_file_count": manifest_file_count,
        "database_copy": str(db_copy),
        "output_path": str(out_path),
        "checks": [],
        "overall": "FAIL",
    }
    api_proc = None
    vite_proc = None
    api_log = None
    vite_log = None
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        api_log = (out_path.parent / "api.log").open("x", encoding="utf-8")
        vite_log = (out_path.parent / "vite.log").open("x", encoding="utf-8")
        print(f"Starting disposable API on 127.0.0.1:{api_port}...")
        api_proc = subprocess.Popen(
            api_cmd, cwd=str(root), env=env, stdin=subprocess.DEVNULL,
            stdout=api_log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        print(f"Starting Vite on 127.0.0.1:{vite_port}...")
        vite_proc = subprocess.Popen(
            vite_cmd, cwd=str(root / "web"), env=vite_env, stdin=subprocess.DEVNULL,
            stdout=vite_log, stderr=subprocess.STDOUT, start_new_session=True,
        )

        if not wait_until_ready(f"{api_url}/api/v1/morphology/previews", timeout=20.0):
            raise RuntimeError(f"disposable API did not become ready; see {out_path.parent / 'api.log'}")
        if not wait_until_ready(vite_url, timeout=20.0):
            raise RuntimeError(f"Vite did not become ready; see {out_path.parent / 'vite.log'}")

        with urllib.request.urlopen(vite_url, timeout=5.0) as response:
            html = response.read().decode("utf-8", errors="replace")
            assert response.status == 200
            assert '<div id="root">' in html or "<script" in html
            smoke_results["checks"].append({"check": "vite_index", "status": "PASS"})

        with urllib.request.urlopen(f"{api_url}/api/v1/morphology/previews", timeout=5.0) as response:
            catalog_data = json.loads(response.read().decode("utf-8"))
            assert response.status == 200
            assert catalog_data["status"] == "AVAILABLE"
            assert catalog_data["count"] == 10
            assert catalog_data["manifest_sha256"] == manifest_sha256
        candidates = catalog_data["previews"]
        assert sum(item["identity"]["intensity"] == "A" for item in candidates) == 5
        assert sum(item["identity"]["intensity"] == "B" for item in candidates) == 5
        smoke_results["checks"].append({
            "check": "catalog_listing",
            "status": "PASS",
            "count": len(candidates),
            "manifest_sha256": catalog_data["manifest_sha256"],
            "manifest_file_count": manifest_file_count,
        })

        candidate_results = []
        for candidate in candidates:
            identity = candidate["identity"]
            intensity = identity["intensity"]
            strategy_id = identity["strategy_id"]
            card_key = f"{intensity}/{strategy_id}"
            detail_url = f"{api_url}/api/v1/morphology/previews/{card_key}"
            with urllib.request.urlopen(detail_url, timeout=5.0) as response:
                detail_data = json.loads(response.read().decode("utf-8"))
                assert response.status == 200
                assert detail_data["identity"]["status"] == "UNAPPROVED_PREVIEW"
                assert detail_data["identity"]["human_decision_created"] is False
                assert detail_data["metrics"]["building_count"] > 0

            asset_hashes = {}
            asset_sizes = {}
            for kind, source_name in ASSET_SOURCE_NAMES.items():
                asset_url = f"{api_url}/api/v1/morphology/previews/{card_key}/assets/{kind}"
                with urllib.request.urlopen(asset_url, timeout=5.0) as response:
                    content = response.read()
                    expected_type = "application/geo+json" if kind == "geometry" else "image/png"
                    assert response.status == 200
                    assert response.headers.get_content_type() == expected_type
                    source_path = preview_root / intensity / strategy_id / source_name
                    digest = verify_asset_bytes(source_path, content, response.headers.get("ETag"))
                    asset_hashes[kind] = digest
                    asset_sizes[kind] = len(content)
                    if kind == "geometry":
                        geometry = json.loads(content.decode("utf-8"))
                        assert geometry["type"] == "FeatureCollection"
                        assert geometry["features"]

            candidate_results.append({
                "candidate": card_key,
                "strategy_label": candidate["strategy_label"],
                "status": "PASS",
                "asset_sizes": asset_sizes,
                "asset_sha256": asset_hashes,
                "building_count": detail_data["metrics"]["building_count"],
                "human_decision_created": detail_data["identity"]["human_decision_created"],
            })

        smoke_results["checks"].append({
            "check": "all_10_candidates_and_30_assets",
            "status": "PASS",
            "candidates": candidate_results,
            "source_bytes_match": True,
            "etag_sha256_match": True,
        })

        with urllib.request.urlopen(f"{api_url}/api/v1/scenarios", timeout=5.0) as response:
            scenarios_data = json.loads(response.read().decode("utf-8"))
            assert response.status == 200
            assert "scenarios" in scenarios_data
            smoke_results["checks"].append({
                "check": "persisted_scenario_api",
                "status": "PASS",
                "count": len(scenarios_data["scenarios"]),
            })

        smoke_results["overall"] = "PASS"
        print("HTTP smoke passed: 52 source entries, 10 candidates, 30 exact-byte assets.")
    except Exception as exc:
        smoke_results["error"] = {"type": type(exc).__name__, "message": str(exc)}
        print(f"HTTP smoke failed ({type(exc).__name__}): {exc}", file=sys.stderr)
    finally:
        print("Stopping only directly spawned verifier-owned processes...")
        owned_processes = [
            (name, proc)
            for name, proc in (("API", api_proc), ("Vite", vite_proc))
            if proc is not None
        ]
        finalized = finalize_smoke_run(
            smoke_results,
            out_path,
            owned_processes,
            log_streams=[("API", api_log), ("Vite", vite_log)],
        )
        if finalized["receipt_written"]:
            print(f"Saved smoke receipt to {out_path}")
        else:
            print(f"Could not save an exclusive smoke receipt: {finalized}", file=sys.stderr)
        if finalized["overall"] == "OUTCOME_UNKNOWN":
            print("HTTP result or verifier-owned process cleanup remains unresolved.", file=sys.stderr)

    return 0 if smoke_results.get("overall") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
