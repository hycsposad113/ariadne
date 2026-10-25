#!/usr/bin/env python3
"""Render maps from the reviewed problem-definition artifacts.

This fallback entry point reconstructs the typed bundle and delegates to the
same renderer used by build_problem_definition.py, keeping figure semantics
and metric labels synchronized.
"""

from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

# The QGIS interpreter may not contain application-only dependencies such as
# Pydantic.  Install a lightweight package namespace so this read-only analysis
# module can load its standard-library/Shapely submodules without executing the
# application's broad urban_design/__init__.py import chain.
if "urban_design" not in sys.modules:
    package = types.ModuleType("urban_design")
    package.__path__ = [str(SOURCE_ROOT / "urban_design")]
    package.__package__ = "urban_design"
    sys.modules["urban_design"] = package

from build_problem_definition import render_all_problem_figures
from urban_design.problem_definition import (
    MetricItem,
    MorphologyRecommendation,
    ProblemDefinitionBundle,
    ProblemStatement,
    SpatialProblemResult,
)

DEFAULT_ARTIFACTS_DIR = ROOT / "artifacts/w6-problem-definition"
LAYER_FILES = {
    "prob-01-functional-monoculture": "problem_01_functional_monoculture.geojson",
    "prob-02-spatial-fragmentation": "problem_02_spatial_fragmentation.geojson",
    "prob-03-sociospatial-isolation": "problem_03_sociospatial_isolation.geojson",
    "prob-04-ecological-disconnection": "problem_04_ecological_disconnection.geojson",
    "prob-05-waterfront-inaccessibility": "problem_05_waterfront_inaccessibility.geojson",
    "prob-06-unclassified-residual-ground": "problem_06_unclassified_residual_ground.geojson",
}


def load_bundle(artifacts_dir: Path) -> ProblemDefinitionBundle:
    summary = json.loads((artifacts_dir / "problem-summary.json").read_text(encoding="utf-8"))
    statements_doc = json.loads((artifacts_dir / "problem-statements.json").read_text(encoding="utf-8"))
    statements: dict[str, dict[str, Any]] = {
        row["problem_id"]: row for row in statements_doc["statements"]
    }
    problems: list[SpatialProblemResult] = []
    for row in summary["problems"]:
        raw_statement = dict(statements[row["problem_id"]])
        raw_statement["metrics"] = [MetricItem(**metric) for metric in raw_statement["metrics"]]
        raw_statement["recommended_morphology"] = [
            MorphologyRecommendation(**recommendation)
            for recommendation in raw_statement["recommended_morphology"]
        ]
        statement = ProblemStatement(**raw_statement)
        layer = json.loads((artifacts_dir / LAYER_FILES[row["problem_id"]]).read_text(encoding="utf-8"))
        problems.append(SpatialProblemResult(
            problem_id=row["problem_id"],
            title_zh=row["title_zh"],
            summary_zh=row["summary_zh"],
            statement=statement,
            geojson_layer=layer,
            metrics={metric.key: metric.value for metric in statement.metrics},
        ))
    return ProblemDefinitionBundle(
        timestamp=summary["timestamp"],
        study_area_id=summary["study_area_id"],
        study_area_area_m2=summary["study_area_area_m2"],
        land_area_m2=summary["land_area_m2"],
        water_area_m2=summary["water_area_m2"],
        problems=problems,
        metadata=summary.get("metadata", {}),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Render reviewed problem-definition map figures.")
    parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACTS_DIR, help="Reviewed artifact directory")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ARTIFACTS_DIR / "figures", help="Figure output directory")
    args = parser.parse_args()
    bundle = load_bundle(args.artifacts_dir)
    figures = render_all_problem_figures(bundle, args.output_dir)
    print(f"Rendered {len(figures)} reviewed problem-definition maps to {args.output_dir}.")
    for figure in figures:
        print(f"  {figure.name} ({figure.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
