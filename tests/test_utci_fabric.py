"""Tests for Outdoor Thermal Comfort (UTCI) fabric simulation.

Verifies:
1. Shaded sensor point has strictly lower MRT and UTCI than sun-exposed point on a hot summer day.
2. Urban roughness logarithmic wind profile converts 10m wind to 1.1m within valid bounds.
3. UTCI classification correctly maps temperatures to standard heat stress levels.
"""

import math
import sys
import types
from pathlib import Path

# Intercept urban_design package so top-level __init__.py does not load missing server modules
if "urban_design" not in sys.modules:
    pkg = types.ModuleType("urban_design")
    pkg.__path__ = ["src/urban_design"]
    sys.modules["urban_design"] = pkg

from ladybug_comfort import solarcal, utci

from scripts.utci_fabric import (
    classify_utci,
    compute_log_wind_1_1m,
    get_utci_color,
    URBAN_ROUGHNESS_Z0,
    REFERENCE_HEIGHT_Z10,
    SENSOR_HEIGHT_Z1_1,
)


def test_shaded_point_utci_lower_than_sunlit():
    """Verify that a shaded point has significantly lower MRT and UTCI than a sun-exposed point."""
    # Peak summer day conditions (2017-08-19 14:00)
    ta = 32.1
    rh = 35.0
    ws10 = 5.0
    v1_1 = compute_log_wind_1_1m(ws10, URBAN_ROUGHNESS_Z0)
    dni = 780.0
    dhi = 104.0
    ir = 378.0
    alt = 48.0

    # Point A: Sun-exposed open plaza (fract_exposed = 1.0, high SVF = 0.95)
    sunlit_res = solarcal.outdoor_sky_heat_exch(
        srfs_temp=ta,
        horiz_ir=ir,
        diff_horiz_solar=dhi,
        dir_normal_solar=dni,
        alt=alt,
        sky_exposure=0.95,
        fract_exposed=1.0,
        floor_reflectance=0.25,
        posture="standing",
        sharp=135,
        body_absorptivity=0.7,
        body_emissivity=0.95,
    )
    mrt_sunlit = sunlit_res["mrt"]
    utci_sunlit = utci.universal_thermal_climate_index(ta, mrt_sunlit, v1_1, rh)

    # Point B: Building-shaded sidewalk (fract_exposed = 0.0, lower SVF = 0.55)
    shaded_res = solarcal.outdoor_sky_heat_exch(
        srfs_temp=ta,
        horiz_ir=ir,
        diff_horiz_solar=dhi,
        dir_normal_solar=dni,
        alt=alt,
        sky_exposure=0.55,
        fract_exposed=0.0,
        floor_reflectance=0.25,
        posture="standing",
        sharp=135,
        body_absorptivity=0.7,
        body_emissivity=0.95,
    )
    mrt_shaded = shaded_res["mrt"]
    utci_shaded = utci.universal_thermal_climate_index(ta, mrt_shaded, v1_1, rh)

    # Shaded point MRT must be much lower than sunlit point
    assert mrt_shaded < mrt_sunlit - 15.0, (
        f"Expected shaded MRT ({mrt_shaded:.1f}C) to be at least 15C lower than sunlit ({mrt_sunlit:.1f}C)"
    )

    # Shaded point UTCI must be strictly lower than sunlit point (遮陰點 UTCI 低於曝曬點)
    assert utci_shaded < utci_sunlit - 3.5, (
        f"Expected shaded UTCI ({utci_shaded:.2f}C) to be significantly lower than sunlit ({utci_sunlit:.2f}C)"
    )

    # Sunlit point should be in very strong heat stress (>= 38C)
    assert utci_sunlit >= 38.0, f"Expected sunlit UTCI >= 38.0C, got {utci_sunlit:.2f}C"
    # Shaded point should drop to moderate/strong stress (< 34C)
    assert utci_shaded < 34.0, f"Expected shaded UTCI < 34.0C, got {utci_shaded:.2f}C"


def test_logarithmic_wind_speed_reduction():
    """Verify that logarithmic wind law properly scales down wind speed to pedestrian height."""
    for ws10 in [2.0, 4.0, 5.0, 8.0]:
        v1_1 = compute_log_wind_1_1m(ws10, URBAN_ROUGHNESS_Z0)
        # Pedestrian wind at 1.1m in urban area must be less than 10m wind
        assert v1_1 < ws10, f"Pedestrian wind ({v1_1}) should be less than 10m wind ({ws10})"
        # Must respect lower bound of 0.5 m/s for UTCI polynomial
        assert v1_1 >= 0.5, f"Pedestrian wind ({v1_1}) must be >= 0.5 m/s"

    # With z0 = 0.5m, ratio is ln(1.1/0.5) / ln(10/0.5) = ln(2.2)/ln(20) ~ 0.2632
    expected_ratio = math.log(SENSOR_HEIGHT_Z1_1 / URBAN_ROUGHNESS_Z0) / math.log(REFERENCE_HEIGHT_Z10 / URBAN_ROUGHNESS_Z0)
    assert abs(expected_ratio - 0.2632) < 0.001


def test_utci_classification_thresholds():
    """Verify standard UTCI heat stress classification categories."""
    assert classify_utci(22.0) == "no_stress"
    assert classify_utci(26.0) == "no_stress"
    assert classify_utci(26.1) == "moderate"
    assert classify_utci(32.0) == "moderate"
    assert classify_utci(32.1) == "strong"
    assert classify_utci(38.0) == "strong"
    assert classify_utci(38.5) == "very_strong"
    assert classify_utci(46.0) == "very_strong"
    assert classify_utci(47.0) == "extreme"

    # Colors match expected palette
    assert get_utci_color(24.0) == "#2a9d8f"
    assert get_utci_color(29.0) == "#e9c46a"
    assert get_utci_color(35.0) == "#f4a261"
    assert get_utci_color(39.0) == "#e76f51"
    assert get_utci_color(48.0) == "#7209b7"


if __name__ == "__main__":
    test_shaded_point_utci_lower_than_sunlit()
    test_logarithmic_wind_speed_reduction()
    test_utci_classification_thresholds()
    print("All UTCI fabric unit tests passed successfully!")
