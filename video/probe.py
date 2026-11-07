from playwright.sync_api import sync_playwright
import os, time
EXE = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium_headless_shell-1243\chrome-headless-shell-win64\chrome-headless-shell.exe")
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, executable_path=EXE, args=["--force-color-profile=srgb","--hide-scrollbars","--disable-lcd-text"])
    pg = b.new_page(viewport={'width':1920,'height':1080}, device_scale_factor=1)
    pg.set_content("""<html><body style="margin:0;background:#0b0b0f;color:#fff;font-family:'Segoe UI',sans-serif">
    <div style="padding:80px"><div style="font-size:120px;font-weight:800;letter-spacing:-4px">CERFA<span style="color:#7C5CFF">.</span></div>
    <div style="font-size:40px;opacity:.7">Tu parles. Il clique.</div></div></body></html>""")
    t0=time.time()
    for i in range(5):
        pg.screenshot(path=f"probe_{i}.png")
    print("OK 5 shots in", round(time.time()-t0,2), "s")
    print(pg.evaluate("document.fonts.check('700 120px \"Segoe UI\"')"))
    b.close()
