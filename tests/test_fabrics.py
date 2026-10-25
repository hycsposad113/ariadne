from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
FABRIC_IDS = {
    "fabric.harbour_grain",
    "fabric.closed_block_extension",
    "fabric.courtyard_islands",
    "fabric.landscape_figure",
    "fabric.orthogonal_grid",
    "fabric.irregular_fine",
}


def _validator_module():
    path = ROOT / "scripts" / "validate_fabrics.py"
    spec = importlib.util.spec_from_file_location("validate_fabrics", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_six_fabrics_match_schema_and_resolve_all_references():
    schema = json.loads((ROOT / "knowledge/v2/fabric.schema.json").read_text("utf-8"))
    files = sorted((ROOT / "knowledge/v2/domains/MOR/fabrics").glob("*.json"))
    assert len(files) == 6

    validator = Draft202012Validator(schema)
    fabrics = [json.loads(path.read_text("utf-8")) for path in files]
    assert {fabric["id"] for fabric in fabrics} == FABRIC_IDS

    for fabric in fabrics:
        assert list(validator.iter_errors(fabric)) == [], fabric["id"]

    assert _validator_module().validate_fabrics(ROOT) == []


def test_each_land_use_budget_can_sum_to_one_hundred_percent():
    files = sorted((ROOT / "knowledge/v2/domains/MOR/fabrics").glob("*.json"))
    assert len(files) == 6
    for path in files:
        budget = json.loads(path.read_text("utf-8"))["land_use_budget"]
        minimum_total = sum(item["minimum"] for item in budget.values())
        maximum_total = sum(item["maximum"] for item in budget.values())
        assert minimum_total <= 100 <= maximum_total, path.name


def test_new_fabric_knowledge_units_match_the_kb_v2_schema():
    schema = json.loads((ROOT / "knowledge/v2/unit.schema.json").read_text("utf-8"))
    validator = Draft202012Validator(schema)
    paths = [ROOT / f"knowledge/v2/domains/MOR/units/KU-MOR-{number}.json" for number in range(100, 106)]
    assert all(path.is_file() for path in paths)
    for path in paths:
        unit = json.loads(path.read_text("utf-8"))
        assert list(validator.iter_errors(unit)) == [], path.name


def test_validator_cli_reports_clear_success():
    errors = _validator_module().validate_fabrics(ROOT)
    assert errors == []


def test_harbour_grain_does_not_make_perimeter_blocks_the_largest_share():
    path = ROOT / "knowledge/v2/domains/MOR/fabrics/fabric.harbour_grain.json"
    fabric = json.loads(path.read_text("utf-8"))
    shares = {
        item["part_id"]: item["recommended_share_percent"]
        for item in fabric["building_composition"]["components"]
    }

    assert shares["block.perimeter"] < max(
        share for part_id, share in shares.items() if part_id != "block.perimeter"
    )


def test_six_fabric_compositions_are_pairwise_distinct():
    files = sorted((ROOT / "knowledge/v2/domains/MOR/fabrics").glob("*.json"))
    compositions = []
    for path in files:
        fabric = json.loads(path.read_text("utf-8"))
        compositions.append(
            tuple(
                sorted(
                    (
                        item["part_id"],
                        item["recommended_share_percent"],
                    )
                    for item in fabric["building_composition"]["components"]
                )
            )
        )

    assert len(compositions) == 6
    assert len(set(compositions)) == 6


def test_each_composition_share_has_an_explicit_basis():
    files = sorted((ROOT / "knowledge/v2/domains/MOR/fabrics").glob("*.json"))
    for path in files:
        fabric = json.loads(path.read_text("utf-8"))
        for item in fabric["building_composition"]["components"]:
            assert item.get("basis_zh"), (fabric["id"], item["part_id"])


def test_each_fabric_records_the_20m_height_cap_translation():
    files = sorted((ROOT / "knowledge/v2/domains/MOR/fabrics").glob("*.json"))
    for path in files:
        fabric = json.loads(path.read_text("utf-8"))
        assert len(fabric.get("height_cap_adaptation_zh", "")) >= 30, fabric["id"]

    landscape = json.loads(
        (ROOT / "knowledge/v2/domains/MOR/fabrics/fabric.landscape_figure.json").read_text("utf-8")
    )
    assert any(
        item["part_id"] == "block.towers_park"
        for item in landscape["building_composition"]["components"]
    )


def test_block_dimensions_and_street_gap_proxy_are_status_labeled():
    files = sorted((ROOT / "knowledge/v2/domains/MOR/fabrics").glob("*.json"))
    allowed_block_statuses = {"EDITORIAL", "MEASURED_PRECEDENT_DERIVED"}
    for path in files:
        fabric = json.loads(path.read_text("utf-8"))
        for dimension in ("short_edge_m", "long_edge_m"):
            basis = fabric["blocks"][dimension].get("basis", {})
            assert basis.get("status") in allowed_block_statuses, (fabric["id"], dimension)

        proxy = fabric["street_network"].get("street_width_building_gap_proxy_m", {})
        assert proxy.get("status") == "MEASURED_PRECEDENT_PROXY", fabric["id"]
        assert proxy.get("p25", float("inf")) <= proxy.get("p75", -1), fabric["id"]
