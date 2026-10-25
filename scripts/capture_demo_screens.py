"""Read-only screenshots of the live platform tabs for the offline backup demo (no clicks that write state)."""
import sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright
url, out = sys.argv[1], Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
tabs = [('基地', 'site'), ('條件', 'conditions'), ('生成', 'generate'), ('比較', 'compare'), ('細修', 'refine')]
with sync_playwright() as p:
    b = p.chromium.launch(headless=True); pg = b.new_page(viewport={'width': 1600, 'height': 1000})
    pg.goto(url, wait_until='networkidle'); time.sleep(3)
    lang = pg.get_by_role('button', name='English')
    if lang.count():
        lang.first.click(); time.sleep(0.5)
        zh = pg.get_by_text('中文', exact=False)
        if zh.count(): zh.first.click(); time.sleep(1)
    for label, slug in tabs:
        t = pg.get_by_role('tab', name=label)
        if not t.count(): t = pg.get_by_text(label, exact=True)
        if t.count():
            t.first.click(); time.sleep(4)
            pg.screenshot(path=str(out / f'{slug}-zh.png'))
            print('captured', slug)
        else:
            print('missing tab', label)
    b.close()
