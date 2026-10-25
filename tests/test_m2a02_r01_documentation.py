"""Consistency checks for the M2-A02-R01 active-site documentation repair."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE_DOCS = (
    ROOT / "docs/00_PRODUCT_VISION.md",
    ROOT / "docs/01_PRODUCT_REQUIREMENTS.md",
    ROOT / "docs/02_SYSTEM_ARCHITECTURE.md",
    ROOT / "docs/03_AGENT_ARCHITECTURE.md",
    ROOT / "docs/05_EVIDENCE_FRAMEWORK.md",
    ROOT / "docs/06_EVALUATION_FRAMEWORK.md",
    ROOT / "docs/07_IMPLEMENTATION_PLAN.md",
)


def test_forward_looking_mvp_identity_is_rotterdam_m4h() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in AUTHORITATIVE_DOCS)
    stale_active_patterns = (
        r"one researcher working on one Delft case",
        r"one human-confirmed Delft StudyArea",
        r"approved Delft pilot",
        r"selected Delft site",
        r"implementation must demonstrate one human-confirmed, human-drawn Delft",
    )
    for pattern in stale_active_patterns:
        assert re.search(pattern, text, flags=re.IGNORECASE) is None, pattern

    assert "Rotterdam M4H" in text
    assert "human-confirmed Rotterdam M4H" in text
    assert "M2-A02-R01 decision record" in text
    assert "DesignBoundary" in text and "HumanDecision" in text


def test_historical_delft_evidence_is_still_labeled_and_preserved() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs/07_IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")

    assert "Historical M2-R01" in readme
    assert "site-proposal-delft-v2" in readme
    assert "site-proposal-delft-v3" in readme
    assert "Delft proposal packages remain historical" in plan
    assert "rejected or proposed Rotterdam boundary" in plan
