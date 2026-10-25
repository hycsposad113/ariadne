from __future__ import annotations

import pytest

from urban_design.models import RunStatus
from urban_design.week7.service import Week7Refusal, idempotency_key
from tests.week7_support import seed_pair

pytest_plugins = ["tests.week7_support"]

WORKSPACE = "ws-w7"


def test_late_b1_result_does_not_become_b2_current(service) -> None:
    seed_pair(service)
    service.switch_scheme(
        WORKSPACE,
        project_id="rotterdam-m4h-pilot-project",
        scenario_id="B1",
        revision="rev-b1",
        results=[{"kind": "gfa_far", "value": 1.1, "unit": "ratio"}],
    )
    idem = idempotency_key(actor="designer", action="run", expected_revision="rev-b1", logical_request="b1-sun")
    job = service.submit_job(WORKSPACE, logical_run_id="b1-sun", idempotency=idem, expected_revision="rev-b1")
    service.switch_scheme(
        WORKSPACE,
        project_id="rotterdam-m4h-pilot-project",
        scenario_id="B2",
        revision="rev-b2",
        results=[{"kind": "gfa_far", "value": 2.2, "unit": "ratio"}],
    )
    delivered = service.deliver_job(job["job_id"], value=1.1)
    view = service.view(WORKSPACE)
    assert delivered["stored_on_scenario"] == "B1"
    assert delivered["current_scenario"] == "B2"
    assert delivered["polluted_current"] is False
    assert view["scenario_id"] == "B2"
    assert view["panels"]["dashboard"]["far"] == 2.2
    assert view["panels"]["map"]["revision"] == "rev-b2"


def test_duplicate_submit_and_second_tab_do_not_create_a_second_logical_run(service) -> None:
    seed_pair(service)
    idem = idempotency_key(actor="designer", action="run", expected_revision="rev-b2", logical_request="once")
    first = service.submit_job(WORKSPACE, logical_run_id="once", idempotency=idem, expected_revision="rev-b2")
    second = service.submit_job(WORKSPACE, logical_run_id="once", idempotency=idem, expected_revision="rev-b2")
    assert first["job_id"] == second["job_id"]
    assert second["created_new"] is False


def test_revision_conflict_is_visible_and_does_not_overwrite(service) -> None:
    seed_pair(service)
    idem = idempotency_key(actor="designer", action="run", expected_revision="rev-b1", logical_request="stale-tab")
    with pytest.raises(Week7Refusal) as caught:
        service.submit_job(WORKSPACE, logical_run_id="stale-tab", idempotency=idem, expected_revision="rev-b1")
    assert caught.value.code == "revision_conflict"
    assert caught.value.detail["diff"] == {"submitted": "rev-b1", "head": "rev-b2"}
    assert service.view(WORKSPACE)["revision"] == "rev-b2"


def test_post_dispatch_loss_stays_outcome_unknown_and_is_not_resent(service) -> None:
    seed_pair(service)
    idem = idempotency_key(actor="designer", action="run", expected_revision="rev-b2", logical_request="lost")
    job = service.submit_job(WORKSPACE, logical_run_id="lost", idempotency=idem, expected_revision="rev-b2")
    recovered = service.reconcile_job(
        job["job_id"],
        receipt={"id": "receipt-1"},
        process_state=None,
        output_hash=None,
        ledger_event_id=None,
    )
    assert recovered["status"] == RunStatus.OUTCOME_UNKNOWN.value
    assert recovered["resent"] is False
    assert recovered["resubmit_count"] == 0


def test_delivered_cancel_does_not_mean_the_process_stopped(service) -> None:
    seed_pair(service)
    idem = idempotency_key(actor="designer", action="run", expected_revision="rev-b2", logical_request="cancel")
    job = service.submit_job(WORKSPACE, logical_run_id="cancel", idempotency=idem, expected_revision="rev-b2")
    cancelled = service.cancel_job(job["job_id"])
    assert cancelled["cancel_request_delivered"] is True
    assert cancelled["external_process_stopped"] is False
    assert cancelled["status"] == RunStatus.RUNNING.value
