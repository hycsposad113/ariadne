#!/usr/bin/env python3
"""Build the bounded M2-A03 analysis-input decision package.

The command writes a replayable package even when the active StudyArea fails
the geographic-anchor gate.  A blocked package exits with status 2 and never
substitutes a historical site proposal or guessed city anchor.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from urban_design.analysis_inputs import (
    PACKAGE_STATUS_BLOCKED,
    PROJECT_ID,
    STUDY_AREA_ID,
    build_m2a03_package,
    load_analysis_input_package,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--project-id", default=PROJECT_ID)
    parser.add_argument("--study-area-id", default=STUDY_AREA_ID)
    parser.add_argument("--revision", help="immutable package revision suffix, e.g. r03", default="r03")
    parser.add_argument("--no-ledger-event", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        package_dir = build_m2a03_package(
            args.database,
            args.output_root,
            project_id=args.project_id,
            study_area_id=args.study_area_id,
            append_ledger=not args.no_ledger_event,
            package_revision=args.revision,
        )
        package = load_analysis_input_package(package_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"m2-a03-analysis-inputs: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"package_dir": str(package_dir), "status": package.get("status"), "package_id": package.get("package_id")}, indent=2, sort_keys=True))
    return 2 if package.get("status") in {PACKAGE_STATUS_BLOCKED, "PARTIAL"} else 0


if __name__ == "__main__":  # pragma: no cover - CLI smoke uses the public builder
    raise SystemExit(main())
