from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import pytest

from urban_design.site_proposal import SiteProposal
from urban_design.site_proposal_v3 import (
    SiteProposalV3ValidationError,
    validate_layout_svg,
    validate_rendered_png,
    validate_site_proposal_v3,
    verify_package_integrity,
)
from urban_design.site_proposal_v2 import validate_site_proposal_v2, verify_v1_integrity
from urban_design.store import ProjectStateStore


ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ROOT / "artifacts" / "milestone2-site-proposal" / "run-20260915T000500Z"
V2_ROOT = ROOT / "artifacts" / "milestone2-site-proposal-v2" / "run-20260915T013000Z"
V3_ROOT = ROOT / "artifacts" / "milestone2-site-proposal-v3" / "run-20260915T020700Z"
BOUNDARY_SHA256 = "sha256:671117c91589b20ca28ffb39df1eb1697f12e42e0e7a3a5b969e7f7b5c1dc9c4"


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _payload() -> dict[str, object]:
    return json.loads((V3_ROOT / "site-proposal-v3.json").read_text(encoding="utf-8"))


def _all_points(value: object):
    if isinstance(value, dict):
        for item in value.values():
            yield from _all_points(item)
        return
    if isinstance(value, list):
        if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            yield float(value[0]), float(value[1])
        else:
            for item in value:
                yield from _all_points(item)


def test_v3_package_validates_against_retained_v2_and_external_parent() -> None:
    proposal = validate_site_proposal_v3(_payload(), V3_ROOT, v2_root=V2_ROOT)
    assert proposal.id == "site-proposal-delft-v3"
    assert proposal.version == "v3"
    assert proposal.status == "PROPOSED"
    assert proposal.supersedes_proposal_id == "site-proposal-delft-v2"


def test_v1_and_v2_validators_still_pass_after_v3_creation() -> None:
    v2_payload = json.loads((V2_ROOT / "site-proposal-v2.json").read_text(encoding="utf-8"))
    v2 = validate_site_proposal_v2(v2_payload, V2_ROOT, v1_root=V1_ROOT)
    assert v2.id == "site-proposal-delft-v2"
    v1_manifest = verify_v1_integrity(V2_ROOT / "v1-integrity.json", V1_ROOT)
    assert v1_manifest["file_count"] == 14


def test_v2_parent_manifest_and_all_parent_bytes_are_preserved() -> None:
    manifest = V3_ROOT / "v2-integrity.json"
    retained = verify_package_integrity(manifest, V3_ROOT / "parent-v2")
    external = verify_package_integrity(manifest, V2_ROOT)
    assert retained["file_count"] == external["file_count"] == 18
    entries = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    for entry in entries:
        relative = Path(entry["path"])
        assert (V3_ROOT / "parent-v2" / relative).read_bytes() == (V2_ROOT / relative).read_bytes()
    v1_manifest = V3_ROOT / "parent-v2" / "v1-integrity.json"
    v1_entries = json.loads(v1_manifest.read_text(encoding="utf-8"))["files"]
    for entry in v1_entries:
        artifact = V1_ROOT / entry["path"]
        assert artifact.stat().st_size == entry["size_bytes"]
        assert _sha256(artifact) == entry["sha256"]


def test_v3_boundary_is_byte_identical_to_v2_and_hash_is_exact() -> None:
    v3_boundary = V3_ROOT / "boundary-epsg28992-v3.geojson"
    v2_boundary = V2_ROOT / "boundary-epsg28992-v2.geojson"
    assert v3_boundary.read_bytes() == v2_boundary.read_bytes()
    assert v3_boundary.read_bytes() == (V3_ROOT / "parent-v2" / "boundary-epsg28992-v2.geojson").read_bytes()
    assert v3_boundary.stat().st_size == 322
    assert _sha256(v3_boundary) == BOUNDARY_SHA256
    payload = _payload()
    assert payload["boundary_sha256"] == BOUNDARY_SHA256
    assert payload["geometry_sha256"] == json.loads((V2_ROOT / "site-proposal-v2.json").read_text())["geometry_sha256"]


def test_v3_svg_layout_is_inside_viewbox_and_layers_are_ordered() -> None:
    payload = _payload()
    context = payload["delft_context"]
    assert isinstance(context, dict)
    result = validate_layout_svg(
        V3_ROOT / "map-preview-v3.svg",
        expected_sha256=context["map_svg_sha256"],
        expected_size_bytes=context["map_svg_size_bytes"],
    )
    assert result["viewbox"] == (0.0, 0.0, 1240.0, 850.0)
    boxes = result["layout_boxes"]
    assert boxes["legend"][0] + boxes["legend"][2] <= 1240
    assert boxes["footer-attribution"][1] + boxes["footer-attribution"][3] <= 850
    assert result["layer_order"].index("layer-boundary") > result["layer_order"].index("layer-rail")
    assert {"layer-water", "layer-public-space", "layer-buildings", "layer-roads", "layer-rail", "layer-boundary", "layer-markers"} <= set(result["layer_order"])

    root = ET.parse(V3_ROOT / "map-preview-v3.svg").getroot()
    boundary = next(element for element in root if element.attrib.get("id") == "layer-boundary")
    polygons = [element for element in boundary.iter() if element.tag.rsplit("}", 1)[-1] == "polygon"]
    assert polygons
    assert any(float(element.attrib["stroke-width"]) > 0 and float(element.attrib["fill-opacity"]) > 0 for element in polygons)
    boundary_points = [(float(x), float(y)) for x, y in (pair.split(",") for pair in polygons[0].attrib["points"].split())]
    assert all(44 <= x <= 834 and 100 <= y <= 690 for x, y in boundary_points)
    assert max(x for x, _ in boundary_points) - min(x for x, _ in boundary_points) > 100
    assert max(y for _, y in boundary_points) - min(y for _, y in boundary_points) > 100
    for layer_id in ("layer-water", "layer-buildings", "layer-roads", "layer-rail"):
        layer = next(element for element in root if element.attrib.get("id") == layer_id)
        assert any(child.tag.rsplit("}", 1)[-1] in {"polyline", "polygon"} for child in layer.iter())
    assert "Delft station" in "".join(root.itertext())
    assert "Oude Lijn railway" in "".join(root.itertext())
    assert "Buitenwatersloot canal" in "".join(root.itertext())
    assert "Houttuinen" in "".join(root.itertext())


def test_context_is_projected_to_margin_viewport_and_not_whole_way_extent() -> None:
    payload = _payload()
    context = payload["delft_context"]
    render = json.loads((V3_ROOT / context["render_record_path"]).read_text(encoding="utf-8"))
    viewport = render["viewport"]
    assert viewport == {"bbox": [84065.47777029805, 446708.456821202, 84509.79911601526, 447374.3074473919], "crs": "EPSG:28992", "margin_m": 120.0}
    xmin, ymin, xmax, ymax = viewport["bbox"]
    points = list(_all_points(json.loads((V3_ROOT / render["projected_context_path"]).read_text(encoding="utf-8"))))
    assert points
    assert any(x < xmin or x > xmax or y < ymin or y > ymax for x, y in points)
    boundary = json.loads((V3_ROOT / "boundary-epsg28992-v3.geojson").read_text(encoding="utf-8"))
    boundary_points = list(_all_points(boundary))
    assert all(xmin <= x <= xmax and ymin <= y <= ymax for x, y in boundary_points)
    bx0 = min(x for x, _ in boundary_points)
    bx1 = max(x for x, _ in boundary_points)
    by0 = min(y for _, y in boundary_points)
    by1 = max(y for _, y in boundary_points)
    assert bx1 - bx0 > 200
    assert by1 - by0 > 300
    assert render["context_geometry_clipped"] is True
    assert render["boundary_above_context"] is True
    assert render["margin_m"] == 120.0
    root = ET.parse(V3_ROOT / "map-preview-v3.svg").getroot()
    frame = (44.0, 100.0, 834.0, 690.0)
    context_points = []
    for element in root:
        if element.attrib.get("data-map-layer") != "context":
            continue
        for child in element.iter():
            if child.tag.rsplit("}", 1)[-1] not in {"polyline", "polygon"}:
                continue
            context_points.extend((float(x), float(y)) for x, y in (pair.split(",") for pair in child.attrib.get("points", "").split()))
    assert context_points
    assert all(frame[0] - 1e-6 <= x <= frame[2] + 1e-6 and frame[1] - 1e-6 <= y <= frame[3] + 1e-6 for x, y in context_points)


def test_v3_rendered_png_and_render_record_hashes_are_verified() -> None:
    payload = _payload()
    context = payload["delft_context"]
    render = json.loads((V3_ROOT / context["render_record_path"]).read_text(encoding="utf-8"))
    png_result = validate_rendered_png(
        V3_ROOT / context["rendered_png_path"],
        expected_sha256=context["rendered_png_sha256"],
        expected_size_bytes=context["rendered_png_size_bytes"],
    )
    assert png_result["dimensions"] == (1240, 850)
    assert render["svg_sha256"] == context["map_svg_sha256"]
    assert render["png_sha256"] == context["rendered_png_sha256"]
    assert _sha256(V3_ROOT / context["rendered_png_path"]) == context["rendered_png_sha256"]


def test_v3_state_is_proposed_and_appends_lineage_without_human_decision() -> None:
    with ProjectStateStore(V3_ROOT / "proposal-state-v3.sqlite3", read_only=True) as store:
        project = store.current("delft-pilot-project")
        assert project.get("site_id") is None
        proposal = store.replay("site-proposal-delft-v3")
        assert proposal.get("status") == "PROPOSED"
        assert proposal.get("supersedes_proposal_id") == "site-proposal-delft-v2"
        site = store.replay("site-delft-v3")
        assert site.get("status") == "proposed"
        events = store.events(project_id="delft-pilot-project")
        assert len(events) == 41
        assert any(event.target_id == "site-proposal-delft-v3" and event.supersedes == "site-proposal-delft-v2" for event in events)
        assert any(event.target_id == "site-delft-v3" and event.supersedes == "site-delft-v2" for event in events)
        assert all(event.target_type != "HumanDecision" for event in events)
        assert all("Approve" not in event.action and "Accept" not in event.action for event in events)


def test_v3_boundary_or_map_tamper_is_rejected(tmp_path: Path) -> None:
    payload = _payload()
    package = tmp_path / "m2-r02-tamper"
    shutil.copytree(V3_ROOT, package)
    boundary = package / "boundary-epsg28992-v3.geojson"
    boundary.write_bytes(boundary.read_bytes() + b" ")
    with pytest.raises(SiteProposalV3ValidationError, match="boundary bytes differ|boundary hash|artifact hash or size"):
        validate_site_proposal_v3(payload, package, v2_root=V2_ROOT)

    package = tmp_path / "m2-r02-map-tamper"
    shutil.copytree(V3_ROOT, package)
    svg = package / "map-preview-v3.svg"
    svg.write_text(svg.read_text(encoding="utf-8").replace("MAP REVIEW v3", "MAP REVIEW altered"), encoding="utf-8")
    with pytest.raises(SiteProposalV3ValidationError, match="SVG artifact hash mismatch"):
        validate_site_proposal_v3(payload, package, v2_root=V2_ROOT)


def test_v3_payload_remains_typed_and_does_not_mutate_v2_payload() -> None:
    v2 = json.loads((V2_ROOT / "site-proposal-v2.json").read_text(encoding="utf-8"))
    before = copy.deepcopy(v2)
    proposal = SiteProposal.model_validate(_payload())
    assert proposal.version == "v3"
    assert v2 == before
    assert proposal.delft_context["parent_boundary_sha256"] == BOUNDARY_SHA256
