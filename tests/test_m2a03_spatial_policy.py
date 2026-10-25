"""Human spatial policy freeze. Selections in these tests are explicit fixtures."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
import sqlite3
import shutil
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from test_m2a03_analysis_inputs import _make_store, _osm_body, _spatial_fetcher
from urban_design.analysis_inputs import (
    _manifest_for,
    _write_json,
    build_m2a03_spatial_package,
    load_m2a03_spatial_package,
    sha256_bytes,
)
from urban_design.models import ActorKind, ParameterDefinition, SourceType
from urban_design.spatial_input_policy import (
    CURATED_INCLUDE_HIGHWAYS,
    SpatialPolicyError,
    _analytical_r03,
    approve_spatial_addendum_options as _approve_spatial_addendum_options,
    authorize_week3_entry,
    build_repaired_origin_options,
    build_repaired_spatial_policy_addendum,
    build_spatial_decision_addendum_r03,
    build_spatial_policy_addendum,
    measure_network_policy,
    verify_addendum_for_approval,
    verify_repaired_spatial_addendum,
    verify_spatial_decision_addendum_r03,
    write_spatial_decision_addendum_r03,
    write_repaired_spatial_decision_addendum,
    authorize_week3_from_persisted_state,
    authorize_week6_entry,
    build_spatial_decision_packet,
    freeze_m2a03_spatial_policies as _freeze_m2a03_spatial_policies,
    replay_acceptance_sqlite,
)
from urban_design.store import ProjectStateStore
from urban_design.study_area_workflow import FormalClaimGuardError, validate_formal_claim


NOW = "2026-09-18T12:00:00+00:00"
ACTOR = "ada-lovelace"
REASON = "Freeze the observed M4H spatial denominator for Week 3 exploration."
_TEST_POLICY_KEYS: dict[Path, tuple[str, Path]] = {}


def _policy_test_credentials(database: str | Path) -> tuple[str, Path]:
    from urban_design.decision_key import initialize_decision_key

    database_path = Path(database)
    cached = _TEST_POLICY_KEYS.get(database_path)
    if cached is not None:
        return cached
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    key_path = database_path.with_suffix(database_path.suffix + ".decision-key")
    initialize_decision_key(path=key_path, password_prompt=lambda _prompt: secret)
    cached = (secret, key_path)
    _TEST_POLICY_KEYS[database_path] = cached
    return cached


def freeze_m2a03_spatial_policies(*args, **kwargs):
    """Use an ephemeral fake key while exercising the production HUMAN_UI path."""

    secret, key_path = _policy_test_credentials(args[0] if args else kwargs["database"])
    kwargs.setdefault("actor_kind", ActorKind.HUMAN_UI)
    kwargs.setdefault("actor_session_id", "test-spatial-policy-session")
    kwargs.setdefault("decision_key", secret)
    kwargs.setdefault("decision_key_path", key_path)
    return _freeze_m2a03_spatial_policies(*args, **kwargs)


def approve_spatial_addendum_options(*args, **kwargs):
    """Route package-approval fixtures through an ephemeral HUMAN_UI key."""

    secret, key_path = _policy_test_credentials(args[0] if args else kwargs["database"])
    kwargs.setdefault("actor_kind", ActorKind.HUMAN_UI)
    kwargs.setdefault("actor_session_id", "test-spatial-policy-session")
    kwargs.setdefault("decision_key", secret)
    kwargs.setdefault("decision_key_path", key_path)
    return _approve_spatial_addendum_options(*args, **kwargs)


def test_decision_key_prompt_reads_a_piped_key_and_does_not_open_the_tty(monkeypatch):
    from scripts.approve_m2a03_spatial_inputs import _default_decision_key_prompt

    monkeypatch.setattr(
        "scripts.approve_m2a03_spatial_inputs.getpass.getpass",
        lambda _prompt: pytest.fail("must not open /dev/tty"),
    )

    class _Pipe:
        def isatty(self) -> bool:
            return False

        def readline(self) -> str:
            return "fixture-piped-key\n"

    monkeypatch.setattr("scripts.approve_m2a03_spatial_inputs.sys.stdin", _Pipe())
    assert _default_decision_key_prompt("Designer decision key: ") == "fixture-piped-key"


def test_piped_decision_key_stays_on_stdin_when_dev_tty_exists():
    """A controlling terminal must not make the piped key read ``/dev/tty``."""

    import fcntl
    import pty
    import termios

    script = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
os.close(fd)
assert not sys.stdin.isatty()
from scripts.approve_m2a03_spatial_inputs import _default_decision_key_prompt
sys.stdout.write(_default_decision_key_prompt("Designer decision key: "))
"""
    master, slave = pty.openpty()

    def _take_controlling_tty() -> None:
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, str(Path(__file__).resolve().parents[1])],
            input=b"fixture-piped-key\n",
            capture_output=True,
            check=False,
            timeout=10,
            pass_fds=(slave,),
            preexec_fn=_take_controlling_tty,
        )
    finally:
        os.close(master)
        os.close(slave)
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert completed.stdout == b"fixture-piped-key"


def test_decision_key_prompt_uses_getpass_when_stdin_is_a_tty(monkeypatch):
    from scripts.approve_m2a03_spatial_inputs import _default_decision_key_prompt

    monkeypatch.setattr(
        "scripts.approve_m2a03_spatial_inputs.getpass.getpass",
        lambda prompt: f"hidden:{prompt}",
    )

    class _Tty:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("scripts.approve_m2a03_spatial_inputs.sys.stdin", _Tty())
    assert _default_decision_key_prompt("Designer decision key: ") == "hidden:Designer decision key: "


def _test_decision_key_environment(tmp_path: Path) -> tuple[str, dict[str, str]]:
    from urban_design.decision_key import initialize_decision_key

    secret = "fixture-" + uuid.uuid4().hex + "-K"
    home = tmp_path / "fake-home"
    initialize_decision_key(
        path=home / ".config" / "urban-design" / "decision-key",
        password_prompt=lambda _prompt: secret,
    )
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    return secret, environment


def _fetcher_observing_highways(highways: tuple[str, ...]):
    """Fixture Overpass body that records each requested highway class once."""

    payload = json.loads(_osm_body(rich=True))
    elements = payload["elements"]
    present = {
        element.get("tags", {}).get("highway")
        for element in elements
        if element.get("type") == "way"
    }
    next_id = 1000
    latitude = 51.91
    for highway in highways:
        if highway in present:
            continue
        elements.append(
            {
                "type": "way",
                "id": next_id,
                "nodes": [next_id * 2, next_id * 2 + 1],
                "tags": {"highway": highway, "foot": "yes"},
                "geometry": [
                    {"lat": latitude, "lon": 4.43},
                    {"lat": latitude + 0.0001, "lon": 4.431},
                ],
            }
        )
        next_id += 1
        latitude += 0.0002
    body = json.dumps(payload).encode()
    base = _spatial_fetcher()

    def fetch(url: str, **kwargs: object):
        if "overpass" in url.lower():
            return body, 200, {}, NOW
        return base(url, **kwargs)

    return fetch


def _package(tmp_path: Path, revision: str = "spatial-policy", fetcher=None) -> tuple[Path, Path, str, str]:
    database, project_id, area_id, _ = _make_store(tmp_path, version="v5", x=88700, y=435700)
    package_dir = build_m2a03_spatial_package(
        database,
        tmp_path / "packages",
        project_id=project_id,
        study_area_id=area_id,
        package_revision=revision,
        created_at=NOW,
        fetcher=fetcher or _spatial_fetcher(),
    )
    return database, package_dir, project_id, area_id


def _selection(package: dict[str, object]) -> tuple[list[str], list[str], dict[str, object]]:
    packet = package["decision_packet"]
    origin_ids = packet["options"]["origin_denominator"][0]["cli_origin_ids"]
    tags = packet["options"]["destination_taxonomy"][-1]["cli_destination_tags"]
    network = packet["options"]["pedestrian_network"][0]["network_policy"]
    return origin_ids, tags, network


def _decision_count(database: Path) -> tuple[int, int, int]:
    with ProjectStateStore(database) as store:
        parameters = store.connection.execute("SELECT COUNT(*) FROM state_heads WHERE entity_type = 'ParameterDefinition'").fetchone()[0]
        decisions = store.connection.execute("SELECT COUNT(*) FROM state_heads WHERE entity_type = 'HumanDecision'").fetchone()[0]
        approvals = sum(1 for event in store.events() if event.action == "Approve")
    return int(parameters), int(decisions), int(approvals)


def test_policy_freeze_rejects_unclassified_human_decision_creation(tmp_path: Path) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-unclassified")
    package = load_m2a03_spatial_package(package_dir)
    origins, tags, network = _selection(package)

    with pytest.raises(SpatialPolicyError, match="require HUMAN_UI"):
        _freeze_m2a03_spatial_policies(
            database,
            package_dir,
            tmp_path / "acceptance",
            actor=ACTOR,
            reason=REASON,
            origin_ids=origins,
            destination_tags=tags,
            network_policy=network,
            historical_replay=True,
        )

    assert _decision_count(database) == (0, 0, 0)


def test_decision_packet_lists_options_without_choosing(tmp_path: Path) -> None:
    _database, package_dir, _project_id, _area_id = _package(tmp_path)
    package = load_m2a03_spatial_package(package_dir)
    packet = build_spatial_decision_packet(package)
    assert packet["selected_origin_ids"] is None
    assert packet["selected_destination_tags"] is None
    assert packet["selected_network_policy"] is None
    assert packet["approval_reason"] is None
    assert packet["origin_count"] == len(packet["origin_ids"])
    assert set(packet["observed_destination_categories"]) == {"supermarket", "convenience"}
    assert packet["grocery_tag_counts"]["supermarket"] == 1
    assert packet["network_tag_distribution"]["highway"]["footway"] == 1
    assert packet["options"]["origin_denominator"]
    assert packet["options"]["pedestrian_network"][0]["network_policy"]["allow_ambiguous_access"] is False
    exclusions = {(item["key"], item["value"]) for item in packet["options"]["pedestrian_network"][0]["network_policy"]["exclude"]}
    assert {("foot", "no"), ("access", "no"), ("access", "private")} <= exclusions


def test_policy_freeze_rejects_unobserved_values_and_hash_drift(tmp_path: Path) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-reject")
    package = load_m2a03_spatial_package(package_dir)
    origins, tags, network = _selection(package)
    before = _decision_count(database)
    with pytest.raises(SpatialPolicyError, match="origin"):
        freeze_m2a03_spatial_policies(database, package_dir, tmp_path / "acceptance", actor=ACTOR, reason=REASON, origin_ids=[], destination_tags=tags, network_policy=network, historical_replay=True)
    with pytest.raises(SpatialPolicyError, match="origin"):
        freeze_m2a03_spatial_policies(database, package_dir, tmp_path / "acceptance", actor=ACTOR, reason=REASON, origin_ids=["node/missing"], destination_tags=tags, network_policy=network, historical_replay=True)
    with pytest.raises(SpatialPolicyError, match="destination"):
        freeze_m2a03_spatial_policies(database, package_dir, tmp_path / "acceptance", actor=ACTOR, reason=REASON, origin_ids=origins, destination_tags=["bakery"], network_policy=network, historical_replay=True)
    with pytest.raises(SpatialPolicyError, match="grocery"):
        freeze_m2a03_spatial_policies(database, package_dir, tmp_path / "acceptance", actor=ACTOR, reason=REASON, origin_ids=origins, destination_tags=["grocery"], network_policy=network, historical_replay=True)
    loose = json.loads(json.dumps(network))
    loose["exclude"] = [item for item in loose["exclude"] if item["value"] != "private"]
    with pytest.raises(SpatialPolicyError, match="exclude"):
        freeze_m2a03_spatial_policies(database, package_dir, tmp_path / "acceptance", actor=ACTOR, reason=REASON, origin_ids=origins, destination_tags=tags, network_policy=loose, historical_replay=True)
    allowed = json.loads(json.dumps(network))
    allowed["allow_ambiguous_access"] = True
    with pytest.raises(SpatialPolicyError, match="ambiguous"):
        freeze_m2a03_spatial_policies(database, package_dir, tmp_path / "acceptance", actor=ACTOR, reason=REASON, origin_ids=origins, destination_tags=tags, network_policy=allowed, historical_replay=True)
    unobserved = json.loads(json.dumps(network))
    unobserved["include_highways"] = [*unobserved["include_highways"], "motorway"]
    with pytest.raises(SpatialPolicyError, match="not observed"):
        freeze_m2a03_spatial_policies(database, package_dir, tmp_path / "acceptance", actor=ACTOR, reason=REASON, origin_ids=origins, destination_tags=tags, network_policy=unobserved, historical_replay=True)
    assert _decision_count(database) == before

    decision_path = package_dir / "spatial-input-decision-package.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision["study_area"]["geometry_sha256"] = "sha256:" + "cd" * 32
    decision_path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = json.loads((package_dir / "package-manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        data = (package_dir / entry["path"]).read_bytes()
        entry["sha256"] = sha256_bytes(data)
        entry["size_bytes"] = len(data)
    (package_dir / "package-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(Exception, match="drift|stale|hash"):
        freeze_m2a03_spatial_policies(database, package_dir, tmp_path / "acceptance", actor=ACTOR, reason=REASON, origin_ids=origins, destination_tags=tags, network_policy=network, historical_replay=True)
    assert _decision_count(database) == before


def test_source_byte_drift_invalidates_policy_freeze(tmp_path: Path) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-byte-drift")
    package = load_m2a03_spatial_package(package_dir)
    origins, tags, network = _selection(package)
    raw = next((package_dir / "sources" / "raw").iterdir())
    raw.write_bytes(raw.read_bytes() + b"\n")
    before = _decision_count(database)
    with pytest.raises(Exception, match="integrity|hash|mismatch"):
        freeze_m2a03_spatial_policies(
            database,
            package_dir,
            tmp_path / "acceptance",
            actor=ACTOR,
            reason=REASON,
            origin_ids=origins,
            destination_tags=tags,
            network_policy=network, historical_replay=True,
        )
    assert _decision_count(database) == before


def test_explicit_policy_freeze_authorizes_week3_and_blocks_week6(tmp_path: Path) -> None:
    database, package_dir, _project_id, area_id = _package(tmp_path, "spatial-accept")
    package = load_m2a03_spatial_package(package_dir)
    source_manifest = sha256_bytes((package_dir / "package-manifest.json").read_bytes())
    origins, tags, network = _selection(package)
    before = _decision_count(database)
    with pytest.raises(SpatialPolicyError, match="historical_replay"):
        freeze_m2a03_spatial_policies(
            database,
            package_dir,
            tmp_path / "acceptance",
            actor=ACTOR,
            reason=REASON,
            origin_ids=origins,
            destination_tags=tags,
            network_policy=network,
        )
    assert _decision_count(database) == before
    acceptance_dir = freeze_m2a03_spatial_policies(
        database,
        package_dir,
        tmp_path / "acceptance",
        actor=ACTOR,
        reason=REASON,
        origin_ids=origins,
        destination_tags=tags,
        network_policy=network, historical_replay=True,
    )
    assert sha256_bytes((package_dir / "package-manifest.json").read_bytes()) == source_manifest
    acceptance = json.loads((acceptance_dir / "spatial-input-acceptance.json").read_text(encoding="utf-8"))
    assert acceptance["schema_version"] == "m2-a03-spatial-input-acceptance-v1"
    assert acceptance["status"] == "ACCEPTED_FOR_WEEK3"
    assert acceptance["study_area_id"] == area_id
    assert acceptance["weather_gate_status"] == "SEMANTICS_UNRESOLVED"
    assert set(acceptance["policy_decision_ids"]) == {"origin_denominator", "destination_taxonomy", "pedestrian_network"}
    with ProjectStateStore(database) as store:
        for policy_name, parameter_id in acceptance["parameter_ids"].items():
            parameter = ParameterDefinition.model_validate(store.current(parameter_id).payload)
            assert parameter.source_type is SourceType.PROJECT_DECISION
            assert parameter.version == "v1"
            decision = store.current(acceptance["policy_decision_ids"][policy_name])
            assert decision.payload["actor_kind"] == ActorKind.HUMAN_UI.value
            assert decision.payload["actor_session_id"] == "test-spatial-policy-session"
            assert decision.payload["actor"] == ACTOR
            assert decision.payload["reason"] == REASON
            assert decision.payload["target_geometry_sha256"] == package["study_area"]["geometry_sha256"]
        approval = next(
            event for event in store.events()
            if event.event_id == acceptance["approval_event_ids"]["origin_denominator"]
        )
        assert approval.actor_kind is ActorKind.HUMAN_UI
        assert approval.actor_session_id == "test-spatial-policy-session"
    assert authorize_week3_entry(acceptance) == "AUTHORIZED"
    with pytest.raises(SpatialPolicyError, match="WEEK_6"):
        authorize_week6_entry(acceptance)
    assert replay_acceptance_sqlite(database, acceptance) == "MATCH"
    assert replay_acceptance_sqlite(
        database,
        {**acceptance, "actor_session_id": "wrong-session"},
    ) == "INCONSISTENT"
    assert replay_acceptance_sqlite(
        database,
        {**acceptance, "actor_kind": ActorKind.TEST_HARNESS.value},
    ) == "INCONSISTENT"
    persisted_before_replay = database.read_bytes()
    assert authorize_week3_from_persisted_state(database, acceptance_dir) == "AUTHORIZED"
    assert database.read_bytes() == persisted_before_replay
    for column, value in (
        ("target_type", "Artifact"),
        ("project_id", "other-project"),
        ("actor_kind", None),
        ("actor_session_id", ""),
    ):
        corrupted = tmp_path / f"corrupt-{column}.sqlite3"
        with sqlite3.connect(database) as source, sqlite3.connect(corrupted) as destination:
            source.backup(destination)
        event_id = acceptance["approval_event_ids"]["origin_denominator"]
        with sqlite3.connect(corrupted) as connection:
            for (trigger_name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            ).fetchall():
                escaped_name = trigger_name.replace('"', '""')
                connection.execute(f'DROP TRIGGER "{escaped_name}"')
            connection.execute(
                f"UPDATE ledger_events SET {column} = ? WHERE event_id = ?",
                (value, event_id),
            )
        assert replay_acceptance_sqlite(corrupted, acceptance) == "INCONSISTENT"
        with pytest.raises(SpatialPolicyError, match="human decision|approval ledger event"):
            authorize_week3_from_persisted_state(corrupted, acceptance_dir)
    with pytest.raises(SpatialPolicyError, match="conflicting"):
        freeze_m2a03_spatial_policies(
            database,
            package_dir,
            tmp_path / "acceptance",
            actor=ACTOR,
            reason=REASON,
            origin_ids=origins[:1],
            destination_tags=tags,
            network_policy=network, historical_replay=True,
        )
    with pytest.raises(FormalClaimGuardError):
        validate_formal_claim("LEGAL_BUILDABILITY")
    repeated = freeze_m2a03_spatial_policies(
        database,
        package_dir,
        tmp_path / "acceptance",
        actor=ACTOR,
        reason=REASON,
        origin_ids=origins,
        destination_tags=tags,
        network_policy=network, historical_replay=True,
    )
    assert repeated == acceptance_dir
    assert _decision_count(database) == (3, 3, 3)


def test_approval_cli_does_not_write_without_explicit_selections(tmp_path: Path) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-cli")
    before = _decision_count(database)
    script = Path(__file__).resolve().parents[1] / "scripts" / "approve_m2a03_spatial_inputs.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--database",
            str(database),
            "--spatial-package",
            str(package_dir),
            "--output-root",
            str(tmp_path / "acceptance"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    packet = json.loads(result.stdout)
    assert packet["selected_origin_ids"] is None
    assert packet["origin_ids"]
    assert _decision_count(database) == before


def test_spatial_cli_rejects_missing_and_used_revisions_before_dispatch(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_m2a03_spatial_inputs.py"
    output = tmp_path / "packages"
    study_area_id = "study-area-rotterdam-m4h-pilot-project-v5"
    database = tmp_path / "missing.sqlite3"
    missing = subprocess.run(
        [sys.executable, str(script), "--database", str(database), "--output-root", str(output), "--study-area-id", study_area_id],
        check=False,
        capture_output=True,
        text=True,
    )
    assert missing.returncode != 0
    assert not database.exists()
    used = output / f"run-{study_area_id}-r03"
    used.mkdir(parents=True)
    (used / "historical.json").write_text("{}\n", encoding="utf-8")
    existing = subprocess.run(
        [sys.executable, str(script), "--database", str(database), "--output-root", str(output), "--study-area-id", study_area_id, "--revision", "r03"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert existing.returncode == 2
    assert "already used" in existing.stderr
    assert not database.exists()
    assert (used / "historical.json").read_text(encoding="utf-8") == "{}\n"


FROZEN_SPATIAL_R01 = (
    Path(__file__).resolve().parents[1]
    / "artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01"
)


def test_endpoints_0_04_m_apart_share_a_component() -> None:
    """Endpoints 0.04 m apart are within the 0.05 m rule even when grid rounding would split them."""

    features = [
        {
            "type": "Feature",
            "id": "way/a",
            "geometry": {"type": "LineString", "coordinates": [[100.0, 0.0], [0.0, 0.0]]},
            "properties": {"tags": {"highway": "footway"}},
        },
        {
            "type": "Feature",
            "id": "way/b",
            "geometry": {"type": "LineString", "coordinates": [[100.0, 0.04], [100.0, 50.0]]},
            "properties": {"tags": {"highway": "footway"}},
        },
        {
            "type": "Feature",
            "id": "node/a",
            "geometry": {"type": "Point", "coordinates": [50.0, 0.0]},
            "properties": {"tags": {}},
        },
        {
            "type": "Feature",
            "id": "node/b",
            "geometry": {"type": "Point", "coordinates": [100.0, 40.0]},
            "properties": {"tags": {}},
        },
    ]
    origins = [{"feature_id": "node/a", "tags": {}}, {"feature_id": "node/b", "tags": {}}]
    metrics = measure_network_policy(features, origins, [], {"include_highways": ["footway"], "exclude": []})
    assert metrics["connected_component_count"] == 1
    assert metrics["known_path_check"]["result"] == "CONNECTED"
    assert metrics["known_path_check"]["connected"] is True


def test_known_pair_distance_matches_geometry_not_the_diagnostic() -> None:
    features = [
        {"type": "Feature", "id": "way/a", "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [100.0, 0.0]]}, "properties": {"tags": {"highway": "footway"}}},
        {"type": "Feature", "id": "way/b", "geometry": {"type": "LineString", "coordinates": [[100.0, 0.0], [100.0, 40.0]]}, "properties": {"tags": {"highway": "footway"}}},
        {"type": "Feature", "id": "node/a", "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}, "properties": {"tags": {}}},
        {"type": "Feature", "id": "node/b", "geometry": {"type": "Point", "coordinates": [100.0, 40.0]}, "properties": {"tags": {}}},
    ]
    expected = math.hypot(100.0, 0.0) + math.hypot(0.0, 40.0)
    pair = {"pair_kind": "origin_origin", "origin_a": "node/a", "origin_b": "node/b", "expected_connected": True, "expected_distance_m": expected}
    metrics = measure_network_policy(features, [{"feature_id": "node/a", "tags": {}}, {"feature_id": "node/b", "tags": {}}], [], {"include_highways": ["footway"], "exclude": []}, known_pair=pair)
    validation = metrics["known_path_validation"]
    assert validation["matches_expected"] is True
    assert validation["implementation_distance_m"] == pytest.approx(expected)
    assert metrics["diagnostic_endpoint_connectivity"]["role"] if False else metrics["diagnostic_endpoint_connectivity"]["result"] in {"CONNECTED", "NOT_CONNECTED", "NOT_SNAPPED"}
    assert "expected_distance_m" not in metrics["diagnostic_endpoint_connectivity"]


def test_distant_same_normalized_name_is_not_merged() -> None:
    records = [
        {"feature_id": "node/near-a", "tags": {"name": "Rotterdam, Centrum", "public_transport": "stop_position"}},
        {"feature_id": "node/near-b", "tags": {"name": "Centrum", "public_transport": "platform"}},
        {"feature_id": "node/far", "tags": {"name": "Schiedam, Centrum", "public_transport": "station"}},
    ]
    coordinates = {"node/near-a": (0.0, 0.0), "node/near-b": (10.0, 0.0), "node/far": (500.0, 0.0)}
    report = build_repaired_origin_options(records, coordinates)
    clustered = next(option for option in report["options"] if option["option_id"] == "clustered-normalized-name-places")
    exact = next(option for option in report["options"] if option["option_id"] == "exact-name-only-deduplicated-stop-places")
    assert "exact-name-only" in exact["rule"].casefold() or "Exact-name-only" in exact["rule"]
    assert clustered["cluster_count"] == 2
    assert clustered["maximum_within_cluster_distance_m"] == pytest.approx(10.0)
    assert any(cluster["member_ids"] == ["node/near-a", "node/near-b"] or set(cluster["member_ids"]) == {"node/near-a", "node/near-b"} for cluster in clustered["clusters"])
    assert report["unresolved_ambiguous_clusters"]
    assert "node/far" in report["unresolved_ambiguous_clusters"][0]["member_ids"]
    assert "node/far" in clustered["member_ids"]
    near_representative = [member for member in clustered["member_ids"] if member in {"node/near-a", "node/near-b"}]
    assert len(near_representative) == 1
    chain = [
        {"feature_id": "node/chain-0", "tags": {"name": "Chain", "public_transport": "stop_position"}},
        {"feature_id": "node/chain-100", "tags": {"name": "Chain", "public_transport": "stop_position"}},
        {"feature_id": "node/chain-200", "tags": {"name": "Chain", "public_transport": "stop_position"}},
    ]
    chain_report = build_repaired_origin_options(chain, {"node/chain-0": (0.0, 0.0), "node/chain-100": (100.0, 0.0), "node/chain-200": (200.0, 0.0)})
    chain_option = next(option for option in chain_report["options"] if option["option_id"] == "clustered-normalized-name-places")
    assert chain_option["cluster_count"] == 2
    assert chain_option["maximum_within_cluster_distance_m"] <= 150.0
    assert not any(set(cluster["member_ids"]) == {"node/chain-0", "node/chain-100", "node/chain-200"} for cluster in chain_option["clusters"])
    assert {"node/chain-0", "node/chain-200"} not in [set(cluster["member_ids"]) for cluster in chain_option["clusters"]]


def test_option_approval_binds_ids_and_rejects_mismatches(tmp_path: Path) -> None:
    database, package_dir, _project_id, _area_id = _package(
        tmp_path,
        "spatial-options",
        fetcher=_fetcher_observing_highways(CURATED_INCLUDE_HIGHWAYS),
    )
    addendum_dir = write_repaired_spatial_decision_addendum(package_dir, tmp_path / "addenda")
    addendum = json.loads((addendum_dir / "decision-addendum.json").read_text(encoding="utf-8"))
    origin = next(option for option in addendum["origin_options"] if option["member_ids"])
    destination = addendum["destination_options"][0]
    network = next(option for option in addendum["network_options"] if option["option_id"] == "curated-ordinary-streets-and-footways")
    acceptance_dir = approve_spatial_addendum_options(
        database,
        addendum_dir,
        package_dir,
        tmp_path / "acceptance",
        actor=ACTOR,
        reason=REASON,
        origin_option_id=origin["option_id"],
        destination_option_id=destination["option_id"],
        network_option_id=network["option_id"],
        approved_at=datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc),
    )
    acceptance = json.loads((acceptance_dir / "spatial-input-acceptance.json").read_text(encoding="utf-8"))
    binding = acceptance["decision_binding"]
    assert binding["origin_option_id"] == origin["option_id"]
    assert binding["destination_option_id"] == destination["option_id"]
    assert binding["network_option_id"] == network["option_id"]
    manifest_hash = sha256_bytes((addendum_dir / "package-manifest.json").read_bytes())
    assert binding["decision_addendum_manifest_sha256"] == manifest_hash
    stored_origin = acceptance["parameters"]["origin_denominator"]["value"]
    assert stored_origin["origin_ids"] == origin["member_ids"]
    assert stored_origin["origin_option_id"] == origin["option_id"]
    stored_network = acceptance["parameters"]["pedestrian_network"]["value"]
    assert stored_network["excluded_highways"] == network["network_policy"]["excluded_highways"]
    assert stored_network["pedestrian_access_rule"] == network["network_policy"]["pedestrian_access_rule"]
    assert stored_network["pedestrian_access_rule_text"] == network["network_policy"]["pedestrian_access_rule_text"]
    for policy_name in ("origin_denominator", "destination_taxonomy", "pedestrian_network"):
        stored_value = acceptance["parameters"][policy_name]["value"]
        assert stored_value["decision_addendum_manifest_sha256"] == manifest_hash
        assert stored_value["origin_option_id"] == origin["option_id"]
        assert stored_value["destination_option_id"] == destination["option_id"]
        assert stored_value["network_option_id"] == network["option_id"]
    with ProjectStateStore(database) as store:
        parameter = store.current(acceptance["parameter_ids"]["pedestrian_network"]).payload
        assert parameter["value"]["excluded_highways"] == network["network_policy"]["excluded_highways"]
        assert parameter["value"]["pedestrian_access_rule"] == network["network_policy"]["pedestrian_access_rule"]
        assert parameter["value"]["pedestrian_access_rule_text"] == network["network_policy"]["pedestrian_access_rule_text"]
        assert parameter["value"]["decision_addendum_manifest_sha256"] == manifest_hash
        assert parameter["value"]["network_option_id"] == network["option_id"]
        event = next(item for item in store.events() if item.event_id == acceptance["approval_event_ids"]["origin_denominator"])
        assert event.payload["origin_option_id"] == origin["option_id"]
        assert event.payload["destination_option_id"] == destination["option_id"]
        assert event.payload["network_option_id"] == network["option_id"]
        assert event.payload["decision_addendum_manifest_sha256"] == manifest_hash
        decision = store.current(acceptance["policy_decision_ids"]["origin_denominator"]).payload
        refs = decision["resulting_refs"]
        assert manifest_hash in refs
        assert origin["option_id"] in refs
        assert destination["option_id"] in refs
        assert network["option_id"] in refs
    with pytest.raises(SpatialPolicyError, match="differ from the selected option"):
        approve_spatial_addendum_options(
            database,
            addendum_dir,
            package_dir,
            tmp_path / "acceptance",
            actor=ACTOR,
            reason=REASON,
            origin_option_id=origin["option_id"],
            destination_option_id=destination["option_id"],
            network_option_id=network["option_id"],
            supplied_origin_ids=["node/not-the-option"],
            approved_at=datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc),
        )
    with pytest.raises(SpatialPolicyError, match="mismatched option id"):
        approve_spatial_addendum_options(
            database,
            addendum_dir,
            package_dir,
            tmp_path / "acceptance-missing",
            actor=ACTOR,
            reason=REASON,
            origin_option_id="not-an-option",
            destination_option_id=destination["option_id"],
            network_option_id=network["option_id"],
            approved_at=datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc),
        )


def test_acceptance_directory_without_sqlite_is_blocked(tmp_path: Path) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-retry")
    package = load_m2a03_spatial_package(package_dir)
    origins, tags, network = _selection(package)
    with pytest.raises(Exception):
        freeze_m2a03_spatial_policies(
            database,
            package_dir,
            tmp_path / "acceptance",
            actor=ACTOR,
            reason=REASON,
            origin_ids=origins,
            destination_tags=tags,
            network_policy=network, historical_replay=True,
            approved_at=datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc),
            commit_hook=lambda: (_ for _ in ()).throw(OSError("injected SQLite failure")),
        )
    assert _decision_count(database) == (0, 0, 0)
    with pytest.raises(SpatialPolicyError, match="BLOCKED"):
        freeze_m2a03_spatial_policies(
            database,
            package_dir,
            tmp_path / "acceptance",
            actor=ACTOR,
            reason=REASON,
            origin_ids=origins,
            destination_tags=tags,
            network_policy=network, historical_replay=True,
            approved_at=datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc),
        )
    assert _decision_count(database) == (0, 0, 0)


def test_repaired_verifier_rejects_mutation_and_missing_parent(tmp_path: Path) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-verify")
    del database
    addendum_dir = write_repaired_spatial_decision_addendum(package_dir, tmp_path / "addenda")
    assert verify_repaired_spatial_addendum(addendum_dir, package_dir)["status"] == "PASS"
    mutated = tmp_path / "mutated"
    shutil.copytree(addendum_dir, mutated)
    decision = mutated / "decision-addendum.json"
    decision.write_bytes(decision.read_bytes() + b"\n")
    with pytest.raises(SpatialPolicyError, match="integrity mismatch"):
        verify_repaired_spatial_addendum(mutated, package_dir)
    orphan = tmp_path / "orphan"
    shutil.copytree(addendum_dir, orphan)
    payload = json.loads((orphan / "decision-addendum.json").read_text(encoding="utf-8"))
    payload["source_package_manifest_sha256"] = "sha256:" + "ab" * 32
    (orphan / "decision-addendum.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = json.loads((orphan / "package-manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        data = (orphan / entry["path"]).read_bytes()
        entry["sha256"] = sha256_bytes(data)
        entry["size_bytes"] = len(data)
    (orphan / "package-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(SpatialPolicyError, match="parent"):
        verify_repaired_spatial_addendum(orphan, package_dir)


def test_frozen_repaired_addendum_is_unselected_and_verifies(monkeypatch) -> None:
    def fail_fetch(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("repaired addendum issued a live request")

    monkeypatch.setattr("urban_design.m2a03_sources.default_fetch", fail_fetch)
    first = build_repaired_spatial_policy_addendum(FROZEN_SPATIAL_R01, generated_at="2026-09-22T00:00:00+00:00")
    second = build_repaired_spatial_policy_addendum(FROZEN_SPATIAL_R01, generated_at="2026-09-22T00:00:00+00:00")
    assert first["status"] == "UNSELECTED"
    assert first["selected_origin_ids"] is None
    assert "grocery" not in first["observed_destination_categories"]
    assert first["snap_distance_m"] == 30.0
    assert first["topology_tolerance_m"] == 0.05
    assert set(first["curated_unsnapped_origin_ids"]) == {"node/3135826254", "node/4762185310", "node/5639766145"}
    clustered = next(option for option in first["origin_options"] if option["option_id"] == "clustered-normalized-name-places")
    assert clustered["cluster_count"]
    assert clustered["member_ids"]
    assert clustered["maximum_within_cluster_distance_m"] <= 150.0
    for cluster in clustered["clusters"]:
        assert cluster["maximum_within_cluster_distance_m"] <= 150.0
        assert {"node/3135826255", "node/6214863211"} != set(cluster["member_ids"])
        assert not {"node/3135826255", "node/6214863211"} <= set(cluster["member_ids"])
    exact = next(option for option in first["origin_options"] if option["option_id"] == "exact-name-only-deduplicated-stop-places")
    assert "exact-name-only" in exact["rule"].casefold() or "Exact-name-only" in exact["rule"]
    coverage_ids = {item["origin_option_id"] for item in first["denominator_coverage"]}
    assert "clustered-normalized-name-places" in coverage_ids
    for option in first["network_options"]:
        assert option["metrics"]["known_path_validation"]["matches_expected"] is True
        diagnostic = option["metrics"]["diagnostic_endpoint_connectivity"]
        assert diagnostic["result"] in {"CONNECTED", "NOT_CONNECTED", "NOT_SNAPPED"}
        assert not str(diagnostic.get("origin_a") or "").startswith("reference-node/")
        assert not str(diagnostic.get("origin_b") or "").startswith("reference-node/")
    assert first["origin_options"] == second["origin_options"]
    assert [option["metrics"]["known_path_validation"] for option in first["network_options"]] == [
        option["metrics"]["known_path_validation"] for option in second["network_options"]
    ]


def test_frozen_addendum_classifies_origins_and_measures_curated_network(monkeypatch) -> None:
    def fail_fetch(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("addendum issued a live request")

    monkeypatch.setattr("urban_design.m2a03_sources.default_fetch", fail_fetch)
    first = build_spatial_policy_addendum(FROZEN_SPATIAL_R01)
    second = build_spatial_policy_addendum(FROZEN_SPATIAL_R01)
    assert first["status"] == "UNSELECTED"
    assert first["selected_origin_ids"] is None
    assert first["selected_destination_tags"] is None
    assert first["selected_network_policy"] is None
    assert "grocery" not in first["observed_destination_categories"]
    classification = first["origin_classification"]
    assert classification["record_count"] == 174
    classified = sum(bucket["count"] for bucket in classification["by_public_transport"].values())
    assert classified == 174
    assert classification["residual_missing_public_transport"]["count"] > 0
    deduped = next(option for option in first["origin_options"] if option["option_id"] == "deduplicated-named-stop-places")
    assert deduped["count"] < 174
    assert deduped["rule"]
    assert deduped["member_ids"]
    assert first["review_table"]
    assert any(row["dimension"] == "repeated_stop" for row in first["review_table"])
    assert first["origin_map"]["features"]
    network_ids = [option["option_id"] for option in first["network_options"]]
    assert "all-observed-highways" in network_ids
    assert "observed-pedestrian-highways" in network_ids
    assert "curated-ordinary-streets-and-footways" in network_ids
    for option in first["network_options"]:
        metrics = option["metrics"]
        assert {"way_count", "edge_count", "connected_component_count", "origin_snapping_coverage", "destination_snapping_coverage", "known_path_check"} <= set(metrics)
        assert metrics["known_path_check"]["result"] in {"CONNECTED", "NOT_CONNECTED", "NOT_SNAPPED"}
    curated = next(option for option in first["network_options"] if option["option_id"] == "curated-ordinary-streets-and-footways")
    assert {"construction", "proposed", "busway", "track"} <= set(curated["network_policy"]["excluded_highways"])
    assert first["origin_classification"] == second["origin_classification"]
    assert [option["option_id"] for option in first["network_options"]] == [option["option_id"] for option in second["network_options"]]
    assert [option["metrics"] for option in first["network_options"]] == [option["metrics"] for option in second["network_options"]]


def test_policy_validation_rejects_duplicate_choices(tmp_path: Path) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-duplicates")
    package = load_m2a03_spatial_package(package_dir)
    origins, tags, network = _selection(package)
    before = _decision_count(database)
    with pytest.raises(SpatialPolicyError, match="duplicate origin"):
        freeze_m2a03_spatial_policies(database, package_dir, tmp_path / "acceptance", actor=ACTOR, reason=REASON, origin_ids=[origins[0], origins[0]], destination_tags=tags, network_policy=network, historical_replay=True)
    with pytest.raises(SpatialPolicyError, match="duplicate destination"):
        freeze_m2a03_spatial_policies(database, package_dir, tmp_path / "acceptance", actor=ACTOR, reason=REASON, origin_ids=origins, destination_tags=[tags[0], tags[0]], network_policy=network, historical_replay=True)
    duplicated_network = json.loads(json.dumps(network))
    duplicated_network["include_highways"] = [network["include_highways"][0], network["include_highways"][0]]
    with pytest.raises(SpatialPolicyError, match="duplicate network"):
        freeze_m2a03_spatial_policies(database, package_dir, tmp_path / "acceptance", actor=ACTOR, reason=REASON, origin_ids=origins, destination_tags=tags, network_policy=duplicated_network, historical_replay=True)
    assert _decision_count(database) == before


def test_fixture_approval_time_is_later_than_source_acquisition(tmp_path: Path) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-clock")
    package = load_m2a03_spatial_package(package_dir)
    origins, tags, network = _selection(package)
    source_time = datetime.fromisoformat(package["created_at"])
    approved_at = datetime(2026, 9, 21, 18, 30, tzinfo=timezone.utc)
    assert approved_at > source_time
    acceptance_dir = freeze_m2a03_spatial_policies(
        database,
        package_dir,
        tmp_path / "acceptance",
        actor=ACTOR,
        reason=REASON,
        origin_ids=origins,
        destination_tags=tags,
        network_policy=network, historical_replay=True,
        approved_at=approved_at,
    )
    acceptance = json.loads((acceptance_dir / "spatial-input-acceptance.json").read_text(encoding="utf-8"))
    decision_times = {name: decision["timestamp"] for name, decision in acceptance["decisions"].items()}
    assert len(set(decision_times.values())) == 1
    stored = datetime.fromisoformat(next(iter(decision_times.values())))
    assert stored == approved_at
    assert stored != source_time
    with ProjectStateStore(database) as store:
        for event_id in acceptance["approval_event_ids"].values():
            event = next(item for item in store.events() if item.event_id == event_id)
            assert datetime.fromisoformat(event.timestamp) == stored
    reloaded = json.loads((acceptance_dir / "spatial-input-acceptance.json").read_text(encoding="utf-8"))
    assert reloaded["parameters"]["origin_denominator"]["value"]["origin_ids"] == origins


def _junction_measurement(north_start: tuple[float, float], north_end: tuple[float, float], expected: float) -> dict[str, object]:
    start = "reference-node/way/junction-east/start"
    end = "reference-node/way/junction-north/end"
    features = [
        {"type": "Feature", "id": "way/junction-east", "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [100.0, 0.0]]}, "properties": {"tags": {"highway": "footway"}}},
        {"type": "Feature", "id": "way/junction-north", "geometry": {"type": "LineString", "coordinates": [list(north_start), list(north_end)]}, "properties": {"tags": {"highway": "footway"}}},
        {"type": "Feature", "id": "node/inventory", "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}, "properties": {"tags": {}}},
    ]
    references = [
        {"type": "Feature", "id": start, "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}, "properties": {"tags": {}}},
        {"type": "Feature", "id": end, "geometry": {"type": "Point", "coordinates": list(north_end)}, "properties": {"tags": {}}},
    ]
    pair = {
        "pair_kind": "origin_origin",
        "origin_a": start,
        "origin_b": end,
        "expected_connected": True,
        "expected_distance_m": expected,
        "way_ids": ["way/junction-east", "way/junction-north"],
        "vertex_ids": [start, "way/junction-east/end", end],
    }
    return measure_network_policy(
        features,
        [{"feature_id": "node/inventory", "tags": {}}],
        [],
        {"include_highways": ["footway"], "exclude": []},
        known_pair=pair,
        reference_features=references,
    )


def test_junction_known_path_fails_when_junction_or_weight_changes() -> None:
    expected = math.hypot(100.0, 0.0) + math.hypot(0.0, 40.0)
    connected = _junction_measurement((100.0, 0.0), (100.0, 40.0), expected)
    validation = connected["known_path_validation"]
    assert validation["matches_expected"] is True
    assert validation["implementation_distance_m"] == pytest.approx(expected)
    assert connected["origin_snapping_coverage"]["total_count"] == 1
    assert connected["snapped_origin_ids"] == ["node/inventory"]
    assert all(not str(feature_id).startswith("reference-node/") for feature_id in connected["snapped_origin_ids"])
    assert all(not str(feature_id).startswith("reference-node/") for feature_id in connected["unsnapped_origin_ids"])
    omitted = _junction_measurement((100.0, 1.0), (100.0, 41.0), expected)
    assert omitted["known_path_validation"]["matches_expected"] is False
    assert omitted["known_path_validation"]["implementation_connected"] is False
    reweighted = _junction_measurement((100.0, 0.0), (100.0, 50.0), expected)
    assert reweighted["known_path_validation"]["implementation_connected"] is True
    assert reweighted["known_path_validation"]["matches_expected"] is False
    assert reweighted["known_path_validation"]["implementation_distance_m"] == pytest.approx(150.0)


def _regenerate_r03_manifest(root: Path) -> None:
    files = [path for path in root.rglob("*") if path.is_file() and path.name != "package-manifest.json"]
    _write_json(root / "package-manifest.json", _manifest_for(root, files))


def test_r03_verifier_rejects_regenerated_semantic_tampering(tmp_path: Path) -> None:
    _database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-r03-verify")
    addendum_dir = write_spatial_decision_addendum_r03(package_dir, tmp_path / "addenda")
    assert verify_spatial_decision_addendum_r03(addendum_dir, package_dir)["status"] == "PASS"
    decision = json.loads((addendum_dir / "decision-addendum.json").read_text(encoding="utf-8"))
    assert decision["inventory_totals"]["observed_destinations"] == decision["network_options"][0]["metrics"]["destination_snapping_coverage"]["total_count"]
    assert decision["network_options"][0]["metrics"]["destination_snapping_coverage"]["total_count"] > 0
    assert decision["network_options"][0]["metrics"]["origin_snapping_coverage"]["total_count"] == decision["inventory_totals"]["observed_origins"]
    coverage_tags = [set(item["destination_tags"]) for item in decision["network_options"][0]["destination_option_coverage"]]
    assert {"supermarket"} in coverage_tags
    assert {"convenience"} in coverage_tags
    assert {"supermarket", "convenience"} in coverage_tags

    def reject(mutate) -> None:
        copied = tmp_path / "mutated"
        if copied.exists():
            shutil.rmtree(copied)
        shutil.copytree(addendum_dir, copied)
        payload = json.loads((copied / "decision-addendum.json").read_text(encoding="utf-8"))
        mutate(payload, copied)
        _write_json(copied / "decision-addendum.json", payload)
        _write_json(copied / "origin-map.geojson", payload["origin_map"])
        _write_json(copied / "origin-review-table.json", {"rows": payload["review_table"], "ambiguous_clusters": payload["unresolved_ambiguous_clusters"]})
        _write_json(
            copied / "network-policy-metrics.json",
            {
                "options": payload["network_options"],
                "denominator_coverage": payload["denominator_coverage"],
                "inventory_totals": payload["inventory_totals"],
                "junction_known_path": payload["junction_known_path"],
            },
        )
        _regenerate_r03_manifest(copied)
        with pytest.raises(SpatialPolicyError):
            verify_spatial_decision_addendum_r03(copied, package_dir)

    reject(lambda payload, _root: payload.__setitem__("status", "SELECTED"))
    reject(lambda payload, _root: payload["network_options"][0].__setitem__("selected", True))
    reject(lambda payload, _root: payload.__setitem__("cluster_count", int(payload.get("cluster_count") or 0) + 1))
    reject(lambda payload, _root: payload.__setitem__("review_table", [*list(payload.get("review_table") or []), {"dimension": "tampered", "value": "x", "count": 1, "feature_ids": [], "maximum_within_cluster_distance_m": 1}]))
    reject(lambda payload, _root: payload.__setitem__("selected_origin_ids", ["node/not-selected"]))
    reject(lambda payload, _root: payload.__setitem__("approval_reason", "agent selected this"))
    reject(lambda payload, _root: payload["origin_options"][0].__setitem__("member_ids", ["node/tampered"]))
    reject(lambda payload, _root: payload["network_options"][0]["network_policy"].__setitem__("include_highways", ["footway"]))
    reject(lambda payload, _root: payload["network_options"][0]["metrics"].__setitem__("way_count", 0))
    reject(lambda payload, _root: payload["source_artifact_hashes"].__setitem__("package_manifest", "sha256:" + "ab" * 32))
    reject(lambda payload, _root: payload.__setitem__("schema_version", "not-r03"))

    duplicated = tmp_path / "duplicated"
    shutil.copytree(addendum_dir, duplicated)
    manifest = json.loads((duplicated / "package-manifest.json").read_text(encoding="utf-8"))
    manifest["files"].append(dict(manifest["files"][0]))
    _write_json(duplicated / "package-manifest.json", manifest)
    with pytest.raises(SpatialPolicyError, match="duplicate"):
        verify_spatial_decision_addendum_r03(duplicated, package_dir)

    unexpected = tmp_path / "unexpected"
    shutil.copytree(addendum_dir, unexpected)
    (unexpected / "extra.json").write_text("{}\n", encoding="utf-8")
    _regenerate_r03_manifest(unexpected)
    with pytest.raises(SpatialPolicyError, match="unexpected"):
        verify_spatial_decision_addendum_r03(unexpected, package_dir)

    missing = tmp_path / "missing"
    shutil.copytree(addendum_dir, missing)
    (missing / "origin-map.geojson").unlink()
    with pytest.raises(SpatialPolicyError, match="missing"):
        verify_spatial_decision_addendum_r03(missing, package_dir)


def test_spatial_r01_bypass_does_not_authorize_week3(tmp_path: Path) -> None:
    database = tmp_path / "bypass.sqlite3"
    with pytest.raises(SpatialPolicyError, match="decision_binding"):
        freeze_m2a03_spatial_policies(
            database,
            FROZEN_SPATIAL_R01,
            tmp_path / "acceptance",
            actor=ACTOR,
            reason=REASON,
            origin_ids=["node/1"],
            destination_tags=["supermarket"],
            network_policy={"include_highways": ["footway"], "exclude": [], "ambiguous_access_limitation": "visible limitation", "allow_ambiguous_access": False},
            historical_replay=True,
        )
    assert not database.exists()
    acceptance = {
        "schema_version": "m2-a03-spatial-input-acceptance-v1",
        "status": "ACCEPTED_FOR_WEEK3",
        "weather_gate_status": "SEMANTICS_UNRESOLVED",
        "spatial_package_id": "m2-a03-spatial-input-study-area-rotterdam-m4h-pilot-project-v5-spatial-r01",
    }
    with pytest.raises(SpatialPolicyError, match="addendum manifest"):
        authorize_week3_entry(acceptance)
    acceptance["decision_binding"] = {"origin_option_id": "all-observed-osm-ids"}
    with pytest.raises(SpatialPolicyError, match="addendum manifest"):
        authorize_week3_entry(acceptance)
    script = Path(__file__).resolve().parents[1] / "scripts" / "approve_m2a03_spatial_inputs.py"
    unbound = subprocess.run(
        [
            sys.executable,
            str(script),
            "--database",
            str(database),
            "--spatial-package",
            str(FROZEN_SPATIAL_R01),
            "--output-root",
            str(tmp_path / "cli-acceptance"),
            "--actor",
            ACTOR,
            "--reason",
            REASON,
            "--origin-id",
            "node/1",
            "--destination-tag",
            "supermarket",
            "--network-policy",
            "{}",
            "--historical-replay",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert unbound.returncode == 2
    assert "decision-addendum" in unbound.stderr
    assert not database.exists()


def test_historical_replay_cli_accepts_a_fixture_and_refuses_the_unmarked_path(tmp_path: Path) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-replay")
    package = load_m2a03_spatial_package(package_dir)
    origins, tags, network = _selection(package)
    script = Path(__file__).resolve().parents[1] / "scripts" / "approve_m2a03_spatial_inputs.py"
    common = [
        sys.executable,
        str(script),
        "--database",
        str(database),
        "--spatial-package",
        str(package_dir),
        "--output-root",
        str(tmp_path / "acceptance"),
        "--actor",
        ACTOR,
        "--reason",
        REASON,
        "--destination-tag",
        tags[0],
        "--network-policy",
        json.dumps(network),
    ]
    unmarked = subprocess.run([*common, "--origin-id", origins[0]], check=False, capture_output=True, text=True)
    assert unmarked.returncode == 2
    assert "historical replay" in unmarked.stderr
    assert _decision_count(database) == (0, 0, 0)
    secret, environment = _test_decision_key_environment(tmp_path)
    marked = subprocess.run(
        [*common, "--origin-id", origins[0], "--historical-replay"],
        check=False,
        capture_output=True,
        text=True,
        input=secret + "\n",
        env=environment,
    )
    assert marked.returncode == 0, marked.stderr
    assert secret not in marked.stdout + marked.stderr
    acceptance_dir = Path(json.loads(marked.stdout)["acceptance_dir"])
    assert authorize_week3_from_persisted_state(database, acceptance_dir) == "AUTHORIZED"


def test_frozen_r03_reports_destination_coverage_without_reference_counts(monkeypatch, tmp_path: Path) -> None:
    def fail_fetch(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("r03 issued a live request")

    monkeypatch.setattr("urban_design.m2a03_sources.default_fetch", fail_fetch)
    stamp = "2026-09-22T12:00:00+00:00"
    first = build_spatial_decision_addendum_r03(FROZEN_SPATIAL_R01, generated_at=stamp)
    second = build_spatial_decision_addendum_r03(FROZEN_SPATIAL_R01, generated_at=stamp)
    assert first["status"] == "UNSELECTED"
    assert first["selected_origin_ids"] is None
    assert first["selected_destination_tags"] is None
    assert first["selected_network_policy"] is None
    assert first["approval_reason"] is None
    assert "grocery" not in first["observed_destination_categories"]
    assert first["inventory_totals"] == {"observed_origins": 174, "observed_destinations": 32, "supermarket": 16, "convenience": 16}
    assert first["snap_distance_m"] == 30.0
    assert first["topology_tolerance_m"] == 0.05
    assert first["junction_known_path"]["matches_expected"] is True
    assert first["junction_known_path"]["way_ids"] == ["way/junction-east", "way/junction-north"]
    assert _analytical_r03(first) == _analytical_r03(second)
    for option in first["network_options"]:
        metrics = option["metrics"]
        assert metrics["origin_snapping_coverage"]["total_count"] == 174
        assert metrics["destination_snapping_coverage"]["total_count"] == 32
        assert metrics["known_path_validation"]["matches_expected"] is True
        for feature_id in [*metrics["snapped_origin_ids"], *metrics["unsnapped_origin_ids"], *metrics["origin_component_ids"]]:
            assert not str(feature_id).startswith("reference-node/")
        by_tags = {frozenset(item["destination_tags"]): item for item in option["destination_option_coverage"]}
        assert by_tags[frozenset({"supermarket"})]["total_count"] == 16
        assert by_tags[frozenset({"convenience"})]["total_count"] == 16
        assert by_tags[frozenset({"supermarket", "convenience"})]["total_count"] == 32
    for item in first["denominator_coverage"]:
        assert "reference-node/" not in json.dumps(item)
    written = write_spatial_decision_addendum_r03(FROZEN_SPATIAL_R01, tmp_path)
    again = write_spatial_decision_addendum_r03(FROZEN_SPATIAL_R01, tmp_path)
    assert written == again
    assert verify_spatial_decision_addendum_r03(written, FROZEN_SPATIAL_R01) == verify_spatial_decision_addendum_r03(again, FROZEN_SPATIAL_R01)


def _publish_r03_copy(source: Path, destination: Path, mutate) -> Path:
    copied = destination
    if copied.exists():
        shutil.rmtree(copied)
    shutil.copytree(source, copied)
    payload = json.loads((copied / "decision-addendum.json").read_text(encoding="utf-8"))
    mutate(payload)
    _write_json(copied / "decision-addendum.json", payload)
    _write_json(copied / "origin-map.geojson", payload["origin_map"])
    _write_json(copied / "origin-review-table.json", {"rows": payload["review_table"], "ambiguous_clusters": payload["unresolved_ambiguous_clusters"]})
    _write_json(
        copied / "network-policy-metrics.json",
        {
            "options": payload["network_options"],
            "denominator_coverage": payload["denominator_coverage"],
            "inventory_totals": payload["inventory_totals"],
            "junction_known_path": payload["junction_known_path"],
        },
    )
    _regenerate_r03_manifest(copied)
    return copied


def _r03_choice(addendum: dict[str, object]) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    origin = next(option for option in addendum["origin_options"] if option["member_ids"])
    destination = next(option for option in addendum["destination_options"] if option.get("destination_tags") or option.get("cli_destination_tags"))
    network = next(option for option in addendum["network_options"] if option["option_id"] == "all-observed-highways")
    return origin, destination, network


def test_r03_approval_uses_the_strict_verifier_and_binds_the_manifest(tmp_path: Path, monkeypatch) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-r03-approve")
    addendum_dir = write_spatial_decision_addendum_r03(package_dir, tmp_path / "addenda")
    addendum = json.loads((addendum_dir / "decision-addendum.json").read_text(encoding="utf-8"))
    origin, destination, network = _r03_choice(addendum)
    calls = {"strict": 0, "weak": 0}
    real_strict = verify_spatial_decision_addendum_r03

    def strict(*args, **kwargs):
        calls["strict"] += 1
        return real_strict(*args, **kwargs)

    def weak(*_args, **_kwargs):
        calls["weak"] += 1
        raise AssertionError("r03 approval used the weak verifier")

    monkeypatch.setattr("urban_design.spatial_input_policy.verify_spatial_decision_addendum_r03", strict)
    monkeypatch.setattr("urban_design.spatial_input_policy.verify_repaired_spatial_addendum", weak)
    acceptance_dir = approve_spatial_addendum_options(
        database,
        addendum_dir,
        package_dir,
        tmp_path / "acceptance",
        actor=ACTOR,
        reason=REASON,
        origin_option_id=origin["option_id"],
        destination_option_id=destination["option_id"],
        network_option_id=network["option_id"],
        approved_at=datetime(2026, 9, 22, 11, 0, tzinfo=timezone.utc),
    )
    assert calls == {"strict": 1, "weak": 0}
    acceptance = json.loads((acceptance_dir / "spatial-input-acceptance.json").read_text(encoding="utf-8"))
    manifest_hash = sha256_bytes((addendum_dir / "package-manifest.json").read_bytes())
    assert acceptance["decision_binding"]["decision_addendum_manifest_sha256"] == manifest_hash
    assert acceptance["parameters"]["origin_denominator"]["value"]["origin_ids"] == origin["member_ids"]
    assert acceptance["parameters"]["destination_taxonomy"]["value"]["destination_tags"] == (destination.get("destination_tags") or destination.get("cli_destination_tags"))
    assert acceptance["parameters"]["pedestrian_network"]["value"]["include_highways"] == network["network_policy"]["include_highways"]
    assert addendum["selected_origin_ids"] is None
    assert addendum["selected_destination_tags"] is None
    assert addendum["selected_network_policy"] is None
    assert addendum["approval_reason"] is None


def test_r03_approval_rejects_regenerated_semantic_tamper_before_any_write(tmp_path: Path) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-r03-tamper")
    addendum_dir = write_spatial_decision_addendum_r03(package_dir, tmp_path / "addenda")
    tampered = _publish_r03_copy(
        addendum_dir,
        tmp_path / "tampered",
        lambda payload: payload["inventory_totals"].__setitem__("observed_origins", 1),
    )
    addendum = json.loads((tampered / "decision-addendum.json").read_text(encoding="utf-8"))
    origin, destination, network = _r03_choice(addendum)
    assert verify_repaired_spatial_addendum(tampered, package_dir)["status"] == "PASS"
    with pytest.raises(SpatialPolicyError, match="rebuild|analytical|selection"):
        verify_spatial_decision_addendum_r03(tampered, package_dir)
    with pytest.raises(SpatialPolicyError, match="rebuild|analytical|selection"):
        approve_spatial_addendum_options(
            database,
            tampered,
            package_dir,
            tmp_path / "acceptance",
            actor=ACTOR,
            reason=REASON,
            origin_option_id=origin["option_id"],
            destination_option_id=destination["option_id"],
            network_option_id=network["option_id"],
            approved_at=datetime(2026, 9, 22, 11, 30, tzinfo=timezone.utc),
        )
    assert _decision_count(database) == (0, 0, 0)
    assert not (tmp_path / "acceptance").exists() or not any((tmp_path / "acceptance").glob("acceptance-*"))


def test_unknown_addendum_schema_fails_before_approval_writes(tmp_path: Path) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-r03-unknown")
    addendum_dir = write_spatial_decision_addendum_r03(package_dir, tmp_path / "addenda")
    unknown = _publish_r03_copy(addendum_dir, tmp_path / "unknown", lambda payload: payload.__setitem__("schema_version", "m2-a03-not-a-schema"))
    with pytest.raises(SpatialPolicyError, match="unsupported"):
        verify_addendum_for_approval(unknown, package_dir)
    with pytest.raises(SpatialPolicyError, match="unsupported"):
        approve_spatial_addendum_options(
            database,
            unknown,
            package_dir,
            tmp_path / "acceptance",
            actor=ACTOR,
            reason=REASON,
            origin_option_id="all-observed-osm-ids",
            destination_option_id="tags-supermarket",
            network_option_id="all-observed-highways",
            approved_at=datetime(2026, 9, 22, 11, 40, tzinfo=timezone.utc),
        )
    assert _decision_count(database) == (0, 0, 0)
    assert not (tmp_path / "acceptance").exists() or not any((tmp_path / "acceptance").glob("acceptance-*"))


def test_r02_approval_keeps_its_own_verifier(tmp_path: Path, monkeypatch) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-r02-route")
    addendum_dir = write_repaired_spatial_decision_addendum(package_dir, tmp_path / "addenda")
    addendum = json.loads((addendum_dir / "decision-addendum.json").read_text(encoding="utf-8"))
    origin, destination, network = _r03_choice(addendum)

    def forbid_r03(*_args, **_kwargs):
        raise AssertionError("r02 approval called the r03 verifier")

    monkeypatch.setattr("urban_design.spatial_input_policy.verify_spatial_decision_addendum_r03", forbid_r03)
    acceptance_dir = approve_spatial_addendum_options(
        database,
        addendum_dir,
        package_dir,
        tmp_path / "acceptance",
        actor=ACTOR,
        reason=REASON,
        origin_option_id=origin["option_id"],
        destination_option_id=destination["option_id"],
        network_option_id=network["option_id"],
        approved_at=datetime(2026, 9, 22, 11, 50, tzinfo=timezone.utc),
    )
    assert acceptance_dir.is_dir()
    assert verify_addendum_for_approval(addendum_dir, package_dir)["schema_version"] == addendum["schema_version"]


def test_cli_r03_approval_rejects_tamper_without_publishing(tmp_path: Path) -> None:
    database, package_dir, _project_id, _area_id = _package(tmp_path, "spatial-r03-cli")
    addendum_dir = write_spatial_decision_addendum_r03(package_dir, tmp_path / "addenda")
    addendum = json.loads((addendum_dir / "decision-addendum.json").read_text(encoding="utf-8"))
    origin, destination, network = _r03_choice(addendum)
    script = Path(__file__).resolve().parents[1] / "scripts" / "approve_m2a03_spatial_inputs.py"
    output = tmp_path / "cli-acceptance"
    common = [
        sys.executable,
        str(script),
        "--database",
        str(database),
        "--spatial-package",
        str(package_dir),
        "--output-root",
        str(output),
        "--decision-addendum",
        str(addendum_dir),
        "--actor",
        ACTOR,
        "--reason",
        REASON,
        "--origin-option-id",
        origin["option_id"],
        "--destination-option-id",
        destination["option_id"],
        "--network-option-id",
        network["option_id"],
    ]
    secret, environment = _test_decision_key_environment(tmp_path)
    valid = subprocess.run(
        common,
        check=False,
        capture_output=True,
        text=True,
        input=secret + "\n",
        env=environment,
    )
    assert valid.returncode == 0, valid.stderr
    assert secret not in valid.stdout + valid.stderr
    printed = json.loads(valid.stdout)
    assert printed["decision_binding"]["decision_addendum_manifest_sha256"] == sha256_bytes((addendum_dir / "package-manifest.json").read_bytes())
    tampered = _publish_r03_copy(
        addendum_dir,
        tmp_path / "cli-tampered",
        lambda payload: payload["network_options"][0]["network_policy"].__setitem__("include_highways", ["footway"]),
    )
    failed = subprocess.run(
        [*common[: common.index("--decision-addendum") + 1], str(tampered), *common[common.index("--decision-addendum") + 2 :]],
        check=False,
        capture_output=True,
        text=True,
        input=secret + "\n",
        env=environment,
    )
    assert failed.returncode != 0
    assert secret not in failed.stdout + failed.stderr
    assert _decision_count(database) == (3, 3, 3)
    published = list(output.glob("acceptance-*"))
    assert len(published) == 1
