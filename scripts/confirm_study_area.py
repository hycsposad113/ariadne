#!/usr/bin/env python3
"""Confirm a saved QGIS StudyArea artifact through the bounded domain service.

This command accepts an existing local polygon artifact and never dispatches
QGIS code, dynamic Python, SQL, or an unregistered processing operation.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from urban_design.models import ActorKind
from urban_design.study_area_workflow import (
    StudyAreaConfirmationError,
    StudyAreaConfirmationService,
    StudyAreaValidationError,
)
from urban_design.store import ProjectStateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--artifact-path", required=True, type=Path)
    parser.add_argument("--artifact-id")
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--actor-kind", choices=[kind.value for kind in ActorKind], required=True)
    parser.add_argument("--actor-session-id", required=True)
    parser.add_argument("--version")
    parser.add_argument("--study-area-id")
    parser.add_argument("--horizontal-crs")
    parser.add_argument("--units")
    parser.add_argument("--confirmed-at", type=str)
    parser.add_argument("--confirmation-event-id")
    parser.add_argument("--activation-event-id")
    parser.add_argument(
        "--reason",
        default="Human confirmed the saved QGIS Study Area for exploration",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        confirmed_at = datetime.fromisoformat(args.confirmed_at) if args.confirmed_at else None
        with ProjectStateStore(args.database) as store:
            area = StudyAreaConfirmationService(store, artifact_root=args.artifact_root).confirm(
                args.project_id,
                actor=args.actor,
                actor_kind=ActorKind(args.actor_kind),
                actor_session_id=args.actor_session_id,
                artifact_id=args.artifact_id,
                artifact_path=args.artifact_path,
                version=args.version,
                study_area_id=args.study_area_id,
                horizontal_crs=args.horizontal_crs,
                units=args.units,
                confirmed_at=confirmed_at,
                confirmation_event_id=args.confirmation_event_id,
                activation_event_id=args.activation_event_id,
                reason=args.reason,
            )
    except (StudyAreaValidationError, StudyAreaConfirmationError, ValueError, OSError) as exc:
        print(f"confirm-study-area: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(area.model_dump(mode="json"), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a CLI smoke
    raise SystemExit(main())
