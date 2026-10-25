#!/usr/bin/env python3
"""One-request live AI smoke check against a newly created, explicitly named DB."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from urban_design.model_provider import ModelProviderRouter, get_configured_provider
from urban_design.model_profiles import load_model_provider_config
from urban_design.site_critic import SiteCriticService
from urban_design.store import ProjectStateStore


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True, help="new SQLite path for this smoke run")
    parser.add_argument("--project-id", required=True, help="isolated project identifier recorded in the smoke DB")
    parser.add_argument("--profile-id", required=True, help="one explicitly selected enabled profile")
    parser.add_argument("--confirm-live", action="store_true", help="confirm one external model request")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if not args.confirm_live:
        print("Blocked: pass --confirm-live to permit one external model request.", file=sys.stderr)
        return 2
    if os.environ.get("PROJECT_AI_AUTHORIZED", "").strip() != "1":
        print("Blocked: PROJECT_AI_AUTHORIZED must equal 1.", file=sys.stderr)
        return 2
    if not args.project_id.strip():
        print("Blocked: --project-id must not be blank.", file=sys.stderr)
        return 2

    database_path = args.database.expanduser().resolve()
    if database_path.exists():
        print("Blocked: smoke database path already exists; choose a new path.", file=sys.stderr)
        return 2
    if not database_path.parent.is_dir():
        print("Blocked: smoke database parent directory must already exist.", file=sys.stderr)
        return 2

    config = load_model_provider_config()
    selected_profile = next((profile for profile in config.profiles if profile.id == args.profile_id), None)
    if selected_profile is None or not selected_profile.enabled:
        print("Blocked: selected model profile is missing or disabled.", file=sys.stderr)
        return 2

    store: ProjectStateStore | None = None
    try:
        store = ProjectStateStore(database_path)
        configured = get_configured_provider(store=store, project_id=args.project_id.strip())
        if not isinstance(configured, ModelProviderRouter):
            print("Blocked: configured live provider router is unavailable.", file=sys.stderr)
            return 2
        adapter = configured.providers.get(selected_profile.id)
        if adapter is None or not adapter.is_live_available:
            print("Blocked: selected profile is not currently available; no fallback was attempted.", file=sys.stderr)
            return 2

        one_profile_router = ModelProviderRouter(
            providers={selected_profile.id: adapter},
            fallback_order=[selected_profile.id],
            store=store,
            project_id=args.project_id.strip(),
            weekly_call_limit=config.weekly_call_limit,
        )
        response = SiteCriticService(provider=one_profile_router).generate_and_validate(
            study_area_id="live-ai-smoke-test",
            evidence_bundle=[],
            query=(
                "Return an empty critic response with no evidence references, observations, "
                "design hypotheses, limitations, or next questions."
            ),
        )
        [run] = store.list_current("ModelRun", project_id=args.project_id.strip())
        print(
            f"status={response.provider_status} provider={response.provider_name} "
            f"model={response.provider_model} model_run={run.entity_id} "
            f"run_status={run.payload.get('status')} database={database_path}"
        )
        return 0 if run.payload.get("status") == "SUCCEEDED" else 1
    except Exception as exc:
        print(f"Smoke run failed ({type(exc).__name__}); inspect the explicitly named DB before any retry.", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
