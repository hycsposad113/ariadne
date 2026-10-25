import hashlib
from pathlib import Path

import pytest

from urban_design.fabric_syntax_segments import REPO_ROOT, verify

PLAN = REPO_ROOT / "artifacts/net2/round-7/plans/harbour_grain-plan.json"


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_receipt_from_another_checkout_resolves_inside_this_repository():
    moved = "/somewhere/else/old-checkout/artifacts/net2/round-7/plans/harbour_grain-plan.json"
    assert verify({"path": moved, "sha256": _sha(PLAN)}) == PLAN


def test_relocated_receipt_still_requires_matching_hash():
    moved = "/somewhere/else/old-checkout/artifacts/net2/round-7/plans/harbour_grain-plan.json"
    with pytest.raises(ValueError, match="BLOCKED"):
        verify({"path": moved, "sha256": "sha256:" + "0" * 64})


def test_unknown_location_stays_blocked():
    with pytest.raises(ValueError, match="BLOCKED"):
        verify({"path": "/private/tmp/net2-round-7-v3-pb/gone.json", "sha256": _sha(PLAN)})


def test_data_root_relocation(tmp_path, monkeypatch):
    target = tmp_path / "week5-syntax-modes" / "x.geojson"
    target.parent.mkdir(parents=True)
    target.write_text("{}")
    monkeypatch.setenv("URBAN_DESIGN_DATA_ROOT", str(tmp_path))
    recorded = "/Users/someone/.local/share/urban-design-data/week5-syntax-modes/x.geojson"
    assert verify({"path": recorded, "sha256": _sha(target)}) == target
