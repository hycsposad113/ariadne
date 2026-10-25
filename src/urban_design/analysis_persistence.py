"""Analysis persistence service for Site Analysis and Space Syntax.

Implements C3 / WC-2:
- Persists site analysis cards and syntax layers as ToolExecution + Artifact + EvidenceCard.
- Retrieves persisted results and validates input hashes.
- Detects stale results when active StudyArea or source snapshots change.
- Returns NOT_COMPUTED when no persisted execution is present.
- Enforces idempotency key uniqueness without duplicate ledger writes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import ActorKind, Artifact, EvidenceCard, ToolExecution
from .r03_evidence import LEGACY_VERIFIED_OBSERVATION, SOURCE_ALIGNED_COVERAGE_LIMITED
from .r04_evidence import build_r04_observational_evidence_bundle
from .store import EntityNotFoundError, ProjectStateStore, StateRecord
from .workspace_sources import WorkspaceSourceCatalog


def _canonical_bytes(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_bytes(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _canonical_sha256(value: Any) -> str:
    """Return the domain-model SHA-256 representation for a recorded digest."""
    if not isinstance(value, str):
        raise ValueError("SHA-256 value must be text")
    digest = value.removeprefix("sha256:").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("SHA-256 value must contain exactly 64 hexadecimal characters")
    return "sha256:" + digest


def _canonical_hash_map(value: Mapping[str, Any]) -> dict[str, str]:
    return {str(key): _canonical_sha256(digest) for key, digest in value.items()}


def _snapshot_hashes(
    store: ProjectStateStore,
    catalog: WorkspaceSourceCatalog,
    snapshot_ids: Sequence[str],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for snapshot_id in sorted(set(snapshot_ids)):
        try:
            record = store.current(snapshot_id)
            if record.entity_type != "DatasetSnapshot":
                raise ValueError(f"input reference {snapshot_id!r} is not a DatasetSnapshot")
            payload = record.payload
        except EntityNotFoundError:
            payload = catalog.snapshots.get(snapshot_id, {})
        digest = payload.get("sha256") if isinstance(payload, Mapping) else None
        if not isinstance(digest, str) or not digest.strip():
            raise ValueError(f"DatasetSnapshot {snapshot_id!r} has no verified SHA-256")
        hashes[snapshot_id] = _canonical_sha256(digest)
    return hashes


def _artifact_hashes(
    store: ProjectStateStore,
    catalog: WorkspaceSourceCatalog,
    artifact_ids: Sequence[str],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for artifact_id in sorted(set(artifact_ids)):
        normalized = catalog.normalized_artifacts.get(artifact_id, {})
        digest = normalized.get("sha256") if isinstance(normalized, Mapping) else None
        if not isinstance(digest, str) or not digest.strip():
            try:
                record = store.current(artifact_id)
            except EntityNotFoundError as exc:
                raise ValueError(f"input Artifact {artifact_id!r} is missing") from exc
            if record.entity_type != "Artifact":
                raise ValueError(f"input reference {artifact_id!r} is not an Artifact")
            digest = record.payload.get("sha256")
        if not isinstance(digest, str) or not digest.strip():
            raise ValueError(f"Artifact {artifact_id!r} has no verified SHA-256")
        hashes[artifact_id] = _canonical_sha256(digest)
    return hashes


def _artifact_bundle_hash_error(execution: Mapping[str, Any], artifact: Mapping[str, Any]) -> str | None:
    bundle = artifact.get("bundle")
    if not isinstance(bundle, Mapping):
        return "output Artifact does not contain a JSON bundle"
    bundle_bytes = _canonical_bytes(bundle)
    actual_sha = _sha256_bytes(bundle_bytes)
    try:
        artifact_sha = _canonical_sha256(artifact.get("sha256"))
    except ValueError:
        return "stored Artifact SHA-256 is not a typed SHA-256 value"
    if artifact_sha != actual_sha:
        return "stored Artifact SHA-256 does not match its bundle bytes"
    if artifact.get("size_bytes") != len(bundle_bytes):
        return "stored Artifact size does not match its bundle bytes"
    output_hashes = execution.get("output_artifact_hashes")
    try:
        output_sha = _canonical_sha256(output_hashes[0]) if isinstance(output_hashes, list) and output_hashes else None
    except ValueError:
        output_sha = None
    if output_sha != actual_sha:
        return "ToolExecution output hash does not match its Artifact bundle"
    return None


def _latest_execution(store: ProjectStateStore, project_id: str, records: Sequence[StateRecord]) -> StateRecord:
    sequences = {event.target_id: event.sequence for event in store.events(project_id)}
    return max(records, key=lambda record: (sequences.get(record.entity_id, 0), record.entity_id))


def _idempotent_pair(
    store: ProjectStateStore,
    *,
    execution_id: str,
    artifact_id: str,
    expected_bundle_sha: str,
) -> tuple[StateRecord, StateRecord] | None:
    try:
        execution = store.current(execution_id)
    except EntityNotFoundError:
        execution = None
    try:
        artifact = store.current(artifact_id)
    except EntityNotFoundError:
        artifact = None
    if execution is None and artifact is None:
        return None
    if execution is None or artifact is None:
        raise ValueError("idempotency key is bound to an incomplete persisted execution/artifact pair")
    try:
        artifact_sha = _canonical_sha256(artifact.payload.get("sha256"))
        execution_sha = _canonical_sha256(execution.payload.get("output_artifact_hashes", [None])[0])
    except (IndexError, TypeError, ValueError):
        raise ValueError("idempotency key is already bound to invalid output hashes")
    if artifact_sha != _canonical_sha256(expected_bundle_sha):
        raise ValueError("idempotency key is already bound to a different result bundle")
    if execution_sha != _canonical_sha256(expected_bundle_sha):
        raise ValueError("idempotency key is already bound to a different execution output")
    return execution, artifact


def _ensure_typed_output_pair(
    store: ProjectStateStore,
    execution: StateRecord,
    artifact: StateRecord,
    *,
    input_refs: Sequence[str],
    input_snapshot_hashes: Mapping[str, str],
    input_artifact_ids: Sequence[str],
    input_artifact_hashes_by_id: Mapping[str, str],
    input_artifact_hashes: Sequence[str],
    study_area_geometry_sha256: str,
    actor: str,
    actor_kind: ActorKind | str,
    actor_session_id: str | None,
) -> tuple[StateRecord, StateRecord]:
    """Validate and, when needed, append typed metadata revisions for a pair."""
    artifact_payload = dict(artifact.payload)
    artifact_payload["sha256"] = _canonical_sha256(artifact_payload.get("sha256"))
    artifact_model_payload = {key: value for key, value in artifact_payload.items() if key != "bundle"}
    Artifact.model_validate(artifact_model_payload)

    execution_payload = dict(execution.payload)
    execution_payload["input_refs"] = sorted(set(input_refs))
    execution_payload["input_snapshot_hashes"] = _canonical_hash_map(input_snapshot_hashes)
    execution_payload["input_artifact_ids"] = sorted(set(input_artifact_ids))
    execution_payload["input_artifact_hashes_by_id"] = _canonical_hash_map(input_artifact_hashes_by_id)
    execution_payload["input_artifact_hashes"] = [
        _canonical_sha256(digest) for digest in input_artifact_hashes
    ]
    execution_payload["output_artifact_hashes"] = [
        _canonical_sha256(digest) for digest in execution_payload.get("output_artifact_hashes", [])
    ]
    parameters = dict(execution_payload.get("parameters", {}))
    parameters["study_area_geometry_sha256"] = _canonical_sha256(study_area_geometry_sha256)
    parameters["persistence_schema_version"] = "typed-evidence-v2"
    execution_payload["parameters"] = parameters
    ToolExecution.model_validate(execution_payload)

    if artifact_payload != dict(artifact.payload):
        artifact = store.update(
            artifact.entity_id,
            artifact_payload,
            expected_revision=artifact.revision,
            actor=actor,
            actor_kind=actor_kind,
            actor_session_id=actor_session_id,
            action="NormalizeAnalysisArtifactSha256",
            replace=True,
        )
    if execution_payload != dict(execution.payload):
        execution = store.update(
            execution.entity_id,
            execution_payload,
            expected_revision=execution.revision,
            actor=actor,
            actor_kind=actor_kind,
            actor_session_id=actor_session_id,
            action="NormalizeAnalysisToolExecutionSchema",
            replace=True,
        )
    return execution, artifact


def _typed_site_analysis_card(
    raw_card: Mapping[str, Any],
    *,
    catalog: WorkspaceSourceCatalog,
    artifact_id: str,
    artifact_sha256: str,
    created_at: str,
) -> dict[str, Any]:
    metric_key = str(raw_card["metric_key"])
    metric_name = str(raw_card["metric_name"])
    unit = str(raw_card["unit"])
    source_card_id = str(raw_card["card_id"])
    value = raw_card["value"]
    snapshot_ids = sorted(set(str(item) for item in raw_card.get("dataset_snapshot_ids", [])))
    dataset_refs = []
    for snapshot_id in snapshot_ids:
        snapshot = catalog.snapshots.get(snapshot_id, {})
        dataset_refs.append({
            "id": snapshot_id,
            "project_id": catalog.project_id,
            "version": str(snapshot.get("version") or "unknown"),
            "sha256": _canonical_sha256(snapshot.get("sha256")),
        })
    source_artifact_ids = sorted(set(str(item) for item in raw_card.get("source_artifact_ids", [])))
    statement = (
        f"{metric_name}: {value} {unit} from the retained, hash-verified spatial-r01 inputs "
        f"within StudyArea {catalog.study_area_id}."
    )
    payload = {
        "id": f"card-domain-site-{source_card_id}",
        "project_id": catalog.project_id,
        "scenario_id": None,
        "input_versions": [catalog.study_area_id, *snapshot_ids],
        "claim": {
            "id": f"claim-card-domain-site-{source_card_id}",
            "type": "observation",
            "statement": statement,
            "evidence_ids": [],
            "assumption_ids": [],
            "scope": catalog.study_area_id,
        },
        "source_refs": sorted({artifact_id, *source_artifact_ids}),
        "dataset_refs": dataset_refs,
        "metric": {"id": f"metric-{metric_key}", "name": metric_name, "unit": unit},
        "parameters": [
            f"source_evidence_card_id={source_card_id}",
            f"formula_version={raw_card.get('algorithm_version') or 'unspecified'}",
            f"study_area_id={catalog.study_area_id}",
        ],
        "method": {
            "id": str(raw_card.get("algorithm_version") or "r04-source-scoped-site-summary-v1"),
            "description": str(raw_card.get("method_definition") or "Deterministic source-scoped site analysis."),
        },
        "tool": "site-analysis",
        "tool_version": "r04-source-scoped-site-summary-v1",
        "result": {
            "artifact_refs": [artifact_id],
            "artifact_hashes": [_canonical_sha256(artifact_sha256)],
            "values": {metric_key: value},
            "status": "computed",
            "project_id": catalog.project_id,
            "dataset_ids": snapshot_ids,
            "units": unit,
            "validation_status": "unverified",
        },
        "units": unit,
        "assumptions": ["The observation is limited to the retained source inputs and stated method."],
        "limitations": [str(item) for item in raw_card.get("limitations", [])],
        "confidence": {
            "level": "low",
            "basis": "Deterministic source-scoped measurement with recorded input lineage.",
            "uncertainty": "Coverage and semantic completeness remain limited to the retained source package.",
            "assessed_by": "WC-2 persistence validation",
        },
        "validation_status": "unverified",
        "semantic_type": "COMPUTED_RESULT",
        "human_status": "not_reviewed",
        "created_at": created_at,
    }
    return EvidenceCard.model_validate(payload).model_dump(mode="json", exclude_none=True)


def persist_site_analysis_bundle(
    store: ProjectStateStore,
    catalog: WorkspaceSourceCatalog,
    bundle: Mapping[str, Any] | None = None,
    *,
    actor: str = "agent-automation",
    actor_kind: ActorKind | str = ActorKind.AGENT_AUTOMATION,
    actor_session_id: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[StateRecord, StateRecord, list[StateRecord]]:
    """Persist source-scoped site-analysis cards and their hash-bound inputs."""
    if bundle is None:
        bundle = build_r04_observational_evidence_bundle(catalog, store)
    else:
        bundle = dict(bundle)

    raw_cards = bundle.get("cards")
    if isinstance(raw_cards, list):
        cards: list[Any] = []
        for raw_card in raw_cards:
            if not isinstance(raw_card, Mapping):
                cards.append(raw_card)
                continue
            card = dict(raw_card)
            if card.get("status") == SOURCE_ALIGNED_COVERAGE_LIMITED:
                try:
                    existing_card = store.current(str(card.get("card_id", "")))
                except EntityNotFoundError:
                    pass
                else:
                    legacy_card = {**card, "status": LEGACY_VERIFIED_OBSERVATION}
                    if existing_card.entity_type == "EvidenceCard" and existing_card.payload == legacy_card:
                        # The same immutable card ID keeps its historical label on idempotent replay.
                        card["status"] = LEGACY_VERIFIED_OBSERVATION
            cards.append(card)
        bundle["cards"] = cards

    ik = idempotency_key or f"site-analysis-{catalog.package_revision}-{catalog.study_area_id}"
    exec_id = f"toolexec-site-analysis-{ik}"
    artifact_id = f"artifact-site-analysis-{ik}"
    bundle_bytes = _canonical_bytes(bundle)
    bundle_sha = _sha256_bytes(bundle_bytes)

    snapshot_ids = sorted(catalog.snapshots)
    snapshot_hashes = _snapshot_hashes(store, catalog, snapshot_ids)
    input_artifact_ids = sorted(catalog.normalized_artifacts)
    input_hashes_by_id = _artifact_hashes(store, catalog, input_artifact_ids)
    existing = _idempotent_pair(
        store,
        execution_id=exec_id,
        artifact_id=artifact_id,
        expected_bundle_sha=bundle_sha,
    )
    artifact_payload = {
        "id": artifact_id,
        "type": "evidence_bundle",
        "uri": f"artifacts/site-analysis/{artifact_id}.json",
        "sha256": bundle_sha,
        "mime": "application/json",
        "producer": "r04-source-scoped-site-summary-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_id": catalog.project_id,
        "size_bytes": len(bundle_bytes),
        "parent_artifact_ids": input_artifact_ids,
        "bundle": bundle,
    }
    exec_payload = {
        "id": exec_id,
        "project_id": catalog.project_id,
        "tool": "site-analysis",
        "tool_version": "r04-source-scoped-site-summary-v1",
        "idempotency_key": ik,
        "status": "succeeded",
        "input_refs": snapshot_ids,
        "input_snapshot_hashes": _canonical_hash_map(snapshot_hashes),
        "input_artifact_ids": input_artifact_ids,
        "input_artifact_hashes_by_id": _canonical_hash_map(input_hashes_by_id),
        "input_artifact_hashes": [
            _canonical_sha256(catalog.study_area_geometry_sha256),
            *[_canonical_sha256(value) for value in input_hashes_by_id.values()],
        ],
        "output_artifact_refs": [artifact_id],
        "output_artifact_hashes": [bundle_sha],
        "parameters": {
            "formula_version": "r04-source-scoped-site-summary-v1",
            "package_id": catalog.package_id,
            "package_revision": catalog.package_revision,
            "study_area_id": catalog.study_area_id,
            "study_area_geometry_sha256": _canonical_sha256(catalog.study_area_geometry_sha256),
            "persistence_schema_version": "typed-evidence-v2",
        },
        "limitations": [
            "Counts nonblank attributes only within retained valid features intersecting the active StudyArea.",
            "OSM centerline length counts clipped geometries union; coincident linework counted once.",
            "Unclassified surface residual is geometric remainder after subtracting building footprints and water geometries.",
        ],
    }
    if existing is None:
        artifact_rec = store.create(
            entity_type="Artifact",
            payload=artifact_payload,
            entity_id=artifact_id,
            project_id=catalog.project_id,
            actor=actor,
            actor_kind=actor_kind,
            actor_session_id=actor_session_id,
            action="CreateArtifact",
        )
        Artifact.model_validate({key: value for key, value in artifact_payload.items() if key != "bundle"})
        exec_rec = store.create(
            entity_type="ToolExecution",
            payload=exec_payload,
            entity_id=exec_id,
            project_id=catalog.project_id,
            actor=actor,
            actor_kind=actor_kind,
            actor_session_id=actor_session_id,
            action="CreateToolExecution",
        )
    else:
        exec_rec, artifact_rec = existing
    exec_rec, artifact_rec = _ensure_typed_output_pair(
        store,
        exec_rec,
        artifact_rec,
        input_refs=snapshot_ids,
        input_snapshot_hashes=snapshot_hashes,
        input_artifact_ids=input_artifact_ids,
        input_artifact_hashes_by_id=input_hashes_by_id,
        input_artifact_hashes=[catalog.study_area_geometry_sha256, *input_hashes_by_id.values()],
        study_area_geometry_sha256=catalog.study_area_geometry_sha256,
        actor=actor,
        actor_kind=actor_kind,
        actor_session_id=actor_session_id,
    )

    typed_cards: list[StateRecord] = []
    card_created_at = str(artifact_rec.payload["created_at"])
    for card in bundle.get("cards", []):
        card_id = str(card["card_id"])
        try:
            card_record = store.current(card_id)
        except EntityNotFoundError:
            card_record = store.create(
                entity_type="EvidenceCard",
                payload=card,
                entity_id=card_id,
                project_id=catalog.project_id,
                actor=actor,
                actor_kind=actor_kind,
                actor_session_id=actor_session_id,
                action="CreateEvidenceCard",
            )
        if card_record.entity_type != "EvidenceCard" or card_record.payload != dict(card):
            raise ValueError(f"EvidenceCard id {card_id!r} already exists with different content")
        typed_payload = _typed_site_analysis_card(
            card,
            catalog=catalog,
            artifact_id=artifact_id,
            artifact_sha256=str(artifact_rec.payload["sha256"]),
            created_at=card_created_at,
        )
        try:
            typed_record = store.current(str(typed_payload["id"]))
        except EntityNotFoundError:
            typed_record = store.create(
                entity_type="EvidenceCard",
                payload=typed_payload,
                entity_id=str(typed_payload["id"]),
                project_id=catalog.project_id,
                actor=actor,
                actor_kind=actor_kind,
                actor_session_id=actor_session_id,
                action="CreateTypedSiteAnalysisEvidenceCard",
            )
        if typed_record.entity_type != "EvidenceCard" or typed_record.payload != typed_payload:
            raise ValueError(f"typed EvidenceCard {typed_payload['id']!r} differs from deterministic source evidence")
        EvidenceCard.model_validate(typed_record.payload)
        typed_cards.append(typed_record)

    return exec_rec, artifact_rec, typed_cards


def persist_syntax_bundle(
    store: ProjectStateStore,
    catalog: WorkspaceSourceCatalog,
    syntax_bundle: Mapping[str, Any],
    *,
    tool: str = "PST 3.3.1",
    tool_version: str = "3.3.1",
    is_historical_r02: bool = False,
    actor: str = "agent-automation",
    actor_kind: ActorKind | str = ActorKind.AGENT_AUTOMATION,
    actor_session_id: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[StateRecord, StateRecord]:
    """Persist Syntax results with explicit snapshot/artifact lineage."""
    tool_name = "space-syntax-historical" if is_historical_r02 else tool
    tool_ver = "r02-historical" if is_historical_r02 else tool_version
    ik = idempotency_key or f"syntax-{tool_name.lower().replace(' ', '-')}-{catalog.study_area_id}"
    exec_id = f"toolexec-syntax-{ik}"
    artifact_id = f"artifact-syntax-{ik}"
    bundle_dict = dict(syntax_bundle)

    segment_rows = bundle_dict.get("segments", [])
    if not isinstance(segment_rows, list):
        raise ValueError("Syntax bundle segments must be a list")
    input_snapshot_ids = set(bundle_dict.get("source_input_snapshot_ids", []))
    input_artifact_ids = set(bundle_dict.get("source_input_artifact_ids", []))
    for segment in segment_rows:
        if not isinstance(segment, Mapping):
            continue
        snapshot_id = segment.get("source_snapshot_id")
        artifact_ref = segment.get("source_artifact_id")
        if isinstance(snapshot_id, str) and snapshot_id:
            input_snapshot_ids.add(snapshot_id)
        if isinstance(artifact_ref, str) and artifact_ref:
            input_artifact_ids.add(artifact_ref)

    snapshot_ids = sorted(input_snapshot_ids)
    snapshot_hashes = _snapshot_hashes(store, catalog, snapshot_ids)
    artifact_ids = sorted(input_artifact_ids)
    artifact_hashes_by_id = _artifact_hashes(store, catalog, artifact_ids)
    bundle_dict["source_input_snapshot_ids"] = snapshot_ids
    bundle_dict["source_input_artifact_ids"] = artifact_ids
    bundle_bytes = _canonical_bytes(bundle_dict)
    bundle_sha = _sha256_bytes(bundle_bytes)

    existing = _idempotent_pair(
        store,
        execution_id=exec_id,
        artifact_id=artifact_id,
        expected_bundle_sha=bundle_sha,
    )
    artifact_payload = {
        "id": artifact_id,
        "type": "syntax_bundle",
        "uri": f"artifacts/syntax/{artifact_id}.json",
        "sha256": bundle_sha,
        "mime": "application/json",
        "producer": tool_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_id": catalog.project_id,
        "size_bytes": len(bundle_bytes),
        "parent_artifact_ids": [catalog.study_area_id, *artifact_ids],
        "bundle": bundle_dict,
    }
    input_artifact_hashes = [catalog.study_area_geometry_sha256, *artifact_hashes_by_id.values()]
    exec_payload = {
        "id": exec_id,
        "project_id": catalog.project_id,
        "tool": tool_name,
        "tool_version": tool_ver,
        "idempotency_key": ik,
        "status": "succeeded",
        "input_refs": snapshot_ids,
        "input_snapshot_hashes": _canonical_hash_map(snapshot_hashes),
        "input_artifact_ids": artifact_ids,
        "input_artifact_hashes_by_id": _canonical_hash_map(artifact_hashes_by_id),
        "input_artifact_hashes": [_canonical_sha256(value) for value in input_artifact_hashes],
        "output_artifact_refs": [artifact_id],
        "output_artifact_hashes": [bundle_sha],
        "parameters": {
            "tool": tool_name,
            "tool_version": tool_ver,
            "is_historical_r02": is_historical_r02,
            "study_area_id": catalog.study_area_id,
            "study_area_geometry_sha256": _canonical_sha256(catalog.study_area_geometry_sha256),
            "persistence_schema_version": "typed-evidence-v2",
        },
        "limitations": bundle_dict.get("limitations", []),
    }
    if existing is None:
        artifact_rec = store.create(
            entity_type="Artifact",
            payload=artifact_payload,
            entity_id=artifact_id,
            project_id=catalog.project_id,
            actor=actor,
            actor_kind=actor_kind,
            actor_session_id=actor_session_id,
            action="CreateArtifact",
        )
        Artifact.model_validate({key: value for key, value in artifact_payload.items() if key != "bundle"})
        exec_rec = store.create(
            entity_type="ToolExecution",
            payload=exec_payload,
            entity_id=exec_id,
            project_id=catalog.project_id,
            actor=actor,
            actor_kind=actor_kind,
            actor_session_id=actor_session_id,
            action="CreateToolExecution",
        )
    else:
        exec_rec, artifact_rec = existing
    exec_rec, artifact_rec = _ensure_typed_output_pair(
        store,
        exec_rec,
        artifact_rec,
        input_refs=snapshot_ids,
        input_snapshot_hashes=snapshot_hashes,
        input_artifact_ids=artifact_ids,
        input_artifact_hashes_by_id=artifact_hashes_by_id,
        input_artifact_hashes=input_artifact_hashes,
        study_area_geometry_sha256=catalog.study_area_geometry_sha256,
        actor=actor,
        actor_kind=actor_kind,
        actor_session_id=actor_session_id,
    )
    return exec_rec, artifact_rec

_SYNTAX_LAYER_PLAN = (
    ("syntax_local_800m_integration", 800.0, "nain"),
    ("syntax_local_800m_choice", 800.0, "nach"),
    ("syntax_mid_2000m_integration", 2000.0, "nain"),
    ("syntax_mid_2000m_choice", 2000.0, "nach"),
    ("syntax_regional_10000m_integration", 10000.0, "nain"),
    ("syntax_regional_10000m_choice", 10000.0, "nach"),
)


def _current_artifact_hashes(
    store: ProjectStateStore,
    catalog: WorkspaceSourceCatalog,
    artifact_ids: Sequence[str],
) -> dict[str, str]:
    return _artifact_hashes(store, catalog, artifact_ids)


def _current_snapshot_hashes(
    store: ProjectStateStore,
    catalog: WorkspaceSourceCatalog,
    snapshot_ids: Sequence[str],
) -> dict[str, str]:
    return _snapshot_hashes(store, catalog, snapshot_ids)


def _not_computed_syntax(reason: str, *, result_source: str = "none") -> dict[str, Any]:
    return {
        "engine": "NONE",
        "status": "NOT_COMPUTED",
        "result_source": result_source,
        "layers": [],
        "layer_plan": [
            {
                "layer_id": layer_id,
                "calculation_status": "NOT_COMPUTED",
                "radius_m": radius,
                "metric_key": metric,
                "segment_values": {},
                "reason": reason,
            }
            for layer_id, radius, metric in _SYNTAX_LAYER_PLAN
        ],
        "segments": [],
        "figure": {},
        "limitations": [reason],
    }


def _blocked_syntax(reason: str, engine: str = "UNKNOWN") -> dict[str, Any]:
    result = _not_computed_syntax(reason)
    result["engine"] = engine
    result["status"] = "BLOCKED_ARTIFACT_HASH_MISMATCH"
    result["result_source"] = "persisted_database_record"
    for layer in result["layer_plan"]:
        layer["calculation_status"] = "BLOCKED"
    return result


def get_persisted_site_analysis(
    store: ProjectStateStore,
    project_id: str,
    catalog: WorkspaceSourceCatalog,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str, str | None, list[dict[str, str]]]:
    """Read persisted Site Analysis and fail closed on output or lineage drift."""
    executions = store.list_current(entity_type="ToolExecution", project_id=project_id)
    analysis_execs = [record for record in executions if record.payload.get("tool") == "site-analysis"]
    if not analysis_execs:
        return (
            None,
            [],
            "NOT_COMPUTED",
            None,
            [{"topic": "site analysis", "status": "NOT_COMPUTED", "reason": "No persisted site-analysis ToolExecution found in the project store."}],
        )

    analysis_exec = _latest_execution(store, project_id, analysis_execs)
    payload = analysis_exec.payload
    output_refs = payload.get("output_artifact_refs", [])
    if not output_refs:
        return None, [], "NOT_COMPUTED", None, [{"topic": "site analysis", "status": "NOT_COMPUTED", "reason": "ToolExecution has no output Artifact reference."}]
    artifact_id = output_refs[0]
    try:
        artifact_record = store.current(artifact_id)
    except EntityNotFoundError:
        return None, [], "BLOCKED_MISSING_ARTIFACT", None, [{"topic": "site analysis", "status": "BLOCKED", "reason": f"Artifact {artifact_id} is missing."}]
    if artifact_record.entity_type != "Artifact":
        return None, [], "BLOCKED_MISSING_ARTIFACT", None, [{"topic": "site analysis", "status": "BLOCKED", "reason": f"Output {artifact_id} is not an Artifact."}]

    hash_error = _artifact_bundle_hash_error(payload, artifact_record.payload)
    if hash_error:
        return None, [], "BLOCKED_ARTIFACT_HASH_MISMATCH", None, [{"topic": "site analysis", "status": "BLOCKED", "reason": hash_error}]

    bundle = dict(artifact_record.payload["bundle"])
    raw_cards = bundle.get("cards", [])
    if not isinstance(raw_cards, list):
        return None, [], "BLOCKED_ARTIFACT_HASH_MISMATCH", None, [{"topic": "site analysis", "status": "BLOCKED", "reason": "Artifact cards are not a list."}]
    cards: list[dict[str, Any]] = []
    for card in raw_cards:
        if not isinstance(card, Mapping) or not isinstance(card.get("card_id"), str):
            return None, [], "BLOCKED_ARTIFACT_HASH_MISMATCH", None, [{"topic": "site analysis", "status": "BLOCKED", "reason": "Artifact contains an invalid EvidenceCard reference."}]
        try:
            card_record = store.current(card["card_id"])
        except EntityNotFoundError:
            return None, [], "BLOCKED_MISSING_ARTIFACT", None, [{"topic": "site analysis", "status": "BLOCKED", "reason": f"EvidenceCard {card['card_id']} is missing."}]
        if card_record.entity_type != "EvidenceCard" or card_record.payload != dict(card):
            return None, [], "BLOCKED_ARTIFACT_HASH_MISMATCH", None, [{"topic": "site analysis", "status": "BLOCKED", "reason": f"EvidenceCard {card['card_id']} does not match the bound Artifact."}]
        cards.append(dict(card))

    stale_reasons: list[str] = []
    stored_sa_hash = payload.get("parameters", {}).get("study_area_geometry_sha256")
    try:
        area_hash_matches = _canonical_sha256(stored_sa_hash) == _canonical_sha256(catalog.study_area_geometry_sha256)
    except ValueError:
        area_hash_matches = False
    if not area_hash_matches:
        stale_reasons.append("active StudyArea geometry hash changed")

    stored_snapshot_ids = set(payload.get("input_refs", []))
    current_snapshot_ids = set(catalog.snapshots)
    if stored_snapshot_ids != current_snapshot_ids:
        stale_reasons.append("input DatasetSnapshot references changed")
    try:
        current_snapshot_hashes = _current_snapshot_hashes(store, catalog, sorted(stored_snapshot_ids | current_snapshot_ids))
    except ValueError:
        current_snapshot_hashes = {}
    stored_snapshot_hashes = payload.get("input_snapshot_hashes", {})
    expected_snapshot_hashes = {key: current_snapshot_hashes[key] for key in stored_snapshot_ids if key in current_snapshot_hashes}
    try:
        normalized_snapshot_hashes = _canonical_hash_map(stored_snapshot_hashes) if isinstance(stored_snapshot_hashes, Mapping) else {}
    except ValueError:
        normalized_snapshot_hashes = {}
    if normalized_snapshot_hashes != expected_snapshot_hashes or set(expected_snapshot_hashes) != stored_snapshot_ids:
        stale_reasons.append("input DatasetSnapshot hashes changed or cannot be verified")

    stored_artifact_ids = set(payload.get("input_artifact_ids", []))
    current_artifact_ids = set(catalog.normalized_artifacts)
    if stored_artifact_ids != current_artifact_ids:
        stale_reasons.append("input normalized Artifact references changed")
    try:
        expected_artifact_hashes = _current_artifact_hashes(store, catalog, sorted(stored_artifact_ids | current_artifact_ids))
    except ValueError:
        expected_artifact_hashes = {}
    stored_artifact_hashes = payload.get("input_artifact_hashes_by_id", {})
    expected_referenced_hashes = {key: expected_artifact_hashes[key] for key in stored_artifact_ids if key in expected_artifact_hashes}
    try:
        normalized_artifact_hashes = _canonical_hash_map(stored_artifact_hashes) if isinstance(stored_artifact_hashes, Mapping) else {}
    except ValueError:
        normalized_artifact_hashes = {}
    if normalized_artifact_hashes != expected_referenced_hashes or set(expected_referenced_hashes) != stored_artifact_ids:
        stale_reasons.append("input Artifact hashes changed or cannot be verified")

    blob = _canonical_bytes(bundle)
    bundle_sha256 = "sha256:" + hashlib.sha256(blob).hexdigest()
    if stale_reasons:
        return bundle, cards, "STALE", bundle_sha256, [{"topic": "site analysis", "status": "STALE", "reason": "; ".join(stale_reasons)}]
    return bundle, cards, "VERIFIED_SOURCE_RESULT_ALIGNMENT", bundle_sha256, bundle.get("evidence_gaps", [])


def get_persisted_syntax_bundle(
    store: ProjectStateStore,
    project_id: str,
    catalog: WorkspaceSourceCatalog,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Read the latest persisted Syntax artifact and verify its hashes and lineage."""
    executions = store.list_current(entity_type="ToolExecution", project_id=project_id)
    syntax_execs = [
        record for record in executions
        if record.payload.get("tool") in ("PST 3.3.1", "space-syntax-historical")
    ]
    if not syntax_execs:
        return _not_computed_syntax("No Syntax ToolExecution has been persisted in the project store.")

    active_exec = _latest_execution(store, project_id, syntax_execs)
    payload = active_exec.payload
    output_refs = payload.get("output_artifact_refs", [])
    if not output_refs:
        return _not_computed_syntax(
            "Syntax ToolExecution has no output Artifact reference.",
            result_source="persisted_database_record",
        )
    artifact_id = output_refs[0]
    try:
        artifact_record = store.current(artifact_id)
    except EntityNotFoundError:
        return _blocked_syntax(f"Syntax Artifact {artifact_id} is missing.", str(payload.get("tool", "UNKNOWN")))
    if artifact_record.entity_type != "Artifact":
        return _blocked_syntax(f"Syntax output {artifact_id} is not an Artifact.", str(payload.get("tool", "UNKNOWN")))
    hash_error = _artifact_bundle_hash_error(payload, artifact_record.payload)
    if hash_error:
        return _blocked_syntax(hash_error, str(payload.get("tool", "UNKNOWN")))

    bundle = dict(artifact_record.payload["bundle"])
    bundle["result_source"] = "persisted_database_record"
    for layer in [*bundle.get("layers", []), *bundle.get("layer_plan", [])]:
        if layer.get("calculation_status") != "COMPUTED":
            layer["segment_values"] = {}
            layer["statistics"] = None
            layer.pop("legend_breaks", None)
    if "segments" not in bundle:
        bundle["segments"] = []
        bundle["limitations"] = [
            *bundle.get("limitations", []),
            "Persisted Syntax result does not include segment geometry; the segment overlay is unavailable.",
        ]
    bundle.setdefault("figure", {})
    stale_reasons: list[str] = []
    stored_sa_hash = payload.get("parameters", {}).get("study_area_geometry_sha256")
    try:
        area_hash_matches = _canonical_sha256(stored_sa_hash) == _canonical_sha256(catalog.study_area_geometry_sha256)
    except ValueError:
        area_hash_matches = False
    if not area_hash_matches:
        stale_reasons.append("active StudyArea geometry hash changed")

    snapshot_hashes = payload.get("input_snapshot_hashes", {})
    if not isinstance(snapshot_hashes, Mapping):
        stale_reasons.append("input DatasetSnapshot hashes are missing")
    else:
        try:
            current_hashes = _current_snapshot_hashes(store, catalog, list(snapshot_hashes))
        except ValueError:
            current_hashes = {}
        try:
            normalized_snapshot_hashes = _canonical_hash_map(snapshot_hashes)
        except ValueError:
            normalized_snapshot_hashes = {}
        if normalized_snapshot_hashes != current_hashes or set(current_hashes) != set(snapshot_hashes):
            stale_reasons.append("input DatasetSnapshot hashes changed or cannot be verified")

    input_artifact_hashes = payload.get("input_artifact_hashes_by_id", {})
    if not isinstance(input_artifact_hashes, Mapping):
        stale_reasons.append("input Artifact hashes are missing")
    else:
        try:
            current_hashes = _current_artifact_hashes(store, catalog, list(input_artifact_hashes))
        except ValueError:
            current_hashes = {}
        try:
            normalized_input_artifact_hashes = _canonical_hash_map(input_artifact_hashes)
        except ValueError:
            normalized_input_artifact_hashes = {}
        if normalized_input_artifact_hashes != current_hashes or set(current_hashes) != set(input_artifact_hashes):
            stale_reasons.append("input Artifact hashes changed or cannot be verified")

    if stale_reasons:
        bundle["status"] = "STALE"
        bundle["limitations"] = [*bundle.get("limitations", []), *stale_reasons]
        for layer in [*bundle.get("layers", []), *bundle.get("layer_plan", [])]:
            if layer.get("calculation_status") == "COMPUTED":
                layer["calculation_status"] = "STALE"
                layer["reason"] = "; ".join(stale_reasons)
                layer["segment_values"] = {}
                layer["statistics"] = None
                layer.pop("legend_breaks", None)
    return bundle
