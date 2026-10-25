"""Security and reliability tests for the bounded QGIS facade."""

from __future__ import annotations

import threading
import time

import pytest

from urban_design.qgis_facade import QgisMCPFacade, QgisFacadePolicy


def test_policy_denies_unrestricted_and_out_of_root_requests(tmp_path):
    policy = QgisFacadePolicy(controlled_root=tmp_path)
    for operation in ("execute_code", "qgis.execute_code", "dynamic_python", "run_sql", "batch_process"):
        with pytest.raises(PermissionError, match="denied"):
            policy.validate(operation, {"output_path": str(tmp_path / "result.gpkg")})
    with pytest.raises(PermissionError, match="outside"):
        policy.validate(
            "urban.render_evidence_map",
            {"project_id": "project-1", "layer_ids": ["layer-1"], "output_path": str(tmp_path.parent / "result.gpkg")},
        )


def test_facade_allows_registered_operation_but_serializes_dispatch(tmp_path):
    policy = QgisFacadePolicy(controlled_root=tmp_path)
    active = 0
    maximum = 0
    guard = threading.Lock()

    def dispatch(operation, request):
        nonlocal active, maximum
        assert operation == "urban.validate_crs"
        with guard:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.01)
        with guard:
            active -= 1
        return {"ok": True, "request": request}

    facade = QgisMCPFacade(policy, dispatch)
    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(
                facade.execute(
                    "urban.validate_crs",
                    {
                        "layer_id": "layer-1",
                        "snapshot_id": "snapshot-1",
                        "expected_crs": "EPSG:3857",
                        "output_path": str(tmp_path / "result.gpkg"),
                    },
                    request_id=f"request-{index}",
                )
            )
        )
        for index in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert maximum == 1
    assert {result.status for result in results} == {"SUCCEEDED"}
    assert all(result.dispatched and not result.retry_allowed for result in results)


def test_connection_loss_after_dispatch_is_outcome_unknown_without_retry(tmp_path):
    policy = QgisFacadePolicy(controlled_root=tmp_path)
    calls = []

    def lost_dispatch(operation, request):
        calls.append((operation, request))
        raise ConnectionError("socket closed after dispatch")

    facade = QgisMCPFacade(policy, lost_dispatch)
    result = facade.execute(
        "urban.buffer_fixture",
        {"input_path": str(tmp_path / "point.geojson"), "output_path": str(tmp_path / "result.gpkg"), "distance_m": 10, "segments": 4},
        request_id="request-unknown",
    )
    assert result.status == "OUTCOME_UNKNOWN"
    assert result.dispatched is True
    assert result.retry_allowed is False
    assert len(calls) == 1


def test_facade_rejects_non_object_requests(tmp_path):
    facade = QgisMCPFacade(QgisFacadePolicy(controlled_root=tmp_path), lambda *_: None)
    with pytest.raises(TypeError, match="object"):
        facade.execute("urban.validate_crs", [], request_id="request-1")


def test_policy_rejects_unregistered_algorithm_or_parameter_keys(tmp_path):
    policy = QgisFacadePolicy(controlled_root=tmp_path)
    with pytest.raises(PermissionError, match="parameter"):
        policy.validate("urban.calculate_far", {"algorithm": "native:buffer"})
    with pytest.raises(PermissionError, match="parameter"):
        policy.validate("urban.validate_crs", {"code": "print('unsafe')"})


def test_policy_requires_operation_parameters(tmp_path):
    policy = QgisFacadePolicy(controlled_root=tmp_path)
    with pytest.raises(PermissionError, match="required"):
        policy.validate("urban.get_project_info", {})
    with pytest.raises(PermissionError, match="required"):
        policy.validate("urban.validate_crs", {"expected_crs": "EPSG:3857"})


def test_policy_bounds_input_paths_and_numeric_ranges(tmp_path):
    policy = QgisFacadePolicy(controlled_root=tmp_path)
    with pytest.raises(PermissionError, match="outside"):
        policy.validate("urban.load_snapshot", {"snapshot_id": "snapshot-1", "snapshot_path": str(tmp_path.parent / "snapshot.gpkg")})
    with pytest.raises(ValueError, match="positive"):
        policy.validate("urban.calculate_far", {"scenario_id": "scenario-1", "footprint_area_m2": -1, "site_area_m2": 100})


def test_buffer_fixture_operation_has_fixed_geometry_parameters(tmp_path):
    policy = QgisFacadePolicy(controlled_root=tmp_path)
    request = policy.validate(
        "urban.buffer_fixture",
        {
            "input_path": str(tmp_path / "point.geojson"),
            "output_path": str(tmp_path / "buffer.gpkg"),
            "distance_m": 10,
            "segments": 4,
        },
    )
    assert request["distance_m"] == 10
    assert request["segments"] == 4
    with pytest.raises(PermissionError, match="parameter"):
        policy.validate(
            "urban.buffer_fixture",
            {**request, "algorithm": "native:buffer"},
        )


def test_policy_cannot_expand_the_closed_allowlist(tmp_path):
    with pytest.raises(ValueError, match="allowlist"):
        QgisFacadePolicy(controlled_root=tmp_path, allowed_operations=frozenset({"custom.operation"}))


def test_denied_request_is_audited_without_transport(tmp_path):
    input_root = tmp_path / "inputs"
    output_root = tmp_path / "run"
    input_root.mkdir()
    output_root.mkdir()
    calls = []
    audits = []
    facade = QgisMCPFacade(
        QgisFacadePolicy(approved_input_roots=(input_root,), run_output_root=output_root),
        lambda *args: calls.append(args),
        audit_sink=audits.append,
    )
    with pytest.raises(PermissionError):
        facade.execute("execute_code", {"output_path": str(output_root / "x.gpkg")}, request_id="deny-1")
    assert calls == []
    assert len(audits) == 1
    assert audits[0].status == "REJECTED"
    assert audits[0].dispatched is False
    assert audits[0].transport_called is False


def test_explicit_roots_reject_input_output_crossing_and_symlink_escape(tmp_path):
    input_root = tmp_path / "inputs"
    output_root = tmp_path / "run"
    outside = tmp_path / "outside"
    input_root.mkdir()
    output_root.mkdir()
    outside.mkdir()
    link = input_root / "escape"
    link.symlink_to(outside, target_is_directory=True)
    policy = QgisFacadePolicy(approved_input_roots=(input_root,), run_output_root=output_root)
    with pytest.raises(PermissionError, match="approved input roots"):
        policy.validate("urban.load_snapshot", {"snapshot_id": "s1", "snapshot_path": str(link / "snapshot.gpkg")})
    with pytest.raises(PermissionError, match="run output root"):
        policy.validate(
            "urban.render_evidence_map",
            {"project_id": "p1", "layer_ids": ["l1"], "output_path": str(input_root / "unsafe.gpkg")},
        )


def test_policy_rejects_symlinked_root(tmp_path):
    input_root = tmp_path / "inputs"
    output_root = tmp_path / "run"
    outside = tmp_path / "outside"
    input_root.mkdir()
    outside.mkdir()
    output_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        QgisFacadePolicy(approved_input_roots=(input_root,), run_output_root=output_root)
