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


# --------------------------------------------------------------------------- temps réel

# Mots que le STT générique écorche et que le jury va entendre : on les impose.
VOCABULARY = [
    "Cerfa", "ANTS", "FranceConnect", "France Connect", "CAF", "URSSAF", "Ameli", "CPAM",
    "service-public.gouv.fr", "impots.gouv.fr", "carte grise", "certificat d'immatriculation",
    "certificat de cession", "permis de conduire", "carte d'identité", "passeport",
    "APL", "RSA", "prime d'activité", "SIRET", "IBAN", "auto-entrepreneur", "Holo",
]

LIVE_SAMPLE_RATE = 16000


def init_live_session(language: str = "fr") -> dict:
    """Ouvre une session Gladia temps réel (WebSocket) et renvoie {id, url}.

    Le navigateur se connecte directement à `url` et y pousse le micro en PCM
    16 kHz mono : la transcription arrive mot à mot pendant que l'on parle, au
    lieu d'attendre upload + job + polling (~3 s) comme en mode fichier.

    `endpointing` = silence (en secondes) qui clôt une phrase. 0.05 par défaut chez
    Gladia : trop court pour une consigne dite d'une traite, une respiration la couperait.
    """
    load_dotenv(Path(__file__).with_name(".env"))
    endpointing = float(os.environ.get("GLADIA_ENDPOINTING", "0.6"))
    body = {
        "model": "solaria-1",
        "encoding": "wav/pcm",
        "sample_rate": LIVE_SAMPLE_RATE,
        "bit_depth": 16,
        "channels": 1,
        "endpointing": endpointing,
        "maximum_duration_without_endpointing": 15,
        "language_config": {"languages": [language], "code_switching": False},
        "messages_config": {"receive_partial_transcripts": True},
        "realtime_processing": {
            "custom_vocabulary": True,
            "custom_vocabulary_config": {"vocabulary": VOCABULARY, "default_intensity": 0.5},
        },
    }
    response = requests.post(
        f"{API}/live",
        headers={"x-gladia-key": _key(), "Content-Type": "application/json"},
        json=body,
        timeout=15,
    )
    if response.status_code >= 300:
        raise GladiaError(f"live {response.status_code}: {response.text[:300]}")
    data = response.json()
    if "url" not in data:
        raise GladiaError(f"live: réponse sans url ({str(data)[:200]})")
    return {"id": data.get("id"), "url": data["url"], "sample_rate": LIVE_SAMPLE_RATE}


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
