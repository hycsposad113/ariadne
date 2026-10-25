#!/usr/bin/env python3
"""Build Level 2 evidence package for approved regional OSM download (WC-3, PD-17)."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "artifacts/week4-regional-osm"
PACKAGE_ID = "week4-regional-osm-20260925T155741Z"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Parent references
    parent_files = [
        "docs/decisions/2026-09-25-plan-decisions-zh.md",
        "config/runtimes/pst-method-manifest-v1.json",
        "config/runtimes/syntax-network-policy-v1.json",
        "docs/methods/syntax-network-policy-v1.md",
    ]
    parent_refs: dict[str, str] = {}
    for pf in parent_files:
        p = ROOT / pf
        if not p.exists():
            # Check main repo if not in worktree
            main_p = Path("/Users/jackhsieh/Downloads/TUD/Q5/project") / pf
            if main_p.exists():
                parent_refs[pf] = digest(main_p)
                continue
            raise FileNotFoundError(f"Parent file not found: {pf}")
        parent_refs[pf] = digest(p)

    save_json(PACKAGE_DIR / "parent-references.json", parent_refs)

    # 2. Package record
    download_record = load_json(PACKAGE_DIR / "download-record.json")
    package_record = {
        "package_id": PACKAGE_ID,
        "created_at_utc": download_record["timestamp_utc"],
        "purpose": "Level 2 evidence package for approved Zuid-Holland OSM PBF and POLY extract download per PD-17 and WC-3.",
        "license": "ODbL 1.0",
        "attribution": "© OpenStreetMap contributors",
        "provider": "Geofabrik Download Server",
        "downloads": download_record["files"],
        "scope": {
            "authoritative_sqlite_writes": 0,
            "dataset_snapshots_published": 0,
            "status": "RAW_EXTRACT_DOWNLOADED_AWAITING_DEPENDENCY_AND_ETL",
        },
        "dependency_request": {
            "package": "osmium",
            "version": ">=3.7.0, <=4.0.2",
            "license": "BSD-2-Clause",
            "status": "PENDING_DESIGNER_APPROVAL_PER_WC3",
            "purpose": "Memory-efficient C++ streaming parser to extract road segments within StudyArea 4km, 6km, and 20km envelopes from 211MB PBF."
        }
    }
    save_json(PACKAGE_DIR / "package-record.json", package_record)

    # 3. README.md
    readme_content = f"""# Approved Regional OSM Download Evidence Package

**Package ID:** `{PACKAGE_ID}`  
**Evidence Level:** Level 2 (Full Evidence Package per PD-06)  
**Authority Reference:** `docs/decisions/2026-09-25-plan-decisions-zh.md` PD-17, `docs/superpowers/plans/2026-09-25-week4-closeout-plan-zh.md` WC-3  
**Licence & Attribution:** Open Database License (ODbL) 1.0, © OpenStreetMap contributors  

## Downloaded Files

| File | Size (bytes) | SHA-256 | HTTP Status | Provider Date |
|---|---|---|---|---|
| `raw/zuid-holland-260922.osm.pbf` | 211,355,323 | `71379de6fcb38b114ae2ee564cac99cfb2763b6cc3f6d87667c1079ea578401c` | 200 OK | 2026-09-22 23:40:44 GMT |
| `raw/zuid-holland.poly` | 5,099 | `29cd8492d4a535488c59680f3b07e0b64024efdb0669e3c4c8a5d14a82f33c67` | 200 OK | 2026-09-25 03:45:53 GMT |

## Constraints & Execution Accounting

- Request counts: exactly 1 GET per file.
- Follow redirects: disabled (`follow_redirects=False`). Zero redirects occurred.
- Timeouts: 300 seconds client timeout.
- Size caps: PBF capped at 262,144,000 bytes (actual: 211,355,323 bytes exact match); POLY capped at 1,048,576 bytes (actual: 5,099 bytes).
- Retries: 0.
- Authoritative DB writes: 0.
"""
    (PACKAGE_DIR / "README.md").write_text(readme_content, encoding="utf-8")

    # 4. verify_package.py
    verify_script_content = '''#!/usr/bin/env python3
"""Verify integrity of regional OSM evidence package."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify(package_dir: Path, project_root: Path) -> dict[str, Any]:
    failures: list[str] = []
    manifest_path = package_dir / "integrity-manifest.json"
    if not manifest_path.exists():
        return {"status": "FAIL", "error": "Missing integrity manifest"}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    
    # Check parent references
    parents = manifest.get("parent_references", {})
    for rel_path, expected_hash in parents.items():
        target = project_root / rel_path
        if not target.exists():
            target = Path("/Users/jackhsieh/Downloads/TUD/Q5/project") / rel_path
        if not target.exists():
            failures.append(f"Missing parent: {rel_path}")
            continue
        if digest(target) != expected_hash:
            failures.append(f"Parent hash mismatch: {rel_path}")

    # Check files in manifest
    files = manifest.get("files", {})
    external_osm_dir = Path.home() / ".local/share/urban-design-data/osm"

    for rel_path, meta in files.items():
        file_path = package_dir / rel_path
        if not file_path.exists() and file_path.suffix == ".pbf":
            external_candidate = external_osm_dir / file_path.name
            if external_candidate.exists():
                file_path = external_candidate

        if not file_path.exists():
            failures.append(f"Missing package file: {rel_path}")
            continue
        if digest(file_path) != meta["sha256"]:
            failures.append(f"SHA-256 mismatch: {rel_path}")
        if file_path.stat().st_size != meta["size_bytes"]:
            failures.append(f"Size mismatch: {rel_path}")

    # Check for unmanifested files
    for p in package_dir.rglob("*"):
        if p.is_file() and p.name not in {"integrity-manifest.json", "integrity-fault-results.json"}:
            if "__pycache__" in p.parts or p.suffix == ".pyc":
                continue
            rel = str(p.relative_to(package_dir))
            if rel not in files:
                failures.append(f"Unmanifested file in package: {rel}")

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "files_checked": len(files),
        "parents_checked": len(parents),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    res = verify(args.package_dir, args.project_root)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "PASS" else 1)
'''
    (PACKAGE_DIR / "verify_package.py").write_text(verify_script_content, encoding="utf-8")

    # 5. run_integrity_fault_tests.py
    fault_script_content = '''#!/usr/bin/env python3
"""Run disposable fault tests against regional OSM evidence package."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from verify_package import verify


def main() -> int:
    package_dir = Path(__file__).resolve().parent
    project_root = package_dir.parents[1]

    # Baseline verification
    baseline = verify(package_dir, project_root)
    if baseline["status"] != "PASS":
        print(f"FAIL: Baseline package does not pass verification: {baseline}")
        return 1

    results = []
    # Fault 1: corrupt poly file in disposable clone
    with tempfile.TemporaryDirectory() as tmpdir:
        clone = Path(tmpdir) / "clone"
        shutil.copytree(package_dir, clone)
        (clone / "raw/zuid-holland.poly").write_text("corrupted content", encoding="utf-8")
        res = verify(clone, project_root)
        passed = (res["status"] == "FAIL" and any("zuid-holland.poly" in f for f in res["failures"]))
        results.append({"fault": "tampered_poly_file", "detected": passed})

    # Fault 2: missing manifest file in disposable clone
    with tempfile.TemporaryDirectory() as tmpdir:
        clone = Path(tmpdir) / "clone"
        shutil.copytree(package_dir, clone)
        (clone / "download-record.json").unlink()
        res = verify(clone, project_root)
        passed = (res["status"] == "FAIL" and any("download-record.json" in f for f in res["failures"]))
        results.append({"fault": "missing_package_file", "detected": passed})

    all_passed = all(r["detected"] for r in results)
    out = {
        "status": "PASS" if all_passed else "FAIL",
        "results": results,
    }
    (package_dir / "integrity-fault-results.json").write_text(json.dumps(out, indent=2) + "\\n")
    print(json.dumps(out, indent=2))
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
'''
    (PACKAGE_DIR / "run_integrity_fault_tests.py").write_text(fault_script_content, encoding="utf-8")

    # 6. Build integrity manifest
    manifest_files: dict[str, Any] = {}
    for p in sorted(PACKAGE_DIR.rglob("*")):
        if p.is_file() and p.name not in {"integrity-manifest.json", "integrity-fault-results.json"}:
            if "__pycache__" in p.parts or p.suffix == ".pyc":
                continue
            rel = str(p.relative_to(PACKAGE_DIR))
            manifest_files[rel] = {
                "sha256": digest(p),
                "size_bytes": p.stat().st_size,
            }

    manifest = {
        "package_id": PACKAGE_ID,
        "schema_version": "integrity-manifest-v1",
        "parent_references": parent_refs,
        "files": manifest_files,
    }
    save_json(PACKAGE_DIR / "integrity-manifest.json", manifest)

    print("Integrity manifest generated successfully.")
    return 0


if __name__ == "__main__":
    main()
