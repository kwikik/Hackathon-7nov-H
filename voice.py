"""Gladia : un fichier audio -> la consigne en texte.

Flux officiel v2 (pre-recorded) :
  1. POST /v2/upload           (multipart)  -> audio_url
  2. POST /v2/pre-recorded     (json)       -> job id + result_url
  3. GET  /v2/pre-recorded/:id              -> result.transcription.full_transcript

Modèle : Solaria-3 par défaut, le plus précis de Gladia sur le français (pre-recorded
uniquement). Solaria-1 reste disponible via GLADIA_MODEL=solaria-1.

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
DEFAULT_MODEL = "solaria-3"
POLL_INTERVAL = 0.25
TIMEOUT = 90

# Mots que le STT générique écorche et que le jury va entendre : on les impose.
VOCABULARY = [
    "Cerfa", "ANTS", "FranceConnect", "CAF", "URSSAF", "Ameli", "CPAM",
    "service-public.gouv.fr", "impots.gouv.fr", "carte grise", "certificat d'immatriculation",
    "certificat de cession", "permis de conduire", "carte d'identité", "passeport",
    "APL", "RSA", "prime d'activité", "SIRET", "IBAN", "auto-entrepreneur", "Holo",
]

# Une seule connexion HTTPS réutilisée : upload, job et polling ne refont pas
# chacun la poignée de main TLS (plusieurs centaines de ms gagnées par phrase).
_session = requests.Session()


class GladiaError(RuntimeError):
    pass


def _key() -> str:
    key = os.environ.get("GLADIA_API_KEY")
    if not key:
        raise GladiaError("GLADIA_API_KEY manquante (docs.gladia.io, clé gratuite).")
    return key


def model_name() -> str:
    load_dotenv(Path(__file__).with_name(".env"))
    return os.environ.get("GLADIA_MODEL", DEFAULT_MODEL)


def transcribe(path: str | Path, language: str = "fr") -> str:
    """Transcrit un fichier audio et renvoie le texte brut."""
    load_dotenv(Path(__file__).with_name(".env"))
    headers = {"x-gladia-key": _key()}
    path = Path(path)

    with path.open("rb") as handle:
        upload = _session.post(
            f"{API}/upload",
            headers=headers,
            files={"audio": (path.name, handle, mimetypes.guess_type(path.name)[0] or "audio/wav")},
            timeout=60,
        )
    if upload.status_code >= 300:
        raise GladiaError(f"upload {upload.status_code}: {upload.text[:200]}")
    audio_url = upload.json()["audio_url"]

    job = _session.post(
        f"{API}/pre-recorded",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "audio_url": audio_url,
            "model": model_name(),
            "language_config": {"languages": [language], "code_switching": False},
            "diarization": False,
            "custom_vocabulary": True,
            "custom_vocabulary_config": {"vocabulary": VOCABULARY, "default_intensity": 0.5},
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
        poll = _session.get(result_url, headers=headers, timeout=30)
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


def keep_warm(every: float = 25.0) -> None:
    """Garde la connexion HTTPS vers Gladia ouverte (à lancer dans un thread).

    La première requête paie DNS + TLS (~1,5 s mesurées) et une connexion inactive
    finit par être fermée. Un petit GET régulier évite de payer ça sur la phrase
    dite devant le jury.
    """
    load_dotenv(Path(__file__).with_name(".env"))
    while True:
        try:
            _session.get(f"{API}/pre-recorded", params={"limit": 1}, headers={"x-gladia-key": _key()}, timeout=10)
        except (requests.RequestException, GladiaError):
            pass
        time.sleep(every)


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
        started = time.monotonic()
        text = clean_command(transcribe(args.wav))
        print(f"[{model_name()} · {time.monotonic() - started:.1f} s] {text}")
    except GladiaError as exc:
        print(f"erreur: {exc}", file=sys.stderr)
        sys.exit(1)
