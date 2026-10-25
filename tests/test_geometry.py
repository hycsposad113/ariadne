"""Release-blocking deterministic geometry verifier tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from urban_design.geometry import (
    GeometryValidationError,
    canonical_geometry_hash,
    polygon_area,
    polygon_perimeter,
    validate_geometry,
    validate_metric_input,
)


FIXTURE = Path(__file__).parent / "fixtures" / "geometry_100m_square.json"


def test_det002_known_answer_square() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    geometry = fixture["geometry"]
    assert polygon_area(geometry) == fixture["expected_area_m2"]
    assert polygon_perimeter(geometry) == fixture["expected_perimeter_m"]
    assert validate_geometry(geometry)["sha256"].startswith("sha256:")


def test_det003_invalid_geometry_fails_closed() -> None:
    cases = [
        {"type": "Polygon", "coordinates": []},
        {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [0, 2], [2, 0], [0, 0]]]},
        {"type": "Polygon", "coordinates": [[[0, 0, 1], [1, 0], [1, 1], [0, 0]]]},
        {"type": "Point", "coordinates": []},
        {"type": "LineString", "coordinates": [[0, 0], [0, 0]]},
    ]
    for geometry in cases:
        with pytest.raises(GeometryValidationError):
            validate_geometry(geometry)


def test_det008_canonical_hash_is_stable() -> None:
    geometry = json.loads(FIXTURE.read_text(encoding="utf-8"))["geometry"]
    assert canonical_geometry_hash(geometry) == canonical_geometry_hash(json.loads(json.dumps(geometry)))


def test_det009_missing_units_boundary_and_nonfinite_fail_closed() -> None:
    geometry = {"type": "Point", "coordinates": [1, 2]}
    boundary = json.loads(FIXTURE.read_text(encoding="utf-8"))["geometry"]
    with pytest.raises(GeometryValidationError, match="units"):
        validate_metric_input(geometry=geometry, units=None, boundary=boundary)
    with pytest.raises(GeometryValidationError, match="boundary"):
        validate_metric_input(geometry=geometry, units="m", boundary=None)
    with pytest.raises(GeometryValidationError, match="finite"):
        validate_metric_input(
            geometry={"type": "Point", "coordinates": [float("nan"), 2]}, units="m", boundary=boundary
        )
