"""J4 statistical policy is authored and non-significant trends are excluded."""
from urban_design.environment.e2_service import Recipe, direction_summary, METHODS


def test_recipe_records_repeated_sampling_and_assumed_threshold():
    recipe = Recipe().model_dump(mode='json')
    assert recipe.get('noise_repetitions', 0) >= 3
    assert recipe['noise_classification'] == 'ASSUMED_COMMANDER'
    assert '-u-' in recipe['verification']


def test_direction_agreement_excludes_non_significant_pairs():
    comparisons = {method:{str(i):{'direction':'NOT_SIGNIFICANT'} for i in (-1,0,1)} for method in METHODS}
    summary = direction_summary(comparisons)
    assert summary['direction_agreement_by_offset']['0'] is None
    assert summary['sensitivity_reversed'] is False


def test_observed_delta_noise_band_retains_uncertainty_and_significance():
    import math
    import statistics
    import urban_design.environment.e2_service as service
    assert callable(getattr(service,'noise_assessment',None)), 'No repeated-delta noise estimator'
    values = [0.063,-0.052,0.010]
    noise = service.noise_assessment(values, Recipe())
    assert noise['sample_count'] == 3
    assert math.isclose(noise['delta_sample_stddev_kwh_m2'], statistics.stdev(values))
    assert noise['threshold_kwh_m2'] == 2 * statistics.stdev(values)
    assert noise['direction'] == 'NOT_SIGNIFICANT'
    assert noise['classification'] == 'ASSUMED_COMMANDER'
    assert service.noise_assessment([2.,2.,2.],Recipe())['direction'] == 'INCREASED'
    assert service.noise_assessment([-2.,-2.,-2.],Recipe())['direction'] == 'DECREASED'
    assert service.noise_assessment([0.,0.,0.],Recipe())['direction'] == 'NOT_SIGNIFICANT'
    import pytest
    with pytest.raises(ValueError): service.noise_assessment([1.,2.],Recipe())
    with pytest.raises(ValueError): service.noise_assessment([1.,2.,float('nan')],Recipe())
