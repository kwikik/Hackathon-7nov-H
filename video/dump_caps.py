import json, os
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).parent
EXE=os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium_headless_shell-1243\chrome-headless-shell-win64\chrome-headless-shell.exe")
tl=json.loads((ROOT/'timeline.json').read_text(encoding='utf-8'))
with sync_playwright() as p:
    b=p.chromium.launch(headless=True, executable_path=EXE)
    pg=b.new_page(viewport={'width':1920,'height':1080})
    pg.add_init_script("window.__TL__ = "+json.dumps(tl,ensure_ascii=False)+";")
    pg.goto((ROOT/'index.html').as_uri())
    pg.wait_for_function("document.fonts.status==='loaded'")
    caps=pg.evaluate("window.__caps.map(c=>c.map(w=>w.w).join(' '))")
    pos=pg.evaluate("(()=>{const p=positions();return p})()")
    for c in caps: print('|', c)
    print('POS', json.dumps(pos))
    b.close()
