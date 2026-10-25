#!/usr/bin/env python3
"""Append a corrected final test-count docket without rewriting the R04 base."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_week4_repair_r04_amendments import verify_package_with_amendments  # noqa: E402

PACKAGE_REL = PurePosixPath("artifacts/week4-repair-r04")
PACKAGE = ROOT.joinpath(*PACKAGE_REL.parts)
PUBLIC_DOCKET = ROOT / "docs/week4-r04-repair-evidence-docket-r01.md"
AMENDMENT_FILES = ("docket-correction-r01.json", "decision-docket-r01.md", "implementation-record-r01.json")
SUPPLEMENTAL_MANIFEST = "integrity-manifest-r01.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dump_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n")


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _file_entry(path: Path, relative: str, parents: list[str], root: Path) -> dict[str, Any]:
    parent_paths = sorted(set(parents))
    return {
        "path": relative,
        "size_bytes": path.stat().st_size,
        "sha256": _sha(path),
        "kind": path.suffix.lower().lstrip(".") or "data",
        "parent_paths": parent_paths,
        "parent_sha256": {parent: _sha(root / parent) for parent in parent_paths},
    }


def append_correction() -> dict[str, Any]:
    if not PACKAGE.is_dir() or not (PACKAGE / "integrity-manifest.json").is_file():
        raise FileNotFoundError("validated R04 base package is missing")
    if PUBLIC_DOCKET.exists() or PUBLIC_DOCKET.is_symlink():
        raise FileExistsError(f"R04 docket amendment already exists; refusing to overwrite: {PUBLIC_DOCKET}")
    if (PACKAGE / SUPPLEMENTAL_MANIFEST).exists() or any((PACKAGE / name).exists() for name in AMENDMENT_FILES):
        raise FileExistsError("R04 docket amendment paths are already present; refusing to overwrite")

    base_result = verify_package_with_amendments(PACKAGE, project_root=ROOT)
    if base_result["status"] != "PASS" or base_result.get("amendment_manifests"):
        raise RuntimeError(f"R04 base package is not in an amendable PASS state: {base_result}")
    base_manifest_path = PACKAGE / "integrity-manifest.json"
    base_manifest_sha = _sha(base_manifest_path)
    base_docket_path = PACKAGE / "decision-docket.md"
    base_docket_sha = _sha(base_docket_path)
    results_path = PACKAGE / "test-results.json"
    results = _read(results_path)
    focused_summary = results["focused_backend"]["summary"]
    full_summary = results["full_pytest_summary"]
    focused_match = re.search(r"\b(\d+) passed\b", focused_summary)
    full_match = re.search(r"\b(\d+) passed\b", full_summary)
    if focused_match is None or full_match is None:
        raise RuntimeError("preserved test results do not contain final passed-test counts")
    focused_count = int(focused_match.group(1))
    full_count = int(full_match.group(1))
    if (focused_count, full_count) != (43, 451):
        raise RuntimeError(f"unexpected corrected test counts: focused={focused_count}, full={full_count}")

    old_docket = base_docket_path.read_text(encoding="utf-8")
    if old_docket.count("42 passed") != 1 or old_docket.count("450 passed") != 1:
        raise RuntimeError("base docket no longer contains the exact provisional counts this addendum corrects")
    corrected_body = old_docket.replace("42 passed", "43 passed", 1).replace("450 passed", "451 passed", 1)
    corrected_docket = (
        "# Append-only correction R01\n\n"
        "This correction supersedes the provisional focused/full pytest counts in the base package's `decision-docket.md`. "
        "The final retained logs and `test-results.json` record 43 focused tests and 451 full-suite tests. "
        "All other R04 findings, method values, source lineage, limitations, and gate states remain unchanged.\n\n"
        f"Base docket SHA-256: `{base_docket_sha}`  \n"
        f"Base integrity-manifest SHA-256: `{base_manifest_sha}`\n\n"
        + corrected_body
    )

    stage_parent = Path(tempfile.mkdtemp(prefix="week4-r04-docket-r01-", dir="/private/tmp"))
    stage_package = stage_parent.joinpath(*PACKAGE_REL.parts)
    shutil.copytree(PACKAGE, stage_package)
    correction = {
        "schema_version": "week4-r04-docket-correction-v1",
        "amendment_id": "docket-correction-r01",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "supersedes": {
            "path": (PACKAGE_REL / "decision-docket.md").as_posix(),
            "sha256": base_docket_sha,
        },
        "basis": "The base docket was generated at 42 focused and 450 full tests; one additional R03 serialization-preservation regression was then added and the final suites were rerun.",
        "corrected_results": {
            "focused_test_count": focused_count,
            "focused_summary": focused_summary,
            "full_pytest_count": full_count,
            "full_pytest_summary": full_summary,
            "deprecation_warning_count": 7,
            "focused_log_path": (PACKAGE_REL / "test-logs/focused-pytest.log").as_posix(),
            "full_log_path": (PACKAGE_REL / "test-logs/full-pytest.log").as_posix(),
            "vitest_summary": results["frontend_vitest"]["summary"],
        },
        "base_package_bytes_modified": False,
    }
    _dump_new(stage_package / "docket-correction-r01.json", correction)
    (stage_package / "decision-docket-r01.md").write_text(corrected_docket, encoding="utf-8")

    implementation_files = [
        ("scripts/append_week4_repair_r04_docket_r01.py", "Build the append-only correction for final test counts."),
        ("scripts/verify_week4_repair_r04_amendments.py", "Verify the immutable R04 base and supplemental amendment chain."),
    ]
    implementation_entries = []
    for relative, role in implementation_files:
        source = ROOT / relative
        implementation_entries.append({"path": relative, "size_bytes": source.stat().st_size, "sha256": _sha(source), "role": role})
    _dump_new(stage_package / "implementation-record-r01.json", {
        "schema_version": "week4-r04-implementation-amendment-v1",
        "amendment_id": "implementation-record-r01",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": implementation_entries,
    })

    amendment_parent_map = {
        "docket-correction-r01.json": [
            (PACKAGE_REL / "decision-docket.md").as_posix(),
            (PACKAGE_REL / "test-results.json").as_posix(),
            (PACKAGE_REL / "test-logs/focused-pytest.log").as_posix(),
            (PACKAGE_REL / "test-logs/full-pytest.log").as_posix(),
        ],
        "decision-docket-r01.md": [
            (PACKAGE_REL / "decision-docket.md").as_posix(),
            (PACKAGE_REL / "docket-correction-r01.json").as_posix(),
            (PACKAGE_REL / "test-results.json").as_posix(),
            (PACKAGE_REL / "test-logs/focused-pytest.log").as_posix(),
            (PACKAGE_REL / "test-logs/full-pytest.log").as_posix(),
        ],
        "implementation-record-r01.json": [relative for relative, _ in implementation_files],
    }
    amendment_entries = []
    for relative, parents in amendment_parent_map.items():
        path = stage_package / relative
        parent_hashes = {}
        for parent in sorted(set(parents)):
            if parent.startswith(PACKAGE_REL.as_posix() + "/"):
                parent_path = stage_package / PurePosixPath(parent).relative_to(PACKAGE_REL)
            else:
                parent_path = ROOT / parent
            parent_hashes[parent] = _sha(parent_path)
        amendment_entries.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": _sha(path),
            "kind": path.suffix.lower().lstrip(".") or "data",
            "parent_paths": sorted(set(parents)),
            "parent_sha256": parent_hashes,
        })
    manifest = {
        "schema_version": "week4-r04-integrity-manifest-amendment-v1",
        "amendment_id": "integrity-manifest-r01",
        "package_path": PACKAGE_REL.as_posix(),
        "manifest_excludes_self": True,
        "base_manifest_path": (PACKAGE_REL / "integrity-manifest.json").as_posix(),
        "base_manifest_sha256": base_manifest_sha,
        "previous_manifest_path": (PACKAGE_REL / "integrity-manifest.json").as_posix(),
        "previous_manifest_sha256": base_manifest_sha,
        "files": amendment_entries,
    }
    _dump_new(stage_package / SUPPLEMENTAL_MANIFEST, manifest)
    stage_check = verify_package_with_amendments(
        stage_package,
        project_root=ROOT,
        check_public_docket=False,
    )
    if stage_check["status"] != "PASS":
        raise RuntimeError(f"staged R04 R01 amendment failed verification: {stage_check['errors']}")

    for name in (*AMENDMENT_FILES, SUPPLEMENTAL_MANIFEST):
        with (stage_package / name).open("rb") as source, (PACKAGE / name).open("xb") as destination:
            shutil.copyfileobj(source, destination)
    with (PACKAGE / "decision-docket-r01.md").open("rb") as source, PUBLIC_DOCKET.open("xb") as destination:
        shutil.copyfileobj(source, destination)
    final_check = verify_package_with_amendments(PACKAGE, project_root=ROOT, run_fault_tests=True)
    if final_check["status"] != "PASS":
        raise RuntimeError(f"published R04 R01 amendment failed verification: {final_check['errors']}")
    return {
        "status": "PASS",
        "base_manifest_sha256": base_manifest_sha,
        "supplemental_manifest_sha256": _sha(PACKAGE / SUPPLEMENTAL_MANIFEST),
        "checked_files": final_check["checked_files"],
        "checked_parents": final_check["checked_parents"],
        "fault_tests": final_check["fault_tests"],
        "errors": final_check["errors"],
    }


if __name__ == "__main__":
    print(json.dumps(append_correction(), sort_keys=True, indent=2))
