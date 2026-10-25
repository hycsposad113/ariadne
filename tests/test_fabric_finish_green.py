"""The frozen run-4 road divider must preserve all measured geometry."""
import copy
import json
from pathlib import Path

import pytest
from shapely.geometry import shape
from shapely.ops import unary_union

from urban_design.generation.fabric_finish_green import finish_green
from urban_design.generation.fabric_plan import validate_plan


@pytest.fixture(scope='module')
def frozen_plan():
    path = Path(__file__).resolve().parents[1] / 'artifacts/fab1/run-4/landscape_figure-plan.json'
    return json.loads(path.read_text())


def test_complete_road_defined_park_units_preserve_geometry(frozen_plan):
    original = copy.deepcopy(frozen_plan)
    finished = finish_green(frozen_plan)
    assert frozen_plan == original
    assert finished['roads'] == original['roads']
    assert finished['buildings'] == original['buildings']
    for category in ('parks', 'blocks', 'roads', 'waterfront'):
        def footprint(plan):
            return unary_union([shape(r['geometry']) for r in plan['land_use'] if r['properties']['category'] == category])
        assert footprint(finished).symmetric_difference(footprint(original)).area < .01
    record = finished['green_finish_evidence'][0]
    assert record['road_id'] == 'road-clean-1'
    assert all(a >= 1000 for a in record['unit_areas_m2'])
    assert record['dissolved_difference_m2'] < .01
    assert finish_green(finished)['land_use'] == finished['land_use']


def test_original_validator_green_gates_and_no_regressions(frozen_plan):
    before = validate_plan(frozen_plan)['checks']
    after = validate_plan(finish_green(frozen_plan))['checks']
    for gate in ('PARK_COHERENT_SHAPE', 'LANDSCAPE_GREEN_AXIS_CONTINUITY', 'PARK_AREA_BUDGET', 'NO_LARGE_UNBUILT_PLOT'):
        assert after[gate]['passed'], after[gate]
    assert {k for k,v in after.items() if not v['passed']} <= {k for k,v in before.items() if not v['passed']}
