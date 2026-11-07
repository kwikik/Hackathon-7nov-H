"""Gladia : un fichier audio -> la consigne en texte.

Flux officiel v2 :
  1. POST /v2/upload           (multipart)  -> audio_url
  2. POST /v2/pre-recorded     (json)       -> job id + result_url
  3. GET  /v2/pre-recorded/:id              -> result.transcription.full_transcript

Test rapide sans micro :
    python voice.py --wav commande.wav
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

API = "https://api.gladia.io/v2"
POLL_INTERVAL = 0.7
TIMEOUT = 90


class GladiaError(RuntimeError):
    pass


def _key() -> str:
    key = os.environ.get("GLADIA_API_KEY")
    if not key:
        raise GladiaError("GLADIA_API_KEY manquante (docs.gladia.io, clé gratuite).")
    return key


def transcribe(path: str | Path, language: str = "fr") -> str:
    """Transcrit un fichier audio et renvoie le texte brut."""
    load_dotenv(Path(__file__).with_name(".env"))
    headers = {"x-gladia-key": _key()}
    path = Path(path)

    with path.open("rb") as handle:
        upload = requests.post(
            f"{API}/upload",
            headers=headers,
            files={"audio": (path.name, handle, mimetypes.guess_type(path.name)[0] or "audio/wav")},
            timeout=60,
        )
    if upload.status_code >= 300:
        raise GladiaError(f"upload {upload.status_code}: {upload.text[:200]}")
    audio_url = upload.json()["audio_url"]

    job = requests.post(
        f"{API}/pre-recorded",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "audio_url": audio_url,
            "language_config": {"languages": [language], "code_switching": False},
            "diarization": False,
        },
        timeout=60,
    )
    if job.status_code >= 300:
        raise GladiaError(f"pre-recorded {job.status_code}: {job.text[:200]}")
    payload = job.json()
    job_id = payload["id"]
    result_url = payload.get("result_url", f"{API}/pre-recorded/{job_id}")

    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        poll = requests.get(result_url, headers=headers, timeout=30)
        if poll.status_code >= 300:
            raise GladiaError(f"poll {poll.status_code}: {poll.text[:200]}")
        data = poll.json()
        status = data.get("status")
        if status == "done":
            return (data.get("result", {}).get("transcription", {}) or {}).get("full_transcript", "").strip()
        if status == "error":
            raise GladiaError(f"job en erreur: {str(data)[:300]}")
        time.sleep(POLL_INTERVAL)

    raise GladiaError(f"timeout après {TIMEOUT}s sur le job {job_id}")


def clean_command(text: str) -> str:
    """Nettoie la sortie STT : ponctuation parasite, hésitations, espaces."""
    for filler in ("euh", "heu", "bah", "ben"):
        text = text.replace(f" {filler} ", " ")
    return " ".join(text.split()).strip(" .,;:")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gladia STT")
    parser.add_argument("--wav", required=True, help="fichier audio à transcrire")
    args = parser.parse_args()
    try:
        print(clean_command(transcribe(args.wav)))
    except GladiaError as exc:
        print(f"erreur: {exc}", file=sys.stderr)
        sys.exit(1)
