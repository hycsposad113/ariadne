"""Human spatial-policy freeze. This module does not select policies."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import heapq
import itertools
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

from .analysis_inputs import (
    AnalysisInputError,
    ArtifactIntegrityError,
    StudyAreaAnchorError,
    _manifest_for,
    _write_json,
    inspect_active_study_area,
    load_m2a03_spatial_package,
    require_spatial_package_use,
    sha256_bytes,
    sha256_file,
)
from .models import (
    ActorKind,
    DecisionAction,
    HumanDecision,
    HumanStatus,
    ParameterDefinition,
    ParameterStatus,
    SourceType,
)
from .decision_key import DecisionKeyUnavailable, verify_decision_key_strict
from .store import EntityExistsError, EntityNotFoundError, ProjectStateStore


ALLOWED_DESTINATION_TAGS = ("supermarket", "convenience", "grocery")
REQUIRED_NETWORK_EXCLUSIONS = (
    {"key": "foot", "value": "no"},
    {"key": "access", "value": "no"},
    {"key": "access", "value": "private"},
)
_PEDESTRIAN_HIGHWAYS = {"footway", "path", "pedestrian", "living_street", "steps", "corridor"}
ACCEPTANCE_SCHEMA = "m2-a03-spatial-input-acceptance-v1"
ACCEPTED_STATUS = "ACCEPTED_FOR_WEEK3"


class SpatialPolicyError(AnalysisInputError):
    """Raised when a spatial policy selection cannot be frozen."""


def _origin_records(package: Mapping[str, Any]) -> tuple[str, list[str] | None]:
    inventory = package.get("origin_inventory") if isinstance(package.get("origin_inventory"), Mapping) else {}
    status = str(inventory.get("status") or "UNAVAILABLE")
    if status == "UNAVAILABLE" or inventory.get("records") is None:
        return status, None
    records = inventory.get("records")
    if not isinstance(records, list):
        return "UNAVAILABLE", None
    return status, [str(record.get("feature_id")) for record in records if isinstance(record, Mapping) and record.get("feature_id")]


def _grocery_observation(package: Mapping[str, Any]) -> tuple[str, dict[str, int] | None, list[str]]:
    inventory = package.get("grocery_inventory") if isinstance(package.get("grocery_inventory"), Mapping) else {}
    status = str(inventory.get("status") or "UNAVAILABLE")
    if status == "UNAVAILABLE" or "counts_by_shop_tag" not in inventory:
        return status, None, []
    raw_counts = inventory.get("counts_by_shop_tag")
    if not isinstance(raw_counts, Mapping):
        return "UNAVAILABLE", None, []
    counts = {str(key): int(value) for key, value in raw_counts.items()}
    observed = [tag for tag in ALLOWED_DESTINATION_TAGS if counts.get(tag, 0) > 0]
    return status, counts, observed


def _network_distribution(package: Mapping[str, Any]) -> dict[str, Any]:
    inventory = package.get("network_inventory") if isinstance(package.get("network_inventory"), Mapping) else {}
    distribution = inventory.get("network_tag_distribution")
    if not isinstance(distribution, Mapping):
        return {}
    return {str(key): dict(value) if isinstance(value, Mapping) else value for key, value in distribution.items()}


def _network_limitation(package: Mapping[str, Any]) -> str:
    inventory = package.get("network_inventory") if isinstance(package.get("network_inventory"), Mapping) else {}
    text = inventory.get("conditional_access_limitation")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return (
        "Conditional, destination-only, permissive, unknown, or otherwise ambiguous "
        "access tags are not treated as public access and remain a visible limitation."
    )


def _subsets(items: Sequence[str]) -> list[list[str]]:
    found: list[list[str]] = []
    for size in range(1, len(items) + 1):
        for combo in itertools.combinations(items, size):
            found.append(list(combo))
    return found


def _policy_template(include_highways: Sequence[str], limitation: str) -> dict[str, Any]:
    return {
        "include_highways": list(include_highways),
        "exclude": [dict(item) for item in REQUIRED_NETWORK_EXCLUSIONS],
        "ambiguous_access_limitation": limitation,
        "allow_ambiguous_access": False,
    }


def build_spatial_decision_packet(package: Mapping[str, Any]) -> dict[str, Any]:
    """Describe observed choices. Nothing in the packet is an approval."""

    origin_status, origin_ids = _origin_records(package)
    grocery_status, grocery_counts, observed_tags = _grocery_observation(package)
    distribution = _network_distribution(package)
    limitation = _network_limitation(package)
    highways = [key for key in (distribution.get("highway") or {}) if key and key != "None"]
    origin_options = []
    if origin_ids:
        origin_options.append({"option_id": "all-observed-origins", "origin_ids": list(origin_ids), "cli_origin_ids": list(origin_ids), "selected": None})
        for origin_id in origin_ids:
            origin_options.append({"option_id": f"only-{origin_id}", "origin_ids": [origin_id], "cli_origin_ids": [origin_id], "selected": None})
    destination_options = [
        {"option_id": "tags-" + "-".join(subset), "destination_tags": subset, "cli_destination_tags": subset, "selected": None}
        for subset in _subsets(observed_tags)
    ]
    network_options = []
    if highways:
        network_options.append({"option_id": "all-observed-highways", "network_policy": _policy_template(highways, limitation), "selected": None})
        pedestrian = [value for value in highways if value in _PEDESTRIAN_HIGHWAYS]
        if pedestrian and pedestrian != highways:
            network_options.append({"option_id": "observed-pedestrian-highways", "network_policy": _policy_template(pedestrian, limitation), "selected": None})
    return {
        "schema_version": "m2-a03-spatial-decision-packet-v1",
        "status": "AWAITING_HUMAN_SELECTION",
        "selected_origin_ids": None,
        "selected_destination_tags": None,
        "selected_network_policy": None,
        "approval_reason": None,
        "approved_by": None,
        "origin_status": origin_status,
        "origin_count": None if origin_ids is None else len(origin_ids),
        "origin_ids": origin_ids,
        "grocery_status": grocery_status,
        "grocery_tag_counts": grocery_counts,
        "observed_destination_categories": observed_tags,
        "network_tag_distribution": distribution,
        "limitations": [
            limitation,
            "OSM and PDOK tags do not prove legal access, ownership, safety, or buildability.",
            "Vertical reference is unavailable and is not zero.",
            "Weather method remains SEMANTICS_UNRESOLVED and is not part of this decision. It blocks Week 6 only.",
            "Conditional or ambiguous access stays a visible limitation and is not approved as public access.",
        ],
        "options": {
            "origin_denominator": origin_options,
            "destination_taxonomy": destination_options,
            "pedestrian_network": network_options,
        },
    }


def _exclusion_pairs(policy: Mapping[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for item in policy.get("exclude") or policy.get("exclude_tags") or []:
        if isinstance(item, Mapping) and item.get("key") and item.get("value"):
            pairs.add((str(item["key"]), str(item["value"])))
    return pairs


def validate_spatial_policy_selection(
    package: Mapping[str, Any],
    *,
    origin_ids: Sequence[str],
    destination_tags: Sequence[str],
    network_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Reject empty, unobserved, or implicit spatial policy choices."""

    if not origin_ids or any(not isinstance(origin_id, str) or not origin_id.strip() for origin_id in origin_ids):
        raise SpatialPolicyError("origin IDs must be a non-empty list of observed identifiers")
    normalized_origins = [origin_id.strip() for origin_id in origin_ids]
    if len(normalized_origins) != len(set(normalized_origins)):
        raise SpatialPolicyError("duplicate origin IDs are rejected")
    _status, observed_origins = _origin_records(package)
    if observed_origins is None:
        raise SpatialPolicyError("origin inventory is unavailable; missing origins cannot be approved as zero")
    unknown_origins = [origin_id for origin_id in origin_ids if origin_id not in set(observed_origins)]
    if unknown_origins:
        raise SpatialPolicyError(f"origin IDs are not in the acquired inventory: {', '.join(unknown_origins)}")
    if not destination_tags or any(not isinstance(tag, str) or not tag.strip() for tag in destination_tags):
        raise SpatialPolicyError("destination tags must be a non-empty list")
    normalized_tags = [tag.strip() for tag in destination_tags]
    if len(normalized_tags) != len(set(normalized_tags)):
        raise SpatialPolicyError("duplicate destination tags are rejected")
    _grocery_status, _counts, observed_tags = _grocery_observation(package)
    allowed = set(observed_tags)
    unknown_tags = [tag for tag in destination_tags if tag not in allowed or tag not in ALLOWED_DESTINATION_TAGS]
    if unknown_tags:
        raise SpatialPolicyError(f"destination tags are outside the observed grocery classes: {', '.join(unknown_tags)}")
    include = network_policy.get("include_highways")
    if not isinstance(include, Sequence) or isinstance(include, (str, bytes)) or not list(include):
        raise SpatialPolicyError("pedestrian-network include rules must be an explicit non-empty list")
    include_values = [str(value) for value in include]
    if len(include_values) != len(set(include_values)):
        raise SpatialPolicyError("duplicate network include classes are rejected")
    observed_highways = set((_network_distribution(package).get("highway") or {}))
    unobserved = [str(value) for value in include if str(value) not in observed_highways]
    if unobserved:
        raise SpatialPolicyError(f"network include values were not observed: {', '.join(unobserved)}")
    pairs = _exclusion_pairs(network_policy)
    missing = [item for item in REQUIRED_NETWORK_EXCLUSIONS if (item["key"], item["value"]) not in pairs]
    if missing:
        raise SpatialPolicyError("pedestrian-network policy must exclude foot=no, access=no, and access=private")
    limitation = network_policy.get("ambiguous_access_limitation")
    if not isinstance(limitation, str) or "limitation" not in limitation.lower():
        raise SpatialPolicyError("conditional or ambiguous access must remain a visible limitation")
    if network_policy.get("allow_ambiguous_access") is True:
        raise SpatialPolicyError("ambiguous access cannot be approved as allowed")
    preserved_policy = dict(network_policy)
    preserved_policy["include_highways"] = include_values
    preserved_policy["exclude"] = [dict(item) for item in (network_policy.get("exclude") or [])]
    preserved_policy["ambiguous_access_limitation"] = limitation.strip()
    preserved_policy["allow_ambiguous_access"] = False
    return {
        "origin_ids": [origin_id.strip() for origin_id in origin_ids],
        "destination_tags": [tag.strip() for tag in destination_tags],
        "network_policy": preserved_policy,
    }


def _stable_ids(package_id: str, policy_name: str) -> tuple[str, str, str]:
    digest = hashlib.sha256(f"{package_id}:{policy_name}".encode("utf-8")).hexdigest()[:24]
    return (
        f"param-spatial-{policy_name}-{digest}",
        f"decision-spatial-{policy_name}-{digest}",
        f"m2-a03-spatial-approve-{policy_name}-{digest}",
    )


def _manifest_sha256(package_root: Path) -> str:
    manifest_path = package_root / "package-manifest.json"
    return sha256_file(manifest_path)


def _is_live_spatial_r01(package: Mapping[str, Any], package_root: str | Path | None = None) -> bool:
    """The active spatial-r01 package, not a fixture and not an addendum directory."""

    package_id = str(package.get("package_id") or package.get("spatial_package_id") or "")
    revision = str(package.get("package_revision") or "")
    if revision == "spatial-r01" or package_id.endswith("-spatial-r01"):
        return True
    if package_root is not None and Path(package_root).name == "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01":
        return True
    root = str(package.get("spatial_package_root") or "")
    return root.rstrip("/").endswith("run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01")


def _binding_has_addendum_hash(decision_binding: Mapping[str, Any] | None) -> bool:
    if not isinstance(decision_binding, Mapping):
        return False
    value = decision_binding.get("decision_addendum_manifest_sha256")
    return isinstance(value, str) and value.startswith("sha256:") and len(value) == 71


def authorize_week3_entry(package: Mapping[str, Any]) -> str:
    """Week 3 is authorized by spatial acceptance, not by a weather approval."""

    if package.get("schema_version") != ACCEPTANCE_SCHEMA or package.get("status") != ACCEPTED_STATUS:
        raise SpatialPolicyError("Week 3 requires an ACCEPTED_FOR_WEEK3 spatial acceptance package")
    if _is_live_spatial_r01(package) and not _binding_has_addendum_hash(package.get("decision_binding")):
        raise SpatialPolicyError(
            "spatial-r01 Week 3 requires decision_binding and the addendum manifest hash"
        )
    if package.get("weather_gate_status") == "PASS":
        return "AUTHORIZED"
    if package.get("weather_gate_status") != "SEMANTICS_UNRESOLVED":
        raise SpatialPolicyError("Week 3 acceptance has an unexpected weather gate status")
    return "AUTHORIZED"


def authorize_week6_entry(package: Mapping[str, Any]) -> str:
    """Week 6 stays blocked while the weather method is unresolved."""

    if package.get("weather_gate_status") != "PASS":
        raise SpatialPolicyError(
            "WEEK_6 blocked until weather method gate PASS; "
            f"current status is {package.get('weather_gate_status') or 'BLOCKED'}"
        )
    return "AUTHORIZED"


def load_spatial_acceptance_package(package_root: str | Path) -> dict[str, Any]:
    root = Path(package_root)
    manifest_path = root / "package-manifest.json"
    if not manifest_path.is_file():
        raise ArtifactIntegrityError("acceptance package-manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        path = root / entry["path"]
        if not path.is_file():
            raise ArtifactIntegrityError(f"acceptance file is missing: {entry['path']}")
        data = path.read_bytes()
        if sha256_bytes(data) != entry.get("sha256") or len(data) != entry.get("size_bytes"):
            raise ArtifactIntegrityError(f"acceptance file integrity mismatch: {entry['path']}")
    package = json.loads((root / "spatial-input-acceptance.json").read_text(encoding="utf-8"))
    if package.get("schema_version") != ACCEPTANCE_SCHEMA:
        raise SpatialPolicyError("package is not a spatial acceptance package")
    return package


def _aware_utc(value: datetime | str, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise SpatialPolicyError(f"{field} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SpatialPolicyError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _resolve_approval_clock(package: Mapping[str, Any], approved_at: datetime | str | None) -> datetime:
    """Use the actual approval time, which must be later than source acquisition."""

    source_time = _aware_utc(str(package["created_at"]), "source created_at")
    clock = datetime.now(timezone.utc) if approved_at is None else _aware_utc(approved_at, "approved_at")
    if clock <= source_time:
        raise SpatialPolicyError("approval time must be later than and distinct from source acquisition created_at")
    return clock


def _policy_records(
    *,
    package: Mapping[str, Any],
    actor: str,
    reason: str,
    selection: Mapping[str, Any],
    manifest_sha256: str,
    approved_at: datetime,
    decision_binding: Mapping[str, Any] | None = None,
    actor_kind: ActorKind,
    actor_session_id: str,
) -> list[dict[str, Any]]:
    project_id = str(package["project_id"])
    package_id = str(package["package_id"])
    study_area = package["study_area"]
    created_at = approved_at
    values = {
        "origin_denominator": {"origin_ids": list(selection["origin_ids"])},
        "destination_taxonomy": {"destination_tags": list(selection["destination_tags"])},
        "pedestrian_network": dict(selection["network_policy"]),
    }
    if decision_binding:
        for value in values.values():
            value.update(dict(decision_binding))
    records = []
    for policy_name, value in values.items():
        parameter_id, decision_id, event_id = _stable_ids(package_id, policy_name)
        parameter = ParameterDefinition.model_validate(
            {
                "id": parameter_id,
                "name": policy_name,
                "value": value,
                "unit": "1",
                "context": "week2_spatial_input",
                "scale": "study_area",
                "source_type": SourceType.PROJECT_DECISION,
                "version": "v1",
                "evidence_refs": [
                    package_id,
                    str(study_area["id"]),
                    str(study_area["geometry_sha256"]),
                    str(study_area["artifact_sha256"]),
                    manifest_sha256,
                ],
                "status": ParameterStatus.EFFECTIVE,
            }
        )
        decision = HumanDecision.model_validate(
            {
                "id": decision_id,
                "project_id": project_id,
                "target_id": parameter_id,
                "target_type": "ParameterDefinition",
                "target_version": "v1",
                "target_geometry_sha256": study_area["geometry_sha256"],
                "target_artifact_sha256": study_area["artifact_sha256"],
                "action": DecisionAction.APPROVE,
                "status": HumanStatus.APPROVED,
                "actor": actor,
                "actor_kind": actor_kind,
                "actor_session_id": actor_session_id,
                "reason": reason,
                "timestamp": created_at,
                "decision_event_id": event_id,
                "resulting_refs": [
                    parameter_id,
                    package_id,
                    str(study_area["id"]),
                    *[
                        str(decision_binding[key])
                        for key in (
                            "decision_addendum_manifest_sha256",
                            "origin_option_id",
                            "destination_option_id",
                            "network_option_id",
                        )
                        if decision_binding and decision_binding.get(key)
                    ],
                ],
            }
        )
        records.append(
            {
                "policy_name": policy_name,
                "parameter_id": parameter_id,
                "decision_id": decision_id,
                "event_id": event_id,
                "parameter": parameter.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
            }
        )
    return records


def _same_record(current_payload: Mapping[str, Any], expected_payload: Mapping[str, Any]) -> bool:
    return json.dumps(current_payload, sort_keys=True) == json.dumps(expected_payload, sort_keys=True)


def _acceptance_matches_selection(
    existing: Mapping[str, Any],
    selection: Mapping[str, Any],
    *,
    actor: str,
    reason: str,
    manifest_sha256: str,
    decision_binding: Mapping[str, Any] | None,
) -> bool:
    if existing.get("actor") != actor or existing.get("reason") != reason:
        return False
    if existing.get("spatial_package_manifest_sha256") != manifest_sha256:
        return False
    origin = existing["parameters"]["origin_denominator"]["value"]
    destination = existing["parameters"]["destination_taxonomy"]["value"]
    network = existing["parameters"]["pedestrian_network"]["value"]
    if list(origin.get("origin_ids") or []) != list(selection["origin_ids"]):
        return False
    if list(destination.get("destination_tags") or []) != list(selection["destination_tags"]):
        return False
    for key in ("include_highways", "exclude", "ambiguous_access_limitation", "allow_ambiguous_access"):
        if network.get(key) != selection["network_policy"].get(key):
            return False
    binding = dict(decision_binding or {})
    for key, value in binding.items():
        if origin.get(key) != value or destination.get(key) != value or network.get(key) != value:
            return False
    stored_binding = {key: origin.get(key) for key in ("decision_addendum_manifest_sha256", "origin_option_id", "destination_option_id", "network_option_id") if key in origin}
    if stored_binding != binding:
        return False
    return True


def replay_acceptance_sqlite(database: str | Path, acceptance: Mapping[str, Any]) -> str:
    """Return MATCH, ABSENT, or INCONSISTENT after reading persisted approval records."""

    acceptance_session = acceptance.get("actor_session_id")
    if (
        acceptance.get("actor_kind") != ActorKind.HUMAN_UI.value
        or not isinstance(acceptance_session, str)
        or not acceptance_session.strip()
    ):
        return "INCONSISTENT"
    try:
        with ProjectStateStore(database, read_only=True) as store:
            for policy_name, decision_id in acceptance["policy_decision_ids"].items():
                parameter_id = acceptance["parameter_ids"][policy_name]
                event_id = acceptance["approval_event_ids"][policy_name]
                try:
                    parameter = store.current(parameter_id)
                    decision = store.current(decision_id)
                except EntityNotFoundError:
                    return "ABSENT"
                if parameter.entity_type != "ParameterDefinition" or decision.entity_type != "HumanDecision":
                    return "INCONSISTENT"
                if not _same_record(parameter.payload, acceptance["parameters"][policy_name]):
                    return "INCONSISTENT"
                if not _same_record(decision.payload, acceptance["decisions"][policy_name]):
                    return "INCONSISTENT"
                event = next((item for item in store.events() if item.event_id == event_id), None)
                if event is None:
                    return "ABSENT"
                if (
                    event.action != "Approve"
                    or event.target_id != decision_id
                    or event.target_type != "HumanDecision"
                    or event.project_id != decision.project_id
                ):
                    return "INCONSISTENT"
                if str(event.timestamp) != str(decision.payload.get("timestamp")):
                    return "INCONSISTENT"
                if (
                    decision.payload.get("actor") != acceptance.get("actor")
                    or decision.payload.get("actor_kind") != acceptance.get("actor_kind")
                    or decision.payload.get("actor_session_id") != acceptance.get("actor_session_id")
                    or event.actor != acceptance.get("actor")
                    or (event.actor_kind.value if event.actor_kind is not None else None) != acceptance.get("actor_kind")
                    or event.actor_session_id != acceptance.get("actor_session_id")
                ):
                    return "INCONSISTENT"
    except (OSError, KeyError, TypeError, json.JSONDecodeError, sqlite3.Error):
        return "ABSENT"
    return "MATCH"


def freeze_m2a03_spatial_policies(
    database: str | Path,
    spatial_package_root: str | Path,
    output_root: str | Path,
    *,
    actor: str,
    reason: str,
    origin_ids: Sequence[str],
    destination_tags: Sequence[str],
    network_policy: Mapping[str, Any],
    approved_at: datetime | str | None = None,
    commit_hook: Any | None = None,
    decision_binding: Mapping[str, Any] | None = None,
    historical_replay: bool = False,
    actor_kind: ActorKind | str | None = None,
    actor_session_id: str | None = None,
    decision_key: str | None = None,
    decision_key_path: str | Path | None = None,
) -> Path:
    """Append three human policy decisions and one acceptance package.

    Raw origin-ID approval is the historical replay API (`historical_replay`).
    The active spatial-r01 package still requires an addendum decision binding.
    """

    if not isinstance(actor, str) or not actor.strip() or actor.strip().startswith("m2-a03-"):
        raise SpatialPolicyError("spatial policy approval requires an explicit human actor")
    if not isinstance(reason, str) or not reason.strip():
        raise SpatialPolicyError("spatial policy approval requires a human reason")
    try:
        resolved_actor_kind = ActorKind(actor_kind) if actor_kind is not None else None
    except ValueError as exc:
        raise SpatialPolicyError("spatial policy approval requires a supported actor kind") from exc
    if resolved_actor_kind is not ActorKind.HUMAN_UI:
        raise SpatialPolicyError("HumanDecision records require HUMAN_UI and a verified designer decision key")
    if not isinstance(actor_session_id, str) or not actor_session_id.strip():
        raise SpatialPolicyError("spatial policy approval requires an actor session ID")
    if not isinstance(decision_key, str):
        raise SpatialPolicyError("spatial policy approval requires a verified designer decision key")
    try:
        if not verify_decision_key_strict(decision_key, path=decision_key_path):
            raise SpatialPolicyError("spatial policy approval requires a verified designer decision key")
    except DecisionKeyUnavailable:
        raise SpatialPolicyError("designer decision key is unavailable") from None
    source_root = Path(spatial_package_root)
    package = load_m2a03_spatial_package(source_root)
    if _is_live_spatial_r01(package, source_root) and not _binding_has_addendum_hash(decision_binding):
        replay = " Historical replay does not bypass this requirement." if historical_replay else ""
        raise SpatialPolicyError(
            "spatial-r01 approval requires decision_binding and the addendum manifest hash." + replay
        )
    if decision_binding is None and not historical_replay:
        raise SpatialPolicyError("raw origin-ID approval requires the historical_replay marker")
    inspection = inspect_active_study_area(database, project_id=package["project_id"], study_area_id=package["study_area"]["id"])
    if inspection.geometry_sha256 != package["study_area"].get("geometry_sha256"):
        raise StudyAreaAnchorError("StudyArea hash drift invalidates the spatial policy freeze")
    if inspection.artifact_sha256 != package["study_area"].get("artifact_sha256"):
        raise StudyAreaAnchorError("StudyArea artifact hash drift invalidates the spatial policy freeze")
    require_spatial_package_use(
        package,
        active_geometry_sha256=inspection.geometry_sha256,
        active_study_area_id=inspection.study_area_id,
    )
    selection = validate_spatial_policy_selection(
        package,
        origin_ids=origin_ids,
        destination_tags=destination_tags,
        network_policy=network_policy,
    )
    manifest_sha256 = _manifest_sha256(source_root)
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    acceptance_dir = output / f"acceptance-{package['package_id']}"
    if acceptance_dir.exists():
        existing = load_spatial_acceptance_package(acceptance_dir)
        if not _acceptance_matches_selection(
            existing,
            selection,
            actor=actor.strip(),
            reason=reason.strip(),
            manifest_sha256=manifest_sha256,
            decision_binding=decision_binding,
        ):
            raise SpatialPolicyError("conflicting reuse of policy decision")
        sqlite_status = replay_acceptance_sqlite(database, existing)
        if sqlite_status != "MATCH":
            raise SpatialPolicyError(
                f"BLOCKED: acceptance directory is not backed by matching SQLite records ({sqlite_status})"
            )
        return acceptance_dir
    approval_clock = _resolve_approval_clock(package, approved_at)
    records = _policy_records(
        package=package,
        actor=actor.strip(),
        reason=reason.strip(),
        selection=selection,
        manifest_sha256=manifest_sha256,
        approved_at=approval_clock,
        decision_binding=decision_binding,
        actor_kind=resolved_actor_kind,
        actor_session_id=actor_session_id.strip(),
    )
    with ProjectStateStore(database, read_only=True) as store:
        for record in records:
            for entity_id, payload in (
                (record["parameter_id"], record["parameter"]),
                (record["decision_id"], record["decision"]),
            ):
                try:
                    current = store.current(entity_id)
                except EntityNotFoundError:
                    current = None
                if current is not None and not _same_record(current.payload, payload):
                    raise SpatialPolicyError(f"conflicting reuse of policy record {entity_id}")
            try:
                existing_event = next(event for event in store.events() if event.event_id == record["event_id"])
            except StopIteration:
                existing_event = None
            if existing_event is not None and existing_event.payload.get("policy_name") != record["policy_name"]:
                raise SpatialPolicyError(f"conflicting reuse of policy decision {record['decision_id']}")
    acceptance = {
        "schema_version": ACCEPTANCE_SCHEMA,
        "status": ACCEPTED_STATUS,
        "spatial_package_id": package["package_id"],
        "spatial_package_root": str(source_root.resolve()),
        "spatial_package_manifest_sha256": manifest_sha256,
        "study_area_id": package["study_area"]["id"],
        "study_area_geometry_sha256": package["study_area"]["geometry_sha256"],
        "study_area_artifact_sha256": package["study_area"]["artifact_sha256"],
        "policy_decision_ids": {record["policy_name"]: record["decision_id"] for record in records},
        "parameter_ids": {record["policy_name"]: record["parameter_id"] for record in records},
        "approval_event_ids": {record["policy_name"]: record["event_id"] for record in records},
        "weather_gate_status": "SEMANTICS_UNRESOLVED",
        "actor": actor.strip(),
        "actor_kind": resolved_actor_kind.value,
        "actor_session_id": actor_session_id.strip(),
        "reason": reason.strip(),
        "effective_version": "v1",
        "no_accessibility_result": True,
        "no_climate_result": True,
        "formal_claim_status": "BLOCKED",
        "parameters": {record["policy_name"]: record["parameter"] for record in records},
        "decisions": {record["policy_name"]: record["decision"] for record in records},
        "decision_binding": dict(decision_binding) if decision_binding else None,
    }
    entities = []
    events = []
    for record in records:
        entities.append(
            {
                "entity_id": record["parameter_id"],
                "entity_type": "ParameterDefinition",
                "project_id": package["project_id"],
                "payload": record["parameter"],
                "event_id": "m2-a03-spatial-parameter-" + hashlib.sha256(record["parameter_id"].encode()).hexdigest()[:24],
                "actor": actor.strip(),
                "actor_kind": resolved_actor_kind,
                "actor_session_id": actor_session_id.strip(),
                "action": "Create",
                "reason": reason.strip(),
                "resulting_refs": (record["parameter_id"],),
                "event_payload": {"package_id": package["package_id"], "policy_name": record["policy_name"]},
            }
        )
        entities.append(
            {
                "entity_id": record["decision_id"],
                "entity_type": "HumanDecision",
                "project_id": package["project_id"],
                "payload": record["decision"],
                "event_id": "m2-a03-spatial-decision-" + hashlib.sha256(record["decision_id"].encode()).hexdigest()[:24],
                "actor": actor.strip(),
                "actor_kind": resolved_actor_kind,
                "actor_session_id": actor_session_id.strip(),
                "action": "Create",
                "reason": reason.strip(),
                "resulting_refs": (record["decision_id"], record["parameter_id"]),
                "event_payload": {"package_id": package["package_id"], "policy_name": record["policy_name"]},
            }
        )
        events.append(
            {
                "event_id": record["event_id"],
                "timestamp": record["decision"]["timestamp"],
                "actor": actor.strip(),
                "action": "Approve",
                "target_id": record["decision_id"],
                "target_type": "HumanDecision",
                "project_id": package["project_id"],
                "prior_status": "PROPOSED_PROJECT_DECISION",
                "changed_refs": (package["package_id"], package["study_area"]["id"]),
                "reason": reason.strip(),
                "resulting_refs": (record["decision_id"], record["parameter_id"], package["package_id"]),
                "payload": {
                    "policy_name": record["policy_name"],
                    "parameter_id": record["parameter_id"],
                    "source_package_id": package["package_id"],
                    "source_package_manifest_sha256": manifest_sha256,
                    "study_area_id": package["study_area"]["id"],
                    "study_area_geometry_sha256": package["study_area"]["geometry_sha256"],
                    "study_area_artifact_sha256": package["study_area"]["artifact_sha256"],
                    "effective_version": "v1",
                    **(dict(decision_binding) if decision_binding else {}),
                },
                "actor_kind": resolved_actor_kind,
                "actor_session_id": actor_session_id.strip(),
            }
        )
    if acceptance_dir.exists():
        raise SpatialPolicyError("BLOCKED: acceptance directory is not backed by matching SQLite records (ABSENT)")
    stage = acceptance_dir.with_name(f".{acceptance_dir.name}.stage")
    if stage.exists():
        raise SpatialPolicyError(f"acceptance staging directory already exists: {stage}")
    stage.mkdir()
    try:
        _write_json(stage / "spatial-input-acceptance.json", acceptance)
        files = [path for path in stage.rglob("*") if path.is_file() and path.name != "package-manifest.json"]
        _write_json(stage / "package-manifest.json", _manifest_for(stage, files))

        def publish() -> None:
            stage.rename(acceptance_dir)
            if commit_hook is not None:
                commit_hook()

        with ProjectStateStore(database) as store:
            store.commit_batch(
                entities=entities,
                events=events,
                before_commit=publish,
                decision_key=decision_key,
                decision_key_path=decision_key_path,
            )
    except Exception:
        if stage.exists():
            import shutil
            shutil.rmtree(stage, ignore_errors=True)
        raise
    reloaded = load_spatial_acceptance_package(acceptance_dir)
    if reloaded["status"] != ACCEPTED_STATUS:
        raise SpatialPolicyError("acceptance package did not reload as ACCEPTED_FOR_WEEK3")
    authorize_week3_from_persisted_state(database, acceptance_dir)
    return acceptance_dir


def authorize_week3_from_persisted_state(database: str | Path, acceptance_root: str | Path) -> str:
    """Replay the acceptance package from SQLite before authorizing Week 3."""

    package = load_spatial_acceptance_package(acceptance_root)
    package_session = package.get("actor_session_id")
    if (
        package.get("actor_kind") != ActorKind.HUMAN_UI.value
        or not isinstance(package_session, str)
        or not package_session.strip()
    ):
        raise SpatialPolicyError("persisted Week 3 approvals require authenticated HUMAN_UI decisions")
    with ProjectStateStore(database, read_only=True) as store:
        for policy_name, decision_id in package["policy_decision_ids"].items():
            parameter_id = package["parameter_ids"][policy_name]
            event_id = package["approval_event_ids"][policy_name]
            parameter = store.current(parameter_id)
            decision = store.current(decision_id)
            if parameter.entity_type != "ParameterDefinition" or decision.entity_type != "HumanDecision":
                raise SpatialPolicyError("persisted policy records have the wrong type")
            typed = ParameterDefinition.model_validate(parameter.payload)
            if typed.source_type is not SourceType.PROJECT_DECISION:
                raise SpatialPolicyError("persisted parameter is not a project decision")
            typed_decision = HumanDecision.model_validate(decision.payload)
            if (
                typed_decision.decision_event_id != event_id
                or typed_decision.actor != package["actor"]
                or typed_decision.actor_kind is None
                or typed_decision.actor_kind.value != package["actor_kind"]
                or typed_decision.actor_session_id != package["actor_session_id"]
            ):
                raise SpatialPolicyError("persisted human decision does not match the acceptance package")
            if typed_decision.reason != package["reason"]:
                raise SpatialPolicyError("persisted human decision reason drifted")
            event = next(item for item in store.events() if item.event_id == event_id)
            if (
                event.action != "Approve"
                or event.target_id != decision_id
                or event.target_type != "HumanDecision"
                or event.project_id != decision.project_id
                or event.actor != package["actor"]
                or event.actor_kind is None
                or event.actor_kind.value != package["actor_kind"]
                or event.actor_session_id != package["actor_session_id"]
                or not isinstance(event.actor_session_id, str)
                or not event.actor_session_id.strip()
            ):
                raise SpatialPolicyError("approval ledger event does not match the human decision")
            if event.payload.get("study_area_geometry_sha256") != package["study_area_geometry_sha256"]:
                raise SpatialPolicyError("approval event StudyArea hash drifted")
            if event.payload.get("source_package_manifest_sha256") != package["spatial_package_manifest_sha256"]:
                raise SpatialPolicyError("approval event source hash drifted")
    try:
        authorize_week6_entry(package)
    except SpatialPolicyError:
        week6_blocked = True
    else:
        week6_blocked = False
    if not week6_blocked:
        raise SpatialPolicyError("Week 6 must remain blocked while weather is unresolved")
    return authorize_week3_entry(package)


SNAP_DISTANCE_M = 30.0
ENDPOINT_TOLERANCE_M = 0.05
NAMED_STOP_ROLES = ("station", "stop_position", "platform")
_ROLE_PREFERENCE = {"station": 0, "stop_position": 1, "platform": 2}
CURATED_EXCLUDED_HIGHWAYS = ("construction", "proposed", "busway", "track")
CURATED_INCLUDE_HIGHWAYS = (
    "footway",
    "path",
    "pedestrian",
    "living_street",
    "steps",
    "residential",
    "unclassified",
    "tertiary",
    "secondary",
    "secondary_link",
    "service",
    "cycleway",
)
ADDENDUM_DIRECTORY_NAME = "spatial-r01-decision-addendum"
_CURATED_ACCESS_RULE = (
    "Ordinary streets in the include list are traversable only when foot is not no or "
    "use_sidepath and access is not no, private, customers, or destination. cycleway is "
    "included only when foot is yes or designated. access=permissive is kept in the graph "
    "but is not treated as proof of legal public access. construction, proposed, busway, "
    "and track are excluded as unsuitable classes; track is excluded because it is not an "
    "ordinary urban pedestrian street in this inventory."
)


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[tuple[float, float], tuple[float, float]] = {}

    def add(self, key: tuple[float, float]) -> None:
        self._parent.setdefault(key, key)

    def find(self, key: tuple[float, float]) -> tuple[float, float]:
        parent = self._parent.setdefault(key, key)
        if parent != key:
            self._parent[key] = self.find(parent)
        return self._parent[key]

    def union(self, left: tuple[float, float], right: tuple[float, float]) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self._parent[right_root] = left_root

    def component_count(self) -> int:
        return len({self.find(key) for key in self._parent})


def _feature_tags(feature: Mapping[str, Any]) -> dict[str, Any]:
    properties = feature.get("properties") if isinstance(feature.get("properties"), Mapping) else {}
    tags = properties.get("tags") if isinstance(properties, Mapping) else None
    return dict(tags) if isinstance(tags, Mapping) else {}


def _origin_tag(record: Mapping[str, Any], key: str) -> str:
    tags = record.get("tags") if isinstance(record.get("tags"), Mapping) else {}
    value = tags.get(key)
    if not isinstance(value, str) or not value.strip():
        return "MISSING"
    return value.strip()


def _named_stop_key(record: Mapping[str, Any]) -> str | None:
    tags = record.get("tags") if isinstance(record.get("tags"), Mapping) else {}
    name = tags.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    if _origin_tag(record, "public_transport") not in NAMED_STOP_ROLES:
        return None
    return name.strip().casefold()


def classify_spatial_origins(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Classify every origin record. Missing tags stay as an explicit residual."""

    by_public_transport: dict[str, list[str]] = {}
    by_entrance: dict[str, list[str]] = {}
    repeated: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        feature_id = str(record.get("feature_id") or "")
        public_transport = _origin_tag(record, "public_transport")
        entrance = _origin_tag(record, "entrance")
        by_public_transport.setdefault(public_transport, []).append(feature_id)
        by_entrance.setdefault(entrance, []).append(feature_id)
        group_key = _named_stop_key(record)
        if group_key is not None:
            repeated.setdefault(group_key, []).append(record)
    repeated_groups = []
    for name in sorted(repeated):
        members = repeated[name]
        if len(members) < 2:
            continue
        repeated_groups.append(
            {
                "name": str((members[0].get("tags") or {}).get("name")),
                "name_key": name,
                "count": len(members),
                "feature_ids": [str(member.get("feature_id")) for member in members],
                "public_transport_values": [_origin_tag(member, "public_transport") for member in members],
                "rule": "Same non-empty name and public_transport in station, stop_position, or platform.",
            }
        )
    return {
        "record_count": len(list(records)),
        "by_public_transport": {key: {"count": len(ids), "feature_ids": ids} for key, ids in sorted(by_public_transport.items())},
        "by_entrance": {key: {"count": len(ids), "feature_ids": ids} for key, ids in sorted(by_entrance.items())},
        "residual_missing_public_transport": {
            "count": len(by_public_transport.get("MISSING", [])),
            "feature_ids": by_public_transport.get("MISSING", []),
            "rule": "Records with no public_transport tag are retained as a counted residual.",
        },
        "residual_missing_entrance": {
            "count": len(by_entrance.get("MISSING", [])),
            "feature_ids": by_entrance.get("MISSING", []),
            "rule": "Records with no entrance tag are retained as a counted residual.",
        },
        "repeated_stop_groups": repeated_groups,
        "limitation": "Unique OSM identifiers are not semantically independent places when they repeat one named stop or station.",
    }


def _representative_id(members: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(
        members,
        key=lambda record: (
            _ROLE_PREFERENCE.get(_origin_tag(record, "public_transport"), 9),
            str(record.get("feature_id")),
        ),
    )
    return str(ordered[0].get("feature_id"))


def build_origin_denominator_options(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Category and deduplicated denominator options. None is selected."""

    classification = classify_spatial_origins(records)
    options: list[dict[str, Any]] = []
    all_ids = [str(record.get("feature_id")) for record in records if record.get("feature_id")]
    options.append(
        {
            "option_id": "all-observed-osm-ids",
            "rule": "Keep every observed OSM origin identifier.",
            "count": len(all_ids),
            "member_ids": all_ids,
            "limitations": [
                "These unique OSM IDs are not semantically independent places. Named stop and station groups repeat one place as stop_position, platform, or station."
            ],
            "selected": None,
        }
    )
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    ungrouped: list[str] = []
    for record in records:
        key = _named_stop_key(record)
        if key is None:
            if record.get("feature_id"):
                ungrouped.append(str(record["feature_id"]))
            continue
        grouped.setdefault(key, []).append(record)
    deduped = [_representative_id(members) for _, members in sorted(grouped.items())] + ungrouped
    options.append(
        {
            "option_id": "deduplicated-named-stop-places",
            "rule": "One representative per non-empty stop/station name, preferring station, then stop_position, then platform, then the lowest feature id. Records without that named public_transport role stay individually listed.",
            "count": len(deduped),
            "member_ids": deduped,
            "repeated_group_count": len(classification["repeated_stop_groups"]),
            "limitations": [
                "Unnamed nodes can still repeat a nearby named stop. This option removes same-name public-transport duplicates only.",
                classification["limitation"],
            ],
            "selected": None,
        }
    )
    for label, bucket in classification["by_public_transport"].items():
        options.append(
            {
                "option_id": f"category-public-transport-{label}",
                "rule": f"Include only records whose public_transport class is {label}. MISSING means the tag is absent and is kept as a residual.",
                "count": bucket["count"],
                "member_ids": list(bucket["feature_ids"]),
                "limitations": ["A public_transport class can still repeat another class at the same named stop."],
                "selected": None,
            }
        )
    for label, bucket in classification["by_entrance"].items():
        options.append(
            {
                "option_id": f"category-entrance-{label}",
                "rule": f"Include only records whose entrance class is {label}. MISSING means the tag is absent and is kept as a residual.",
                "count": bucket["count"],
                "member_ids": list(bucket["feature_ids"]),
                "limitations": ["Entrance tags do not prove public access."],
                "selected": None,
            }
        )
    return options


def _way_allowed(tags: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    highway = str(tags.get("highway") or "")
    excluded = {str(value) for value in policy.get("excluded_highways") or []}
    include = {str(value) for value in policy.get("include_highways") or []}
    if highway in excluded or highway not in include:
        return False
    for item in policy.get("exclude") or []:
        if str(tags.get(str(item.get("key")))) == str(item.get("value")):
            return False
    if policy.get("pedestrian_access_rule") == "curated-v1":
        if str(tags.get("foot")) in {"no", "use_sidepath"}:
            return False
        if str(tags.get("access")) in {"no", "private", "customers", "destination"}:
            return False
        if highway == "cycleway" and str(tags.get("foot")) not in {"yes", "designated"}:
            return False
    return True


def _node_key(x: float, y: float) -> tuple[float, float]:
    return (float(x), float(y))


def _union_endpoints_within_tolerance(components: _UnionFind, endpoints: Sequence[tuple[float, float]]) -> list[tuple[tuple[float, float], tuple[float, float], float]]:
    """Join endpoints whose Euclidean distance is at most the stated tolerance.

    Grid rounding is not used. Two endpoints 0.04 m apart share a node when the
    tolerance is 0.05 m, even if they fall in different 0.05 m grid cells.
    """

    joined: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    unique = list(dict.fromkeys(endpoints))
    limit = ENDPOINT_TOLERANCE_M * ENDPOINT_TOLERANCE_M
    for index, left in enumerate(unique):
        for right in unique[index + 1 :]:
            dx = left[0] - right[0]
            dy = left[1] - right[1]
            if dx * dx + dy * dy <= limit:
                components.union(left, right)
                joined.append((left, right, math.sqrt(dx * dx + dy * dy)))
    return joined


def _load_normalized_features(package_root: Path, package: Mapping[str, Any]) -> list[dict[str, Any]]:
    for record in package.get("normalized_artifacts") or []:
        uri = str(record.get("uri") or "")
        if uri.endswith("osm-overpass-v5-epsg28992.geojson"):
            return list(json.loads((package_root / uri).read_text(encoding="utf-8"))["features"])
    raise SpatialPolicyError("frozen package has no normalized OSM geometry")


def _shortest_path_distance(
    adjacency: Mapping[tuple[float, float], Sequence[tuple[tuple[float, float], float]]],
    start: tuple[float, float],
    goal: tuple[float, float],
) -> float | None:
    if start == goal:
        return 0.0
    queue: list[tuple[float, tuple[float, float]]] = [(0.0, start)]
    best: dict[tuple[float, float], float] = {start: 0.0}
    while queue:
        distance, node = heapq.heappop(queue)
        if distance > best.get(node, float("inf")):
            continue
        if node == goal:
            return distance
        for neighbor, weight in adjacency.get(node, ()):
            candidate = distance + weight
            if candidate < best.get(neighbor, float("inf")):
                best[neighbor] = candidate
                heapq.heappush(queue, (candidate, neighbor))
    return None


def _validate_known_pair(
    known_pair: Mapping[str, Any] | None,
    origin_snaps: Mapping[str, tuple[bool, tuple[float, float] | None]],
    destination_snaps: Mapping[str, tuple[bool, tuple[float, float] | None]],
    adjacency: Mapping[tuple[float, float], Sequence[tuple[tuple[float, float], float]]],
) -> dict[str, Any] | None:
    if not known_pair:
        return None
    left_id = str(known_pair.get("origin_a") or known_pair.get("left_id"))
    right_id = str(known_pair.get("origin_b") or known_pair.get("right_id") or known_pair.get("destination_id"))
    left_map = origin_snaps
    right_map = destination_snaps if known_pair.get("pair_kind") == "origin_destination" else origin_snaps
    left_ok, left_key = left_map.get(left_id, (False, None))
    right_ok, right_key = right_map.get(right_id, (False, None))
    distance = _shortest_path_distance(adjacency, left_key, right_key) if left_ok and right_ok and left_key and right_key else None
    implementation_connected = distance is not None
    expected_connected = bool(known_pair.get("expected_connected"))
    expected_distance = known_pair.get("expected_distance_m")
    distance_matches = (
        isinstance(expected_distance, (int, float))
        and distance is not None
        and abs(float(distance) - float(expected_distance)) <= 0.05
    )
    return {
        "pair_kind": known_pair.get("pair_kind"),
        "origin_a": left_id,
        "origin_b": right_id if known_pair.get("pair_kind") != "origin_destination" else None,
        "destination_id": right_id if known_pair.get("pair_kind") == "origin_destination" else None,
        "expected_connected": expected_connected,
        "expected_distance_m": expected_distance,
        "implementation_connected": implementation_connected,
        "implementation_distance_m": distance,
        "matches_expected": implementation_connected == expected_connected and (distance_matches or not expected_connected),
        "role": "known_path_validation",
    }


def measure_network_policy(
    features: Sequence[Mapping[str, Any]],
    origins: Sequence[Mapping[str, Any]],
    destinations: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
    *,
    known_pair: Mapping[str, Any] | None = None,
    reference_features: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Measure one frozen-network policy. A failed known path is reported.

    Reference features are snapped only for known-path validation. They are not
    production origins or destinations.
    """

    from shapely.geometry import LineString, Point

    included: list[tuple[str, list[tuple[float, float]]]] = []
    points = {str(feature.get("id")): feature for feature in features if (feature.get("geometry") or {}).get("type") == "Point"}
    for feature in features:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "LineString":
            continue
        tags = _feature_tags(feature)
        if not _way_allowed(tags, policy):
            continue
        coordinates = [(float(point[0]), float(point[1])) for point in geometry.get("coordinates") or [] if isinstance(point, Sequence) and len(point) >= 2]
        if len(coordinates) >= 2:
            included.append((str(feature.get("id")), coordinates))
    components = _UnionFind()
    lines = []
    endpoints: list[tuple[float, float]] = []
    adjacency: dict[tuple[float, float], list[tuple[tuple[float, float], float]]] = {}

    def _link(left: tuple[float, float], right: tuple[float, float], weight: float) -> None:
        adjacency.setdefault(left, []).append((right, weight))
        adjacency.setdefault(right, []).append((left, weight))

    for _feature_id, coordinates in included:
        keys = [_node_key(x, y) for x, y in coordinates]
        for key in keys:
            components.add(key)
        for left, right, start, end in zip(keys, keys[1:], coordinates, coordinates[1:]):
            components.union(left, right)
            _link(left, right, math.hypot(end[0] - start[0], end[1] - start[1]))
        endpoints.append(keys[0])
        endpoints.append(keys[-1])
        lines.append(LineString(coordinates))
    for left, right, gap in _union_endpoints_within_tolerance(components, endpoints):
        _link(left, right, gap)
    way_count = len(included)
    edge_count = sum(max(0, len(coordinates) - 1) for _feature_id, coordinates in included)

    def _point_for(feature_id: str) -> Point | None:
        feature = points.get(feature_id)
        if feature is None:
            return None
        coordinates = (feature.get("geometry") or {}).get("coordinates")
        if not isinstance(coordinates, Sequence) or len(coordinates) < 2:
            return None
        return Point(float(coordinates[0]), float(coordinates[1]))

    def _snap(feature_id: str) -> tuple[bool, tuple[float, float] | None]:
        point = _point_for(feature_id)
        if point is None or not lines:
            return False, None
        best_index = min(range(len(lines)), key=lambda index: lines[index].distance(point))
        if lines[best_index].distance(point) > SNAP_DISTANCE_M:
            return False, None
        nearest = min(
            included[best_index][1],
            key=lambda vertex: (vertex[0] - point.x) ** 2 + (vertex[1] - point.y) ** 2,
        )
        return True, _node_key(nearest[0], nearest[1])

    for feature in reference_features or []:
        if (feature.get("geometry") or {}).get("type") == "Point" and feature.get("id"):
            points[str(feature.get("id"))] = feature
    origin_ids = [str(record.get("feature_id")) for record in origins if record.get("feature_id")]
    destination_ids = [str(record.get("feature_id")) for record in destinations if record.get("feature_id")]
    reference_ids = [str(feature.get("id")) for feature in reference_features or [] if feature.get("id")]
    leaked_reference_ids = [feature_id for feature_id in origin_ids if feature_id.startswith("reference-node/")]
    reference_ids = list(dict.fromkeys([*reference_ids, *leaked_reference_ids]))
    production_origin_ids = [feature_id for feature_id in origin_ids if feature_id not in set(reference_ids)]
    production_destination_ids = [feature_id for feature_id in destination_ids if not feature_id.startswith("reference-node/")]
    origin_snaps = {feature_id: _snap(feature_id) for feature_id in production_origin_ids}
    destination_snaps = {feature_id: _snap(feature_id) for feature_id in production_destination_ids}
    reference_snaps = {feature_id: _snap(feature_id) for feature_id in reference_ids}
    snapped_origins = [feature_id for feature_id, (ok, _key) in origin_snaps.items() if ok]
    snapped_destinations = [feature_id for feature_id, (ok, _key) in destination_snaps.items() if ok]
    diagnostic_origins = list(snapped_origins)
    known_path = {
        "rule": "Diagnostic only: lexicographic first and last snapped inventory origin, excluding known-path reference nodes. This is not the known-path validation.",
        "origin_a": None,
        "origin_b": None,
        "result": "NOT_SNAPPED",
        "connected": False,
    }
    if len(diagnostic_origins) >= 2:
        ordered = sorted(diagnostic_origins)
        origin_a, origin_b = ordered[0], ordered[-1]
        _ok_a, key_a = origin_snaps[origin_a]
        _ok_b, key_b = origin_snaps[origin_b]
        connected = key_a is not None and key_b is not None and components.find(key_a) == components.find(key_b)
        known_path = {
            "rule": known_path["rule"],
            "origin_a": origin_a,
            "origin_b": origin_b,
            "result": "CONNECTED" if connected else "NOT_CONNECTED",
            "connected": connected,
        }
    return {
        "way_count": way_count,
        "edge_count": edge_count,
        "connected_component_count": components.component_count() if included else 0,
        "origin_snapping_coverage": {
            "snap_distance_m": SNAP_DISTANCE_M,
            "snapped_count": len(snapped_origins),
            "total_count": len(production_origin_ids),
            "unsnapped_count": len(production_origin_ids) - len(snapped_origins),
        },
        "destination_snapping_coverage": {
            "snap_distance_m": SNAP_DISTANCE_M,
            "snapped_count": len(snapped_destinations),
            "total_count": len(production_destination_ids),
            "unsnapped_count": len(production_destination_ids) - len(snapped_destinations),
        },
        "known_path_check": known_path,
        "diagnostic_endpoint_connectivity": known_path,
        "known_path_validation": _validate_known_pair(known_pair, {**origin_snaps, **reference_snaps}, destination_snaps, adjacency),
        "snapped_origin_ids": snapped_origins,
        "snapped_destination_ids": snapped_destinations,
        "unsnapped_origin_ids": [feature_id for feature_id in production_origin_ids if feature_id not in set(snapped_origins)],
        "unsnapped_destination_ids": [feature_id for feature_id in production_destination_ids if feature_id not in set(snapped_destinations)],
        "origin_component_ids": {
            feature_id: str(components.find(key))
            for feature_id, (ok, key) in origin_snaps.items()
            if ok and key is not None
        },
        "measurement_status": "COMPUTED",
        "edge_rule": "An edge is one segment between consecutive vertices of an included way.",
        "component_rule": f"Endpoints within {ENDPOINT_TOLERANCE_M} m share a node. Components are unions of those nodes.",
    }


def _curated_network_policy(limitation: str) -> dict[str, Any]:
    return {
        "include_highways": list(CURATED_INCLUDE_HIGHWAYS),
        "excluded_highways": list(CURATED_EXCLUDED_HIGHWAYS),
        "exclude": [dict(item) for item in REQUIRED_NETWORK_EXCLUSIONS],
        "ambiguous_access_limitation": limitation,
        "allow_ambiguous_access": False,
        "pedestrian_access_rule": "curated-v1",
        "pedestrian_access_rule_text": _CURATED_ACCESS_RULE,
    }


def _policy_catalog(package: Mapping[str, Any]) -> list[dict[str, Any]]:
    packet = package.get("decision_packet") if isinstance(package.get("decision_packet"), Mapping) else {}
    options = (packet.get("options") or {}).get("pedestrian_network") if isinstance(packet.get("options"), Mapping) else None
    catalog = []
    if isinstance(options, list):
        for option in options:
            catalog.append({"option_id": option.get("option_id"), "network_policy": dict(option.get("network_policy") or {}), "selected": None})
    limitation = _network_limitation(package)
    catalog.append(
        {
            "option_id": "curated-ordinary-streets-and-footways",
            "network_policy": _curated_network_policy(limitation),
            "selected": None,
            "rule": _CURATED_ACCESS_RULE,
        }
    )
    return catalog


def build_spatial_policy_addendum(spatial_package_root: str | Path) -> dict[str, Any]:
    """Derive an unselected review addendum from a frozen spatial package."""

    root = Path(spatial_package_root)
    package = load_m2a03_spatial_package(root)
    origins = list((package.get("origin_inventory") or {}).get("records") or [])
    groceries = [
        record
        for record in ((package.get("grocery_inventory") or {}).get("records") or [])
        if isinstance(record, Mapping) and record.get("shop") in {"supermarket", "convenience"}
    ]
    classification = classify_spatial_origins(origins)
    origin_options = build_origin_denominator_options(origins)
    features = _load_normalized_features(root, package)
    policies = []
    for option in _policy_catalog(package):
        measured = measure_network_policy(features, origins, groceries, option["network_policy"])
        policies.append({**option, "metrics": measured})
    points = {str(feature.get("id")): feature for feature in features if (feature.get("geometry") or {}).get("type") == "Point"}
    map_features = []
    for record in origins:
        feature_id = str(record.get("feature_id"))
        source = points.get(feature_id)
        if source is None:
            continue
        map_features.append(
            {
                "type": "Feature",
                "id": feature_id,
                "geometry": source.get("geometry"),
                "properties": {
                    "feature_id": feature_id,
                    "public_transport": _origin_tag(record, "public_transport"),
                    "entrance": _origin_tag(record, "entrance"),
                    "name": (record.get("tags") or {}).get("name"),
                    "named_stop_key": _named_stop_key(record),
                },
            }
        )
    review_table = [
        {"dimension": "public_transport", "value": key, "count": bucket["count"]}
        for key, bucket in classification["by_public_transport"].items()
    ] + [
        {"dimension": "entrance", "value": key, "count": bucket["count"]}
        for key, bucket in classification["by_entrance"].items()
    ] + [
        {"dimension": "repeated_stop", "value": group["name"], "count": group["count"], "feature_ids": group["feature_ids"]}
        for group in classification["repeated_stop_groups"]
    ]
    packet = build_spatial_decision_packet(package)
    return {
        "schema_version": "m2-a03-spatial-decision-addendum-v1",
        "status": "UNSELECTED",
        "source_package_id": package.get("package_id"),
        "source_package_manifest_sha256": _manifest_sha256(root),
        "study_area_id": (package.get("study_area") or {}).get("id"),
        "weather_gate_status": "SEMANTICS_UNRESOLVED",
        "selected_origin_ids": None,
        "selected_destination_tags": None,
        "selected_network_policy": None,
        "approval_reason": None,
        "origin_classification": classification,
        "origin_options": origin_options,
        "destination_options": packet["options"]["destination_taxonomy"],
        "observed_destination_categories": packet["observed_destination_categories"],
        "grocery_tag_counts": packet["grocery_tag_counts"],
        "network_options": policies,
        "review_table": review_table,
        "origin_map": {"type": "FeatureCollection", "features": map_features, "crs": "EPSG:28992"},
        "limitations": packet["limitations"],
    }


def write_spatial_decision_addendum(spatial_package_root: str | Path, output_root: str | Path) -> Path:
    """Publish the addendum beside the frozen package, never inside it."""

    source = Path(spatial_package_root).resolve()
    target = Path(output_root) / ADDENDUM_DIRECTORY_NAME
    if source == target.resolve() or source in target.resolve().parents:
        raise SpatialPolicyError("decision addendum must not be written inside the frozen spatial package")
    addendum = build_spatial_policy_addendum(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = json.loads((target / "decision-addendum.json").read_text(encoding="utf-8"))
        if _analytical_addendum(existing) != _analytical_addendum(addendum):
            raise SpatialPolicyError("existing decision addendum does not match a rebuild from the frozen package")
        return target
    stage = target.with_name(f".{target.name}.stage")
    if stage.exists():
        import shutil
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    try:
        _write_json(stage / "decision-addendum.json", addendum)
        _write_json(stage / "origin-review-table.json", {"rows": addendum["review_table"]})
        _write_json(stage / "origin-map.geojson", addendum["origin_map"])
        _write_json(stage / "network-policy-metrics.json", {"options": addendum["network_options"]})
        files = [path for path in stage.rglob("*") if path.is_file() and path.name != "package-manifest.json"]
        _write_json(stage / "package-manifest.json", _manifest_for(stage, files))
        stage.rename(target)
    except Exception:
        import shutil
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def _analytical_addendum(addendum: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "classification": addendum.get("origin_classification"),
        "origin_option_ids": [option.get("option_id") for option in addendum.get("origin_options") or []],
        "origin_option_counts": [option.get("count") for option in addendum.get("origin_options") or []],
        "network_option_ids": [option.get("option_id") for option in addendum.get("network_options") or []],
        "network_metrics": [option.get("metrics") for option in addendum.get("network_options") or []],
    }


CLUSTER_DISTANCE_M = 150.0
REPAIRED_ADDENDUM_DIRECTORY_NAME = "spatial-r01-decision-addendum-r02"
REPAIRED_ADDENDUM_SCHEMA = "m2-a03-spatial-decision-addendum-r02-v1"
_MUNICIPALITY_PREFIXES = ("rotterdam,", "schiedam,")


def normalize_stop_name(name: str) -> str:
    """Drop a leading Rotterdam or Schiedam municipality prefix from a stop name."""

    text = " ".join(name.strip().casefold().split())
    for prefix in _MUNICIPALITY_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text


def _cluster_members(
    members: Sequence[tuple[str, float, float, Mapping[str, Any]]],
    *,
    threshold_m: float,
) -> list[list[tuple[str, float, float, Mapping[str, Any]]]]:
    """Agglomerate only merges whose combined diameter stays within the threshold."""

    clusters: list[list[tuple[str, float, float, Mapping[str, Any]]]] = [[member] for member in members]
    while True:
        best: tuple[float, int, int] | None = None
        for left in range(len(clusters)):
            for right in range(left + 1, len(clusters)):
                diameter = _max_pairwise_distance([*clusters[left], *clusters[right]])
                if diameter <= threshold_m and (best is None or (diameter, left, right) < best):
                    best = (diameter, left, right)
        if best is None:
            break
        _diameter, left, right = best
        clusters[left].extend(clusters.pop(right))
    return clusters


def _max_pairwise_distance(members: Sequence[tuple[str, float, float, Mapping[str, Any]]]) -> float:
    farthest = 0.0
    for left in range(len(members)):
        for right in range(left + 1, len(members)):
            farthest = max(farthest, math.hypot(members[left][1] - members[right][1], members[left][2] - members[right][2]))
    return farthest


def build_repaired_origin_options(
    records: Sequence[Mapping[str, Any]],
    coordinates: Mapping[str, tuple[float, float]],
) -> dict[str, Any]:
    """Normalize municipality prefixes and cluster same names only within 150 m."""

    exact = build_origin_denominator_options(records)
    for option in exact:
        if option["option_id"] == "deduplicated-named-stop-places":
            option["option_id"] = "exact-name-only-deduplicated-stop-places"
            option["rule"] = "Exact-name-only. " + option["rule"]
    by_name: dict[str, list[tuple[str, float, float, Mapping[str, Any]]]] = {}
    unpositioned: list[str] = []
    for record in records:
        feature_id = str(record.get("feature_id") or "")
        tags = record.get("tags") if isinstance(record.get("tags"), Mapping) else {}
        raw_name = tags.get("name") if isinstance(tags.get("name"), str) else ""
        point = coordinates.get(feature_id)
        if not raw_name.strip() or point is None or _origin_tag(record, "public_transport") not in NAMED_STOP_ROLES:
            if feature_id:
                unpositioned.append(feature_id)
            continue
        by_name.setdefault(normalize_stop_name(raw_name), []).append((feature_id, point[0], point[1], record))
    clusters = []
    ambiguous = []
    representatives: list[str] = []
    max_within = 0.0
    for name, members in sorted(by_name.items()):
        pieces = _cluster_members(members, threshold_m=CLUSTER_DISTANCE_M)
        if len(pieces) > 1:
            ambiguous.append(
                {
                    "normalized_name": name,
                    "cluster_count": len(pieces),
                    "member_ids": [member[0] for member in members],
                    "reason": f"Same normalized name is split because the cluster diameter would exceed {CLUSTER_DISTANCE_M} m. Distant records are not merged.",
                }
            )
        for piece in pieces:
            distance = _max_pairwise_distance(piece)
            max_within = max(max_within, distance)
            representative = _representative_id([member[3] for member in piece])
            representatives.append(representative)
            clusters.append(
                {
                    "normalized_name": name,
                    "count": len(piece),
                    "member_ids": [member[0] for member in piece],
                    "representative_id": representative,
                    "maximum_within_cluster_distance_m": distance,
                }
            )
    option = {
        "option_id": "clustered-normalized-name-places",
        "rule": f"Normalize a leading 'Rotterdam,' or 'Schiedam,' prefix, then keep a same-name cluster only when its diameter is at most {CLUSTER_DISTANCE_M} m. A chain is split rather than merged through intermediate points. One representative per cluster prefers station, then stop_position, then platform, then the lowest feature id. Records without a positioned named public-transport role stay listed individually.",
        "count": len(representatives) + len(unpositioned),
        "member_ids": representatives + unpositioned,
        "cluster_count": len(clusters),
        "representative_rule": "station, then stop_position, then platform, then lowest feature id",
        "maximum_within_cluster_distance_m": max_within,
        "cluster_distance_m": CLUSTER_DISTANCE_M,
        "unresolved_ambiguous_clusters": ambiguous,
        "clusters": clusters,
        "limitations": [
            "Distant same-name records are not merged.",
            "Names that remain different after municipality-prefix removal stay separate.",
        ],
        "selected": None,
    }
    return {"options": [option, *exact], "clusters": clusters, "unresolved_ambiguous_clusters": ambiguous}


def _reference_pair(features: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    for feature in features:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "LineString" or not _way_allowed(_feature_tags(feature), policy):
            continue
        coordinates = [
            (float(point[0]), float(point[1]))
            for point in geometry.get("coordinates") or []
            if isinstance(point, Sequence) and len(point) >= 2
        ]
        if len(coordinates) != 2:
            continue
        distance = math.hypot(coordinates[1][0] - coordinates[0][0], coordinates[1][1] - coordinates[0][1])
        if distance <= 1:
            continue
        way_id = str(feature.get("id"))
        origin_a = f"reference-node/{way_id}/start"
        origin_b = f"reference-node/{way_id}/end"
        pair = {
            "pair_kind": "origin_origin",
            "origin_a": origin_a,
            "origin_b": origin_b,
            "expected_connected": True,
            "expected_distance_m": distance,
            "reference_way_id": way_id,
            "reference_coordinates": coordinates,
            "independent_distance_rule": "Euclidean length of the predeclared two-vertex way, calculated with math.hypot and not taken from the routed result.",
        }
        extras = [
            {"type": "Feature", "id": origin_a, "geometry": {"type": "Point", "coordinates": list(coordinates[0])}, "properties": {"tags": {}}},
            {"type": "Feature", "id": origin_b, "geometry": {"type": "Point", "coordinates": list(coordinates[1])}, "properties": {"tags": {}}},
        ]
        return pair, extras
    raise SpatialPolicyError("no two-vertex way is available for a known-path reference")


def _denominator_coverage(option: Mapping[str, Any], metrics: Mapping[str, Any]) -> dict[str, Any]:
    members = [str(feature_id) for feature_id in option.get("member_ids") or []]
    snapped = set(metrics.get("snapped_origin_ids") or [])
    components = metrics.get("origin_component_ids") or {}
    snapped_members = [feature_id for feature_id in members if feature_id in snapped]
    component_counts: dict[str, int] = {}
    for feature_id in snapped_members:
        component = str(components.get(feature_id))
        component_counts[component] = component_counts.get(component, 0) + 1
    largest = max(component_counts.values()) if component_counts else 0
    return {
        "origin_option_id": option.get("option_id"),
        "total_count": len(members),
        "snapped_count": len(snapped_members),
        "largest_component_count": largest,
        "largest_component_coverage": (largest / len(members)) if members else None,
    }


def build_repaired_spatial_policy_addendum(
    spatial_package_root: str | Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the r02 unselected review addendum from a frozen spatial package."""

    root = Path(spatial_package_root)
    package = load_m2a03_spatial_package(root)
    origins = list((package.get("origin_inventory") or {}).get("records") or [])
    features = _load_normalized_features(root, package)
    coordinates = {
        str(feature.get("id")): (float(feature["geometry"]["coordinates"][0]), float(feature["geometry"]["coordinates"][1]))
        for feature in features
        if (feature.get("geometry") or {}).get("type") == "Point"
    }
    origin_report = build_repaired_origin_options(origins, coordinates)
    packet = build_spatial_decision_packet(package)
    policies = []
    for option in _policy_catalog(package):
        pair, extras = _reference_pair(features, option["network_policy"])
        measured = measure_network_policy([*features, *extras], [*origins, {"feature_id": pair["origin_a"], "tags": {}}, {"feature_id": pair["origin_b"], "tags": {}}], [], option["network_policy"], known_pair=pair)
        policies.append({**option, "metrics": measured, "selected": None})
    curated = next(option for option in policies if option["option_id"] == "curated-ordinary-streets-and-footways")
    coverage = [_denominator_coverage(option, curated["metrics"]) for option in origin_report["options"]]
    implementation = Path(__file__).resolve()
    source_hashes = {
        "package_manifest": _manifest_sha256(root),
        "normalized_osm": sha256_file(root / "sources/normalized/osm-overpass-v5-epsg28992.geojson"),
        "origin_inventory": sha256_file(root / "origin-candidate-inventory.json"),
    }
    return {
        "schema_version": REPAIRED_ADDENDUM_SCHEMA,
        "algorithm_version": "spatial-decision-addendum-r02",
        "status": "UNSELECTED",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "source_package_id": package.get("package_id"),
        "source_package_manifest_sha256": source_hashes["package_manifest"],
        "source_artifact_hashes": source_hashes,
        "study_area_id": (package.get("study_area") or {}).get("id"),
        "weather_gate_status": "SEMANTICS_UNRESOLVED",
        "snap_distance_m": SNAP_DISTANCE_M,
        "topology_tolerance_m": ENDPOINT_TOLERANCE_M,
        "implementation_file_sha256": sha256_file(implementation),
        "selected_origin_ids": None,
        "selected_destination_tags": None,
        "selected_network_policy": None,
        "approval_reason": None,
        "origin_options": origin_report["options"],
        "destination_options": packet["options"]["destination_taxonomy"],
        "observed_destination_categories": packet["observed_destination_categories"],
        "grocery_tag_counts": packet["grocery_tag_counts"],
        "network_options": policies,
        "denominator_coverage": coverage,
        "curated_unsnapped_origin_ids": [
            feature_id
            for feature_id in curated["metrics"].get("unsnapped_origin_ids") or []
            if not str(feature_id).startswith("reference-node/")
        ],
        "cluster_count": next(option["cluster_count"] for option in origin_report["options"] if option["option_id"] == "clustered-normalized-name-places"),
        "unresolved_ambiguous_clusters": origin_report["unresolved_ambiguous_clusters"],
        "review_table": [
            {"dimension": "cluster", "value": cluster["normalized_name"], "count": cluster["count"], "feature_ids": cluster["member_ids"], "maximum_within_cluster_distance_m": cluster["maximum_within_cluster_distance_m"]}
            for cluster in origin_report["clusters"]
        ],
        "origin_map": {
            "type": "FeatureCollection",
            "crs": "EPSG:28992",
            "features": [
                {
                    "type": "Feature",
                    "id": feature_id,
                    "geometry": {"type": "Point", "coordinates": [point[0], point[1]]},
                    "properties": {"feature_id": feature_id, "normalized_name": normalize_stop_name(str((record.get("tags") or {}).get("name") or ""))},
                }
                for record in origins
                for feature_id, point in [(str(record.get("feature_id")), coordinates.get(str(record.get("feature_id"))))]
                if point is not None
            ],
        },
    }


def _analytical_repaired_addendum(addendum: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "origin_options": [
            {key: option.get(key) for key in ("option_id", "count", "member_ids", "cluster_count", "maximum_within_cluster_distance_m")}
            for option in addendum.get("origin_options") or []
        ],
        "network": [
            {
                "option_id": option.get("option_id"),
                "metrics": {
                    key: (option.get("metrics") or {}).get(key)
                    for key in ("way_count", "edge_count", "connected_component_count", "known_path_validation", "unsnapped_origin_ids")
                },
            }
            for option in addendum.get("network_options") or []
        ],
        "thresholds": {
            "snap_distance_m": addendum.get("snap_distance_m"),
            "topology_tolerance_m": addendum.get("topology_tolerance_m"),
        },
    }


def write_repaired_spatial_decision_addendum(spatial_package_root: str | Path, output_root: str | Path) -> Path:
    source = Path(spatial_package_root).resolve()
    target = Path(output_root) / REPAIRED_ADDENDUM_DIRECTORY_NAME
    if source == target.resolve() or source in target.resolve().parents or "spatial-r01-decision-addendum" == target.name:
        raise SpatialPolicyError("repaired addendum must be a new directory outside the frozen packages")
    addendum = build_repaired_spatial_policy_addendum(source)
    if target.exists():
        existing = json.loads((target / "decision-addendum.json").read_text(encoding="utf-8"))
        if _analytical_repaired_addendum(existing) != _analytical_repaired_addendum(addendum):
            raise SpatialPolicyError("existing repaired addendum does not match a rebuild")
        return target
    stage = target.with_name(f".{target.name}.stage")
    if stage.exists():
        import shutil
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    try:
        _write_json(stage / "decision-addendum.json", addendum)
        _write_json(stage / "origin-review-table.json", {"rows": addendum["review_table"], "ambiguous_clusters": addendum["unresolved_ambiguous_clusters"]})
        _write_json(stage / "origin-map.geojson", addendum["origin_map"])
        _write_json(stage / "network-policy-metrics.json", {"options": addendum["network_options"], "denominator_coverage": addendum["denominator_coverage"]})
        files = [path for path in stage.rglob("*") if path.is_file() and path.name != "package-manifest.json"]
        _write_json(stage / "package-manifest.json", _manifest_for(stage, files))
        stage.rename(target)
    except Exception:
        import shutil
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def verify_repaired_spatial_addendum(addendum_root: str | Path, spatial_package_root: str | Path) -> dict[str, Any]:
    """Check every addendum byte and the parent spatial-r01 manifest reference."""

    root = Path(addendum_root)
    manifest_path = root / "package-manifest.json"
    if not manifest_path.is_file():
        raise SpatialPolicyError("repaired addendum package-manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        path = root / entry["path"]
        if not path.is_file():
            raise SpatialPolicyError(f"missing addendum file: {entry['path']}")
        data = path.read_bytes()
        if sha256_bytes(data) != entry.get("sha256") or len(data) != entry.get("size_bytes"):
            raise SpatialPolicyError(f"addendum file integrity mismatch: {entry['path']}")
    decision_path = root / "decision-addendum.json"
    if not decision_path.is_file():
        raise SpatialPolicyError("missing parent decision addendum")
    addendum = json.loads(decision_path.read_text(encoding="utf-8"))
    parent_manifest = Path(spatial_package_root) / "package-manifest.json"
    if not parent_manifest.is_file():
        raise SpatialPolicyError("missing parent spatial package manifest")
    parent_hash = sha256_file(parent_manifest)
    if addendum.get("source_package_manifest_sha256") != parent_hash:
        raise SpatialPolicyError("addendum parent manifest hash does not match frozen spatial-r01")
    load_m2a03_spatial_package(spatial_package_root)
    return {"status": "PASS", "parent_manifest_sha256": parent_hash, "schema_version": addendum.get("schema_version")}


R03_DIRECTORY_NAME = "spatial-r01-decision-addendum-r03"
R03_SCHEMA = "m2-a03-spatial-decision-addendum-r03-v1"
R03_EXPECTED_PATHS = (
    "decision-addendum.json",
    "network-policy-metrics.json",
    "origin-map.geojson",
    "origin-review-table.json",
)
_R03_LIMITATIONS = (
    "Production origin snapping counts only observed origin-inventory records.",
    "Synthetic known-path reference points are excluded from origin totals, snapped counts, unsnapped IDs, denominator coverage, and component coverage.",
    "Destination measurements include observed supermarket and convenience records only. grocery is not selectable.",
    "The one-edge known path is a basic edge control. The junction path is a separate multi-edge control and is not a production origin.",
    "Weather method remains SEMANTICS_UNRESOLVED and blocks Week 6 only.",
)
_FROZEN_DIRECTORY_NAMES = {
    "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01",
    "spatial-r01-decision-addendum",
    "spatial-r01-decision-addendum-r02",
    "run-study-area-rotterdam-m4h-pilot-project-v5-r03",
}


def _observed_destination_records(package: Mapping[str, Any]) -> list[dict[str, Any]]:
    inventory = package.get("grocery_inventory") if isinstance(package.get("grocery_inventory"), Mapping) else {}
    records = []
    for record in inventory.get("records") or []:
        if isinstance(record, Mapping) and record.get("shop") in {"supermarket", "convenience"} and record.get("feature_id"):
            records.append(dict(record))
    return records


def _inventory_totals(origins: Sequence[Mapping[str, Any]], destinations: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "observed_origins": len(origins),
        "observed_destinations": len(destinations),
        "supermarket": sum(1 for record in destinations if record.get("shop") == "supermarket"),
        "convenience": sum(1 for record in destinations if record.get("shop") == "convenience"),
    }


def _destination_option_coverage(
    options: Sequence[Mapping[str, Any]],
    destinations: Sequence[Mapping[str, Any]],
    metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    snapped = set(metrics.get("snapped_destination_ids") or [])
    coverage = []
    for option in options:
        tags = {str(tag) for tag in option.get("destination_tags") or []}
        members = [str(record["feature_id"]) for record in destinations if str(record.get("shop")) in tags]
        snapped_members = [feature_id for feature_id in members if feature_id in snapped]
        coverage.append(
            {
                "destination_option_id": option.get("option_id"),
                "destination_tags": [str(tag) for tag in option.get("destination_tags") or []],
                "snap_distance_m": SNAP_DISTANCE_M,
                "total_count": len(members),
                "snapped_count": len(snapped_members),
                "unsnapped_count": len(members) - len(snapped_members),
            }
        )
    return coverage


def _junction_known_path() -> dict[str, Any]:
    """Fixed two-way path through one shared vertex. Distance is the sum of the way lengths."""

    east = ((0.0, 0.0), (100.0, 0.0))
    north = ((100.0, 0.0), (100.0, 40.0))
    expected = math.hypot(east[1][0] - east[0][0], east[1][1] - east[0][1]) + math.hypot(
        north[1][0] - north[0][0], north[1][1] - north[0][1]
    )
    start = "reference-node/way/junction-east/start"
    end = "reference-node/way/junction-north/end"
    features = [
        {
            "type": "Feature",
            "id": "way/junction-east",
            "geometry": {"type": "LineString", "coordinates": [list(point) for point in east]},
            "properties": {"tags": {"highway": "footway"}},
        },
        {
            "type": "Feature",
            "id": "way/junction-north",
            "geometry": {"type": "LineString", "coordinates": [list(point) for point in north]},
            "properties": {"tags": {"highway": "footway"}},
        },
    ]
    references = [
        {"type": "Feature", "id": start, "geometry": {"type": "Point", "coordinates": list(east[0])}, "properties": {"tags": {}}},
        {"type": "Feature", "id": end, "geometry": {"type": "Point", "coordinates": list(north[1])}, "properties": {"tags": {}}},
    ]
    pair = {"pair_kind": "origin_origin", "origin_a": start, "origin_b": end, "expected_connected": True, "expected_distance_m": expected}
    measured = measure_network_policy(
        features,
        [],
        [],
        {"include_highways": ["footway"], "exclude": []},
        known_pair=pair,
        reference_features=references,
    )
    validation = measured["known_path_validation"]
    return {
        "role": "multi_edge_junction_control",
        "way_ids": ["way/junction-east", "way/junction-north"],
        "vertex_ids": [start, "way/junction-east/end", end],
        "junction_coordinates": [100.0, 0.0],
        "expected_connected": True,
        "expected_distance_m": expected,
        "independent_distance_rule": "Sum of math.hypot lengths of way/junction-east and way/junction-north. The ways share (100, 0).",
        "implementation_connected": validation["implementation_connected"],
        "implementation_distance_m": validation["implementation_distance_m"],
        "matches_expected": validation["matches_expected"],
        "excluded_from_production_counts": True,
    }


def build_spatial_decision_addendum_r03(
    spatial_package_root: str | Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the unselected r03 addendum from a frozen spatial package."""

    root = Path(spatial_package_root)
    package = load_m2a03_spatial_package(root)
    origins = list((package.get("origin_inventory") or {}).get("records") or [])
    destinations = _observed_destination_records(package)
    features = _load_normalized_features(root, package)
    coordinates = {
        str(feature.get("id")): (float(feature["geometry"]["coordinates"][0]), float(feature["geometry"]["coordinates"][1]))
        for feature in features
        if (feature.get("geometry") or {}).get("type") == "Point"
    }
    origin_report = build_repaired_origin_options(origins, coordinates)
    packet = build_spatial_decision_packet(package)
    policies = []
    for option in _policy_catalog(package):
        pair, references = _reference_pair(features, option["network_policy"])
        measured = measure_network_policy(
            features,
            origins,
            destinations,
            option["network_policy"],
            known_pair=pair,
            reference_features=references,
        )
        policies.append(
            {
                **option,
                "metrics": measured,
                "destination_option_coverage": _destination_option_coverage(packet["options"]["destination_taxonomy"], destinations, measured),
                "selected": None,
            }
        )
    curated = next(item for item in policies if item["option_id"] == "curated-ordinary-streets-and-footways")
    implementation = Path(__file__).resolve()
    source_hashes = {
        "package_manifest": _manifest_sha256(root),
        "normalized_osm": sha256_file(root / "sources/normalized/osm-overpass-v5-epsg28992.geojson"),
        "origin_inventory": sha256_file(root / "origin-candidate-inventory.json"),
    }
    return {
        "schema_version": R03_SCHEMA,
        "algorithm_version": "spatial-decision-addendum-r03",
        "status": "UNSELECTED",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "source_package_id": package.get("package_id"),
        "source_package_manifest_sha256": source_hashes["package_manifest"],
        "source_artifact_hashes": source_hashes,
        "study_area_id": (package.get("study_area") or {}).get("id"),
        "weather_gate_status": "SEMANTICS_UNRESOLVED",
        "snap_distance_m": SNAP_DISTANCE_M,
        "topology_tolerance_m": ENDPOINT_TOLERANCE_M,
        "implementation_file_sha256": sha256_file(implementation),
        "selected_origin_ids": None,
        "selected_destination_tags": None,
        "selected_network_policy": None,
        "approval_reason": None,
        "inventory_totals": _inventory_totals(origins, destinations),
        "origin_options": origin_report["options"],
        "destination_options": packet["options"]["destination_taxonomy"],
        "observed_destination_categories": packet["observed_destination_categories"],
        "grocery_tag_counts": packet["grocery_tag_counts"],
        "network_options": policies,
        "denominator_coverage": [_denominator_coverage(option, curated["metrics"]) for option in origin_report["options"]],
        "curated_unsnapped_origin_ids": list(curated["metrics"].get("unsnapped_origin_ids") or []),
        "cluster_count": next(option["cluster_count"] for option in origin_report["options"] if option["option_id"] == "clustered-normalized-name-places"),
        "unresolved_ambiguous_clusters": origin_report["unresolved_ambiguous_clusters"],
        "junction_known_path": _junction_known_path(),
        "limitations": list(_R03_LIMITATIONS),
        "review_table": [
            {
                "dimension": "cluster",
                "value": cluster["normalized_name"],
                "count": cluster["count"],
                "feature_ids": cluster["member_ids"],
                "maximum_within_cluster_distance_m": cluster["maximum_within_cluster_distance_m"],
            }
            for cluster in origin_report["clusters"]
        ],
        "origin_map": {
            "type": "FeatureCollection",
            "crs": "EPSG:28992",
            "features": [
                {
                    "type": "Feature",
                    "id": feature_id,
                    "geometry": {"type": "Point", "coordinates": [point[0], point[1]]},
                    "properties": {"feature_id": feature_id, "normalized_name": normalize_stop_name(str((record.get("tags") or {}).get("name") or ""))},
                }
                for record in origins
                for feature_id, point in [(str(record.get("feature_id")), coordinates.get(str(record.get("feature_id"))))]
                if point is not None
            ],
        },
    }


_SELECTION_FIELDS = frozenset(
    {
        "selected",
        "selected_origin_ids",
        "selected_destination_tags",
        "selected_network_policy",
        "approval_reason",
        "approved_by",
    }
)


def _reject_non_null_selections(value: Any, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _SELECTION_FIELDS and item is not None:
                raise SpatialPolicyError(f"r03 selection field must be null: {path}{key}")
            _reject_non_null_selections(item, f"{path}{key}.")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_non_null_selections(item, f"{path}[{index}].")


def _analytical_r03(addendum: Mapping[str, Any]) -> dict[str, Any]:
    """Everything except the generation clock. Selection fields stay in the compare."""

    comparable = dict(addendum)
    comparable.pop("generated_at", None)
    return comparable


def _reject_frozen_output(target: Path) -> None:
    if target.name in _FROZEN_DIRECTORY_NAMES or any(parent.name in _FROZEN_DIRECTORY_NAMES for parent in target.resolve().parents):
        raise SpatialPolicyError("r03 must be a new directory outside the frozen spatial packages")


def write_spatial_decision_addendum_r03(spatial_package_root: str | Path, output_root: str | Path) -> Path:
    source = Path(spatial_package_root).resolve()
    target = Path(output_root) / R03_DIRECTORY_NAME
    _reject_frozen_output(target)
    if target.name != R03_DIRECTORY_NAME:
        raise SpatialPolicyError("r03 directory name is fixed")
    addendum = build_spatial_decision_addendum_r03(source)
    if target.exists():
        existing = json.loads((target / "decision-addendum.json").read_text(encoding="utf-8"))
        if _analytical_r03(existing) != _analytical_r03(addendum):
            raise SpatialPolicyError("existing r03 addendum does not match a rebuild")
        return target
    stage = target.with_name(f".{target.name}.stage")
    if stage.exists():
        import shutil
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    try:
        _write_json(stage / "decision-addendum.json", addendum)
        _write_json(stage / "origin-review-table.json", {"rows": addendum["review_table"], "ambiguous_clusters": addendum["unresolved_ambiguous_clusters"]})
        _write_json(stage / "origin-map.geojson", addendum["origin_map"])
        _write_json(
            stage / "network-policy-metrics.json",
            {
                "options": addendum["network_options"],
                "denominator_coverage": addendum["denominator_coverage"],
                "inventory_totals": addendum["inventory_totals"],
                "junction_known_path": addendum["junction_known_path"],
            },
        )
        files = [path for path in stage.rglob("*") if path.is_file() and path.name != "package-manifest.json"]
        _write_json(stage / "package-manifest.json", _manifest_for(stage, files))
        stage.rename(target)
    except Exception:
        import shutil
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def verify_spatial_decision_addendum_r03(addendum_root: str | Path, spatial_package_root: str | Path) -> dict[str, Any]:
    """Fail closed unless r03 bytes, schema, selections, hashes, and rebuilt analysis agree."""

    root = Path(addendum_root)
    manifest_path = root / "package-manifest.json"
    if not manifest_path.is_file():
        raise SpatialPolicyError("r03 package-manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise SpatialPolicyError("r03 manifest files are missing")
    paths = [entry.get("path") if isinstance(entry, Mapping) else None for entry in entries]
    if any(not isinstance(path, str) for path in paths) or len(paths) != len(set(paths)):
        raise SpatialPolicyError("duplicate manifest path")
    disk = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if set(R03_EXPECTED_PATHS) - disk:
        raise SpatialPolicyError("missing addendum file")
    if disk - (set(R03_EXPECTED_PATHS) | {"package-manifest.json"}):
        raise SpatialPolicyError("unexpected addendum file")
    if set(paths) != set(R03_EXPECTED_PATHS):
        raise SpatialPolicyError("unexpected manifest path")
    for entry in entries:
        path = root / entry["path"]
        if not path.is_file():
            raise SpatialPolicyError(f"missing addendum file: {entry['path']}")
        data = path.read_bytes()
        if sha256_bytes(data) != entry.get("sha256") or len(data) != entry.get("size_bytes"):
            raise SpatialPolicyError(f"addendum file integrity mismatch: {entry['path']}")
    addendum = json.loads((root / "decision-addendum.json").read_text(encoding="utf-8"))
    if addendum.get("schema_version") != R03_SCHEMA:
        raise SpatialPolicyError("r03 schema is required")
    if addendum.get("status") != "UNSELECTED":
        raise SpatialPolicyError("r03 must stay unselected with null approval fields")
    _reject_non_null_selections(addendum)
    parent = Path(spatial_package_root)
    expected_hashes = {
        "package_manifest": sha256_file(parent / "package-manifest.json"),
        "normalized_osm": sha256_file(parent / "sources/normalized/osm-overpass-v5-epsg28992.geojson"),
        "origin_inventory": sha256_file(parent / "origin-candidate-inventory.json"),
    }
    if addendum.get("source_artifact_hashes") != expected_hashes or addendum.get("source_package_manifest_sha256") != expected_hashes["package_manifest"]:
        raise SpatialPolicyError("r03 source artifact hash does not match frozen spatial-r01")
    if addendum.get("implementation_file_sha256") != sha256_file(Path(__file__).resolve()):
        raise SpatialPolicyError("r03 implementation file hash does not match")
    sidecar = json.loads((root / "network-policy-metrics.json").read_text(encoding="utf-8"))
    if sidecar.get("options") != addendum.get("network_options") or sidecar.get("junction_known_path") != addendum.get("junction_known_path"):
        raise SpatialPolicyError("r03 network sidecar does not match the decision addendum")
    review = json.loads((root / "origin-review-table.json").read_text(encoding="utf-8"))
    if review.get("rows") != addendum.get("review_table") or review.get("ambiguous_clusters") != addendum.get("unresolved_ambiguous_clusters"):
        raise SpatialPolicyError("r03 origin review sidecar does not match the decision addendum")
    origin_map = json.loads((root / "origin-map.geojson").read_text(encoding="utf-8"))
    if origin_map != addendum.get("origin_map"):
        raise SpatialPolicyError("r03 origin map sidecar does not match the decision addendum")
    rebuilt = build_spatial_decision_addendum_r03(parent, generated_at=str(addendum.get("generated_at") or ""))
    if _analytical_r03(rebuilt) != _analytical_r03(addendum):
        raise SpatialPolicyError("r03 analytical content does not match a rebuild from frozen spatial-r01")
    load_m2a03_spatial_package(parent)
    return {"status": "PASS", "schema_version": R03_SCHEMA, "parent_manifest_sha256": expected_hashes["package_manifest"]}


def _addendum_schema(decision_addendum: str | Path) -> str:
    path = Path(decision_addendum) / "decision-addendum.json"
    if not path.is_file():
        raise SpatialPolicyError("decision addendum schema is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpatialPolicyError("decision addendum schema is missing") from exc
    schema = payload.get("schema_version") if isinstance(payload, Mapping) else None
    if not isinstance(schema, str) or not schema.strip():
        raise SpatialPolicyError("decision addendum schema is missing")
    return schema


def verify_addendum_for_approval(decision_addendum: str | Path, spatial_package_root: str | Path) -> dict[str, Any]:
    """Dispatch the verifier that matches the addendum schema. r03 never uses the weaker check."""

    schema = _addendum_schema(decision_addendum)
    if schema == R03_SCHEMA:
        return verify_spatial_decision_addendum_r03(decision_addendum, spatial_package_root)
    if schema == REPAIRED_ADDENDUM_SCHEMA:
        return verify_repaired_spatial_addendum(decision_addendum, spatial_package_root)
    raise SpatialPolicyError(f"unsupported decision addendum schema: {schema}")


def approve_spatial_addendum_options(
    database: str | Path,
    decision_addendum: str | Path,
    spatial_package_root: str | Path,
    output_root: str | Path,
    *,
    actor: str,
    reason: str,
    origin_option_id: str,
    destination_option_id: str,
    network_option_id: str,
    supplied_origin_ids: Sequence[str] | None = None,
    supplied_destination_tags: Sequence[str] | None = None,
    supplied_network_policy: Mapping[str, Any] | None = None,
    approved_at: datetime | str | None = None,
    commit_hook: Any | None = None,
    actor_kind: ActorKind | str | None = None,
    actor_session_id: str | None = None,
    decision_key: str | None = None,
    decision_key_path: str | Path | None = None,
) -> Path:
    """Approve only the exact member IDs and policy JSON stored on the addendum options."""

    verified = verify_addendum_for_approval(decision_addendum, spatial_package_root)
    addendum = json.loads((Path(decision_addendum) / "decision-addendum.json").read_text(encoding="utf-8"))
    if verified["parent_manifest_sha256"] != addendum.get("source_package_manifest_sha256"):
        raise SpatialPolicyError("addendum parent manifest hash does not match frozen spatial-r01")
    origin = next((option for option in addendum["origin_options"] if option.get("option_id") == origin_option_id), None)
    destination = next((option for option in addendum["destination_options"] if option.get("option_id") == destination_option_id), None)
    network = next((option for option in addendum["network_options"] if option.get("option_id") == network_option_id), None)
    if origin is None or destination is None or network is None:
        raise SpatialPolicyError("mismatched option id")
    origin_ids = [str(feature_id) for feature_id in origin["member_ids"]]
    destination_tags = [str(tag) for tag in destination.get("destination_tags") or destination.get("cli_destination_tags") or []]
    network_policy = dict(network["network_policy"])
    if supplied_origin_ids is not None and [str(value) for value in supplied_origin_ids] != origin_ids:
        raise SpatialPolicyError("caller-supplied origin IDs differ from the selected option")
    if supplied_destination_tags is not None and [str(value) for value in supplied_destination_tags] != destination_tags:
        raise SpatialPolicyError("caller-supplied destination tags differ from the selected option")
    if supplied_network_policy is not None and dict(supplied_network_policy) != network_policy:
        raise SpatialPolicyError("caller-supplied network policy differs from the selected option")
    binding = {
        "decision_addendum_manifest_sha256": sha256_file(Path(decision_addendum) / "package-manifest.json"),
        "origin_option_id": origin_option_id,
        "destination_option_id": destination_option_id,
        "network_option_id": network_option_id,
    }
    return freeze_m2a03_spatial_policies(
        database,
        spatial_package_root,
        output_root,
        actor=actor,
        reason=reason,
        origin_ids=origin_ids,
        destination_tags=destination_tags,
        network_policy=network_policy,
        approved_at=approved_at,
        commit_hook=commit_hook,
        decision_binding=binding,
        actor_kind=actor_kind,
        actor_session_id=actor_session_id,
        decision_key=decision_key,
        decision_key_path=decision_key_path,
    )


__all__ = [
    "ACCEPTED_STATUS",
    "ACCEPTANCE_SCHEMA",
    "ADDENDUM_DIRECTORY_NAME",
    "ALLOWED_DESTINATION_TAGS",
    "CURATED_EXCLUDED_HIGHWAYS",
    "REQUIRED_NETWORK_EXCLUSIONS",
    "SpatialPolicyError",
    "CLUSTER_DISTANCE_M",
    "REPAIRED_ADDENDUM_DIRECTORY_NAME",
    "R03_DIRECTORY_NAME",
    "R03_SCHEMA",
    "approve_spatial_addendum_options",
    "authorize_week3_entry",
    "authorize_week3_from_persisted_state",
    "authorize_week6_entry",
    "build_origin_denominator_options",
    "build_repaired_origin_options",
    "build_repaired_spatial_policy_addendum",
    "build_spatial_decision_packet",
    "build_spatial_policy_addendum",
    "classify_spatial_origins",
    "freeze_m2a03_spatial_policies",
    "load_spatial_acceptance_package",
    "measure_network_policy",
    "validate_spatial_policy_selection",
    "build_spatial_decision_addendum_r03",
    "verify_addendum_for_approval",
    "verify_repaired_spatial_addendum",
    "verify_spatial_decision_addendum_r03",
    "write_repaired_spatial_decision_addendum",
    "write_spatial_decision_addendum_r03",
    "write_spatial_decision_addendum",
]
