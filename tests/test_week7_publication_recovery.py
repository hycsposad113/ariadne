from __future__ import annotations

import hashlib

import pytest

from urban_design.week7.service import Week7Refusal, Week7Service
from tests.week7_support import seed_pair

pytest_plugins = ["tests.week7_support"]


def test_before_file_fault_is_not_complete(service, tmp_path) -> None:
    with pytest.raises(Week7Refusal) as caught:
        service.publish_package(
            package_id="before",
            stage=tmp_path / "stage",
            target=tmp_path / "target",
            payload=b"bytes",
            fault="before_file",
        )
    assert caught.value.code == "publication_fault"
    assert service.publication_status("before") == "INCOMPLETE"
    recovered = service.reconcile_publication("before", tmp_path / "target")
    assert recovered["complete_with_missing_file"] is False
    assert recovered["status"] != "COMPLETE"


def test_after_file_before_db_can_be_reconciled_by_retry(service, tmp_path) -> None:
    stage = tmp_path / "stage"
    target = tmp_path / "target"
    with pytest.raises(Week7Refusal):
        service.publish_package(package_id="mid", stage=stage, target=target, payload=b"mid-bytes", fault="after_file_before_db")
    assert service.publication_status("mid") != "COMPLETE"
    assert not (target / "package.bin").exists()
    finished = service.publish_package(package_id="mid", stage=stage, target=target, payload=b"mid-bytes")
    assert finished["status"] == "COMPLETE"
    assert hashlib.sha256((target / "package.bin").read_bytes()).hexdigest() == finished["file_sha256"]


def test_db_commit_fault_rolls_back_and_reconciles(service, tmp_path) -> None:
    stage = tmp_path / "stage"
    target = tmp_path / "target"
    with pytest.raises(Week7Refusal):
        service.publish_package(
            package_id="commit",
            stage=stage,
            target=target,
            payload=b"commit-bytes",
            fault="around_db_commit",
        )
    assert service.publication_status("commit") != "COMPLETE"
    assert (target / "package.bin").read_bytes() == b"commit-bytes"
    recovered = service.reconcile_publication("commit", target)
    assert recovered["status"] == "RECONCILED"
    assert recovered["complete_with_missing_file"] is False


def test_final_directory_fault_does_not_replace_a_peer(service, tmp_path) -> None:
    peer = tmp_path / "peer"
    first = service.publish_package(package_id="peer", stage=tmp_path / "peer-stage", target=peer, payload=b"peer-bytes")
    assert first["status"] == "COMPLETE"
    with pytest.raises(Week7Refusal) as caught:
        service.publish_package(
            package_id="intruder",
            stage=tmp_path / "intruder-stage",
            target=peer,
            payload=b"intruder",
            fault="final_directory",
        )
    assert caught.value.code == "peer_package_preserved"
    assert (peer / "package.bin").read_bytes() == b"peer-bytes"


def test_restart_reconciles_a_missing_file_without_leaving_complete(service, tmp_path) -> None:
    seed_pair(service)
    target = tmp_path / "restart"
    published = service.publish_package(package_id="restart", stage=tmp_path / "restart-stage", target=target, payload=b"restart-bytes")
    (target / "package.bin").rename(target / "package.bin.absent")
    service.close()
    restored = Week7Service(service.database)
    try:
        recovered = restored.reconcile_publication("restart", target)
        assert recovered["status"] == "RECONCILED_MISSING_FILE"
        assert recovered["complete_with_missing_file"] is False
        assert restored.publication_status("restart") != "COMPLETE"
        assert published["file_sha256"]
        view = restored.view("ws-w7")
        assert view["revision"] == "rev-b2"
    finally:
        restored.close()
