#!/usr/bin/env python3
"""Run the Urban Design platform API on its dedicated local port."""

import argparse
import os
from pathlib import Path

import uvicorn
from urban_design.api import create_workspace_app
from urban_design.store import ProjectStateStore
from urban_design.server_config import ensure_port_available, resolve_server_config
from urban_design.workspace_sources import DEFAULT_SPATIAL_R01_ROOT

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--database")
    parser.add_argument("--source-package-root", type=Path, default=DEFAULT_SPATIAL_R01_ROOT)
    parser.add_argument("--decision-key-path", type=Path, default=None)
    parser.add_argument("--morphology-preview-root", type=str, default=None)
    parser.add_argument("--morphology-preview-manifest-sha256", type=str, default=None)
    parser.add_argument("--syntax-context-root", type=str, default=None)
    parser.add_argument("--syntax-context-manifest-sha256", type=str, default=None)
    parser.add_argument("--ariadne-live", action="store_true", help="Enable Ariadne Live AI when PROJECT_AI_AUTHORIZED=1.")
    parser.add_argument("--e2-weather-proposal-root", type=Path, default=None)
    parser.add_argument("--e2-weather-source-root", type=Path, default=None)
    parser.add_argument("--e2-artifact-root", type=Path, default=None)
    parser.add_argument("--e2-job-database", type=Path, default=None)
    parser.add_argument("--climate-artifact-root", type=Path, default=None)
    parser.add_argument("--scenario-artifact-root", type=Path, default=None,
                        help="Scenario artifact/staging root (default: ./.urban_design_runtime/scenario-artifacts); isolated runs pass their own.")
    return parser


def apply_e2_config(app, args: argparse.Namespace) -> None:
    if getattr(args, "e2_weather_proposal_root", None) is not None:
        app.state.e2_weather_proposal_root = args.e2_weather_proposal_root
    if getattr(args, "e2_weather_source_root", None) is not None:
        app.state.e2_weather_source_root = args.e2_weather_source_root
    if getattr(args, "e2_artifact_root", None) is not None:
        app.state.e2_artifact_root = args.e2_artifact_root
    if getattr(args, "e2_job_database", None) is not None:
        app.state.e2_job_database = args.e2_job_database
    if getattr(args, "climate_artifact_root", None) is not None:
        app.state.climate_artifact_root = args.climate_artifact_root


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    if args.ariadne_live:
        os.environ["ARIADNE_LIVE"] = "1"
    for flag, val in [
        ("--e2-weather-proposal-root", args.e2_weather_proposal_root),
        ("--e2-weather-source-root", args.e2_weather_source_root),
        ("--e2-artifact-root", args.e2_artifact_root),
        ("--e2-job-database", args.e2_job_database),
        ("--climate-artifact-root", args.climate_artifact_root),
    ]:
        if val is not None and not str(val).strip():
            parser.error(f"{flag} must not be blank")
    if args.morphology_preview_root is not None and not args.morphology_preview_root.strip():
        parser.error("--morphology-preview-root must not be blank")
    if args.morphology_preview_manifest_sha256 is not None and not args.morphology_preview_manifest_sha256.strip():
        parser.error("--morphology-preview-manifest-sha256 must not be blank")
    if (args.morphology_preview_root is None) != (args.morphology_preview_manifest_sha256 is None):
        parser.error(
            "--morphology-preview-root and --morphology-preview-manifest-sha256 "
            "must be specified together or both omitted"
        )
    if args.syntax_context_root is not None and not args.syntax_context_root.strip():
        parser.error("--syntax-context-root must not be blank")
    if args.syntax_context_manifest_sha256 is not None and not args.syntax_context_manifest_sha256.strip():
        parser.error("--syntax-context-manifest-sha256 must not be blank")
    if (args.syntax_context_root is None) != (args.syntax_context_manifest_sha256 is None):
        parser.error(
            "--syntax-context-root and --syntax-context-manifest-sha256 "
            "must be specified together or both omitted"
        )
    config = resolve_server_config(host=args.host, port=args.port, database_path=args.database)
    ensure_port_available(config.host, config.port)
    store = ProjectStateStore(config.database_path)
    app = create_workspace_app(
        store,
        source_package_root=args.source_package_root,
        syntax_figure_record_path=Path.cwd() / "artifacts/week4-repair-r03/syntax/figure-record.json",
        allow_live_critic=False,
        decision_key_path=args.decision_key_path,
        morphology_preview_root=Path(args.morphology_preview_root) if args.morphology_preview_root is not None else None,
        morphology_preview_manifest_sha256=args.morphology_preview_manifest_sha256,
        syntax_context_root=Path(args.syntax_context_root) if args.syntax_context_root is not None else None,
        syntax_context_manifest_sha256=args.syntax_context_manifest_sha256,
        scenario_artifact_root=args.scenario_artifact_root,
    )
    apply_e2_config(app, args)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")
