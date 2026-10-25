#!/usr/bin/env python3
"""Freeze three spatial policies only from explicit human selections.

Missing selections print the decision packet and write no live decision.
"""

from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from urban_design.analysis_inputs import load_m2a03_spatial_package
from urban_design.decision_key import DecisionKeyUnavailable, verify_decision_key_strict
from urban_design.models import ActorKind
from urban_design.spatial_input_policy import (
    approve_spatial_addendum_options,
    build_spatial_decision_packet,
    freeze_m2a03_spatial_policies,
    load_spatial_acceptance_package,
    _is_live_spatial_r01,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--spatial-package", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--actor")
    parser.add_argument("--reason")
    parser.add_argument("--origin-id", action="append", dest="origin_ids")
    parser.add_argument("--destination-tag", action="append", dest="destination_tags")
    parser.add_argument("--network-policy", help="JSON object with include_highways, exclude, and ambiguous_access_limitation")
    parser.add_argument("--decision-addendum", type=Path)
    parser.add_argument("--origin-option-id")
    parser.add_argument("--destination-option-id")
    parser.add_argument("--network-option-id")
    parser.add_argument(
        "--historical-replay",
        action="store_true",
        help="Allow raw origin-ID approval for a fixture package. This does not approve spatial-r01.",
    )
    return parser


def _default_decision_key_prompt(prompt: str) -> str:
    """Read a piped key from stdin; use getpass only on a real terminal.

    ``getpass.getpass`` opens ``/dev/tty`` and ignores a key passed on stdin.
    Under a pty that hangs even when the caller injected the key. A non-tty
    stdin is the injected channel. An interactive terminal still hides the key.
    """

    if sys.stdin is not None and not sys.stdin.isatty():
        line = sys.stdin.readline()
        if line == "":
            raise EOFError
        return line.rstrip("\n")
    return getpass.getpass(prompt)


def _request_decision_key(password_prompt=None) -> str | None:
    """Read and verify the designer key without exposing it in args or output."""

    prompt = password_prompt or _default_decision_key_prompt
    try:
        secret = prompt("Designer decision key: ")
        if not verify_decision_key_strict(secret):
            print("m2-a03-spatial-approval: BLOCKED: designer decision key is incorrect", file=sys.stderr)
            return None
    except (DecisionKeyUnavailable, EOFError, OSError):
        print("m2-a03-spatial-approval: BLOCKED: designer decision key is unavailable", file=sys.stderr)
        return None
    return secret


def main(argv: list[str] | None = None, *, password_prompt=None) -> int:
    args = build_parser().parse_args(argv)
    if args.decision_addendum is not None:
        if not args.actor or not args.reason or not args.origin_option_id or not args.destination_option_id or not args.network_option_id:
            print("m2-a03-spatial-approval: decision addendum approval requires actor, reason, and three option ids", file=sys.stderr)
            return 2
        decision_key = _request_decision_key(password_prompt)
        if decision_key is None:
            return 1
        try:
            acceptance_dir = approve_spatial_addendum_options(
                args.database,
                args.decision_addendum,
                args.spatial_package,
                args.output_root,
                actor=args.actor,
                reason=args.reason,
                origin_option_id=args.origin_option_id,
                destination_option_id=args.destination_option_id,
                network_option_id=args.network_option_id,
                actor_kind=ActorKind.HUMAN_UI,
                actor_session_id=f"spatial-approval-{uuid.uuid4().hex}",
                decision_key=decision_key,
            )
            acceptance = load_spatial_acceptance_package(acceptance_dir)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"m2-a03-spatial-approval: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"acceptance_dir": str(acceptance_dir), "status": acceptance.get("status"), "decision_binding": acceptance.get("decision_binding")}, indent=2, sort_keys=True))
        return 0
    package = load_m2a03_spatial_package(args.spatial_package)
    if _is_live_spatial_r01(package, args.spatial_package):
        print(
            "m2-a03-spatial-approval: spatial-r01 approval requires --decision-addendum and the three option ids",
            file=sys.stderr,
        )
        return 2
    packet = package.get("decision_packet") or build_spatial_decision_packet(package)
    missing = not args.actor or not args.reason or not args.origin_ids or not args.destination_tags or not args.network_policy
    if missing:
        print(json.dumps(packet, indent=2, sort_keys=True))
        print("m2-a03-spatial-approval: explicit origin IDs, destination tags, network policy, actor, and reason are required", file=sys.stderr)
        return 2
    try:
        network_policy = json.loads(args.network_policy)
    except json.JSONDecodeError as exc:
        print(f"m2-a03-spatial-approval: network policy is not JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(network_policy, dict):
        print("m2-a03-spatial-approval: network policy must be a JSON object", file=sys.stderr)
        return 2
    if not args.historical_replay:
        print(
            "m2-a03-spatial-approval: raw origin-ID approval is a historical replay; pass --historical-replay",
            file=sys.stderr,
        )
        return 2
    decision_key = _request_decision_key(password_prompt)
    if decision_key is None:
        return 1
    try:
        acceptance_dir = freeze_m2a03_spatial_policies(
            args.database,
            args.spatial_package,
            args.output_root,
            actor=args.actor,
            reason=args.reason,
            origin_ids=args.origin_ids,
            destination_tags=args.destination_tags,
            network_policy=network_policy,
            historical_replay=True,
            actor_kind=ActorKind.HUMAN_UI,
            actor_session_id=f"spatial-approval-{uuid.uuid4().hex}",
            decision_key=decision_key,
        )
        acceptance = load_spatial_acceptance_package(acceptance_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"m2-a03-spatial-approval: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"acceptance_dir": str(acceptance_dir), "status": acceptance.get("status"), "study_area_id": acceptance.get("study_area_id"), "weather_gate_status": acceptance.get("weather_gate_status"), "policy_decision_ids": acceptance.get("policy_decision_ids")}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
