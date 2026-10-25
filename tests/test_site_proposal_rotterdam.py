from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from urban_design.site_proposal_rotterdam import RotterdamSiteProposalValidationError, validate_site_proposal_rotterdam


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts" / "milestone2-site-proposal-rotterdam-m4h" / "run-20260915T101800Z"


def _payload() -> dict[str, object]:
    return json.loads((PACKAGE / "site-proposal.json").read_text(encoding="utf-8"))


def test_rotterdam_package_validates_and_remains_proposed() -> None:
    proposal = validate_site_proposal_rotterdam(_payload(), PACKAGE)
    assert proposal.id == "site-proposal-rotterdam-m4h-v1"
    assert proposal.status == "PROPOSED"
    assert proposal.human_decision_status == "HUMAN_DECISION_REQUIRED"
    assert proposal.delft_context["boundary_selection_status"] == "AMBIGUOUS_HUMAN_SELECTION_REQUIRED"
    assert proposal.delft_context["display_only"] is True


def test_both_boundary_options_are_retained_with_distinct_measurements() -> None:
    context = _payload()["delft_context"]
    assert isinstance(context, dict)
    options = context["boundary_options"]
    assert set(options) == {"A", "B"}
    assert options["A"]["projected_geometry_sha256"] != options["B"]["projected_geometry_sha256"]
    assert options["A"]["measurements"]["area_m2"] != options["B"]["measurements"]["area_m2"]
    assert options["A"]["edge_refs"] and options["B"]["edge_refs"]


def test_request_manifest_and_human_context_claims_are_retained() -> None:
    manifest = json.loads((PACKAGE / "sources" / "request-manifest.json").read_text(encoding="utf-8"))
    assert manifest["offline_rebuild_supported"] is True
    assert len(manifest["requests"]) >= 5
    claims = json.loads((PACKAGE / "sources" / "human-context-claims.json").read_text(encoding="utf-8"))
    assert {claim["classification"] for claim in claims["claims"]} <= {"HUMAN_PROVIDED_DESIGN_CONTEXT", "INTERPRETATION"}


def test_missing_source_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "package"
    import shutil

    shutil.copytree(PACKAGE, package)
    raw = package / "sources" / "raw" / "osm-overpass-m4h-context.json"
    raw.unlink()
    with pytest.raises(RotterdamSiteProposalValidationError, match="source artifact mismatch|missing"):
        validate_site_proposal_rotterdam(_payload(), package)


def test_ambiguous_boundary_cannot_be_silently_marked_selected() -> None:
    payload = _payload()
    tampered = copy.deepcopy(payload)
    tampered["delft_context"]["boundary_selection_status"] = "SELECTED"
    with pytest.raises(RotterdamSiteProposalValidationError, match="ambiguous boundary"):
        validate_site_proposal_rotterdam(tampered, PACKAGE)


def test_existing_delft_parent_bytes_are_verified() -> None:
    manifest = json.loads((PACKAGE / "delft-parent-integrity.json").read_text(encoding="utf-8"))
    assert {entry["parent"] for entry in manifest["files"]} == {"delft-v1", "delft-v2", "delft-v3"}
    assert all((PACKAGE / entry["retained_path"]).is_file() for entry in manifest["files"])
    assert validate_site_proposal_rotterdam(_payload(), PACKAGE).project_id == "rotterdam-m4h-pilot-project"

