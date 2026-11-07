"""Genere la voix off (edge-tts) + les timings de la timeline.

Sortie :
  audio/vo_<scene>.mp3
  timeline.json  -> { scenes:[{id,start,dur,audio_start,audio_dur}], words:[{t0,t1,w}], total, fps }
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import edge_tts

from script import SCENES, VOICE, RATE, HEAD_PAD, TAIL_PAD

ROOT = Path(__file__).parent
AUDIO = ROOT / "audio"
AUDIO.mkdir(exist_ok=True)


def ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ])
    return float(out.strip())


async def synth(scene: dict) -> tuple[float, list[dict]]:
    mp3 = AUDIO / f"vo_{scene['id']}.mp3"
    comm = edge_tts.Communicate(scene["text"], VOICE, rate=RATE, boundary="WordBoundary")
    words: list[dict] = []
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({
                    "t0": chunk["offset"] / 1e4 / 1000.0,
                    "t1": (chunk["offset"] + chunk["duration"]) / 1e4 / 1000.0,
                    "w": chunk["text"],
                })
    return ffprobe_duration(mp3), words


async def main() -> None:
    scenes_out = []
    words_out = []
    cursor = 0.0
    for scene in SCENES:
        dur_audio, words = await synth(scene)
        audio_start = cursor + HEAD_PAD
        dur = max(scene["min"], HEAD_PAD + dur_audio + TAIL_PAD)
        scenes_out.append({
            "id": scene["id"],
            "start": round(cursor, 3),
            "dur": round(dur, 3),
            "audio_start": round(audio_start, 3),
            "audio_dur": round(dur_audio, 3),
            "text": scene["text"],
        })
        for w in words:
            words_out.append({
                "t0": round(audio_start + w["t0"], 3),
                "t1": round(audio_start + w["t1"], 3),
                "w": w["w"],
            })
        print(f"{scene['id']:8s} audio={dur_audio:5.2f}s  scene={dur:5.2f}s  start={cursor:5.2f}s  words={len(words)}")
        cursor += dur

    timeline = {
        "fps": 30,
        "total": round(cursor + 0.6, 3),
        "scenes": scenes_out,
        "words": words_out,
    }
    (ROOT / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nTOTAL = {timeline['total']}s  ({sum(s['dur'] for s in scenes_out):.1f}s de scenes)")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
