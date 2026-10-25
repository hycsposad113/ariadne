from __future__ import annotations

import calendar
from datetime import timedelta

from urban_design.weather_derived import (
    _angles_at,
    derive_minute_zero_as_hour_end,
    diagnose_solar_semantics,
    interval_datetime,
    restore_source_bytes_from_mapping,
    sensitivity_direct_radiation,
)


def _fixture_epw() -> bytes:
    headers = [
        "LOCATION,Fixture Station,ZH,Netherlands,TMY,063440,51.95,4.14,1,0",
        "DESIGN CONDITIONS,0",
        "TYPICAL/EXTREME PERIODS,0",
        "GROUND TEMPERATURES,0",
        "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
        "COMMENTS 1,fixture-only synthetic rows",
        "COMMENTS 2,",
        "DATA PERIODS,1,1,Data,Sunday,1/1,12/31",
    ]
    rows: list[str] = []
    for month in range(1, 13):
        for day in range(1, calendar.monthrange(2023, month)[1] + 1):
            for hour in range(1, 25):
                fields = ["0"] * 35
                fields[0:5] = ["2023", str(month), str(day), str(hour), "0"]
                fields[14] = "100" if month in {6, 7, 8} and 8 <= hour <= 16 else "0"
                rows.append(",".join(fields))
    return ("\n".join((*headers, *rows)) + "\n").encode("utf-8")


def test_timestamp_assumptions_map_epw_hour_to_start_midpoint_and_end() -> None:
    start = interval_datetime(6, 21, 12, "hour_start")
    midpoint = interval_datetime(6, 21, 12, "hour_midpoint")
    end = interval_datetime(6, 21, 12, "hour_end")

    assert (start.hour, start.minute) == (11, 0)
    assert (midpoint.hour, midpoint.minute) == (11, 30)
    assert (end.hour, end.minute) == (12, 0)
    assert end - start == timedelta(hours=1)


def test_minute_zero_derivation_passes_existing_validator_and_round_trips() -> None:
    original = _fixture_epw()
    derived = derive_minute_zero_as_hour_end(original, filename="fixture.epw")

    assert derived.source_sha256
    assert derived.derived_sha256
    assert derived.validation["chronology_validated"] is True
    assert len(derived.row_mappings) == 8760
    assert derived.row_mappings[0].source_minute == 0
    assert derived.row_mappings[0].derived_minute == 60
    assert restore_source_bytes_from_mapping(derived.derived_bytes, derived.row_mappings) == original


def test_solar_semantics_counts_dni_positive_hours_for_all_three_assumptions() -> None:
    epw = _fixture_epw()
    # The fixture has daylight DNI rows only; the three timestamp assumptions
    # are calculated independently through Ladybug Sunpath.
    start = diagnose_solar_semantics(epw, "hour_start")
    midpoint = diagnose_solar_semantics(epw, "hour_midpoint")
    end = diagnose_solar_semantics(epw, "hour_end")

    assert start["classification"] == ["DATASET_OBSERVATION", "INFERENCE"]
    assert midpoint["positive_dni_hours"] == end["positive_dni_hours"]
    assert start["sun_below_horizon_with_positive_dni_hours"] >= 0
    assert midpoint["sun_below_horizon_with_positive_dni_hours"] >= 0
    assert end["sun_below_horizon_with_positive_dni_hours"] >= 0


def test_sunpath_uses_epw_location_fields_in_their_declared_units() -> None:
    altitude, azimuth = _angles_at(
        {"latitude": 51.95, "longitude": 4.14, "timezone": 1.0, "elevation_m": 0.0},
        interval_datetime(6, 21, 12, "hour_end"),
    )

    # Rotterdam's June 21 solar position should be high and south-facing at noon.
    assert 55.0 < altitude < 66.0
    assert 145.0 < azimuth < 175.0


def test_sensitivity_reports_minus_base_plus_one_hour_for_four_planes() -> None:
    sensitivity = sensitivity_direct_radiation(_fixture_epw())

    assert set(sensitivity["by_offset_hours"]) == {"-1", "0", "1"}
    for result in sensitivity["by_offset_hours"].values():
        assert set(result["kwh_m2"]) == {"horizontal", "south", "east", "west"}
        assert all(value >= 0 for value in result["kwh_m2"].values())
    assert sensitivity["scenario_e2_direction"] == "NOT_ASSESSABLE_WITHOUT_SCENARIO_SENSOR_RESULTS"
