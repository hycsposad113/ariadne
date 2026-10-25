"""Render an SVG to PNG at its full declared size (no square crop) with headless Chromium."""
import re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

def main(svg_path: str, png_path: str, scale: float = 2.0) -> None:
    svg = Path(svg_path).read_text(encoding="utf-8")
    m = re.search(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"', svg)
    w, h = (int(float(m.group(1))), int(float(m.group(2)))) if m else (1200, 1200)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
        page.set_content(f"<html><body style='margin:0'>{svg}</body></html>")
        page.screenshot(path=png_path, clip={"x": 0, "y": 0, "width": w, "height": h})
        browser.close()

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 2.0)
