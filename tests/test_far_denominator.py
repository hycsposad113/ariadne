from types import SimpleNamespace
import pytest
from shapely.geometry import box, GeometryCollection
from urban_design.far import FarSiteContext, resolve_far_denominator
from urban_design.morphology.metrics import calculate_far

@pytest.mark.parametrize("basis,area,expected", [("land_area", 8000, 1.0), ("exploration_design_area", 10000, .8)])
def test_same_gfa_two_bases(basis, area, expected):
    resolved, label = resolve_far_denominator(SimpleNamespace(denominator=basis), FarSiteContext(box(0, 0, 100, 100), box(0, 0, 20, 100)))
    assert resolved == area
    assert label == basis
    assert calculate_far(8000, resolved) == expected
    assert .8 * resolved == pytest.approx(.8 * area)

def test_water_union_clipped_and_zero_water():
    site = box(0, 0, 100, 100)
    assert resolve_far_denominator(SimpleNamespace(denominator="land_area"), FarSiteContext(site, box(-20, 0, 20, 100)))[0] == 8000
    for basis in ("land_area", "exploration_design_area"):
        assert resolve_far_denominator(SimpleNamespace(denominator=basis), FarSiteContext(site, GeometryCollection()))[0] == 10000

def test_legacy_preserves_caller_basis():
    context = FarSiteContext(box(0, 0, 100, 100), box(0, 0, 20, 100))
    assert resolve_far_denominator(SimpleNamespace(denominator=None), context) == (10000, "legacy/unspecified:exploration_design_area")
    assert resolve_far_denominator(None, context, legacy_basis="land_area") == (8000, "legacy/unspecified:land_area")

def test_missing_water_and_invalid_basis_fail_closed():
    context = FarSiteContext(box(0, 0, 100, 100))
    for basis in ("land_area", "invalid"):
        with pytest.raises(ValueError):
            resolve_far_denominator(SimpleNamespace(denominator=basis), context)


def test_approved_report_uses_selected_area_for_known_and_unknown_gfa():
    from urban_design.approved_generation import _candidate_metrics
    from urban_design.models import UnavailableValue
    site = box(0, 0, 100, 100)
    candidate = SimpleNamespace(provenance="APPROVED_PROJECT_DATA", buildings=(SimpleNamespace(footprint=box(0,0,20,100), floor_count=4, use_label="housing"),),
        metrics=SimpleNamespace(gfa_m2=8000, far=.8, coverage_ratio=.2, height_m=12), road_surfaces=(), preserved_road_surfaces=(), open_space=box(20,0,100,100))
    inputs = SimpleNamespace(constraint_set=SimpleNamespace(constraints=(SimpleNamespace(name="far_upper_limit", scope="whole_site", denominator="land_area"),)), water_geometry=box(0,0,20,100))
    report = _candidate_metrics(candidate, site, inputs=inputs, has_unknown_retained_floors=False)
    assert report["far"]["value"] == 1
    assert report["far"]["denominator_area_m2"] == 8000
    candidate.metrics.gfa_m2 = candidate.metrics.far = UnavailableValue(reason="unknown retained floors")
    report = _candidate_metrics(candidate, site, inputs=inputs, has_unknown_retained_floors=True)
    assert report["far"]["known_lower_bound"] == 1
    assert report["far"]["status"] == "PARTIALLY_UNKNOWN"

@pytest.mark.parametrize('basis', ['land_area', 'exploration_design_area', None])
def test_generation_budget_validation_report_integration(basis):
    from dataclasses import replace
    from test_morphology import _site_fixture
    from urban_design.morphology.contracts import NonBuildableArea
    from urban_design.morphology.strategies import generate_site_strategies
    from urban_design.approved_generation import _candidate_metrics
    base = _site_fixture()
    water = box(140, 60, 160, 100)
    constraints = tuple(replace(c, denominator=basis, value=.8 if c.name == 'far_upper_limit' else c.value)
                        if c.name in {'far_upper_limit', 'zone_far_upper_limit'} else c
                        for c in base.approved_constraints)
    inputs = replace(base, approved_constraints=constraints,
                     non_buildable_areas=(NonBuildableArea('water', water, 'water', 'test-water'),),
                     provenance='APPROVED_PROJECT_DATA')
    result = generate_site_strategies(inputs)
    area = inputs.design_area.area if basis == 'exploration_design_area' else inputs.land_area.area
    assert result.metadata['far_gfa_upper_limit_m2'] == pytest.approx(.8 * area)
    assert result.metadata['far_denominator']['area_m2'] == area
    report_inputs = SimpleNamespace(constraint_set=SimpleNamespace(constraints=constraints), water_geometry=water)
    for candidate in result.candidates:
        assert candidate.diff_report['far_denominator']['area_m2'] == area
        assert candidate.metrics.far == pytest.approx(candidate.metrics.gfa_m2 / area)
        zone = candidate.diff_report['zone_far_denominators']['zone-whole-site']
        assert zone['area_m2'] == area
        assert candidate.diff_report['zone_far_ratio']['zone-whole-site'] == pytest.approx(candidate.metrics.gfa_m2 / area)
        report = _candidate_metrics(candidate, inputs.design_area, inputs=report_inputs, has_unknown_retained_floors=False)
        assert report['far']['value'] == pytest.approx(candidate.metrics.far)
        if basis:
            assert report['far']['denominator_area_m2'] == area
            assert report['far']['denominator_label'] == basis
        else:
            assert report['far']['denominator_label'].startswith('legacy/unspecified')
            assert report['far']['denominator_area_m2'] == area
