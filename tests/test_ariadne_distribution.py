"""Tests for Hermes Ariadne profile distribution package integrity and safety."""

from __future__ import annotations

import re
from pathlib import Path

DISTRIBUTION_ROOT = Path(__file__).resolve().parents[1] / "integrations" / "hermes" / "ariadne"


def test_distribution_manifest_validity() -> None:
    manifest_path = DISTRIBUTION_ROOT / "distribution.yaml"
    assert manifest_path.is_file(), "distribution.yaml must exist in the profile root"

    content = manifest_path.read_text(encoding="utf-8")
    assert re.search(r"^name:\s*ariadne\b", content, re.MULTILINE)
    assert re.search(r"^version:\s*0\.1\.0\b", content, re.MULTILINE)
    assert "hermes_requires:" in content
    assert "SOUL.md" in content
    assert "config.yaml" in content
    assert "skills/" in content


def test_soul_is_traditional_chinese_and_has_core_principles() -> None:
    soul_path = DISTRIBUTION_ROOT / "SOUL.md"
    assert soul_path.is_file(), "SOUL.md must exist in the profile root"

    text = soul_path.read_text(encoding="utf-8")
    assert "Ariadne" in text
    assert "繁體中文" in text
    assert "Rotterdam M4H" in text or "M4H" in text
    assert "先證據後建議" in text
    assert "原設計" in text or "Portfolio" in text
    assert "決策權" in text or "Humans decide" in text
    assert "不等於實際人流" in text or "不等於人流" in text
    assert "HumanDecision" in text


def test_config_contains_zero_credentials() -> None:
    config_path = DISTRIBUTION_ROOT / "config.yaml"
    assert config_path.is_file(), "config.yaml must exist in the profile root"

    raw_text = config_path.read_text(encoding="utf-8")
    # Verify no sensitive keywords exist anywhere in config.yaml
    forbidden_pattern = re.compile(r"\b(api[_-]?key|secret|token|password|keychain)\b", re.IGNORECASE)
    matches = forbidden_pattern.findall(raw_text)
    assert not matches, f"config.yaml contains forbidden credential keywords: {matches}"

    assert "name: Ariadne" in raw_text
    assert "mcp_servers:" in raw_text
    assert "ariadne:" in raw_text
    assert "urban_design.ariadne_mcp" in raw_text
    assert "command: python" in raw_text


def test_skills_directory_completeness() -> None:
    skills_dir = DISTRIBUTION_ROOT / "skills"
    assert skills_dir.is_dir(), "skills/ directory must exist"

    expected_skills = [
        "site-understanding",
        "draft-constraints",
        "preview-generation",
        "scenario-critique",
        "compare-with-portfolio",
    ]

    for skill_name in expected_skills:
        skill_path = skills_dir / skill_name / "SKILL.md"
        assert skill_path.is_file(), f"Missing SKILL.md for skill {skill_name}"
        content = skill_path.read_text(encoding="utf-8")
        assert content.startswith("---"), f"{skill_name}/SKILL.md must have frontmatter"
        assert f"name: {skill_name}" in content
        assert "description:" in content


def test_codex_cli_ariadne_persona_switch(monkeypatch) -> None:
    from urban_design.model_profiles import ModelProviderProfile
    from urban_design.model_provider import CliSubprocessCriticProvider, CriticRequest
    from urban_design.site_critic import SiteCriticService

    profile = ModelProviderProfile(
        id="codex-cli",
        adapter="cli_subprocess",
        cli_command="codex",
        model="gpt-6-luna",
        reasoning_effort="max",
        data_egress="cloud",
        enabled=True,
        use_ariadne_persona=False,
    )

    captured_commands = []
    captured_prompts = []

    def mock_runner(command, **kwargs):
        captured_commands.append(command)
        captured_prompts.append(kwargs["input"])
        assert command[-1] == "-"
        assert kwargs["input"] not in command
        import subprocess
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='{"structured_output":{"evidence_refs":[],"observations":[],"design_hypotheses":[],"limitations":[],"next_questions":[]}}',
        )

    # 1. When persona switch is False
    provider_off = CliSubprocessCriticProvider(
        profile,
        cli_runner=mock_runner,
        cli_resolver=lambda cmd: "/bin/codex",
        use_ariadne_persona=False,
    )
    assert provider_off.use_ariadne_persona is False
    monkeypatch.setattr(provider_off, "project_authorized", True)

    req = CriticRequest(study_area_id="test-study-area")
    provider_off.generate_criticism(req)
    assert len(captured_commands) == 1
    prompt_off = captured_prompts[-1]
    assert "[System Persona: Ariadne]" not in prompt_off

    # 2. When persona switch is True
    provider_on = CliSubprocessCriticProvider(
        profile,
        cli_runner=mock_runner,
        cli_resolver=lambda cmd: "/bin/codex",
        use_ariadne_persona=True,
    )
    assert provider_on.use_ariadne_persona is True
    monkeypatch.setattr(provider_on, "project_authorized", True)

    provider_on.generate_criticism(req)
    assert len(captured_commands) == 2
    prompt_on = captured_prompts[-1]
    assert "[System Persona: Ariadne]" in prompt_on
    assert "先證據後建議" in prompt_on

    # 3. Verify SiteCriticService coordinates with use_ariadne_persona
    critic_service = SiteCriticService(provider=provider_on, use_ariadne_persona=True)
    assert critic_service.use_ariadne_persona is True
