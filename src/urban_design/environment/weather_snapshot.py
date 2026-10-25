"""Immutable candidate-01 publication and current, hash-bound approval resolution.

Publication is a proposal. This module never creates a HumanDecision or accesses
any decision key; approval uses the existing HumanDecisionDialog API.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path

from urban_design.models import ActorKind, Artifact, DatasetSnapshot
from urban_design.store import EntityNotFoundError

CANDIDATE_HASHES = {
    "source": "3c9a109d7f0b2e54c2b204d592bf5ec59774d16f36054bb89c284db4b5f7802a",
    "derived": "d6cc646473f2805002e28c99d13eb0c6d5fa08d40734b8fb2c89dbaae1371369",
    "mapping": "df37de88155db44e4d7731bbca79e700666349e21c3b5d2db62e4dcbbe4479e5",
}


class E2Blocked(ValueError):
    """A missing or stale authority/validation dependency prevents dispatch."""


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def create_record(store, entity_type, payload, project_id):
    try:
        existing = store.current(payload["id"])
    except EntityNotFoundError:
        return store.create(entity_type, payload, entity_id=payload["id"], project_id=project_id,
                            actor="e2_service", actor_kind=ActorKind.AGENT_AUTOMATION)
    if existing.entity_type != entity_type or existing.project_id != project_id or existing.payload != payload:
        raise E2Blocked("IMMUTABLE_RECORD_COLLISION")
    return existing


def persist_bytes(store, project_id: str, root: Path, kind: str, raw: bytes, mime="application/json", parents=()):
    digest = sha256(raw)
    identifier = f"artifact-e2-{kind}-" + digest[7:31]
    try:
        existing = store.current(identifier)
    except EntityNotFoundError:
        existing = None
    if existing is not None:
        if existing.entity_type != "Artifact" or existing.project_id != project_id or existing.payload.get("sha256") != digest:
            raise E2Blocked("ARTIFACT_COLLISION")
        checked_artifact(store, identifier, project_id)
        return existing
    root.mkdir(parents=True, exist_ok=True)
    extension = ".epw" if kind in {"weather-source", "weather-derived"} else ".csv" if kind == "weather-mapping" else ".json"
    path = root / (identifier + extension)
    with path.open("xb") as output:
        output.write(raw)
    model = Artifact(id=identifier, project_id=project_id, type=kind, uri=str(path.resolve()), sha256=digest,
                     mime=mime, producer="urban_design.environment.e2_service", created_at=datetime.now(timezone.utc),
                     size_bytes=len(raw), parent_artifact_ids=list(parents))
    return create_record(store, "Artifact", model.model_dump(mode="json"), project_id)


def checked_artifact(store, identifier, project_id):
    try:
        record = store.current(identifier)
    except EntityNotFoundError as exc:
        raise E2Blocked("ARTIFACT_NOT_FOUND:" + identifier) from exc
    if record.entity_type != "Artifact" or record.project_id != project_id:
        raise E2Blocked("ARTIFACT_PROJECT_OR_TYPE_MISMATCH")
    try:
        raw = Path(record.payload["uri"]).read_bytes()
    except (OSError, KeyError) as exc:
        raise E2Blocked("ARTIFACT_BYTES_UNAVAILABLE") from exc
    if sha256(raw) != record.payload.get("sha256"):
        raise E2Blocked("ARTIFACT_HASH_MISMATCH")
    return record, raw


def bound_approval(store, record, digest):
    """Latest decision must approve the current version and exact content hash."""
    from urban_design.decision_resolution import resolve_record_decision
    field = "target_artifact_sha256" if record.entity_type == "Artifact" else "target_payload_digest"
    resolution = resolve_record_decision(store, record, digest, field)
    if resolution.reason == "NO_COMPATIBLE_DECISION":
        raise E2Blocked("NOT_APPROVED:" + record.entity_id)
    if resolution.status != "EFFECTIVE" or resolution.reason != "Approve":
        raise E2Blocked("APPROVAL_BINDING_INVALID:" + resolution.reason + ":" + record.entity_id)
    return resolution.decision.entity_id


def publish_candidate01(store, project_id: str, proposal: Path, source_root: Path, artifact_root: Path):
    analysis = json.loads((proposal / "candidate-01/analysis.json").read_bytes())
    sources = {"source": source_root / analysis["source"]["source_r08_relative_path"],
               "derived": proposal / "candidate-01/derived-minute60.epw",
               "mapping": proposal / "candidate-01/minute-row-mapping.csv"}
    raw = {name: path.read_bytes() for name, path in sources.items()}
    if any(sha256(raw[name]) != "sha256:" + expected for name, expected in CANDIDATE_HASHES.items()):
        raise E2Blocked("CANDIDATE01_HASH_MISMATCH")
    mapping_rows = list(csv.DictReader(io.StringIO(raw["mapping"].decode())))
    if len(mapping_rows) != 8760:
        raise E2Blocked("MAPPING_ROW_COUNT_INVALID")
    # Exact reversible derivation and the original row mapping are both pinned.
    from urban_design.weather_derived import derive_minute_zero_as_hour_end
    derived = derive_minute_zero_as_hour_end(raw["source"], filename=analysis["source"]["filename"])
    if derived.derived_bytes != raw["derived"]:
        raise E2Blocked("DERIVATION_MISMATCH")
    refs = {name: persist_bytes(store, project_id, artifact_root, "weather-" + name, data,
                               "text/csv" if name == "mapping" else "application/octet-stream")
            for name, data in raw.items()}
    bundle = {"schema_version": "e2-weather-v1", "candidate": "candidate-01",
              "rule": "Minute=0 -> Minute=60; hour_end; project assumption PD-08",
              "mapping_rows": 8760,
              "artifacts": {name: {"id": ref.entity_id, "sha256": ref.payload["sha256"]} for name, ref in refs.items()},
              "source_provenance": analysis["source"], "supplier_timing_semantics_proven": False}
    receipt = persist_bytes(store, project_id, artifact_root, "weather-bundle", canonical_bytes(bundle),
                            parents=[item.entity_id for item in refs.values()])
    digest = receipt.payload["sha256"]
    snapshot = DatasetSnapshot(id="snapshot-e2-weather-" + digest[7:31], project_id=project_id,
                              source=analysis["source"]["source_url_from_preserved_record"],
                              query="candidate-01 reversible Minute=0 to 60 transformation; no download",
                              retrieved_at=analysis["source"]["retrieved_at_utc_from_preserved_record"],
                              publisher=analysis["source"]["publisher"], license=analysis["source"]["license_or_terms_from_preserved_record"],
                              version="weather-derived-method-v1", sha256=refs["derived"].payload["sha256"],
                              raw_artifact_id=refs["source"].entity_id, normalized_artifact_id=refs["derived"].entity_id)
    payload = snapshot.model_dump(mode="json")
    payload.update(status="PROPOSED", payload_digest=digest, bundle_artifact_id=receipt.entity_id)
    return create_record(store, "DatasetSnapshot", payload, project_id)


def load_weather(store, snapshot_id, project_id, *, require_approval=True):
    try:
        record = store.current(snapshot_id)
    except EntityNotFoundError as exc:
        raise E2Blocked("WEATHER_SNAPSHOT_NOT_FOUND") from exc
    if record.entity_type != "DatasetSnapshot" or record.project_id != project_id:
        raise E2Blocked("WEATHER_SNAPSHOT_PROJECT_OR_TYPE_MISMATCH")
    receipt, raw = checked_artifact(store, record.payload.get("bundle_artifact_id", ""), project_id)
    if receipt.payload["sha256"] != record.payload.get("payload_digest"):
        raise E2Blocked("WEATHER_BUNDLE_HASH_MISMATCH")
    bundle = json.loads(raw)
    for name, ref in bundle["artifacts"].items():
        artifact, _ = checked_artifact(store, ref["id"], project_id)
        if artifact.payload["sha256"] != ref["sha256"] or ref["sha256"] != "sha256:" + CANDIDATE_HASHES[name]:
            raise E2Blocked("WEATHER_CONTENT_HASH_MISMATCH")
    if (record.payload.get("sha256") != bundle["artifacts"]["derived"]["sha256"]
            or record.payload.get("raw_artifact_id") != bundle["artifacts"]["source"]["id"]
            or record.payload.get("normalized_artifact_id") != bundle["artifacts"]["derived"]["id"]):
        raise E2Blocked("WEATHER_SNAPSHOT_BINDING_MISMATCH")
    decision = bound_approval(store, record, receipt.payload["sha256"]) if require_approval else None
    epw = store.current(bundle["artifacts"]["derived"]["id"]).payload["uri"]
    return record, bundle, Path(epw), decision
