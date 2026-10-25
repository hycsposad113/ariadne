from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .models import ActorKind, ProvenanceAnnotation

if TYPE_CHECKING:
    from .store import ProjectStateStore, StateRecord


PD14_SPECIFICATIONS: dict[int, dict[str, str]] = {
    182: {
        "category": "LEGACY_ACTOR_LABEL_UNVERIFIED",
        "rationale": "The historical designer label is an unverified program default, not authenticated human designer identity.",
    },
    183: {
        "category": "LEGACY_ACTOR_LABEL_UNVERIFIED",
        "rationale": "The historical designer label is an unverified program default, not authenticated human designer identity.",
    },
    184: {
        "category": "LEGACY_ACTOR_LABEL_UNVERIFIED",
        "rationale": "The historical designer label is an unverified program default, not authenticated human designer identity.",
    },
    185: {
        "category": "LEGACY_ACTOR_LABEL_UNVERIFIED",
        "rationale": "The historical designer label is an unverified program default, not authenticated human designer identity.",
    },
    186: {
        "category": "AUTOMATION_GUI_OPERATION_MISATTRIBUTED",
        "rationale": "Operation executed by autonomous agent via GUI automation; the designer actor label is misattributed.",
    },
    187: {
        "category": "AUTOMATION_GUI_OPERATION_MISATTRIBUTED",
        "rationale": "Operation executed by autonomous agent via GUI automation; the designer actor label is misattributed.",
    },
}


def annotate_pd14_events(store: ProjectStateStore) -> list[StateRecord]:
    """Append-only audit annotations for historical ledger events 182-187 per PD-14.

    Does not modify or delete any existing ledger event.
    """
    with store.locked_connection() as connection:
        existing_rows = connection.execute(
            "SELECT payload_json FROM state_versions WHERE entity_type = 'ProvenanceAnnotation'"
        ).fetchall()
    annotated_target_ids = set()
    for (payload_text,) in existing_rows:
        try:
            payload = json.loads(payload_text)
            if "target_event_id" in payload:
                annotated_target_ids.add(payload["target_event_id"])
        except Exception:
            continue

    records: list[StateRecord] = []
    for seq, spec in sorted(PD14_SPECIFICATIONS.items()):
        with store.locked_connection() as connection:
            row = connection.execute(
                "SELECT sequence, event_id, project_id, actor, target_id FROM ledger_events WHERE sequence = ?",
                (seq,),
            ).fetchone()
        if row is None:
            continue

        event_id = row["event_id"]
        if event_id in annotated_target_ids:
            continue

        annotation = ProvenanceAnnotation(
            id=f"provenance-annotation-seq-{seq}",
            project_id=row["project_id"] or "rotterdam-m4h-pilot-project",
            target_event_id=event_id,
            category=spec["category"],
            source_actor_label=row["actor"] or "designer",
            source_actor_kind=None,
            rationale=spec["rationale"],
            related_revision_refs=[row["target_id"]] if row["target_id"] else [],
        )

        rec = store.create_typed(
            annotation,
            actor="annotation-auditor",
            actor_kind=ActorKind.AGENT_AUTOMATION,
            actor_session_id=f"pd14-audit-seq-{seq}",
            reason=f"PD-14 provenance annotation for ledger event sequence {seq}",
        )
        records.append(rec)
        annotated_target_ids.add(event_id)

    return records
