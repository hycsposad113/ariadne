"""Regression tests for the append-only M2-A03-R08-R01 verifier repair."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


PROJECT = Path(__file__).resolve().parents[1]
REPAIR = PROJECT / "artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-r01-verifier-repair-20260919T172048Z"
RETAINED = PROJECT / "artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-minute-semantics-20260919T154701Z"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("m2a03_r08_r01_verify", REPAIR / "r08-r01-verify.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_valid_repair_verification_passes_and_checks_all_three_candidates(tmp_path):
    verifier = _load_verifier()
    result = verifier.verify_package(output_path=tmp_path / "valid.json")

    assert result["status"] == "PASS"
    assert result["acceptance_failures"] == []
    assert result["input_file_count"] == 53
    assert len(result["candidates"]) == 3
    assert all(all(candidate["checks"].values()) for candidate in result["candidates"])


def test_each_repaired_gate_is_fail_closed_by_independent_fault_injection(tmp_path):
    verifier = _load_verifier()
    result = verifier.verify_package(output_path=tmp_path / "valid.json")
    targets = {name for name in result["gate_checks"] if name.startswith("candidate_") and name != "candidate_count_is_three"}

    assert len(targets) == 63
    for target in sorted(targets):
        mutated = dict(result["gate_checks"])
        mutated[target] = False
        failures = verifier.acceptance_failures(mutated)
        assert target in failures
        assert failures


def test_retained_inputs_and_frozen_result_are_immutable_after_later_verification(tmp_path):
    verifier = _load_verifier()
    retained_manifest = json.loads((RETAINED / "integrity-manifest.json").read_text())
    before_inputs = {
        entry["path"]: (entry["size_bytes"], entry["sha256"])
        for entry in retained_manifest["files"]
    }
    frozen = REPAIR / "frozen-verification-result.json"
    frozen_before = frozen.read_bytes()
    frozen_hash = _sha(frozen)

    later = verifier.verify_package(output_path=tmp_path / "later.json")
    assert later["status"] == "PASS"
    assert frozen.read_bytes() == frozen_before
    assert _sha(frozen) == frozen_hash
    for relative, (size, digest) in before_inputs.items():
        path = RETAINED / relative
        assert path.stat().st_size == size
        assert _sha(path) == digest


def test_verifier_rejects_output_inside_repair_package(tmp_path):
    verifier = _load_verifier()
    with pytest.raises(verifier.VerificationError, match="outside the repair package"):
        verifier.verify_package(output_path=REPAIR / "frozen-verification-result.json")
