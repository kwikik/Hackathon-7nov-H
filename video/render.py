"""Rend la timeline HTML en suite de frames puis en MP4 (sans audio).

  python render.py --preview 1.0 6.0 16.0     # quelques PNG pour controle
  python render.py                            # rendu complet + video_silent.mp4
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
EXE = os.path.expandvars(
    r"%LOCALAPPDATA%\ms-playwright\chromium_headless_shell-1243\chrome-headless-shell-win64\chrome-headless-shell.exe"
)
W, H = 1920, 1080


def boot(pg, tl: dict):
    pg.add_init_script("window.__TL__ = " + json.dumps(tl, ensure_ascii=False) + ";")
    pg.goto((ROOT / "index.html").as_uri())
    pg.wait_for_function("window.__TL__ !== undefined && document.fonts.status === 'loaded'")
    pg.wait_for_timeout(250)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", nargs="*", type=float, default=None)
    ap.add_argument("--fps", type=int, default=0)
    args = ap.parse_args()

    tl = json.loads((ROOT / "timeline.json").read_text(encoding="utf-8"))
    fps = args.fps or tl["fps"]
    total = tl["total"]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, executable_path=EXE,
            args=["--force-color-profile=srgb", "--hide-scrollbars",
                  "--disable-lcd-text", "--font-render-hinting=none"],
        )
        pg = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        boot(pg, tl)

        if args.preview is not None:
            out = ROOT / "preview"
            out.mkdir(exist_ok=True)
            for t in args.preview:
                pg.evaluate(f"renderFrame({t})")
                pg.screenshot(path=str(out / f"t{t:06.2f}.png".replace(".", "_", 1)))
                print("preview", t)
            browser.close()
            return

        frames = ROOT / "frames"
        if frames.exists():
            shutil.rmtree(frames)
        frames.mkdir()
        n = int(round(total * fps))
        t0 = time.time()
        for i in range(n):
            pg.evaluate(f"renderFrame({i / fps})")
            pg.screenshot(path=str(frames / f"f{i:05d}.jpg"), type="jpeg", quality=94)
            if i % 300 == 0:
                el = time.time() - t0
                print(f"{i}/{n}  {el:5.1f}s  ({i / max(el, .001):.0f} fps rendu)", flush=True)
        browser.close()

    elapsed = time.time() - t0
    print(f"frames OK: {n} en {elapsed:.1f}s")

    out_mp4 = ROOT / "video_silent.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-framerate", str(fps), "-i", str(frames / "f%05d.jpg"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-preset", "medium",
        "-movflags", "+faststart", str(out_mp4),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("video_silent.mp4 ->", out_mp4, out_mp4.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
