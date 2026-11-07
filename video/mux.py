"""Genere le lit musical + mixe voix off et video_silent.mp4 -> cerfa_agent.mp4."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
AUDIO = ROOT / "audio"
TL = json.loads((ROOT / "timeline.json").read_text(encoding="utf-8"))
TOTAL = TL["total"] + 0.4


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_music() -> Path:
    """Pad sombre + pulse discret, genere en aevalsrc. Volume bas."""
    out = AUDIO / "music.wav"
    expr = (
        "0.055*sin(2*PI*55*t)*(0.55+0.45*sin(2*PI*0.055*t))"
        "+0.045*sin(2*PI*82.41*t)*(0.55+0.45*sin(2*PI*0.041*t))"
        "+0.030*sin(2*PI*110*t)*(0.55+0.45*sin(2*PI*0.073*t))"
        "+0.018*sin(2*PI*164.81*t)*(0.55+0.45*sin(2*PI*0.031*t))"
        "+0.030*sin(2*PI*50*t)*exp(-9*mod(t,0.652))"
    )
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={TOTAL:.2f}",
        "-af", "lowpass=f=2200,aecho=0.7:0.55:180|420:0.35|0.22,"
               "afade=t=in:st=0:d=2.5,afade=t=out:st=" + f"{TOTAL - 2.2:.2f}" + ":d=2.2",
        "-ac", "1", str(out),
    ])
    return out


def make_voice() -> Path:
    """Concatene les prises voix avec les silences exacts de la timeline."""
    inputs, filters, labels = [], [], []
    for i, sc in enumerate(TL["scenes"]):
        mp3 = AUDIO / f"vo_{sc['id']}.mp3"
        inputs += ["-i", str(mp3)]
        delay = int(round(sc["audio_start"] * 1000))
        filters.append(f"[{i}:a]aresample=44100,adelay={delay}|{delay}[v{i}]")
        labels.append(f"[v{i}]")
    out = AUDIO / "voice.wav"
    run(["ffmpeg", "-y", *inputs, "-filter_complex",
         ";".join(filters) + ";" + "".join(labels) + f"amix=inputs={len(labels)}:normalize=0,"
         f"apad,atrim=0:{TOTAL:.2f}[mix]",
         "-map", "[mix]", "-ac", "1", str(out)])
    return out


def main() -> None:
    music = make_music()
    voice = make_voice()
    final = ROOT / "cerfa_agent.mp4"

    run([
        "ffmpeg", "-y",
        "-i", str(ROOT / "video_silent.mp4"),
        "-i", str(voice),
        "-i", str(music),
        "-filter_complex",
        "[1:a]volume=1.0[lv];[2:a]volume=0.30,highpass=f=40[lm];"
        "[lv][lm]amix=inputs=2:duration=longest:weights=1 0.42,"
        "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", str(final),
    ])
    print("OK ->", final, final.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
