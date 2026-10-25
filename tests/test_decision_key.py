from __future__ import annotations

import os
import stat
import uuid

import pytest


def test_init_saves_only_scrypt_hash_with_private_permissions(tmp_path, monkeypatch, capsys):
    from urban_design import decision_key

    monkeypatch.setenv("HOME", str(tmp_path))
    secret = "fixture-" + uuid.uuid4().hex + "-K"
    answers = iter((secret, secret))
    monkeypatch.setattr(decision_key.getpass, "getpass", lambda _prompt: next(answers))

    assert decision_key.main(["init"]) == 0

    key_file = tmp_path / ".config" / "urban-design" / "decision-key"
    assert key_file.is_file()
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(key_file.parent.stat().st_mode) == 0o700
    contents = key_file.read_text(encoding="ascii")
    assert contents.startswith("scrypt$")
    assert secret not in contents
    assert secret not in capsys.readouterr().out
    assert decision_key.verify_decision_key(secret, path=key_file)
    assert not decision_key.verify_decision_key(secret + "wrong", path=key_file)


def test_init_refuses_to_overwrite_existing_key_file(tmp_path, monkeypatch):
    from urban_design import decision_key

    monkeypatch.setenv("HOME", str(tmp_path))
    key_file = tmp_path / ".config" / "urban-design" / "decision-key"
    key_file.parent.mkdir(parents=True)
    key_file.write_text("sentinel", encoding="ascii")
    monkeypatch.setattr(decision_key.getpass, "getpass", lambda _prompt: pytest.fail("must not prompt"))

    assert decision_key.main(["init"]) != 0
    assert key_file.read_text(encoding="ascii") == "sentinel"


def test_key_verification_fails_closed_for_missing_symlink_and_insecure_mode(tmp_path):
    from urban_design import decision_key

    missing = tmp_path / "missing-key"
    assert not decision_key.verify_decision_key("irrelevant", path=missing)

    target = tmp_path / "target"
    target.write_text("not-a-key", encoding="ascii")
    link = tmp_path / "linked-key"
    link.symlink_to(target)
    assert not decision_key.verify_decision_key("irrelevant", path=link)

    insecure = tmp_path / "insecure-key"
    insecure.write_text("scrypt$16384$8$1$AA$AA", encoding="ascii")
    os.chmod(insecure, 0o644)
    assert not decision_key.verify_decision_key("irrelevant", path=insecure)


def test_decision_key_module_does_not_issue_forgeable_authorization_capabilities():
    from urban_design import decision_key

    assert not hasattr(decision_key, "DecisionKeyAuthorization")
    assert not hasattr(decision_key, "authorize_decision_key")
