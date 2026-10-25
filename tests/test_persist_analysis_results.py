from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import scripts.persist_analysis_results as persistence_module
from scripts.persist_analysis_results import (
    _ensure_record,
    backup_database_readonly,
    build_parser,
    enrich_week5_syntax_candidate,
    main,
    sha256_file,
)


def test_persistence_cli_defaults_to_disposable_dry_run() -> None:
    args = build_parser().parse_args(["--database", "/tmp/source.sqlite3"])
    assert args.write_authority is False
    assert args.dry_run is False  # absence of --write-authority selects copy-first mode
    assert args.expected_sha256 is None


def test_authority_write_requires_expected_hash_before_database_access(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--database", "/does/not/exist.sqlite3", "--write-authority"])
    assert exc.value.code == 2
    assert "--write-authority requires --expected-sha256" in capsys.readouterr().err


def test_readonly_sqlite_backup_is_independent_and_self_contained(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    copy = tmp_path / "copy.sqlite3"
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE retained (value TEXT NOT NULL)")
    connection.execute("INSERT INTO retained(value) VALUES ('preserve')")
    connection.commit()
    connection.close()
    source_hash_before = sha256_file(source)

    backup_database_readonly(source, copy)

    assert sha256_file(source) == source_hash_before
    assert copy.is_file()
    assert sha256_file(copy) != source_hash_before
    with sqlite3.connect(copy.as_uri() + "?mode=ro", uri=True) as copied:
        assert copied.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert copied.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert copied.execute("SELECT value FROM retained").fetchone()[0] == "preserve"


def test_authority_write_rechecks_database_hash_after_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = Path("/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3")
    database = tmp_path / "authority-test-copy.sqlite3"
    backup_database_readonly(source, database)
    expected = sha256_file(database)
    monkeypatch.setattr(persistence_module, "AUTHORITY_DB", database.resolve())
    original_backup = persistence_module.backup_database_readonly

    def mutate_after_backup(source_path: Path, backup_path: Path) -> None:
        original_backup(source_path, backup_path)
        with sqlite3.connect(source_path) as connection:
            connection.execute("PRAGMA user_version = 91")

    monkeypatch.setattr(persistence_module, "backup_database_readonly", mutate_after_backup)
    monkeypatch.setattr(
        persistence_module,
        "_persist_pd20_to_open_store",
        lambda *args, **kwargs: pytest.fail("writable persistence opened after the database hash changed"),
    )

    with pytest.raises(RuntimeError, match="changed after expected SHA-256 validation and backup"):
        persistence_module.persist_database(
            database,
            syntax_modes_run_dir=tmp_path / "unused-syntax-run",
            three_d_bag_manifest=tmp_path / "unused-3dbag-manifest.json",
            write_authority=True,
            expected_sha256=expected,
            backup_dir=tmp_path,
        )


def test_week5_syntax_candidate_records_mode_provenance_and_exploratory_limits() -> None:
    modes = ("pedestrian", "bicycle", "motor_vehicle")
    radii = (800.0, 2000.0, 10000.0)
    metrics = ("nain", "nach")
    layers = []
    for mode, radius in zip(modes, radii):
        scale = {800.0: "local", 2000.0: "mid", 10000.0: "regional"}[radius]
        for metric in metrics:
            suffix = "integration" if metric == "nain" else "choice"
            layers.append({
                "layer_id": f"syntax_{scale}_{int(radius)}m_{suffix}",
                "title": f"{scale} {radius:g} {suffix}",
                "scale": scale,
                "network_mode": mode,
                "radius_m": radius,
                "metric_key": metric,
                "unit": f"{metric.upper()} (normalized)",
                "calculation_status": "COMPUTED",
                "data_readiness": "EXPLORATORY",
                "formula_version": "pstalgo-3.3.1-test-v1",
                "engine": "PST 3.3.1",
                "limitations": "Source completeness is not established.",
                "segment_values": {f"segment-{mode}": 0.5},
                "statistics": {"min": 0.5, "mean": 0.5, "max": 0.5, "count": 1},
            })
    candidate = {
        "schema_version": "week5-six-syntax-layer-candidate-v1",
        "status": "EXPLORATORY_CANDIDATE",
        "engine": "PST 3.3.1",
        "policy_version": "syntax-network-policy-v2",
        "study_area_sha256": "a" * 64,
        "layers": layers,
        "layer_plan": [dict(layer, segment_values={}) for layer in layers],
        "limitations": ["Candidate evidence remains exploratory."],
    }
    provenance = {
        layer["layer_id"]: {
            "primary_output_path": f"syntax-{layer['network_mode']}.json",
            "primary_output_sha256": "b" * 64,
            "download_envelope": {"buffer_radius_m": layer["radius_m"] + 700},
            "stability_result": (
                {"status": "NOT_ASSESSED", "reason": "No second-envelope run."}
                if layer["network_mode"] == "pedestrian"
                else {"status": "PASS", "spearman": 1.0}
            ),
            "boundary_effect_limitation": "Boundary sensitivity is not a source-completeness test.",
        }
    for layer in layers
    }
    segments = {
        mode: [{
            "id": f"{mode}:segment-{mode}",
            "source_segment_id": f"segment-{mode}",
            "source_line_id": "way/1",
        }]
        for mode in modes
    }

    result = enrich_week5_syntax_candidate(
        candidate,
        candidate_sha256="c" * 64,
        run_manifest_sha256="d" * 64,
        layer_provenance=provenance,
        segments_by_mode=segments,
    )

    assert result["evidence_level"] == "EXPLORATORY"
    assert result["method_of_record"] == "PST 3.3.1 (PD-15)"
    assert any("method-comparison-v1: FAIL" in item for item in result["limitations"])
    assert len(result["layers"]) == 6
    for layer in result["layers"]:
        assert layer["exploratory_only"] is True
        assert layer["formal_result_eligible"] is False
        assert layer["study_area_sha256"] == "a" * 64
        assert layer["output_file_sha256"] == "b" * 64
        assert layer["network_policy_version"] == "syntax-network-policy-v2"
        assert "method-comparison-v1: FAIL" in layer["limitations"]
    assert result["layers"][0]["stability_result"]["status"] == "NOT_ASSESSED"
    assert len(result["segments"]) == 3


def test_week5_syntax_candidate_rejects_incomplete_layer_provenance() -> None:
    candidate = {
        "schema_version": "week5-six-syntax-layer-candidate-v1",
        "status": "EXPLORATORY_CANDIDATE",
        "engine": "PST 3.3.1",
        "policy_version": "syntax-network-policy-v2",
        "study_area_sha256": "a" * 64,
        "layers": [],
        "layer_plan": [],
        "limitations": [],
    }
    with pytest.raises(ValueError, match="exactly six layers"):
        enrich_week5_syntax_candidate(
            candidate,
            candidate_sha256="c" * 64,
            run_manifest_sha256="d" * 64,
            layer_provenance={},
            segments_by_mode={},
        )


def test_existing_receipt_path_blocks_before_database_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text("preserve", encoding="utf-8")

    def unexpected_persist(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("database persistence must not be called when receipt path already exists")

    monkeypatch.setattr("scripts.persist_analysis_results.persist_database", unexpected_persist)
    with pytest.raises(SystemExit) as exc:
        main([
            "--database", "/does/not/exist.sqlite3",
            "--write-authority",
            "--expected-sha256", "0" * 64,
            "--receipt-out", str(receipt),
        ])
    assert exc.value.code == 2
    assert "refusing to overwrite receipt" in capsys.readouterr().err
    assert receipt.read_text(encoding="utf-8") == "preserve"


def test_existing_evidence_card_is_idempotent_when_only_created_at_differs() -> None:
    class Store:
        def __init__(self, payload: dict[str, object]) -> None:
            self.record = type("Record", (), {"entity_type": "EvidenceCard", "payload": payload})()

        def current(self, entity_id: str) -> object:
            assert entity_id == "card-1"
            return self.record

        def create(self, **kwargs: object) -> object:
            raise AssertionError("an existing card must not be recreated")

    original = {"id": "card-1", "created_at": "2026-09-25T21:38:31.729281Z", "claim": {"statement": "same evidence"}}
    refreshed = {"id": "card-1", "created_at": "2026-09-26T03:45:49.083362Z", "claim": {"statement": "same evidence"}}
    store = Store(original)

    result = _ensure_record(store, "EvidenceCard", refreshed, project_id="project", session_id="session", action="CreateEvidenceCard")

    assert result is store.record
    assert store.record.payload["created_at"] == original["created_at"]


def test_existing_evidence_card_rejects_any_non_timestamp_change() -> None:
    class Store:
        def __init__(self, payload: dict[str, object]) -> None:
            self.record = type("Record", (), {"entity_type": "EvidenceCard", "payload": payload})()

        def current(self, entity_id: str) -> object:
            assert entity_id == "card-1"
            return self.record

        def create(self, **kwargs: object) -> object:
            raise AssertionError("an existing card must not be recreated")

    original = {"id": "card-1", "created_at": "2026-09-25T21:38:31.729281Z", "claim": {"statement": "same evidence"}}
    changed = {"id": "card-1", "created_at": "2026-09-26T03:45:49.083362Z", "claim": {"statement": "different evidence"}}
    store = Store(original)

    with pytest.raises(ValueError, match="differs from the verified source record"):
        _ensure_record(store, "EvidenceCard", changed, project_id="project", session_id="session", action="CreateEvidenceCard")
