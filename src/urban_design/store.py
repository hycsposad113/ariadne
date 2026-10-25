"""Backend-owned SQLite state and an append-only Design Ledger.

The store intentionally keeps the domain payload model-independent. A typed
domain layer can validate a payload before handing it to this module; this
module then gives that payload durable identity, immutable revisions, and an
auditable event linking each state transition to a project.
"""

from __future__ import annotations

import copy
import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Concatenate, ParamSpec, TypeAlias, TypeVar

from pydantic import BaseModel, ValidationError

from .decision_key import DecisionKeyUnavailable, verify_decision_key_strict
from .models import ActorKind, DecisionAction, HumanDecision, HumanStatus, ProvenanceAnnotation


JSONPayload: TypeAlias = Mapping[str, Any]
Updater: TypeAlias = Callable[[dict[str, Any]], Mapping[str, Any] | None]


CORE_ENTITY_TYPES = frozenset(
    {
        "Project",
        "SiteModel",
        "DataSnapshot",
        "DatasetSnapshot",
        "Constraint",
        "ConstraintSet",
        "Assumption",
        "DesignScenario",
        "Artifact",
        "ToolRun",
        "ToolExecution",
        "ModelRun",
        "MetricDefinition",
        "EvidenceRecord",
        "EvidenceCard",
        "ParameterDefinition",
        "Claim",
        "ContestEvent",
        "HumanDecision",
        "ProvenanceAnnotation",
        "ExperimentPlan",
        "LedgerEvent",
        "DesignLedgerEvent",
        "Site",
        "SiteProposal",
        "Scenario",
        "StudyArea",
        "SiteExtentDraft",
        "DesignBoundary",
        "WorkspaceRevision",
        "SpatialBrief",
    }
)

_ENTITY_ALIASES = {
    "project": "Project",
    "site": "SiteModel",
    "sitemodel": "SiteModel",
    "siteproposal": "SiteProposal",
    "studyarea": "StudyArea",
    "study_area": "StudyArea",
    "designboundary": "DesignBoundary",
    "design_boundary": "DesignBoundary",
    "provenanceannotation": "ProvenanceAnnotation",
    "workspacerevision": "WorkspaceRevision",
    "workspace_revision": "WorkspaceRevision",
    "spatialbrief": "SpatialBrief",
    "spatial_brief": "SpatialBrief",
    "datasnapshot": "DataSnapshot",
    "datasetsnapshot": "DatasetSnapshot",
    "constraint": "Constraint",
    "constraintset": "ConstraintSet",
    "assumption": "Assumption",
    "designscenario": "DesignScenario",
    "scenario": "DesignScenario",
    "artifact": "Artifact",
    "toolrun": "ToolRun",
    "toolexecution": "ToolExecution",
    "modelrun": "ModelRun",
    "metricdefinition": "MetricDefinition",
    "evidencerecord": "EvidenceRecord",
    "evidencecard": "EvidenceCard",
    "parameterdefinition": "ParameterDefinition",
    "claim": "Claim",
    "contestevent": "ContestEvent",
    "humandecision": "HumanDecision",
    "experimentplan": "ExperimentPlan",
    "ledgerevent": "LedgerEvent",
    "designledgerevent": "DesignLedgerEvent",
}


class StoreError(RuntimeError):
    """Base error for state-store failures."""


class EntityNotFoundError(StoreError, KeyError):
    """Raised when an entity or requested revision does not exist."""


class EntityExistsError(StoreError):
    """Raised when creating an entity with an existing stable identifier."""


class RevisionConflictError(StoreError):
    """Raised when an update is based on a stale current revision."""


class PayloadError(StoreError, ValueError):
    """Raised for payloads that cannot be stored as JSON objects."""


def _payload_references_study_area(
    payload: Mapping[str, Any],
    *,
    study_area_id: str,
    geometry_sha256: str | Sequence[str],
) -> bool:
    """Return whether a current result explicitly depends on an old StudyArea.

    Generic ``geometry_sha256`` fields are intentionally ignored because they
    commonly describe an output geometry.  Only declared input/reference fields
    can make a result stale; this keeps the evaluator deterministic and avoids
    guessing from arbitrary model prose.
    """

    geometry_hashes = {geometry_sha256} if isinstance(geometry_sha256, str) else set(geometry_sha256)
    id_keys = {
        "study_area_id",
        "input_study_area_id",
        "study_area_ref",
        "study_area_reference",
    }
    hash_keys = {
        "study_area_geometry_sha256",
        "input_study_area_geometry_sha256",
        "study_area_hash",
        "input_study_area_hash",
        "geometry_input_sha256",
    }
    collection_keys = {
        "input_refs",
        "input_artifact_refs",
        "input_hashes",
        "input_artifact_hashes",
        "geometry_input_hashes",
        "study_area_refs",
    }

    def walk(value: Any, key: str | None = None) -> bool:
        if key in id_keys and value == study_area_id:
            return True
        if key in hash_keys and isinstance(value, str) and value in geometry_hashes:
            return True
        if key in collection_keys and isinstance(value, (list, tuple, set)):
            if study_area_id in value or any(item in geometry_hashes for item in value):
                return True
        if isinstance(value, Mapping):
            return any(walk(item, str(item_key)) for item_key, item in value.items())
        if isinstance(value, (list, tuple, set)):
            return any(walk(item, key) for item in value)
        return False

    return walk(payload)


@dataclass(frozen=True)
class StateRecord:
    """One immutable version of an entity's JSON payload."""

    entity_id: str
    entity_type: str
    revision: int
    payload: Mapping[str, Any]
    project_id: str | None
    created_at: str
    parent_revision: int | None
    supersedes: str | None
    event_id: str

    def __getitem__(self, key: str) -> Any:
        return self.payload[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)

    def __contains__(self, key: object) -> bool:
        return key in self.payload

    def as_dict(self) -> dict[str, Any]:
        """Return a detached copy of the payload."""

        return copy.deepcopy(dict(self.payload))

    def to_dict(self) -> dict[str, Any]:
        """Return payload and storage metadata for export or inspection."""

        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "revision": self.revision,
            "payload": self.as_dict(),
            "project_id": self.project_id,
            "created_at": self.created_at,
            "parent_revision": self.parent_revision,
            "supersedes": self.supersedes,
            "event_id": self.event_id,
        }


@dataclass(frozen=True)
class LedgerEvent:
    """An immutable Design Ledger event in commit order."""

    event_id: str
    sequence: int
    timestamp: str
    actor: str
    actor_kind: ActorKind | None
    actor_session_id: str | None
    action: str
    target_id: str
    target_type: str | None
    project_id: str | None
    prior_status: str | None
    changed_refs: tuple[str, ...]
    reason: str | None
    resulting_refs: tuple[str, ...]
    supersedes: str | None
    parent_event_id: str | None
    state_revision: int | None
    payload: Mapping[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "actor_kind": self.actor_kind.value if self.actor_kind is not None else None,
            "actor_session_id": self.actor_session_id,
            "action": self.action,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "project_id": self.project_id,
            "prior_status": self.prior_status,
            "changed_refs": list(self.changed_refs),
            "reason": self.reason,
            "resulting_refs": list(self.resulting_refs),
            "supersedes": self.supersedes,
            "parent_event_id": self.parent_event_id,
            "state_revision": self.state_revision,
            "payload": copy.deepcopy(dict(self.payload)),
        }


_P = ParamSpec("_P")
_R = TypeVar("_R")


def _serialized(
    method: Callable[Concatenate["ProjectStateStore", _P], _R],
) -> Callable[Concatenate["ProjectStateStore", _P], _R]:
    """Keep complete operations (including nested calls and transactions) atomic."""
    @wraps(method)
    def wrapped(self: ProjectStateStore, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapped


class _LockedSQLiteProxy:
    """Compatibility access without exposing an unsynchronized connection/cursor.

    Each call is serialized. Use locked_connection() for multi-call operations
    or transactions; never retain its raw connection outside the context.
    """

    def __init__(self, store: ProjectStateStore, target: sqlite3.Connection | sqlite3.Cursor):
        self._store = store
        self._target = target

    def __getattr__(self, name: str) -> Any:
        with self._store._lock:
            self._store._ensure_open()
            value = getattr(self._target, name)
            if not callable(value):
                if isinstance(value, (sqlite3.Connection, sqlite3.Cursor)):
                    return _LockedSQLiteProxy(self._store, value)
                return value

        def call(*args: Any, **kwargs: Any) -> Any:
            with self._store._lock:
                self._store._ensure_open()
                result = value(*args, **kwargs)
                if isinstance(result, (sqlite3.Connection, sqlite3.Cursor)):
                    return _LockedSQLiteProxy(self._store, result)
                return result
        return call

    def __iter__(self) -> _LockedSQLiteProxy:
        return self

    def __next__(self) -> Any:
        with self._store._lock:
            self._store._ensure_open()
            return next(self._target)


class ProjectStateStore:
    """SQLite state store with transactionally coupled ledger events."""

    SCHEMA_VERSION = "2"

    def __init__(
        self,
        database: str | Path,
        *,
        schema_version: str = SCHEMA_VERSION,
        read_only: bool = False,
    ):
        self._lock = threading.RLock()
        self.database = database
        self.schema_version = schema_version
        self.read_only = read_only
        use_uri = False
        if read_only:
            database_path = Path(database)
            if not database_path.is_file():
                raise FileNotFoundError(database_path)
            database_target: str | Path = f"{database_path.resolve().as_uri()}?mode=ro"
            use_uri = True
        elif isinstance(database, Path):
            if str(database) != ":memory:":
                database.parent.mkdir(parents=True, exist_ok=True)
            database_target: str | Path = str(database)
        else:
            database_target = database
            if database != ":memory:":
                Path(database).parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(
            database_target,
            isolation_level=None,
            check_same_thread=False,
            uri=use_uri,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        if not read_only and database_target != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize_schema()

    @property
    @_serialized
    def connection(self) -> _LockedSQLiteProxy:
        """Serialized compatibility interface; prefer locked_connection()."""
        self._ensure_open()
        return _LockedSQLiteProxy(self, self._connection)

    @contextmanager
    def locked_connection(self) -> Iterator[sqlite3.Connection]:
        """Hold the store lock across execute/fetch or an entire SQL transaction.

        The connection and its cursors must not escape this context.
        """
        with self._lock:
            self._ensure_open()
            yield self._connection

    @_serialized
    def close(self) -> None:
        if getattr(self, "_connection", None) is not None:
            self._connection.close()
            self._connection = None  # type: ignore[assignment]

    @_serialized
    def __enter__(self) -> ProjectStateStore:
        self._ensure_open()
        return self

    @_serialized
    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.close()

    @_serialized
    def _ensure_open(self) -> None:
        if self._connection is None:
            raise StoreError("project state store is closed")

    @_serialized
    def _initialize_schema(self) -> None:
        if self.read_only:
            tables = {
                row[0]
                for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if not {"state_heads", "state_versions", "ledger_events"}.issubset(tables):
                raise StoreError("read-only project database is missing required tables")
            return
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS store_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS state_heads (
                entity_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                project_id TEXT,
                current_revision INTEGER NOT NULL CHECK (current_revision > 0)
            );

            CREATE TABLE IF NOT EXISTS state_versions (
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision > 0),
                project_id TEXT,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                parent_revision INTEGER,
                supersedes TEXT,
                event_id TEXT NOT NULL UNIQUE,
                PRIMARY KEY (entity_id, revision),
                CHECK (parent_revision IS NULL OR parent_revision < revision)
            );

            CREATE TABLE IF NOT EXISTS ledger_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                timestamp TEXT NOT NULL,
                actor TEXT NOT NULL,
                actor_kind TEXT CHECK (
                    actor_kind IS NULL OR actor_kind IN (
                        'HUMAN_UI', 'QGIS_PLUGIN', 'AGENT_AUTOMATION', 'TEST_HARNESS'
                    )
                ),
                actor_session_id TEXT,
                action TEXT NOT NULL,
                target_id TEXT NOT NULL,
                target_type TEXT,
                project_id TEXT,
                prior_status TEXT,
                changed_refs_json TEXT NOT NULL,
                reason TEXT,
                resulting_refs_json TEXT NOT NULL,
                supersedes TEXT,
                parent_event_id TEXT,
                state_revision INTEGER,
                payload_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_state_versions_project
                ON state_versions (project_id, entity_id, revision);
            CREATE INDEX IF NOT EXISTS idx_ledger_events_project_sequence
                ON ledger_events (project_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_ledger_events_target_sequence
                ON ledger_events (target_id, sequence);

            CREATE TRIGGER IF NOT EXISTS state_versions_append_only_update
            BEFORE UPDATE ON state_versions
            BEGIN
                SELECT RAISE(ABORT, 'append-only state_versions');
            END;

            CREATE TRIGGER IF NOT EXISTS state_versions_append_only_delete
            BEFORE DELETE ON state_versions
            BEGIN
                SELECT RAISE(ABORT, 'append-only state_versions');
            END;

            CREATE TRIGGER IF NOT EXISTS ledger_events_append_only_update
            BEFORE UPDATE ON ledger_events
            BEGIN
                SELECT RAISE(ABORT, 'append-only ledger_events');
            END;

            CREATE TRIGGER IF NOT EXISTS ledger_events_append_only_delete
            BEFORE DELETE ON ledger_events
            BEGIN
                SELECT RAISE(ABORT, 'append-only ledger_events');
            END;
            """
        )
        event_columns = {
            row[1] for row in self._connection.execute("PRAGMA table_info(ledger_events)").fetchall()
        }
        if "actor_kind" not in event_columns:
            self._connection.execute("ALTER TABLE ledger_events ADD COLUMN actor_kind TEXT")
        if "actor_session_id" not in event_columns:
            self._connection.execute("ALTER TABLE ledger_events ADD COLUMN actor_session_id TEXT")
        self._connection.execute(
            "INSERT OR IGNORE INTO store_metadata(key, value) VALUES ('schema_version', ?)",
            (self.schema_version,),
        )
        self._connection.execute(
            "UPDATE store_metadata SET value = ? WHERE key = 'schema_version'",
            (self.schema_version,),
        )

    @staticmethod
    def _canonical_entity_type(entity_type: str) -> str:
        if not isinstance(entity_type, str) or not entity_type.strip():
            raise PayloadError("entity_type must be a non-empty string")
        stripped = entity_type.strip()
        canonical = _ENTITY_ALIASES.get(stripped.casefold(), stripped)
        if canonical not in CORE_ENTITY_TYPES:
            raise PayloadError(f"unsupported core entity type: {entity_type!r}")
        return canonical

    @staticmethod
    def _validate_id(value: str, *, field: str = "entity_id") -> str:
        if not isinstance(value, str) or not value.strip():
            raise PayloadError(f"{field} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _validate_actor(actor: str) -> str:
        if not isinstance(actor, str) or not actor.strip():
            raise PayloadError("actor must be a non-empty string")
        return actor.strip()

    @staticmethod
    def _validate_actor_kind(actor_kind: ActorKind | str | None) -> ActorKind | None:
        if actor_kind is None:
            return None
        try:
            return actor_kind if isinstance(actor_kind, ActorKind) else ActorKind(actor_kind)
        except (TypeError, ValueError) as exc:
            raise PayloadError("actor_kind must be HUMAN_UI, QGIS_PLUGIN, AGENT_AUTOMATION, or TEST_HARNESS") from exc

    @classmethod
    def _validate_actor_session_id(cls, actor_session_id: str | None) -> str | None:
        if actor_session_id is None:
            return None
        value = cls._validate_id(actor_session_id, field="actor_session_id")
        if len(value) > 128:
            raise PayloadError("actor_session_id must not exceed 128 characters")
        return value

    @staticmethod
    def _validate_action(action: str) -> str:
        if not isinstance(action, str) or not action.strip():
            raise PayloadError("action must be a non-empty string")
        return action.strip()

    @staticmethod
    def _payload_copy(payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise PayloadError("payload must be a JSON object")
        try:
            copied = copy.deepcopy(dict(payload))
            encoded = json.dumps(
                copied,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            decoded = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PayloadError("payload must contain JSON-serializable values") from exc
        if not isinstance(decoded, dict):
            raise PayloadError("payload must encode as a JSON object")
        return decoded

    @classmethod
    def _json(cls, value: Any) -> str:
        try:
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise PayloadError("value must be JSON-serializable") from exc

    @classmethod
    def _refs(cls, refs: Sequence[str] | None) -> tuple[str, ...]:
        if refs is None:
            return ()
        if isinstance(refs, str):
            refs = (refs,)
        cleaned: list[str] = []
        for ref in refs:
            cleaned.append(cls._validate_id(ref, field="reference"))
        return tuple(cleaned)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex}"

    @staticmethod
    def _payload_project_id(payload: Mapping[str, Any]) -> str | None:
        value = payload.get("project_id", payload.get("projectId"))
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise PayloadError("payload project_id must be a non-empty string")
        return value.strip()

    @classmethod
    def _resolve_project_id(
        cls,
        entity_id: str,
        entity_type: str,
        payload: Mapping[str, Any],
        project_id: str | None,
    ) -> str | None:
        explicit = cls._validate_id(project_id, field="project_id") if project_id is not None else None
        embedded = cls._payload_project_id(payload)
        if explicit is not None and embedded is not None and explicit != embedded:
            raise PayloadError("project_id argument does not match payload project_id")
        if explicit is not None:
            return explicit
        if embedded is not None:
            return embedded
        if entity_type == "Project":
            return entity_id
        return None

    @staticmethod
    def _status(payload: Mapping[str, Any]) -> str | None:
        status = payload.get("status", payload.get("human_status"))
        return status if isinstance(status, str) else None

    @_serialized
    def _begin(self) -> None:
        self._ensure_open()
        self._connection.execute("BEGIN IMMEDIATE")

    @_serialized
    def _rollback(self) -> None:
        if self._connection is not None and self._connection.in_transaction:
            self._connection.rollback()

    @_serialized
    def _record_from_row(self, row: sqlite3.Row) -> StateRecord:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StoreError("stored state payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise StoreError("stored state payload is not a JSON object")
        return StateRecord(
            entity_id=row["entity_id"],
            entity_type=row["entity_type"],
            revision=row["revision"],
            payload=payload,
            project_id=row["project_id"],
            created_at=row["created_at"],
            parent_revision=row["parent_revision"],
            supersedes=row["supersedes"],
            event_id=row["event_id"],
        )

    @_serialized
    def _event_from_row(self, row: sqlite3.Row) -> LedgerEvent:
        try:
            changed_refs = tuple(json.loads(row["changed_refs_json"]))
            resulting_refs = tuple(json.loads(row["resulting_refs_json"]))
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StoreError("stored ledger event contains invalid JSON") from exc
        if not isinstance(payload, dict):
            raise StoreError("stored ledger event payload is not a JSON object")
        columns = set(row.keys())
        actor_kind = row["actor_kind"] if "actor_kind" in columns else None
        actor_session_id = row["actor_session_id"] if "actor_session_id" in columns else None
        return LedgerEvent(
            event_id=row["event_id"],
            sequence=row["sequence"],
            timestamp=row["timestamp"],
            actor=row["actor"],
            actor_kind=ActorKind(actor_kind) if actor_kind is not None else None,
            actor_session_id=actor_session_id,
            action=row["action"],
            target_id=row["target_id"],
            target_type=row["target_type"],
            project_id=row["project_id"],
            prior_status=row["prior_status"],
            changed_refs=changed_refs,
            reason=row["reason"],
            resulting_refs=resulting_refs,
            supersedes=row["supersedes"],
            parent_event_id=row["parent_event_id"],
            state_revision=row["state_revision"],
            payload=payload,
        )

    @_serialized
    def _find_record(
        self,
        entity_id: str,
        revision: int | None = None,
        *,
        at_sequence: int | None = None,
    ) -> StateRecord:
        self._ensure_open()
        entity_id = self._validate_id(entity_id)
        if revision is not None and revision <= 0:
            raise PayloadError("revision must be a positive integer")
        if at_sequence is not None and at_sequence < 0:
            raise PayloadError("at_sequence must be non-negative")
        if revision is not None and at_sequence is not None:
            raise PayloadError("revision and at_sequence are mutually exclusive")

        if at_sequence is not None:
            row = self._connection.execute(
                """
                SELECT sv.*
                FROM state_versions AS sv
                JOIN ledger_events AS le ON le.event_id = sv.event_id
                WHERE sv.entity_id = ? AND le.sequence <= ?
                ORDER BY sv.revision DESC
                LIMIT 1
                """,
                (entity_id, at_sequence),
            ).fetchone()
        elif revision is not None:
            row = self._connection.execute(
                "SELECT * FROM state_versions WHERE entity_id = ? AND revision = ?",
                (entity_id, revision),
            ).fetchone()
        else:
            row = self._connection.execute(
                """
                SELECT sv.*
                FROM state_versions AS sv
                JOIN state_heads AS sh
                  ON sh.entity_id = sv.entity_id AND sh.current_revision = sv.revision
                WHERE sv.entity_id = ?
                """,
                (entity_id,),
            ).fetchone()
        if row is None:
            qualifier = f" revision {revision}" if revision is not None else ""
            raise EntityNotFoundError(f"entity {entity_id!r}{qualifier} does not exist")
        return self._record_from_row(row)

    @_serialized
    def _insert_state(
        self,
        *,
        entity_id: str,
        entity_type: str,
        revision: int,
        project_id: str | None,
        payload: Mapping[str, Any],
        parent_revision: int | None,
        supersedes: str | None,
        event_id: str,
    ) -> StateRecord:
        payload_copy = self._payload_copy(payload)
        created_at = self._timestamp()
        try:
            self._connection.execute(
                """
                INSERT INTO state_versions
                    (entity_id, entity_type, revision, project_id, payload_json,
                     created_at, parent_revision, supersedes, event_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_id,
                    entity_type,
                    revision,
                    project_id,
                    self._json(payload_copy),
                    created_at,
                    parent_revision,
                    supersedes,
                    event_id,
                ),
            )
            if parent_revision is None:
                self._connection.execute(
                    "INSERT INTO state_heads(entity_id, entity_type, project_id, current_revision) VALUES (?, ?, ?, ?)",
                    (entity_id, entity_type, project_id, revision),
                )
            else:
                self._connection.execute(
                    """
                    UPDATE state_heads
                    SET entity_type = ?, project_id = ?, current_revision = ?
                    WHERE entity_id = ? AND current_revision = ?
                    """,
                    (entity_type, project_id, revision, entity_id, parent_revision),
                )
                if self._connection.execute("SELECT changes()").fetchone()[0] != 1:
                    raise RevisionConflictError(
                        f"entity {entity_id!r} changed while this update was being applied"
                    )
        except sqlite3.IntegrityError as exc:
            if parent_revision is None:
                raise EntityExistsError(f"entity {entity_id!r} already exists") from exc
            raise

        row = self._connection.execute(
            "SELECT * FROM state_versions WHERE entity_id = ? AND revision = ?",
            (entity_id, revision),
        ).fetchone()
        if row is None:  # pragma: no cover
            raise StoreError("state revision was not persisted")
        return self._record_from_row(row)

    @_serialized
    def _append_ledger_event(
        self,
        *,
        event_id: str,
        timestamp: str,
        actor: str,
        action: str,
        target_id: str,
        target_type: str | None,
        project_id: str | None,
        prior_status: str | None,
        changed_refs: Sequence[str] | None,
        reason: str | None,
        resulting_refs: Sequence[str] | None,
        supersedes: str | None,
        parent_event_id: str | None,
        state_revision: int | None,
        payload: Mapping[str, Any] | None,
        actor_kind: ActorKind | str | None = None,
        actor_session_id: str | None = None,
    ) -> LedgerEvent:
        """Insert one event; callers own the surrounding transaction."""

        event_id = self._validate_id(event_id, field="event_id")
        actor = self._validate_actor(actor)
        actor_kind = self._validate_actor_kind(actor_kind)
        actor_session_id = self._validate_actor_session_id(actor_session_id)
        if actor_session_id is not None and actor_kind is None:
            raise PayloadError("actor_session_id requires actor_kind")
        action = self._validate_action(action)
        target_id = self._validate_id(target_id, field="target_id")
        changed = self._refs(changed_refs)
        resulting = self._refs(resulting_refs)
        event_payload = self._payload_copy(payload or {})
        self._connection.execute(
            """
            INSERT INTO ledger_events
                (event_id, timestamp, actor, actor_kind, actor_session_id, action, target_id, target_type,
                 project_id, prior_status, changed_refs_json, reason,
                 resulting_refs_json, supersedes, parent_event_id, state_revision,
                 payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                timestamp,
                actor,
                actor_kind.value if actor_kind is not None else None,
                actor_session_id,
                action,
                target_id,
                target_type,
                project_id,
                prior_status,
                self._json(list(changed)),
                reason,
                self._json(list(resulting)),
                supersedes,
                parent_event_id,
                state_revision,
                self._json(event_payload),
            ),
        )
        row = self._connection.execute(
            "SELECT * FROM ledger_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:  # pragma: no cover
            raise StoreError("ledger event was not persisted")
        return self._event_from_row(row)

    @_serialized
    def create(
        self,
        entity_type: str,
        payload: Mapping[str, Any],
        *,
        entity_id: str | None = None,
        project_id: str | None = None,
        actor: str = "system",
        action: str = "Create",
        reason: str | None = None,
        changed_refs: Sequence[str] | None = None,
        resulting_refs: Sequence[str] | None = None,
        supersedes: str | None = None,
        event_id: str | None = None,
        event_payload: Mapping[str, Any] | None = None,
        actor_kind: ActorKind | str | None = None,
        actor_session_id: str | None = None,
        decision_key: str | None = None,
        decision_key_path: str | Path | None = None,
    ) -> StateRecord:
        """Create an entity at revision one and append its create event."""

        canonical_type = self._canonical_entity_type(entity_type)
        if canonical_type == "HumanDecision":
            raise PayloadError("HumanDecision must be written through record_human_decision or authenticated commit_batch")
        entity_id = self._validate_id(entity_id or self._new_id(canonical_type.lower()))
        payload_copy = self._payload_copy(payload)
        actor_kind = self._validate_actor_kind(actor_kind)
        actor_session_id = self._validate_actor_session_id(actor_session_id)
        if actor_session_id is not None and actor_kind is None:
            raise PayloadError("actor_session_id requires actor_kind")
        self._authorize_entity_creation(
            canonical_type,
            payload_copy,
            actor_kind=actor_kind,
            actor_session_id=actor_session_id,
            decision_key=decision_key,
            decision_key_path=decision_key_path,
            actor=actor,
        )
        project_ref = self._resolve_project_id(entity_id, canonical_type, payload_copy, project_id)
        if canonical_type == "ProvenanceAnnotation":
            target_event_id = payload_copy.get("target_event_id")
            target_event = self._connection.execute(
                "SELECT project_id FROM ledger_events WHERE event_id = ?",
                (target_event_id,),
            ).fetchone()
            if target_event is None:
                raise PayloadError("provenance annotation target event does not exist")
            if target_event["project_id"] != project_ref:
                raise PayloadError("provenance annotation project does not match its target event")
        event_id = self._validate_id(event_id or self._new_id("event"), field="event_id")
        resulting = resulting_refs if resulting_refs is not None else (entity_id,)
        self._begin()
        try:
            record = self._insert_state(
                entity_id=entity_id,
                entity_type=canonical_type,
                revision=1,
                project_id=project_ref,
                payload=payload_copy,
                parent_revision=None,
                supersedes=supersedes,
                event_id=event_id,
            )
            self._append_ledger_event(
                event_id=event_id,
                timestamp=record.created_at,
                actor=actor,
                action=action,
                target_id=entity_id,
                target_type=canonical_type,
                project_id=project_ref,
                prior_status=None,
                changed_refs=changed_refs,
                reason=reason,
                resulting_refs=resulting,
                supersedes=supersedes,
                parent_event_id=None,
                state_revision=record.revision,
                payload=event_payload,
                actor_kind=actor_kind,
                actor_session_id=actor_session_id,
            )
            self._connection.commit()
            return record
        except BaseException:
            self._rollback()
            raise

    @staticmethod
    def _authorize_entity_creation(
        entity_type: str,
        payload: Mapping[str, Any],
        *,
        actor_kind: ActorKind | None,
        actor_session_id: str | None,
        decision_key: str | None,
        decision_key_path: str | Path | None,
        actor: str | None = None,
    ) -> None:
        if entity_type == "ConstraintSet" and actor_kind is ActorKind.AGENT_AUTOMATION:
            from urban_design.constraint_sets import validate_constraint_set_definition
            from urban_design.models import ConstraintSet

            try:
                validate_constraint_set_definition(
                    ConstraintSet.model_validate(payload), require_far_denominator=True,
                )
            except (TypeError, ValueError, ValidationError) as exc:
                raise PayloadError("AGENT_AUTOMATION may only create valid ConstraintSet drafts") from exc
        if entity_type != "HumanDecision":
            return
        if actor_kind is not ActorKind.HUMAN_UI:
            raise PayloadError("HumanDecision requires HUMAN_UI and a verified designer decision key")
        if payload.get("actor_kind") != ActorKind.HUMAN_UI.value:
            raise PayloadError("HumanDecision payload actor_kind must be HUMAN_UI")
        if actor_session_id is None or payload.get("actor_session_id") != actor_session_id:
            raise PayloadError("HumanDecision actor session must match its ledger event")
        if actor is not None and payload.get("actor") != actor:
            raise PayloadError("HumanDecision actor must match its ledger event")
        if not isinstance(decision_key, str):
            raise PayloadError("HumanDecision requires a verified designer decision key")
        try:
            verified = verify_decision_key_strict(decision_key, path=decision_key_path)
        except DecisionKeyUnavailable:
            raise PayloadError("designer decision key is unavailable") from None
        if not verified:
            raise PayloadError("HumanDecision requires a verified designer decision key")

    @_serialized
    def _validate_human_decision_target(
        self,
        payload: Mapping[str, Any],
        *,
        project_id: str | None,
    ) -> StateRecord:
        target_id = self._validate_id(payload.get("target_id"), field="decision target_id")
        try:
            target = self._find_record(target_id)
        except EntityNotFoundError:
            raise PayloadError("decision target was not found") from None
        if target.entity_type != payload.get("target_type"):
            raise PayloadError("decision target_type does not match the current target")
        if target.project_id != project_id:
            raise PayloadError("decision project_id does not match the current target")
        target_status = self._status(target.payload)
        if target_status is not None and target_status.upper() in {"STALE", "SUPERSEDED"}:
            raise PayloadError("decision target is stale or superseded")
        if target.entity_type == "ConstraintSet" and (target_status or "").casefold() != "proposed":
            raise PayloadError("decision target ConstraintSet is not a proposed draft")
        if target.entity_type == "DesignScenario" and (
            (payload.get("action") == "Reconsider" and (target_status or "").casefold() not in {"accepted", "rejected"})
            or (payload.get("action") != "Reconsider" and (target_status or "").casefold() != "proposed")
        ):
            raise PayloadError("decision target DesignScenario is not a proposed scenario")
        current_version = target.payload.get("version")
        if current_version is None:
            current_version = str(target.revision)
        if str(payload.get("target_version")) != str(current_version):
            raise PayloadError("decision target version is stale")

        head = self._connection.execute(
            "SELECT current_revision FROM state_heads WHERE entity_id = ?",
            (target.entity_id,),
        ).fetchone()
        if head and head[0] > target.revision:
            raise PayloadError("decision target version is stale")

        hashes = {
            "target_geometry_sha256": "geometry_sha256",
            "target_artifact_sha256": "artifact_sha256",
            "target_payload_digest": "payload_digest",
        }
        bound_hashes = [payload.get(field) for field in hashes]
        if not any(isinstance(value, str) and value for value in bound_hashes):
            raise PayloadError("decision must bind at least one current target hash")

        eda_geometry_hash = None
        if target.entity_type == "WorkspaceRevision":
            spatial_brief = target.payload.get("spatial_brief")
            if isinstance(spatial_brief, dict):
                eda = spatial_brief.get("exploration_design_area")
                if isinstance(eda, dict) and isinstance(eda.get("geometry"), dict):
                    from .geometry import canonical_geometry_hash
                    try:
                        eda_geometry_hash = canonical_geometry_hash(eda["geometry"])
                    except Exception:
                        eda_geometry_hash = None

        for decision_field, target_field in hashes.items():
            expected = payload.get(decision_field)
            if expected is None:
                continue
            if not isinstance(expected, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
                raise PayloadError(f"decision {decision_field} is malformed")
            target_value = target.payload.get(target_field)
            if target.entity_type == "Artifact" and decision_field == "target_artifact_sha256":
                target_value = target.payload.get("sha256")
            if target.entity_type == "ConstraintSet" and decision_field == "target_payload_digest":
                from urban_design.constraint_sets import constraint_set_payload_digest

                try:
                    target_value = constraint_set_payload_digest(target.payload)
                except (TypeError, ValueError) as exc:
                    raise PayloadError("ConstraintSet decision target definition is invalid") from exc
            target_norm = (
                f"sha256:{target_value}"
                if isinstance(target_value, str) and not target_value.startswith("sha256:")
                else target_value
            )
            target_value_matches = (target_value == expected or target_norm == expected)
            if target.entity_type == "ParameterDefinition":
                evidence_refs = target.payload.get("evidence_refs")
                target_value_matches = isinstance(evidence_refs, list) and expected in evidence_refs
            elif target.entity_type == "WorkspaceRevision":
                if decision_field == "target_geometry_sha256":
                    target_value_matches = (expected == eda_geometry_hash or expected == target_norm)
                elif decision_field in ("target_payload_digest", "target_artifact_sha256"):
                    target_value_matches = (expected == target_norm)
            if not target_value_matches:
                raise PayloadError(f"decision {decision_field} does not match the current target")
        return target

    @_serialized
    def create_project(
        self,
        payload: Mapping[str, Any] | str | None = None,
        project_id: str | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> StateRecord:
        """Create a ``Project``; accepts both common argument orderings."""

        if isinstance(payload, str):
            if isinstance(project_id, Mapping):
                payload, project_id = project_id, payload
            elif project_id is None:
                project_id, payload = payload, {}
        if payload is None:
            payload = {}
        if project_id is not None and not isinstance(project_id, str):
            raise PayloadError("project_id must be a string")
        return self.create("Project", payload, entity_id=project_id, project_id=project_id, **kwargs)

    @_serialized
    def create_typed(self, record: Any, **kwargs: Any) -> StateRecord:
        """Persist a validated Pydantic domain record.

        The low-level ``create`` method intentionally remains useful for
        migration and failure fixtures. Production callers can use this entry
        point to ensure serialization starts from a validated typed model.
        """
        model_dump = getattr(record, "model_dump", None)
        entity_id = getattr(record, "id", None)
        if (
            not isinstance(record, BaseModel)
            or not callable(model_dump)
            or not isinstance(entity_id, str)
            or not entity_id.strip()
        ):
            raise PayloadError("create_typed requires a validated domain model with an id")
        payload = model_dump(mode="json")
        entity_type = type(record).__name__
        project_id = getattr(record, "project_id", None)
        return self.create(
            entity_type,
            payload,
            entity_id=entity_id,
            project_id=project_id,
            **kwargs,
        )

    @_serialized
    def commit_batch(
        self,
        *,
        entities: Sequence[Mapping[str, Any]],
        events: Sequence[Mapping[str, Any]],
        before_commit: Callable[[], None] | None = None,
        decision_key: str | None = None,
        decision_key_path: str | Path | None = None,
    ) -> tuple[list[StateRecord], list[LedgerEvent]]:
        """Atomically persist a batch of immutable state and ledger records.

        ``before_commit`` runs while the SQLite transaction is still open.
        Callers use it for the final filesystem publication and verification;
        any exception rolls the transaction back.  Existing records are
        accepted only when their immutable payload matches, which makes a
        retry of the same package idempotent without hiding corruption.
        """

        if not isinstance(entities, Sequence) or not isinstance(events, Sequence):
            raise PayloadError("commit_batch entities and events must be sequences")
        state_records: list[StateRecord] = []
        ledger_events: list[LedgerEvent] = []
        batch_decisions: list[tuple[str, Mapping[str, Any], str | None]] = []
        self._begin()
        try:
            for specification in entities:
                if not isinstance(specification, Mapping):
                    raise PayloadError("commit_batch entity specification must be an object")
                entity_id = self._validate_id(specification.get("entity_id"), field="entity_id")
                entity_type = self._canonical_entity_type(specification.get("entity_type", ""))
                payload = self._payload_copy(specification.get("payload", {}))
                if entity_type == "HumanDecision":
                    try:
                        payload = self._payload_copy(HumanDecision.model_validate(payload).model_dump(mode="json"))
                    except ValidationError as exc:
                        raise PayloadError("commit_batch HumanDecision payload is invalid") from exc
                actor_kind = self._validate_actor_kind(specification.get("actor_kind"))
                actor_session_id = self._validate_actor_session_id(specification.get("actor_session_id"))
                if actor_session_id is not None and actor_kind is None:
                    raise PayloadError("actor_session_id requires actor_kind")
                self._authorize_entity_creation(
                    entity_type,
                    payload,
                    actor_kind=actor_kind,
                    actor_session_id=actor_session_id,
                    decision_key=decision_key,
                    decision_key_path=decision_key_path,
                    actor=specification.get("actor"),
                )
                project_id = self._resolve_project_id(
                    entity_id,
                    entity_type,
                    payload,
                    specification.get("project_id"),
                )
                if entity_type == "HumanDecision":
                    batch_decisions.append((entity_id, payload, project_id))
                event_id = self._validate_id(specification.get("event_id"), field="event_id")
                try:
                    current = self._find_record(entity_id)
                except EntityNotFoundError:
                    current = None
                if entity_type == "HumanDecision":
                    self._validate_human_decision_target(payload, project_id=project_id)
                if current is not None:
                    if (
                        current.entity_type != entity_type
                        or current.project_id != project_id
                        or current.payload != payload
                        or current.revision != 1
                        or current.event_id != event_id
                    ):
                        raise EntityExistsError(
                            f"entity {entity_id!r} already exists with different immutable content"
                        )
                    state_records.append(current)
                    continue
                record = self._insert_state(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    revision=1,
                    project_id=project_id,
                    payload=payload,
                    parent_revision=None,
                    supersedes=specification.get("supersedes"),
                    event_id=event_id,
                )
                self._append_ledger_event(
                    event_id=event_id,
                    timestamp=specification.get("timestamp") or record.created_at,
                    actor=specification.get("actor", "system"),
                    action=specification.get("action", "Create"),
                    target_id=entity_id,
                    target_type=entity_type,
                    project_id=project_id,
                    prior_status=None,
                    changed_refs=specification.get("changed_refs"),
                    reason=specification.get("reason"),
                    resulting_refs=specification.get("resulting_refs") or (entity_id,),
                    supersedes=specification.get("supersedes"),
                    parent_event_id=None,
                    state_revision=record.revision,
                    payload=specification.get("event_payload"),
                    actor_kind=actor_kind,
                    actor_session_id=actor_session_id,
                )
                state_records.append(record)

            for decision_id, payload, project_id in batch_decisions:
                approval_event_id = self._validate_id(
                    payload.get("decision_event_id"), field="HumanDecision decision_event_id"
                )
                matching_events = [
                    event for event in events
                    if isinstance(event, Mapping) and event.get("event_id") == approval_event_id
                ]
                if len(matching_events) != 1:
                    raise PayloadError("batch HumanDecision requires exactly one matching approval event")
                approval = matching_events[0]
                approval_payload = self._payload_copy(approval.get("payload") or {})
                approval_timestamp = approval.get("timestamp")
                if isinstance(approval_timestamp, datetime):
                    approval_timestamp = approval_timestamp.isoformat()

                def event_binds_hash(value: Any, expected: str) -> bool:
                    if value == expected:
                        return True
                    if isinstance(value, Mapping):
                        return any(event_binds_hash(child, expected) for child in value.values())
                    if isinstance(value, (list, tuple, set)):
                        return any(event_binds_hash(child, expected) for child in value)
                    return False

                target_hashes_bound = all(
                    expected is None or event_binds_hash(approval_payload, expected)
                    for expected in (
                        payload.get("target_geometry_sha256"),
                        payload.get("target_artifact_sha256"),
                    )
                )
                if (
                    approval.get("action") != payload.get("action")
                    or approval.get("target_id") != decision_id
                    or approval.get("target_type") != "HumanDecision"
                    or approval.get("project_id") != project_id
                    or str(approval_timestamp) != str(payload.get("timestamp"))
                    or approval.get("actor") != payload.get("actor")
                    or self._validate_actor_kind(approval.get("actor_kind")) is not ActorKind.HUMAN_UI
                    or self._validate_actor_session_id(approval.get("actor_session_id"))
                    != payload.get("actor_session_id")
                    or approval.get("reason") != payload.get("reason")
                    or not target_hashes_bound
                ):
                    raise PayloadError("batch HumanDecision approval event does not match the decision")

            for specification in events:
                if not isinstance(specification, Mapping):
                    raise PayloadError("commit_batch event specification must be an object")
                event_id = self._validate_id(specification.get("event_id"), field="event_id")
                existing_row = self._connection.execute(
                    "SELECT * FROM ledger_events WHERE event_id = ?", (event_id,)
                ).fetchone()
                if existing_row is not None:
                    existing = self._event_from_row(existing_row)
                    expected = {
                        "actor": specification.get("actor", "system"),
                        "actor_kind": self._validate_actor_kind(specification.get("actor_kind")),
                        "actor_session_id": self._validate_actor_session_id(specification.get("actor_session_id")),
                        "action": specification.get("action", "Create"),
                        "target_id": specification.get("target_id"),
                        "target_type": specification.get("target_type"),
                        "project_id": specification.get("project_id"),
                        "payload": self._payload_copy(specification.get("payload") or {}),
                    }
                    if (
                        existing.actor != expected["actor"]
                        or existing.actor_kind != expected["actor_kind"]
                        or existing.actor_session_id != expected["actor_session_id"]
                        or existing.action != expected["action"]
                        or existing.target_id != expected["target_id"]
                        or existing.target_type != expected["target_type"]
                        or existing.project_id != expected["project_id"]
                        or existing.payload != expected["payload"]
                    ):
                        raise EntityExistsError(
                            f"ledger event {event_id!r} already exists with different immutable content"
                        )
                    ledger_events.append(existing)
                    continue
                ledger_events.append(
                    self._append_ledger_event(
                        event_id=event_id,
                        timestamp=specification.get("timestamp") or self._timestamp(),
                        actor=specification.get("actor", "system"),
                        action=specification.get("action", "Create"),
                        target_id=specification.get("target_id"),
                        target_type=specification.get("target_type"),
                        project_id=specification.get("project_id"),
                        prior_status=specification.get("prior_status"),
                        changed_refs=specification.get("changed_refs"),
                        reason=specification.get("reason"),
                        resulting_refs=specification.get("resulting_refs"),
                        supersedes=specification.get("supersedes"),
                        parent_event_id=specification.get("parent_event_id"),
                        state_revision=specification.get("state_revision"),
                        payload=specification.get("payload"),
                        actor_kind=specification.get("actor_kind"),
                        actor_session_id=specification.get("actor_session_id"),
                    )
                )
            if before_commit is not None:
                before_commit()
            self._connection.commit()
            return state_records, ledger_events
        except BaseException:
            self._rollback()
            raise

    @_serialized
    def confirm_study_area(
        self,
        study_area_payload: Mapping[str, Any],
        *,
        project_id: str,
        actor: str,
        reason: str,
        confirmation_event_id: str,
        activation_event_id: str | None = None,
        supersedes_id: str | None = None,
        artifact_payload: Mapping[str, Any] | BaseModel | None = None,
        confirmation_payload: Mapping[str, Any] | None = None,
        actor_kind: ActorKind | str | None = None,
        actor_session_id: str | None = None,
    ) -> StateRecord:
        """Commit StudyArea confirmation, activation, and stale marking atomically.

        The typed workflow validates the payload and artifact before calling
        this backend primitive.  This method owns the transaction so a failure
        cannot leave a confirmed StudyArea without the corresponding project
        pointer or ledger event.
        """

        if hasattr(study_area_payload, "model_dump"):
            study_area_payload = study_area_payload.model_dump(mode="json")  # type: ignore[union-attr]
        payload = self._payload_copy(study_area_payload)
        if hasattr(artifact_payload, "model_dump"):
            artifact_payload = artifact_payload.model_dump(mode="json")  # type: ignore[union-attr]
        artifact_copy = self._payload_copy(artifact_payload) if artifact_payload is not None else None
        confirmation_metadata = self._payload_copy(confirmation_payload or {})
        project_id = self._validate_id(project_id, field="project_id")
        actor = self._validate_actor(actor)
        actor_kind = self._validate_actor_kind(actor_kind)
        actor_session_id = self._validate_actor_session_id(actor_session_id)
        if actor_session_id is not None and actor_kind is None:
            raise PayloadError("actor_session_id requires actor_kind")
        if not isinstance(reason, str) or not reason.strip():
            raise PayloadError("study area confirmation reason must be non-empty")
        confirmation_event_id = self._validate_id(confirmation_event_id, field="confirmation_event_id")
        activation_event_id = self._validate_id(
            activation_event_id or self._new_id("activate-study-area"),
            field="activation_event_id",
        )
        study_area_id = self._validate_id(payload.get("id"), field="study_area_id")
        embedded_project = self._payload_project_id(payload)
        if embedded_project is not None and embedded_project != project_id:
            raise PayloadError("study area project_id does not match project_id")
        geometry_sha256 = payload.get("geometry_sha256", payload.get("geometry_hash"))
        if not isinstance(geometry_sha256, str) or not geometry_sha256.strip():
            raise PayloadError("study area geometry_sha256 is required")
        previous_id = supersedes_id or payload.get("supersedes_id")
        if previous_id is not None:
            previous_id = self._validate_id(previous_id, field="supersedes_id")
        artifact_id = payload.get("geometry_artifact_id", payload.get("geometry_artifact"))
        artifact_id = self._validate_id(artifact_id, field="geometry_artifact_id")
        if artifact_copy is not None:
            supplied_artifact_id = self._validate_id(artifact_copy.get("id"), field="artifact_id")
            if supplied_artifact_id != artifact_id:
                raise PayloadError("artifact payload id must match StudyArea geometry_artifact_id")

        self._begin()
        try:
            project = self._find_record(project_id)
            if project.entity_type != "Project":
                raise PayloadError(f"{project_id!r} is not a Project entity")
            active_id = project.get("active_study_area_id")
            if previous_id is None and active_id:
                previous_id = self._validate_id(active_id, field="supersedes_id")
            if previous_id == study_area_id:
                raise PayloadError("a StudyArea cannot supersede itself")

            previous = None
            if previous_id is not None:
                previous = self._find_record(previous_id)
                if previous.entity_type != "StudyArea":
                    raise PayloadError("supersedes_id must reference a StudyArea")
                if previous.project_id != project_id:
                    raise PayloadError("superseded StudyArea belongs to another project")
                if active_id and active_id != previous_id:
                    raise PayloadError("supersedes_id must match the project's active StudyArea")

            version = payload.get("version")
            if not isinstance(version, str) or not version.strip():
                raise PayloadError("study area version is required")
            existing_area_rows = self._connection.execute(
                """
                SELECT sv.entity_id, sv.payload_json
                FROM state_versions AS sv
                JOIN state_heads AS sh
                  ON sh.entity_id = sv.entity_id AND sh.current_revision = sv.revision
                WHERE sv.project_id = ? AND sv.entity_type = 'StudyArea'
                """,
                (project_id,),
            ).fetchall()
            for existing_row in existing_area_rows:
                if existing_row["entity_id"] == study_area_id:
                    raise EntityExistsError(f"StudyArea {study_area_id!r} already exists")
                try:
                    existing_payload = json.loads(existing_row["payload_json"])
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise StoreError("stored StudyArea payload is not valid JSON") from exc
                if (
                    isinstance(existing_payload, Mapping)
                    and str(existing_payload.get("version", "")).casefold() == version.strip().casefold()
                ):
                    raise PayloadError(f"StudyArea version {version!r} already exists in this project")

            # A confirmed StudyArea may never point at a missing or unrelated
            # artifact.  Registration is part of this same transaction as the
            # confirmation and activation events.
            artifact_record: StateRecord
            current_artifact = None
            try:
                current_artifact = self._find_record(artifact_id)
            except EntityNotFoundError:
                current_artifact = None
            if artifact_copy is not None:
                required = {
                    "project_id": project_id,
                    "type": "study_area_geometry",
                    "mime": "application/geo+json",
                    "sha256": artifact_copy.get("sha256"),
                    "size_bytes": artifact_copy.get("size_bytes"),
                    "crs": artifact_copy.get("crs"),
                    "producer": artifact_copy.get("producer"),
                    "uri": artifact_copy.get("uri"),
                }
                if not isinstance(required["sha256"], str) or not required["sha256"].strip():
                    raise PayloadError("artifact payload sha256 is required")
                if not isinstance(required["uri"], str) or not required["uri"].strip():
                    raise PayloadError("artifact payload uri is required")
                if not isinstance(required["mime"], str) or required["mime"].casefold() != "application/geo+json":
                    raise PayloadError("artifact payload MIME must be application/geo+json")
                if not isinstance(required["producer"], str) or required["producer"].casefold() != "qgis":
                    raise PayloadError("artifact payload producer must be QGIS")
                if required["size_bytes"] is None or not isinstance(required["size_bytes"], int) or required["size_bytes"] < 0:
                    raise PayloadError("artifact payload size_bytes must be a non-negative integer")
                if not isinstance(required["crs"], str) or not required["crs"].strip():
                    raise PayloadError("artifact payload crs is required")
                if current_artifact is not None:
                    if current_artifact.entity_type != "Artifact":
                        raise PayloadError("geometry_artifact_id must reference an Artifact")
                    existing_artifact = current_artifact.as_dict()
                    if existing_artifact.get("id") != artifact_id:
                        raise PayloadError("persisted Artifact id does not match its state identity")
                    for key, expected in required.items():
                        existing_value = existing_artifact.get(key)
                        if key in {"type", "mime", "producer"}:
                            matches = (
                                isinstance(existing_value, str)
                                and isinstance(expected, str)
                                and existing_value.casefold() == expected.casefold()
                            )
                        else:
                            matches = existing_value == expected
                        if not matches:
                            raise PayloadError(f"persisted Artifact {key} does not match the validated payload")
                    artifact_record = current_artifact
                else:
                    artifact_event_id = self._new_id("register-artifact")
                    artifact_record = self._insert_state(
                        entity_id=artifact_id,
                        entity_type="Artifact",
                        revision=1,
                        project_id=project_id,
                        payload=artifact_copy,
                        parent_revision=None,
                        supersedes=None,
                        event_id=artifact_event_id,
                    )
                    self._append_ledger_event(
                        event_id=artifact_event_id,
                        timestamp=artifact_record.created_at,
                        actor=actor,
                        action="Create",
                        target_id=artifact_id,
                        target_type="Artifact",
                        project_id=project_id,
                        prior_status=None,
                        changed_refs=(artifact_id,),
                        reason="register validated Study Area artifact",
                        resulting_refs=(artifact_id,),
                        supersedes=None,
                        parent_event_id=project.event_id,
                        state_revision=artifact_record.revision,
                        payload={
                            "artifact_id": artifact_id,
                            "sha256": artifact_copy.get("sha256"),
                            "size_bytes": artifact_copy.get("size_bytes"),
                            "mime": artifact_copy.get("mime"),
                            "crs": artifact_copy.get("crs"),
                        },
                        actor_kind=actor_kind,
                        actor_session_id=actor_session_id,
                    )
            else:
                if current_artifact is None or current_artifact.entity_type != "Artifact":
                    raise PayloadError("StudyArea geometry_artifact_id must resolve to an Artifact")
                artifact_record = current_artifact
            if artifact_record.project_id != project_id:
                raise PayloadError("Study Area Artifact belongs to another project")

            study_area_record = self._insert_state(
                entity_id=study_area_id,
                entity_type="StudyArea",
                revision=1,
                project_id=project_id,
                payload=payload,
                parent_revision=None,
                supersedes=previous.event_id if previous is not None else None,
                event_id=confirmation_event_id,
            )
            self._append_ledger_event(
                event_id=confirmation_event_id,
                timestamp=study_area_record.created_at,
                actor=actor,
                action="ConfirmStudyArea",
                target_id=study_area_id,
                target_type="StudyArea",
                project_id=project_id,
                prior_status=None,
                changed_refs=(study_area_id,),
                reason=reason.strip(),
                resulting_refs=(study_area_id,),
                supersedes=previous.event_id if previous is not None else None,
                parent_event_id=previous.event_id if previous is not None else project.event_id,
                state_revision=study_area_record.revision,
                payload={
                    **confirmation_metadata,
                    "confirmation": "CONFIRMED_FOR_EXPLORATION",
                    "study_area_id": study_area_id,
                    "geometry_sha256": geometry_sha256,
                    "supersedes_id": previous_id,
                },
                actor_kind=actor_kind,
                actor_session_id=actor_session_id,
            )

            stale_ids: list[str] = []
            if previous is not None:
                previous_payload = previous.as_dict()
                previous_payload["status"] = "SUPERSEDED"
                previous_payload["superseded_by_id"] = study_area_id
                previous_revision = previous.revision + 1
                previous_event_id = self._new_id("supersede-study-area")
                superseded = self._insert_state(
                    entity_id=previous.entity_id,
                    entity_type=previous.entity_type,
                    revision=previous_revision,
                    project_id=previous.project_id,
                    payload=previous_payload,
                    parent_revision=previous.revision,
                    supersedes=previous.event_id,
                    event_id=previous_event_id,
                )
                self._append_ledger_event(
                    event_id=previous_event_id,
                    timestamp=superseded.created_at,
                    actor=actor,
                    action="SupersedeStudyArea",
                    target_id=previous.entity_id,
                    target_type="StudyArea",
                    project_id=project_id,
                    prior_status=self._status(previous.payload),
                    changed_refs=(previous.entity_id, study_area_id),
                    reason="superseded by a newer confirmed StudyArea",
                    resulting_refs=(study_area_id,),
                    supersedes=previous.event_id,
                    parent_event_id=previous.event_id,
                    state_revision=superseded.revision,
                    payload={"superseded_by_id": study_area_id},
                    actor_kind=actor_kind,
                    actor_session_id=actor_session_id,
                )

                # Mark only records that explicitly declare the old geometry or
                # StudyArea as an input.  Historical revisions remain intact.
                rows = self._connection.execute(
                    """
                    SELECT sv.*
                    FROM state_versions AS sv
                    JOIN state_heads AS sh
                      ON sh.entity_id = sv.entity_id AND sh.current_revision = sv.revision
                    WHERE sv.project_id = ?
                    ORDER BY sv.entity_id
                    """,
                    (project_id,),
                ).fetchall()
                for row in rows:
                    current = self._record_from_row(row)
                    if current.entity_id in {previous.entity_id, study_area_id}:
                        continue
                    if current.entity_type in {"Project", "Artifact", "StudyArea", "DesignBoundary"}:
                        continue
                    if not _payload_references_study_area(
                        current.payload,
                        study_area_id=previous.entity_id,
                        geometry_sha256=tuple(
                            value
                            for value in (
                                previous.get("geometry_sha256"),
                                previous.get("artifact_sha256"),
                            )
                            if isinstance(value, str) and value
                        ),
                    ):
                        continue
                    stale_payload = current.as_dict()
                    if stale_payload.get("status") not in {"STALE", "stale"}:
                        stale_payload["status"] = "STALE"
                    stale_payload["stale_reason"] = "depends on superseded StudyArea geometry"
                    stale_payload["stale_geometry_sha256"] = previous.get("geometry_sha256")
                    stale_event_id = self._new_id("stale-study-area")
                    stale_record = self._insert_state(
                        entity_id=current.entity_id,
                        entity_type=current.entity_type,
                        revision=current.revision + 1,
                        project_id=current.project_id,
                        payload=stale_payload,
                        parent_revision=current.revision,
                        supersedes=current.event_id,
                        event_id=stale_event_id,
                    )
                    self._append_ledger_event(
                        event_id=stale_event_id,
                        timestamp=stale_record.created_at,
                        actor="system",
                        action="MarkStale",
                        target_id=current.entity_id,
                        target_type=current.entity_type,
                        project_id=project_id,
                        prior_status=self._status(current.payload),
                        changed_refs=(current.entity_id, previous.entity_id),
                        reason="StudyArea geometry version changed; rerun required",
                        resulting_refs=(current.entity_id,),
                        supersedes=current.event_id,
                        parent_event_id=confirmation_event_id,
                        state_revision=stale_record.revision,
                        payload={
                            "study_area_id": previous.entity_id,
                            "geometry_sha256": previous.get("geometry_sha256"),
                            "requires_rerun": True,
                        },
                        actor_kind=ActorKind.AGENT_AUTOMATION,
                        actor_session_id=actor_session_id,
                    )
                    stale_ids.append(current.entity_id)

            project_payload = project.as_dict()
            project_payload["active_study_area_id"] = study_area_id
            project_revision = project.revision + 1
            project_record = self._insert_state(
                entity_id=project.entity_id,
                entity_type="Project",
                revision=project_revision,
                project_id=project.project_id or project.entity_id,
                payload=project_payload,
                parent_revision=project.revision,
                supersedes=project.event_id,
                event_id=activation_event_id,
            )
            self._append_ledger_event(
                event_id=activation_event_id,
                timestamp=project_record.created_at,
                actor=actor,
                action="ActivateStudyArea",
                target_id=project.entity_id,
                target_type="Project",
                project_id=project_id,
                prior_status=self._status(project.payload),
                changed_refs=(project.entity_id, study_area_id),
                reason="confirmed StudyArea is active for exploration",
                resulting_refs=(study_area_id,),
                supersedes=project.event_id,
                parent_event_id=confirmation_event_id,
                state_revision=project_record.revision,
                payload={
                    "active_study_area_id": study_area_id,
                    "confirmation_event_id": confirmation_event_id,
                    "geometry_sha256": geometry_sha256,
                    "stale_entity_ids": stale_ids,
                },
                actor_kind=actor_kind,
                actor_session_id=actor_session_id,
            )
            self._connection.commit()
            return study_area_record
        except BaseException:
            self._rollback()
            raise

    @_serialized
    def update(
        self,
        entity_id: str,
        payload_or_updater: Mapping[str, Any] | Updater,
        *,
        expected_revision: int | None = None,
        actor: str = "system",
        action: str = "Update",
        reason: str | None = None,
        changed_refs: Sequence[str] | None = None,
        resulting_refs: Sequence[str] | None = None,
        supersedes: str | None = None,
        event_id: str | None = None,
        event_payload: Mapping[str, Any] | None = None,
        replace: bool = False,
        before_commit: Callable[[], None] | None = None,
        actor_kind: ActorKind | str | None = None,
        actor_session_id: str | None = None,
    ) -> StateRecord:
        """Write a new revision and event as one transaction.

        A mapping is a shallow patch by default, preserving fields not
        mentioned by the caller. Pass ``replace=True`` for a complete JSON
        replacement. A callable receives a detached mutable copy and may
        mutate it in place or return a replacement mapping.
        """

        entity_id = self._validate_id(entity_id)
        event_id = self._validate_id(event_id or self._new_id("event"), field="event_id")
        actor_kind = self._validate_actor_kind(actor_kind)
        actor_session_id = self._validate_actor_session_id(actor_session_id)
        if actor_session_id is not None and actor_kind is None:
            raise PayloadError("actor_session_id requires actor_kind")
        self._begin()
        try:
            current = self._find_record(entity_id)
            if current.entity_type == "ConstraintSet" and actor_kind is ActorKind.AGENT_AUTOMATION:
                raise PayloadError("AGENT_AUTOMATION cannot approve, activate, deactivate or update ConstraintSet")
            if current.entity_type in {"HumanDecision", "ProvenanceAnnotation"}:
                raise PayloadError(f"{current.entity_type} records are immutable")
            if expected_revision is not None and current.revision != expected_revision:
                raise RevisionConflictError(
                    f"entity {entity_id!r} is at revision {current.revision}, expected {expected_revision}"
                )
            current_payload = current.as_dict()
            if callable(payload_or_updater):
                candidate = payload_or_updater(copy.deepcopy(current_payload))
                next_payload = current_payload if candidate is None else candidate
            elif isinstance(payload_or_updater, Mapping):
                next_payload = (
                    dict(payload_or_updater)
                    if replace
                    else {**current_payload, **dict(payload_or_updater)}
                )
            else:
                raise PayloadError("update payload must be a JSON object or callable")
            next_payload = self._payload_copy(next_payload)
            embedded_project = self._payload_project_id(next_payload)
            if embedded_project is not None and embedded_project != current.project_id:
                raise PayloadError("an entity's project_id cannot change between revisions")
            if current.project_id is not None and embedded_project is None:
                next_project = current.project_id
            else:
                next_project = embedded_project
            revision = current.revision + 1
            supersedes_ref = supersedes if supersedes is not None else current.event_id
            record = self._insert_state(
                entity_id=entity_id,
                entity_type=current.entity_type,
                revision=revision,
                project_id=next_project,
                payload=next_payload,
                parent_revision=current.revision,
                supersedes=supersedes_ref,
                event_id=event_id,
            )
            self._append_ledger_event(
                event_id=event_id,
                timestamp=record.created_at,
                actor=actor,
                action=action,
                target_id=entity_id,
                target_type=current.entity_type,
                project_id=next_project,
                prior_status=self._status(current.payload),
                changed_refs=changed_refs,
                reason=reason,
                resulting_refs=resulting_refs if resulting_refs is not None else (entity_id,),
                supersedes=supersedes_ref,
                parent_event_id=current.event_id,
                state_revision=record.revision,
                payload=event_payload,
                actor_kind=actor_kind,
                actor_session_id=actor_session_id,
            )
            if before_commit is not None:
                before_commit()
            self._connection.commit()
            return record
        except BaseException:
            self._rollback()
            raise

    @_serialized
    def update_project(self, project_id: str, payload_or_updater: Mapping[str, Any] | Updater, **kwargs: Any) -> StateRecord:
        return self.update(project_id, payload_or_updater, **kwargs)

    @_serialized
    def current(self, entity_id: str) -> StateRecord:
        return self._find_record(entity_id)

    get_current = current
    get = current

    @_serialized
    def get_record(self, entity_id: str, revision: int | None = None) -> StateRecord:
        return self._find_record(entity_id, revision)

    @_serialized
    def list_current(
        self,
        entity_type: str | None = None,
        project_id: str | None = None,
    ) -> list[StateRecord]:
        """List current head revisions of entities, optionally filtered by type and project."""
        self._ensure_open()
        query = """
            SELECT sv.*
            FROM state_versions AS sv
            JOIN state_heads AS sh
              ON sh.entity_id = sv.entity_id AND sh.current_revision = sv.revision
            WHERE 1=1
        """
        params: list[Any] = []
        if entity_type is not None:
            query += " AND sh.entity_type = ?"
            params.append(self._canonical_entity_type(entity_type))
        if project_id is not None:
            query += " AND sh.project_id = ?"
            params.append(self._validate_id(project_id, field="project_id"))
        query += " ORDER BY sv.entity_id ASC"
        rows = self._connection.execute(query, params).fetchall()
        return [self._record_from_row(row) for row in rows]

    @_serialized
    def history(self, entity_id: str) -> list[StateRecord]:
        entity_id = self._validate_id(entity_id)
        rows = self._connection.execute(
            "SELECT * FROM state_versions WHERE entity_id = ? ORDER BY revision ASC",
            (entity_id,),
        ).fetchall()
        if not rows:
            raise EntityNotFoundError(f"entity {entity_id!r} does not exist")
        return [self._record_from_row(row) for row in rows]

    @_serialized
    def append_ledger_event(
        self,
        *,
        target_id: str,
        actor: str,
        action: str,
        project_id: str | None = None,
        target_type: str | None = None,
        prior_status: str | None = None,
        changed_refs: Sequence[str] | None = None,
        reason: str | None = None,
        resulting_refs: Sequence[str] | None = None,
        supersedes: str | None = None,
        parent_event_id: str | None = None,
        state_revision: int | None = None,
        payload: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        timestamp: str | None = None,
        actor_kind: ActorKind | str | None = None,
        actor_session_id: str | None = None,
    ) -> LedgerEvent:
        """Append a standalone contest/audit event transactionally."""

        target_id = self._validate_id(target_id, field="target_id")
        event_id = self._validate_id(event_id or self._new_id("event"), field="event_id")
        target = None
        try:
            target = self.current(target_id)
        except EntityNotFoundError:
            pass
        if target is not None:
            target_type = target_type or target.entity_type
            project_id = project_id if project_id is not None else target.project_id
            prior_status = prior_status if prior_status is not None else self._status(target.payload)
            state_revision = state_revision if state_revision is not None else target.revision
        self._begin()
        try:
            event = self._append_ledger_event(
                event_id=event_id,
                timestamp=timestamp or self._timestamp(),
                actor=actor,
                action=action,
                target_id=target_id,
                target_type=target_type,
                project_id=project_id,
                prior_status=prior_status,
                changed_refs=changed_refs,
                reason=reason,
                resulting_refs=resulting_refs,
                supersedes=supersedes,
                parent_event_id=parent_event_id,
                state_revision=state_revision,
                payload=payload,
                actor_kind=actor_kind,
                actor_session_id=actor_session_id,
            )
            self._connection.commit()
            return event
        except BaseException:
            self._rollback()
            raise

    append_event = append_ledger_event

    @_serialized
    def events(self, project_id: str | None = None, *, target_id: str | None = None) -> list[LedgerEvent]:
        clauses: list[str] = []
        params: list[str] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(self._validate_id(project_id, field="project_id"))
        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(self._validate_id(target_id, field="target_id"))
        query = "SELECT * FROM ledger_events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY sequence ASC"
        return [self._event_from_row(row) for row in self._connection.execute(query, params).fetchall()]

    ledger = events
    ledger_events = events

    @_serialized
    def replay(self, entity_id: str, *, revision: int | None = None, at_sequence: int | None = None) -> StateRecord:
        """Reconstruct one historical/current revision through ledger links."""

        return self._find_record(entity_id, revision, at_sequence=at_sequence)

    @_serialized
    def replay_project(self, project_id: str, *, at_sequence: int | None = None) -> dict[str, StateRecord]:
        """Reconstruct all project entities visible at a ledger sequence."""

        project_id = self._validate_id(project_id, field="project_id")
        if at_sequence is not None and at_sequence < 0:
            raise PayloadError("at_sequence must be non-negative")
        if at_sequence is None:
            rows = self._connection.execute(
                """
                SELECT sv.*
                FROM state_versions AS sv
                JOIN state_heads AS sh
                  ON sh.entity_id = sv.entity_id AND sh.current_revision = sv.revision
                WHERE sv.project_id = ? OR sv.entity_id = ?
                ORDER BY sv.entity_id
                """,
                (project_id, project_id),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT sv.*
                FROM state_versions AS sv
                JOIN ledger_events AS le ON le.event_id = sv.event_id
                WHERE (sv.project_id = ? OR sv.entity_id = ?) AND le.sequence <= ?
                  AND sv.revision = (
                    SELECT MAX(previous.revision)
                    FROM state_versions AS previous
                    JOIN ledger_events AS previous_event
                      ON previous_event.event_id = previous.event_id
                    WHERE previous.entity_id = sv.entity_id
                      AND previous_event.sequence <= ?
                  )
                ORDER BY sv.entity_id
                """,
                (project_id, project_id, at_sequence, at_sequence),
            ).fetchall()
        return {row["entity_id"]: self._record_from_row(row) for row in rows}

    @_serialized
    def record_override(
        self,
        target_id: str,
        decision: Mapping[str, Any] | str,
        *,
        decision_id: str | None = None,
        project_id: str | None = None,
        actor: str,
        actor_kind: ActorKind | str,
        actor_session_id: str | None = None,
        reason: str,
        supersedes: str | None = None,
        event_id: str | None = None,
    ) -> StateRecord:
        """Retired insecure shortcut; use the authenticated decision endpoint."""

        del target_id, decision, decision_id, project_id, actor, actor_kind
        del actor_session_id, reason, supersedes, event_id
        raise PayloadError("record_override is disabled; use the authenticated decision endpoint")

    @_serialized
    def record_human_decision(
        self,
        decision: HumanDecision,
        *,
        decision_key: str,
        decision_key_path: str | Path | None = None,
    ) -> StateRecord:
        """Atomically append a key-authorized HumanDecision and its target event."""

        if not isinstance(decision, HumanDecision):
            raise PayloadError("record_human_decision requires a validated HumanDecision")
        actor_kind = self._validate_actor_kind(decision.actor_kind)
        actor_session_id = self._validate_actor_session_id(decision.actor_session_id)
        if actor_kind is not ActorKind.HUMAN_UI or actor_session_id is None:
            raise PayloadError("HumanDecision requires HUMAN_UI and an actor session")
        payload = self._payload_copy(decision.model_dump(mode="json"))
        self._authorize_entity_creation(
            "HumanDecision",
            payload,
            actor_kind=actor_kind,
            actor_session_id=actor_session_id,
            decision_key=decision_key,
            decision_key_path=decision_key_path,
            actor=decision.actor,
        )
        target_id = self._validate_id(decision.target_id, field="target_id")
        event_id = self._validate_id(
            decision.decision_event_id or self._new_id("decision-event"),
            field="decision_event_id",
        )
        if decision.decision_event_id is None:
            payload["decision_event_id"] = event_id
        self._begin()
        try:
            target = self._validate_human_decision_target(payload, project_id=decision.project_id)
            if decision.action is DecisionAction.RECONSIDER:
                from .decision_resolution import resolve_record_decision
                resolution = resolve_record_decision(self, target, target.payload.get("geometry_sha256"), "target_geometry_sha256")
                expected = "Accept" if target.payload.get("status") == "accepted" else "Reject"
                if resolution.status != "EFFECTIVE" or resolution.reason != expected:
                    raise PayloadError("Reconsider requires a current bound scenario decision")
            activate_constraint_set = (
                target.entity_type == "ConstraintSet"
                and decision.action is DecisionAction.APPROVE
                and decision.status is HumanStatus.APPROVED
            )
            if activate_constraint_set:
                from urban_design.constraint_sets import validate_constraint_set_definition
                from urban_design.models import ConstraintSet

                try:
                    validate_constraint_set_definition(
                        ConstraintSet.model_validate(target.payload),
                        require_complete=True,
                    )
                except (TypeError, ValueError, ValidationError) as exc:
                    raise PayloadError(f"ConstraintSet cannot be activated: {exc}") from exc

            project_ref = self._resolve_project_id(
                decision.id,
                "HumanDecision",
                payload,
                decision.project_id,
            )
            record = self._insert_state(
                entity_id=decision.id,
                entity_type="HumanDecision",
                revision=1,
                project_id=project_ref,
                payload=payload,
                parent_revision=None,
                supersedes=decision.supersedes or target.event_id,
                event_id=event_id,
            )
            self._append_ledger_event(
                event_id=event_id,
                timestamp=decision.timestamp.isoformat(),
                actor=decision.actor,
                action=decision.action.value,
                target_id=target_id,
                target_type=target.entity_type,
                project_id=project_ref,
                prior_status=self._status(target.payload),
                changed_refs=(target_id,),
                reason=decision.reason,
                resulting_refs=(decision.id,),
                supersedes=decision.supersedes or target.event_id,
                parent_event_id=target.event_id,
                state_revision=record.revision,
                payload={
                    "decision_id": decision.id,
                    "target_version": decision.target_version,
                    "target_geometry_sha256": decision.target_geometry_sha256,
                    "target_artifact_sha256": decision.target_artifact_sha256,
                    "target_payload_digest": decision.target_payload_digest,
                },
                actor_kind=actor_kind,
                actor_session_id=actor_session_id,
            )
            if activate_constraint_set:
                activated_payload = copy.deepcopy(dict(target.payload))
                activated_payload["status"] = "effective"
                for constraint in activated_payload.get("constraints", []):
                    constraint["status"] = "effective"
                    constraint["source_refs"] = [decision.id]
                activation_event_id = self._new_id("event")
                activation_record = self._insert_state(
                    entity_id=target.entity_id,
                    entity_type="ConstraintSet",
                    revision=target.revision + 1,
                    project_id=target.project_id,
                    payload=activated_payload,
                    parent_revision=target.revision,
                    supersedes=target.event_id,
                    event_id=activation_event_id,
                )
                self._append_ledger_event(
                    event_id=activation_event_id,
                    timestamp=activation_record.created_at,
                    actor=decision.actor,
                    action="ActivateConstraintSet",
                    target_id=target.entity_id,
                    target_type="ConstraintSet",
                    project_id=target.project_id,
                    prior_status=self._status(target.payload),
                    changed_refs=(target.entity_id,),
                    reason=f"Activated by approved HumanDecision {decision.id}",
                    resulting_refs=(target.entity_id, decision.id),
                    supersedes=target.event_id,
                    parent_event_id=event_id,
                    state_revision=activation_record.revision,
                    payload={
                        "human_decision_id": decision.id,
                        "approved_payload_digest": payload.get("target_payload_digest"),
                    },
                    actor_kind=actor_kind,
                    actor_session_id=actor_session_id,
                )
            elif target.entity_type == "DesignScenario" and (
                (decision.action is DecisionAction.ACCEPT and decision.status is HumanStatus.ACCEPTED)
                or (decision.action is DecisionAction.REJECT and decision.status is HumanStatus.REJECTED)
                or (decision.action is DecisionAction.RECONSIDER and decision.status is HumanStatus.NOT_REVIEWED)
            ):
                transitioned_payload = copy.deepcopy(dict(target.payload))
                if decision.action is DecisionAction.RECONSIDER:
                    transitioned_payload["status"] = "proposed"
                    transitioned_payload["baseline"] = False
                    transitioned_payload.pop("baseline_reason", None)
                    transitioned_payload.pop("rejection_reason", None)
                    transition_action = "ReconsiderDesignScenario"
                    transition_reason = f"Reconsidered by HumanDecision {decision.id}: {decision.reason}"
                elif decision.status is HumanStatus.ACCEPTED:
                    transitioned_payload["status"] = "accepted"
                    transitioned_payload["baseline"] = True
                    transitioned_payload["baseline_reason"] = decision.reason
                    transition_action = "AcceptDesignScenario"
                    transition_reason = f"Accepted as baseline by HumanDecision {decision.id}: {decision.reason}"
                else:
                    transitioned_payload["status"] = "rejected"
                    transitioned_payload["rejection_reason"] = decision.reason
                    transition_action = "RejectDesignScenario"
                    transition_reason = f"Rejected by HumanDecision {decision.id}: {decision.reason}"
                transition_event_id = self._new_id("event")
                transition_record = self._insert_state(
                    entity_id=target.entity_id,
                    entity_type="DesignScenario",
                    revision=target.revision + 1,
                    project_id=target.project_id,
                    payload=transitioned_payload,
                    parent_revision=target.revision,
                    supersedes=target.event_id,
                    event_id=transition_event_id,
                )
                self._append_ledger_event(
                    event_id=transition_event_id,
                    timestamp=transition_record.created_at,
                    actor=decision.actor,
                    action=transition_action,
                    target_id=target.entity_id,
                    target_type="DesignScenario",
                    project_id=target.project_id,
                    prior_status=self._status(target.payload),
                    changed_refs=(target.entity_id,),
                    reason=transition_reason,
                    resulting_refs=(target.entity_id, decision.id),
                    supersedes=target.event_id,
                    parent_event_id=event_id,
                    state_revision=transition_record.revision,
                    payload={
                        "human_decision_id": decision.id,
                        "status": transitioned_payload["status"],
                        "rejection_reason": transitioned_payload.get("rejection_reason"),
                        "baseline_reason": transitioned_payload.get("baseline_reason"),
                    },
                    actor_kind=actor_kind,
                    actor_session_id=actor_session_id,
                )
            self._connection.commit()
            return record
        except BaseException:
            self._rollback()
            raise

    @_serialized
    def record_scenario_comparison_decision(
        self,
        *,
        project_id: str,
        accepted_decision: HumanDecision,
        rejected_decisions: Sequence[HumanDecision],
        decision_key: str,
        decision_key_path: str | Path | None = None,
    ) -> tuple[StateRecord, list[StateRecord]]:
        """Atomically record HumanDecisions for accepted baseline and rejected proposals."""
        all_decisions = [accepted_decision, *rejected_decisions]
        for dec in all_decisions:
            if not isinstance(dec, HumanDecision):
                raise PayloadError("record_scenario_comparison_decision requires validated HumanDecisions")
            actor_kind = self._validate_actor_kind(dec.actor_kind)
            actor_session_id = self._validate_actor_session_id(dec.actor_session_id)
            if actor_kind is not ActorKind.HUMAN_UI or actor_session_id is None:
                raise PayloadError("HumanDecision requires HUMAN_UI and an actor session")
            payload = self._payload_copy(dec.model_dump(mode="json"))
            self._authorize_entity_creation(
                "HumanDecision",
                payload,
                actor_kind=actor_kind,
                actor_session_id=actor_session_id,
                decision_key=decision_key,
                decision_key_path=decision_key_path,
                actor=dec.actor,
            )

        self._begin()
        try:
            # Check for existing accepted baseline in project
            existing_scenarios = self.list_current("DesignScenario", project_id=project_id)
            for s in existing_scenarios:
                if (s.payload.get("status") or "").lower() == "accepted" or s.payload.get("baseline") is True:
                    raise PayloadError(f"A baseline scenario has already been accepted for project {project_id!r}")

            def _record_one(decision: HumanDecision) -> StateRecord:
                payload = self._payload_copy(decision.model_dump(mode="json"))
                target_id = self._validate_id(decision.target_id, field="target_id")
                event_id = self._validate_id(
                    decision.decision_event_id or self._new_id("decision-event"),
                    field="decision_event_id",
                )
                if decision.decision_event_id is None:
                    payload["decision_event_id"] = event_id
                target = self._validate_human_decision_target(payload, project_id=decision.project_id)
                project_ref = self._resolve_project_id(decision.id, "HumanDecision", payload, decision.project_id)
                dec_record = self._insert_state(
                    entity_id=decision.id,
                    entity_type="HumanDecision",
                    revision=1,
                    project_id=project_ref,
                    payload=payload,
                    parent_revision=None,
                    supersedes=decision.supersedes or target.event_id,
                    event_id=event_id,
                )
                self._append_ledger_event(
                    event_id=event_id,
                    timestamp=decision.timestamp.isoformat(),
                    actor=decision.actor,
                    action=decision.action.value,
                    target_id=target_id,
                    target_type=target.entity_type,
                    project_id=project_ref,
                    prior_status=self._status(target.payload),
                    changed_refs=(target_id,),
                    reason=decision.reason,
                    resulting_refs=(decision.id,),
                    supersedes=decision.supersedes or target.event_id,
                    parent_event_id=target.event_id,
                    state_revision=dec_record.revision,
                    payload={
                        "decision_id": decision.id,
                        "target_version": decision.target_version,
                        "target_geometry_sha256": decision.target_geometry_sha256,
                        "target_artifact_sha256": decision.target_artifact_sha256,
                    "target_payload_digest": decision.target_payload_digest,
                    },
                    actor_kind=decision.actor_kind,
                    actor_session_id=decision.actor_session_id,
                )

                transitioned_payload = copy.deepcopy(dict(target.payload))
                if decision.status is HumanStatus.ACCEPTED:
                    transitioned_payload["status"] = "accepted"
                    transitioned_payload["baseline"] = True
                    transitioned_payload["baseline_reason"] = decision.reason
                    transition_action = "AcceptDesignScenario"
                    transition_reason = f"Accepted as baseline by HumanDecision {decision.id}: {decision.reason}"
                else:
                    transitioned_payload["status"] = "rejected"
                    transitioned_payload["rejection_reason"] = decision.reason
                    transition_action = "RejectDesignScenario"
                    transition_reason = f"Rejected by HumanDecision {decision.id}: {decision.reason}"
                transition_event_id = self._new_id("event")
                transition_record = self._insert_state(
                    entity_id=target.entity_id,
                    entity_type="DesignScenario",
                    revision=target.revision + 1,
                    project_id=target.project_id,
                    payload=transitioned_payload,
                    parent_revision=target.revision,
                    supersedes=target.event_id,
                    event_id=transition_event_id,
                )
                self._append_ledger_event(
                    event_id=transition_event_id,
                    timestamp=transition_record.created_at,
                    actor=decision.actor,
                    action=transition_action,
                    target_id=target.entity_id,
                    target_type="DesignScenario",
                    project_id=target.project_id,
                    prior_status=self._status(target.payload),
                    changed_refs=(target.entity_id,),
                    reason=transition_reason,
                    resulting_refs=(target.entity_id, decision.id),
                    supersedes=target.event_id,
                    parent_event_id=event_id,
                    state_revision=transition_record.revision,
                    payload={
                        "human_decision_id": decision.id,
                        "status": transitioned_payload["status"],
                        "rejection_reason": transitioned_payload.get("rejection_reason"),
                        "baseline_reason": transitioned_payload.get("baseline_reason"),
                    },
                    actor_kind=decision.actor_kind,
                    actor_session_id=decision.actor_session_id,
                )
                return dec_record

            accepted_rec = _record_one(accepted_decision)
            rejected_recs = [_record_one(d) for d in rejected_decisions]
            self._connection.commit()
            return accepted_rec, rejected_recs
        except BaseException:
            self._rollback()
            raise

    override = record_override

    @_serialized
    def supersede(self, entity_id: str, payload_or_updater: Mapping[str, Any] | Updater, **kwargs: Any) -> StateRecord:
        """Create a new revision explicitly marked as superseding its parent."""

        kwargs.setdefault("action", "Supersede")
        return self.update(entity_id, payload_or_updater, **kwargs)


SQLiteProjectStore = ProjectStateStore
StateStore = ProjectStateStore
DesignLedgerStore = ProjectStateStore
SQLiteStore = ProjectStateStore
ProjectStore = ProjectStateStore


__all__ = [
    "CORE_ENTITY_TYPES",
    "DesignLedgerStore",
    "EntityExistsError",
    "EntityNotFoundError",
    "LedgerEvent",
    "PayloadError",
    "ProjectStateStore",
    "ProjectStore",
    "RevisionConflictError",
    "SQLiteProjectStore",
    "SQLiteStore",
    "StateRecord",
    "StateStore",
    "StoreError",
]
