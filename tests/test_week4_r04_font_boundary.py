"""The shipped interface uses local/system fonts without external font hosts."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_html_does_not_load_google_fonts():
    html = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8").lower()
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html


def test_css_uses_system_font_fallbacks():
    css = (PROJECT_ROOT / "web/src/index.css").read_text(encoding="utf-8").lower()
    assert "--font-sans:" in css
    assert "system-ui" in css or "-apple-system" in css
    assert "--font-mono:" in css
    assert "ui-monospace" in css or "sfmono-regular" in css
