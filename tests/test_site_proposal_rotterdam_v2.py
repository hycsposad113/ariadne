from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from urban_design.site_proposal_rotterdam_v2 import (
    RotterdamSiteProposalV2ValidationError,
    validate_site_proposal_rotterdam_v2,
    validate_source_edge_relationships,
)
from urban_design.store import ProjectStateStore


ROOT = Path(__file__).resolve().parents[1]
V1_PACKAGE = ROOT / "artifacts" / "milestone2-site-proposal-rotterdam-m4h" / "run-20260915T101800Z"
PACKAGE = ROOT / "artifacts" / "milestone2-site-proposal-rotterdam-m4h-v2" / "run-20260915T110000Z"


def _payload() -> dict[str, object]:
    return json.loads((PACKAGE / "site-proposal.json").read_text(encoding="utf-8"))


def _hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_v2_package_validates_as_append_only_proposed_repair() -> None:
    proposal = validate_site_proposal_rotterdam_v2(_payload(), PACKAGE, v1_root=V1_PACKAGE)
    assert proposal.id == "site-proposal-rotterdam-m4h-v2"
    assert proposal.supersedes_proposal_id == "site-proposal-rotterdam-m4h-v1"
    assert proposal.status == "PROPOSED"
    assert proposal.human_decision_status == "HUMAN_DECISION_REQUIRED"
    assert proposal.delft_context["boundary_selection_status"] == "AMBIGUOUS_HUMAN_SELECTION_REQUIRED"
    assert proposal.delft_context["display_only"] is True


def test_each_control_point_has_retained_source_relationship() -> None:
    result = validate_source_edge_relationships(_payload(), PACKAGE)
    assert result["tolerance_m"] == 1.0
    for option in ("A", "B"):
        controls = result["options"][option]["control_points"]
        assert len(controls) == 4
        assert all(control["status"] == "PASS" for control in controls)
        assert all(control["nearest"]["distance_m"] <= 1.0 for control in controls)


def test_unsupported_v1_option_a_relationship_is_rejected() -> None:
    payload = json.loads((V1_PACKAGE / "site-proposal.json").read_text(encoding="utf-8"))
    with pytest.raises(RotterdamSiteProposalV2ValidationError, match="exceeds source tolerance"):
        validate_source_edge_relationships(payload, V1_PACKAGE, require_evidence=False)


def test_option_maps_have_one_boundary_and_distinct_metadata() -> None:
    context = _payload()["delft_context"]
    assert context["option_maps"]["A"]["viewport"] == context["option_maps"]["B"]["viewport"]
    assert context["option_maps"]["A"]["same_scale"] is True
    for option in ("A", "B"):
        path = PACKAGE / context["option_maps"][option]["svg_path"]
        root = ET.parse(path).getroot()
        boundaries = [element for element in root.iter() if element.attrib.get("data-boundary-option")]
        assert len(boundaries) == 1
        assert boundaries[0].attrib["data-boundary-option"] == option
        assert not any(element.attrib.get("id") == "layer-boundary-option-b" for element in root.iter())
        text = "".join(root.itertext()).casefold()
        assert "rail / station" not in text
        assert "station / verified landmark" in text


def test_comparison_is_two_panel_neutral_numeric_record() -> None:
    context = _payload()["delft_context"]
    root = ET.parse(PACKAGE / context["comparison_map"]["svg_path"]).getroot()
    panels = [element for element in root if element.tag.rsplit("}", 1)[-1] == "g" and element.attrib.get("data-comparison-panel")]
    assert {panel.attrib["data-comparison-panel"] for panel in panels} == {"A", "B"}
    assert len([element for element in root.iter() if element.attrib.get("data-boundary-option")]) == 2
    deltas = context["comparison_deltas"]
    assert deltas["preference"] == "NONE"
    assert deltas["area_delta_m2"] != 0
    assert deltas["perimeter_delta_m"] != 0
    assert "human-sketch" in deltas["different_edge_interpretation"]


def test_v1_bytes_are_retained_and_rehashed() -> None:
    manifest = json.loads((PACKAGE / "parent-v1-integrity.json").read_text(encoding="utf-8"))
    assert manifest["parent_id"] == "site-proposal-rotterdam-m4h-v1"
    assert manifest["files"]
    for entry in manifest["files"]:
        retained = PACKAGE / entry["retained_path"]
        external = V1_PACKAGE / entry["relative_path"]
        assert retained.is_file() and external.is_file()
        assert retained.stat().st_size == external.stat().st_size == entry["size_bytes"]
        assert _hash(retained) == _hash(external) == entry["sha256"]


def test_state_remains_null_and_has_no_human_approval() -> None:
    with ProjectStateStore(PACKAGE / "proposal-state.sqlite3", read_only=True) as store:
        assert store.current("rotterdam-m4h-pilot-project").get("site_id") is None
        assert store.current("site-rotterdam-m4h-v2").get("status") == "proposed"
        assert all(event.target_type != "HumanDecision" and event.action not in {"Approve", "Accept"} for event in store.events(project_id="rotterdam-m4h-pilot-project"))


def test_offline_rebuild_matches_deterministic_artifacts(tmp_path: Path) -> None:
    from scripts.create_site_proposal_rotterdam_v2 import build_rotterdam_v2

    rebuilt = build_rotterdam_v2(tmp_path / "rebuild", v1_dir=V1_PACKAGE, offline=True)
    assert rebuilt.id == "site-proposal-rotterdam-m4h-v2"
    for relative in ("boundary-epsg28992-v2.geojson", "boundary-epsg28992-option-a-v2.geojson", "boundary-epsg28992-option-b-v2.geojson", "sources/source-distance-evidence.json", "map-option-a-v2.svg", "map-option-b-v2.svg", "map-preview-comparison-v2.svg"):
        assert _hash(tmp_path / "rebuild" / relative) == _hash(PACKAGE / relative)
