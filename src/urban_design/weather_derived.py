"""Offline, append-only EPW derivation and solar-time sensitivity methods."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import math
from typing import Literal


TimestampAssumption = Literal["hour_start", "hour_midpoint", "hour_end"]
WEATHER_DERIVED_METHOD_VERSION = "weather-derived-method-v1"
EPW_HEADER_LINES = 8
EPW_COLUMNS = 35
_DNI_COLUMN = 14
_MINUTE_COLUMN = 4


class WeatherMethodError(ValueError):
    """Raised when EPW bytes cannot be transformed without ambiguity."""


@dataclass(frozen=True)
class MinuteRowMapping:
    data_row: int
    year: int
    month: int
    day: int
    hour: int
    source_minute: int
    derived_minute: int
    source_line_sha256: str
    derived_line_sha256: str


@dataclass(frozen=True)
class DerivedEPW:
    source_sha256: str
    derived_sha256: str
    source_bytes: bytes
    derived_bytes: bytes
    row_mappings: tuple[MinuteRowMapping, ...]
    validation: dict[str, object]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _line_parts(line: bytes) -> tuple[bytes, bytes]:
    if line.endswith(b"\r\n"):
        return line[:-2], b"\r\n"
    if line.endswith(b"\n"):
        return line[:-1], b"\n"
    if line.endswith(b"\r"):
        return line[:-1], b"\r"
    return line, b""


def _parse_epw(epw_bytes: bytes) -> tuple[list[bytes], list[list[str]], dict[str, float]]:
    try:
        lines = epw_bytes.splitlines(keepends=True)
        if len(lines) <= EPW_HEADER_LINES:
            raise WeatherMethodError("EPW must include eight header lines and hourly data rows")
        location_fields = _line_parts(lines[0])[0].decode("utf-8", errors="strict").split(",")
        if len(location_fields) < 10 or not location_fields[0].startswith("LOCATION"):
            raise WeatherMethodError("EPW LOCATION header is incomplete")
        location = {
            "latitude": float(location_fields[6]),
            "longitude": float(location_fields[7]),
            "timezone": float(location_fields[8]),
            "elevation_m": float(location_fields[9]),
        }
        rows = [
            _line_parts(line)[0].decode("utf-8", errors="strict").split(",")
            for line in lines[EPW_HEADER_LINES:]
        ]
    except (UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, WeatherMethodError):
            raise
        raise WeatherMethodError("EPW bytes or LOCATION header are invalid") from exc
    if any(len(row) != EPW_COLUMNS for row in rows):
        raise WeatherMethodError("each EPW data row must contain exactly 35 columns")
    return lines, rows, location


def interval_datetime(month: int, day: int, hour: int, assumption: TimestampAssumption):
    """Return the Ladybug local-standard-time instant for an EPW hour row.

    EPW hour fields 1..24 represent the interval starting at hour-1 and ending
    at hour.  The function evaluates the specified start, midpoint, or end
    instant while allowing Ladybug DateTime to roll across midnight/year end.
    """
    if assumption not in {"hour_start", "hour_midpoint", "hour_end"}:
        raise WeatherMethodError("timestamp assumption must be hour_start, hour_midpoint, or hour_end")
    if isinstance(hour, bool) or not isinstance(hour, int) or not 1 <= hour <= 24:
        raise WeatherMethodError("EPW hour must be an integer from 1 through 24")
    from ladybug.dt import DateTime

    start = DateTime(month, day, hour - 1, 0)
    if assumption == "hour_start":
        return start
    if assumption == "hour_midpoint":
        return start.add_minute(30)
    return start.add_hour(1)


def derive_minute_zero_as_hour_end(epw_bytes: bytes, *, filename: str) -> DerivedEPW:
    """Map each source Minute=0 to Minute=60 and run the existing strict validator."""
    lines, rows, _location = _parse_epw(epw_bytes)
    derived_lines = list(lines[:EPW_HEADER_LINES])
    mappings: list[MinuteRowMapping] = []
    for index, (line, fields) in enumerate(zip(lines[EPW_HEADER_LINES:], rows), start=1):
        try:
            year, month, day, hour, minute = (int(fields[position]) for position in range(5))
        except ValueError as exc:
            raise WeatherMethodError(f"EPW row {index} has a nonnumeric timestamp") from exc
        if minute != 0:
            raise WeatherMethodError(
                f"EPW row {index} has Minute={minute}; derivation accepts only Minute=0 source rows"
            )
        original_content, ending = _line_parts(line)
        changed_fields = list(fields)
        changed_fields[_MINUTE_COLUMN] = "60"
        derived_line = ",".join(changed_fields).encode("utf-8") + ending
        mappings.append(
            MinuteRowMapping(
                data_row=index,
                year=year,
                month=month,
                day=day,
                hour=hour,
                source_minute=minute,
                derived_minute=60,
                source_line_sha256=_sha256(line),
                derived_line_sha256=_sha256(derived_line),
            )
        )
        if not original_content:
            raise WeatherMethodError(f"EPW row {index} is empty")
        derived_lines.append(derived_line)

    derived_bytes = b"".join(derived_lines)
    # This is the existing acquisition validator. Its Minute=60 rule remains unchanged.
    from urban_design.m2a03_sources import _epw_metadata

    try:
        validation = _epw_metadata(derived_bytes, filename=filename)
    except Exception as exc:
        raise WeatherMethodError(f"derived EPW failed the existing validator: {exc}") from exc
    if validation.get("chronology_validated") is not True:
        raise WeatherMethodError("existing EPW validator did not confirm chronology")
    return DerivedEPW(
        source_sha256=_sha256(epw_bytes),
        derived_sha256=_sha256(derived_bytes),
        source_bytes=epw_bytes,
        derived_bytes=derived_bytes,
        row_mappings=tuple(mappings),
        validation=validation,
    )


def restore_source_bytes_from_mapping(
    derived_bytes: bytes,
    row_mappings: tuple[MinuteRowMapping, ...] | list[MinuteRowMapping],
) -> bytes:
    """Reverse only listed Minute edits and verify every recorded row hash."""
    lines = derived_bytes.splitlines(keepends=True)
    if len(lines) < EPW_HEADER_LINES:
        raise WeatherMethodError("derived EPW is missing header lines")
    if len(lines) - EPW_HEADER_LINES != len(row_mappings):
        raise WeatherMethodError("row mapping count does not match derived EPW")
    restored = list(lines[:EPW_HEADER_LINES])
    for line, mapping in zip(lines[EPW_HEADER_LINES:], row_mappings):
        if _sha256(line) != mapping.derived_line_sha256:
            raise WeatherMethodError(f"derived EPW row {mapping.data_row} does not match its mapping hash")
        content, ending = _line_parts(line)
        fields = content.decode("utf-8", errors="strict").split(",")
        if len(fields) != EPW_COLUMNS or int(fields[_MINUTE_COLUMN]) != mapping.derived_minute:
            raise WeatherMethodError(f"derived EPW row {mapping.data_row} does not match its mapped Minute")
        fields[_MINUTE_COLUMN] = str(mapping.source_minute)
        source_line = ",".join(fields).encode("utf-8") + ending
        if _sha256(source_line) != mapping.source_line_sha256:
            raise WeatherMethodError(f"restored EPW row {mapping.data_row} failed its source hash")
        restored.append(source_line)
    return b"".join(restored)


@lru_cache(maxsize=32)
def _sunpath(latitude: float, longitude: float, timezone: float, elevation_m: float):
    from ladybug.location import Location
    from ladybug.sunpath import Sunpath

    location = Location(
        city="EPW station",
        latitude=latitude,
        longitude=longitude,
        time_zone=timezone,
        elevation=elevation_m,
    )
    return Sunpath.from_location(location)


def _angles_at(location: dict[str, float], date_time) -> tuple[float, float]:
    from ladybug.dt import DateTime

    if not isinstance(date_time, DateTime):
        raise WeatherMethodError("solar position requires a Ladybug DateTime")
    sun = _sunpath(
        location["latitude"],
        location["longitude"],
        location["timezone"],
        location["elevation_m"],
    ).calculate_sun_from_date_time(date_time)
    return float(sun.altitude), float(sun.azimuth)


def diagnose_solar_semantics(epw_bytes: bytes, assumption: TimestampAssumption) -> dict[str, object]:
    """Count positive-DNI hours with Ladybug sun altitude below the horizon."""
    _lines, rows, location = _parse_epw(epw_bytes)
    positive_dni = 0
    below_horizon = 0
    for row_number, fields in enumerate(rows, start=1):
        try:
            dni = float(fields[_DNI_COLUMN])
            month, day, hour = int(fields[1]), int(fields[2]), int(fields[3])
        except ValueError as exc:
            raise WeatherMethodError(f"EPW row {row_number} has invalid DNI or timestamp") from exc
        if not math.isfinite(dni):
            raise WeatherMethodError(f"EPW row {row_number} has nonfinite DNI")
        if dni <= 0:
            continue
        positive_dni += 1
        altitude, _azimuth = _angles_at(location, interval_datetime(month, day, hour, assumption))
        if altitude < 0:
            below_horizon += 1
    return {
        "timestamp_assumption": assumption,
        "positive_dni_hours": positive_dni,
        "sun_below_horizon_with_positive_dni_hours": below_horizon,
        "classification": ["DATASET_OBSERVATION", "INFERENCE"],
        "observation": "DNI field values are read from the preserved EPW bytes.",
        "inference": "Sun altitude is calculated for the named time assumption using Ladybug Sunpath.",
        "supplier_semantics_evidence": False,
    }


def _direct_plane_cosines(altitude_deg: float, azimuth_deg: float) -> dict[str, float]:
    if altitude_deg <= 0:
        return {"horizontal": 0.0, "south": 0.0, "east": 0.0, "west": 0.0}
    altitude = math.radians(altitude_deg)
    azimuth = math.radians(azimuth_deg)
    east_component = math.cos(altitude) * math.sin(azimuth)
    north_component = math.cos(altitude) * math.cos(azimuth)
    return {
        "horizontal": max(0.0, math.sin(altitude)),
        "south": max(0.0, -north_component),
        "east": max(0.0, east_component),
        "west": max(0.0, -east_component),
    }


def sensitivity_direct_radiation(epw_bytes: bytes) -> dict[str, object]:
    """Sum June-August DNI projection for four planes at -1/0/+1h from hour end.

    EPW DNI is treated as the hourly direct-normal energy value (Wh/m²); each
    record contributes DNI × positive plane-incidence cosine. The solar position
    shift is an inference used only for method sensitivity, not a climate result.
    """
    _lines, rows, location = _parse_epw(epw_bytes)
    offsets = (-1, 0, 1)
    surfaces = ("horizontal", "south", "east", "west")
    totals = {str(offset): {surface: 0.0 for surface in surfaces} for offset in offsets}
    for row_number, fields in enumerate(rows, start=1):
        try:
            month, day, hour = int(fields[1]), int(fields[2]), int(fields[3])
            dni = float(fields[_DNI_COLUMN])
        except ValueError as exc:
            raise WeatherMethodError(f"EPW row {row_number} has invalid DNI or timestamp") from exc
        if month not in {6, 7, 8} or dni <= 0:
            continue
        if not math.isfinite(dni):
            raise WeatherMethodError(f"EPW row {row_number} has nonfinite DNI")
        endpoint = interval_datetime(month, day, hour, "hour_end")
        for offset in offsets:
            altitude, azimuth = _angles_at(location, endpoint.add_hour(offset))
            cosines = _direct_plane_cosines(altitude, azimuth)
            for surface in surfaces:
                totals[str(offset)][surface] += dni * cosines[surface]

    # Convert Wh/m² to kWh/m² and round only the serialized result, not the comparisons.
    kwh = {
        offset: {surface: round(value / 1000.0, 9) for surface, value in values.items()}
        for offset, values in totals.items()
    }
    baseline_order = tuple(sorted(surfaces, key=lambda surface: (-kwh["0"][surface], surface)))
    ranking_changed = any(
        tuple(sorted(surfaces, key=lambda surface: (-kwh[str(offset)][surface], surface)))
        != baseline_order
        for offset in (-1, 1)
    )
    relative_change_pct: dict[str, dict[str, float | None]] = {}
    for offset in ("-1", "1"):
        relative_change_pct[offset] = {}
        for surface in surfaces:
            base = kwh["0"][surface]
            shifted = kwh[offset][surface]
            relative_change_pct[offset][surface] = (
                None if base == 0 else round((shifted - base) / base * 100.0, 6)
            )

    return {
        "period": "June-August inclusive",
        "input_dni_unit": "Wh/m² per hourly EPW record",
        "output_unit": "kWh/m²",
        "time_basis": "Rotterdam local standard time from EPW LOCATION timezone",
        "base_timestamp_assumption": "hour_end",
        "offsets_hours": [-1, 0, 1],
        "by_offset_hours": {
            offset: {"kwh_m2": values}
            for offset, values in kwh.items()
        },
        "relative_change_percent_vs_hour_end": relative_change_pct,
        "surface_order_by_offset": {
            offset: list(sorted(surfaces, key=lambda surface: (-kwh[offset][surface], surface)))
            for offset in ("-1", "0", "1")
        },
        "orientation_proxy_order_changed": ranking_changed,
        "may_change_orientation_sensitive_comparison": (
            "POSSIBLE_FOR_NEAR_TIES" if ranking_changed else "NOT_SHOWN_BY_SURFACE_PROXY"
        ),
        "scenario_e2_direction": "NOT_ASSESSABLE_WITHOUT_SCENARIO_SENSOR_RESULTS",
        "classification": "INFERENCE",
        "limitation": (
            "Plane totals are a screening proxy. W5 performs no E2 scenario, geometry, "
            "sensor-grid, reflected-radiation, or climate experiment calculation."
        ),
    }


__all__ = [
    "DerivedEPW",
    "MinuteRowMapping",
    "TimestampAssumption",
    "WEATHER_DERIVED_METHOD_VERSION",
    "WeatherMethodError",
    "derive_minute_zero_as_hour_end",
    "diagnose_solar_semantics",
    "interval_datetime",
    "restore_source_bytes_from_mapping",
    "sensitivity_direct_radiation",
]
