from __future__ import annotations

import importlib
import importlib.util
import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _dictionary_module():
    spec = importlib.util.find_spec("urban_design.morphology_dictionary")
    assert spec is not None, "the morphology dictionary query module is required"
    return importlib.import_module("urban_design.morphology_dictionary")


def test_loads_schema_valid_entries_and_resolved_sources():
    module = _dictionary_module()
    dictionary = module.load_dictionary(ROOT / "config" / "morphology-dictionary")

    assert module.validate_dictionary(dictionary) is None
    assert len(dictionary["entries"]) >= 31
    assert dictionary["schema"]["$schema"].endswith("2020-12/schema")

    counts = {"building_plan": 0, "block_assembly": 0, "street_open_space": 0}
    source_ids = set(dictionary["atmospheres"]["source_registry"])
    for entry in dictionary["entries"]:
        counts[entry["level"]] += 1
        assert entry["sources"], entry["id"]
        assert {source["id"] for source in entry["sources"]} <= source_ids
        assert 1 <= len(entry["precedents"]) <= 3, entry["id"]
        for precedent in entry["precedents"]:
            assert precedent["source_ids"], entry["id"]
            assert set(precedent["source_ids"]) <= source_ids

    assert counts == {"building_plan": 15, "block_assembly": 8, "street_open_space": 8}


def test_rejects_entry_that_breaks_the_json_schema():
    module = _dictionary_module()
    dictionary = module.load_dictionary(ROOT / "config" / "morphology-dictionary")
    invalid = dict(dictionary["entries"][0])
    invalid.pop("id")

    with pytest.raises(ValueError, match="id"):
        module.validate_entry(invalid, dictionary["schema"])


def test_atmosphere_query_ranks_open_and_private_forms_by_requested_targets():
    module = _dictionary_module()
    dictionary = module.load_dictionary(ROOT / "config" / "morphology-dictionary")

    results = module.query_by_atmosphere(
        dictionary,
        {"permeability": 0.9, "privacy": 0.1},
        levels=["block_assembly"],
        limit=5,
    )

    assert results
    assert results[0]["fit"] >= results[-1]["fit"]
    assert "block.open" in {result["entry_id"] for result in results}
    assert "block.perimeter" not in {result["entry_id"] for result in results[:1]}


def test_recommendation_query_returns_a_resolvable_layered_composition():
    module = _dictionary_module()
    dictionary = module.load_dictionary(ROOT / "config" / "morphology-dictionary")

    result = module.recommend_composition(dictionary, "quiet_belonging_courtyard")

    ids = {item["entry"]["id"] for item in result["entries"]}
    assert "block.perimeter" in ids
    assert "space.courtyard" in ids
    assert result["recipe"]["target_scores"]["privacy"] >= 0.75


def test_catalog_is_self_contained_and_lists_every_dictionary_entry():
    module = _dictionary_module()
    dictionary = module.load_dictionary(ROOT / "config" / "morphology-dictionary")
    html = (ROOT / "artifacts" / "morphology-dictionary" / "catalog.html").read_text(
        encoding="utf-8"
    )

    assert not re.search(r"<script\b[^>]*\bsrc\s*=|<link\b[^>]*\bhref\s*=|@import\s", html, re.I)
    for entry in dictionary["entries"]:
        assert entry["id"] in html
    assert "<svg" in html


def test_parts_envelopes_are_narrowed_and_atmosphere_scores_are_non_decisional():
    module = _dictionary_module()
    dictionary = module.load_dictionary(ROOT / "config" / "morphology-dictionary")
    active_dir = ROOT / "config" / "morphology-dictionary" / "entries"
    backup_dir = ROOT / "config" / "morphology-dictionary" / "entries-v1"
    assert {path.name for path in active_dir.glob("*.yaml")} == {
        path.name for path in backup_dir.glob("*.yaml")
    }

    by_id = {entry["id"]: entry for entry in dictionary["entries"]}
    assert by_id["block.perimeter"]["plan_geometry"]["frontage_m"]["maximum"] == 120
    assert by_id["block.perimeter"]["plan_geometry"]["depth_m"]["maximum"] == 120
    assert by_id["building.i_slab"]["plan_geometry"]["frontage_m"]["maximum"] <= 90
    assert by_id["building.i_slab"]["plan_geometry"]["depth_m"] == {
        "minimum": 10,
        "maximum": 15,
        "unit": "m",
    }
    assert by_id["building.industrial_hall"]["plan_geometry"]["depth_m"] == {
        "minimum": 20,
        "maximum": 40,
        "unit": "m",
    }
    assert by_id["space.courtyard"]["plan_geometry"]["courtyard_clear_width_m"]["minimum"] >= 20

    allowed_statuses = {"EDITORIAL", "MEASURED_PRECEDENT", "LITERATURE", "MIXED"}
    for entry in dictionary["entries"]:
        assert entry["parameter_basis"]["status"] in allowed_statuses
        assert entry["plan_geometry"]["status"] in allowed_statuses
        for metric in entry["density_reference"].values():
            if isinstance(metric, dict):
                assert metric["status"] in allowed_statuses
        for score in entry["atmosphere_scores"].values():
            assert score["decision_use"] == "NOT_FOR_DECISION"

        original = json.loads((backup_dir / next(p.name for p in active_dir.glob("*.yaml") if json.loads(p.read_text("utf-8"))["id"] == entry["id"])).read_text("utf-8"))
        for section in ("plan_geometry", "density_reference"):
            for path, old_span in _numeric_range_spans(original[section]):
                new_value = entry[section]
                for key in path:
                    new_value = new_value[key]
                new_span = new_value["maximum"] - new_value["minimum"]
                assert new_span < old_span if old_span > 0 else new_span == old_span, (entry["id"], section, path)


def _numeric_range_spans(value, path=()):
    spans = []
    if isinstance(value, dict):
        minimum, maximum = value.get("minimum"), value.get("maximum")
        if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)):
            spans.append((path, maximum - minimum))
        for key, nested in value.items():
            spans.extend(_numeric_range_spans(nested, path + (key,)))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            spans.extend(_numeric_range_spans(nested, path + (index,)))
    return spans
