#!/usr/bin/env python3
"""Build an offline W5-12 weather-method proposal from the preserved R08 bytes."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import platform
from typing import Any

from urban_design.weather_derived import (
    WEATHER_DERIVED_METHOD_VERSION,
    derive_minute_zero_as_hour_end,
    diagnose_solar_semantics,
    restore_source_bytes_from_mapping,
    sensitivity_direct_radiation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
R08_ROOT = PROJECT_ROOT / "artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-minute-semantics-20260919T154701Z"
SOURCE_ROOT = R08_ROOT / "source-originals"
TIMESTAMP_ASSUMPTIONS = ("hour_end", "hour_start", "hour_midpoint")
PROGRAM_VERSION = "w5-12-weather-method-proposal-v1"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "NOT_INSTALLED"


def _write_row_mapping(path: Path, mappings) -> None:
    columns = (
        "data_row",
        "year",
        "month",
        "day",
        "hour",
        "source_minute",
        "derived_minute",
        "mapping_rule",
        "source_line_sha256",
        "derived_line_sha256",
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in mappings:
            writer.writerow(
                {
                    "data_row": row.data_row,
                    "year": row.year,
                    "month": row.month,
                    "day": row.day,
                    "hour": row.hour,
                    "source_minute": row.source_minute,
                    "derived_minute": row.derived_minute,
                    "mapping_rule": "Minute=0 -> Minute=60 (hour end); all other source bytes preserved",
                    "source_line_sha256": row.source_line_sha256,
                    "derived_line_sha256": row.derived_line_sha256,
                }
            )


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(data),
        "sha256": _sha256(data),
    }


def build_proposal(output_root: Path) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite existing proposal package: {output_root}")
    if not SOURCE_ROOT.is_dir():
        raise FileNotFoundError(f"preserved R08 weather bytes are unavailable: {SOURCE_ROOT}")
    output_root.mkdir(parents=True)
    candidate_summaries: list[dict[str, Any]] = []
    source_checks: list[dict[str, str]] = []

    for candidate_dir in sorted(SOURCE_ROOT.glob("candidate-*")):
        epw_files = sorted((candidate_dir / "epw").glob("*.epw"))
        if len(epw_files) != 1:
            raise ValueError(f"expected one preserved EPW under {candidate_dir}")
        source_path = epw_files[0]
        source_before = source_path.read_bytes()
        source_sha_before = _sha256(source_before)
        source_record = json.loads((candidate_dir / "source-record.json").read_text(encoding="utf-8"))
        expected_sha = source_record["response"]["epw_sha256"].removeprefix("sha256:")
        if source_sha_before != expected_sha:
            raise ValueError(f"preserved R08 source hash does not match its record: {source_path.name}")

        derived = derive_minute_zero_as_hour_end(source_before, filename=source_path.name)
        round_trip = restore_source_bytes_from_mapping(derived.derived_bytes, derived.row_mappings)
        if round_trip != source_before:
            raise ValueError(f"Minute mapping failed byte-for-byte round trip: {source_path.name}")
        candidate_output = output_root / candidate_dir.name
        candidate_output.mkdir()
        derived_path = candidate_output / "derived-minute60.epw"
        derived_path.write_bytes(derived.derived_bytes)
        mapping_path = candidate_output / "minute-row-mapping.csv"
        _write_row_mapping(mapping_path, derived.row_mappings)

        diagnostics = {
            assumption: diagnose_solar_semantics(source_before, assumption)
            for assumption in TIMESTAMP_ASSUMPTIONS
        }
        sensitivity = sensitivity_direct_radiation(source_before)
        result = {
            "schema_version": "w5-12-weather-candidate-analysis-v1",
            "classification": "PROPOSAL_ONLY",
            "candidate_id": candidate_dir.name,
            "source": {
                "source_r08_relative_path": source_path.relative_to(PROJECT_ROOT).as_posix(),
                "filename": source_path.name,
                "publisher": source_record["source_attribution"]["publisher"],
                "source_url_from_preserved_record": source_record["source_attribution"]["source_url"],
                "license_or_terms_from_preserved_record": source_record["source_attribution"]["license_or_terms"],
                "retrieved_at_utc_from_preserved_record": source_record["request"]["started_at"],
                "last_modified_from_preserved_record": source_record["request"]["response_headers"].get("last-modified"),
                "tmyx_period_from_embedded_comments": source_record["source_attribution"]["embedded_comments"][0],
                "size_bytes": len(source_before),
                "sha256": source_sha_before,
                "bytes_before_sha256": source_sha_before,
                "bytes_after_sha256": _sha256(source_path.read_bytes()),
                "source_minute_values": [0],
                "source_bytes_modified": False,
            },
            "derivation": {
                "rule": "Minute=0 -> Minute=60, interpreted as the end of each hour",
                "project_decision_reference": "PD-08; project assumption pending designer HumanDecision",
                "input_sha256": derived.source_sha256,
                "output_sha256": derived.derived_sha256,
                "validator": "urban_design.m2a03_sources._epw_metadata",
                "validator_result": derived.validation,
                "mapping_file": mapping_path.name,
                "mapping_sha256": _sha256(mapping_path.read_bytes()),
                "mapping_rows": len(derived.row_mappings),
                "round_trip_source_hash": _sha256(round_trip),
            },
            "solar_diagnostics": diagnostics,
            "summer_direct_radiation_sensitivity": sensitivity,
            "evidence_boundary": {
                "solar_diagnostics_classification": ["DATASET_OBSERVATION", "INFERENCE"],
                "supplier_timing_semantics_proven": False,
                "dataset_snapshot_published": False,
                "climate_experiment_started": False,
                "network_requests": 0,
                "e2_scenario_result": "NOT_COMPUTED",
            },
        }
        result_path = candidate_output / "analysis.json"
        _write_json(result_path, result)
        candidate_summaries.append(result)
        source_checks.append(
            {
                "candidate_id": candidate_dir.name,
                "source_sha256_before": source_sha_before,
                "source_sha256_after": _sha256(source_path.read_bytes()),
            }
        )

    period_count = [
        int(item["source"]["tmyx_period_from_embedded_comments"].split("#years=[", 1)[1].split("]", 1)[0])
        for item in candidate_summaries
    ]
    summary = {
        "classification": "PROPOSAL_ONLY",
        "source_candidates_analyzed": len(candidate_summaries),
        "source_hashes_unchanged": all(
            item["source_sha256_before"] == item["source_sha256_after"] for item in source_checks
        ),
        "candidates": [
            {
                "candidate_id": item["candidate_id"],
                "filename": item["source"]["filename"],
                "source_sha256": item["source"]["sha256"],
                "tmyx_period": item["source"]["tmyx_period_from_embedded_comments"],
                "end_start_midpoint_below_horizon_counts": {
                    assumption: item["solar_diagnostics"][assumption]["sun_below_horizon_with_positive_dni_hours"]
                    for assumption in TIMESTAMP_ASSUMPTIONS
                },
                "sensitivity_kwh_m2": item["summer_direct_radiation_sensitivity"]["by_offset_hours"],
                "orientation_proxy_order_changed": item["summer_direct_radiation_sensitivity"]["orientation_proxy_order_changed"],
            }
            for item in candidate_summaries
        ],
        "review_recommendation": (
            "DESIGNER_REVIEW_CANDIDATES_01_AND_02_FIRST: both are Rotterdam.The.Hague.AP TMYx inputs with "
            f"{period_count[0]} and {period_count[1]} source years in preserved comments; candidate-03 is a separate "
            f"Geulhaven station with {period_count[2]} source years. This is a metadata-based review suggestion, "
            "not a weather-source selection or HumanDecision."
        ),
        "scenario_e2_direction": "NOT_ASSESSABLE_WITHOUT_SCENARIO_SENSOR_RESULTS",
    }
    summary_path = output_root / "weather-diagnostics.json"
    _write_json(summary_path, summary)

    file_records = [
        _file_record(output_root, path)
        for path in sorted(output_root.rglob("*"))
        if path.is_file()
    ]
    try:
        generator_sha = _sha256(Path(__file__).read_bytes())
        method_sha = _sha256((PROJECT_ROOT / "src/urban_design/weather_derived.py").read_bytes())
        validator_sha = _sha256((PROJECT_ROOT / "src/urban_design/m2a03_sources.py").read_bytes())
    except OSError as exc:
        raise RuntimeError("unable to hash the local program sources") from exc

    manifest = {
        "schema_version": "w5-12-weather-derived-method-proposal-v1",
        "status": "PROPOSAL_ONLY_PENDING_DESIGNER_DECISION",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_package": "artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-minute-semantics-20260919T154701Z",
        "method_version": WEATHER_DERIVED_METHOD_VERSION,
        "program_version": PROGRAM_VERSION,
        "runtime_versions": {
            "python": platform.python_version(),
            "ladybug_core": _package_version("ladybug-core"),
            "ladybug_geometry": _package_version("ladybug-geometry"),
        },
        "program_sha256": {
            "proposal_builder": generator_sha,
            "weather_derived_method": method_sha,
            "existing_epw_validator_module": validator_sha,
        },
        "timestamp_assumptions": list(TIMESTAMP_ASSUMPTIONS),
        "minute_mapping": "Minute=0 -> Minute=60, treated as the end of the hour",
        "source_hash_reconciliation": source_checks,
        "prohibitions_observed": {
            "network_requests": 0,
            "source_bytes_modified": False,
            "r03_r09_packages_modified": False,
            "dataset_snapshot_published": False,
            "climate_experiment_started": False,
        },
        "files": file_records,
        "approval": {"designer_human_decision_id": None, "status": "PENDING"},
    }
    _write_json(output_root / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir if args.output_dir.is_absolute() else PROJECT_ROOT / args.output_dir
    manifest = build_proposal(output)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "package": output.relative_to(PROJECT_ROOT).as_posix(),
                "file_count": len(manifest["files"]),
                "network_requests": manifest["prohibitions_observed"]["network_requests"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
