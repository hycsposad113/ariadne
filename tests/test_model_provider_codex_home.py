import os
from pathlib import Path

from urban_design.model_provider import CliSubprocessCriticProvider


def test_ariadne_codex_home_is_used_when_prepared(tmp_path, monkeypatch):
    home = tmp_path / 'ariadne-codex'
    home.mkdir()
    monkeypatch.setenv('URBAN_DESIGN_ARIADNE_CODEX_HOME', str(home))
    monkeypatch.setenv('CODEX_HOME', '/global/codex')
    assert CliSubprocessCriticProvider._subprocess_environment()['CODEX_HOME'] == '/global/codex'
    (home / 'auth.json').write_text('{}')
    assert CliSubprocessCriticProvider._subprocess_environment()['CODEX_HOME'] == str(home)
