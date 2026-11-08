"""Le "SaaS" de démo : une page web qui prend la voix, lance l'agent et suit ses actions.

Zéro dépendance : http.server + le dossier runs/ écrit par runner.py.

    python demo_server.py            -> http://localhost:8765

Endpoints
    GET  /            page de contrôle (demo/app.html)
    GET  /slides      deck de pitch
    GET  /state       état courant de l'agent (JSON)
    GET  /profile     profil utilisateur (JSON)
    GET  /live.png    dernière capture de l'écran
    POST /transcribe  audio (webm) -> texte via Gladia (Solaria-3, push-to-talk)
    POST /start       {task, url, interactive, ...} -> lance agent.py --demo
    POST /instruct    {task} ou {quit} -> consigne suivante en mode conversation
    POST /stop        tue le run en cours
    POST /confirm     {approved} -> répond à la demande de confirmation
    POST /answer      {text}     -> répond à ask_user
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).parent
RUNS = ROOT / "runs"
load_dotenv(ROOT / ".env")
PORT = int(os.environ.get("DEMO_PORT", "8765"))

ALLOWED_ORIGINS = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", ""}
# Ajoutés par un tunnel ou un proxy (Cloudflare, ngrok) : un client ne peut pas les retirer.
PROXY_HEADERS = ("Cf-Ray", "Cf-Connecting-Ip", "X-Forwarded-For", "X-Forwarded-Host", "Ngrok-Trace-Id")

_lock = threading.Lock()
_process: subprocess.Popen | None = None


def _json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _log_gladia(kind: str, size: int, detail: str) -> None:
    """Trace chaque transcription : sans ça, une erreur Gladia est invisible côté serveur."""
    try:
        RUNS.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%H:%M:%S")
        with (RUNS / "gladia.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} | {kind:<9} | {size:>7} octets | {detail}\n")
    except OSError:
        pass
    print(f"[gladia] {kind} | {size} octets | {detail[:200]}")


class Handler(BaseHTTPRequestHandler):
    server_version = "CerfaDemo/1.0"

    def log_message(self, fmt: str, *args) -> None:  # silence
        return

    # ---------- GET ----------

    # ---------- accès distant (tunnel) ----------

    def _is_remote(self) -> bool:
        """Vrai si la requête arrive par un tunnel, pas depuis le PC de la démo."""
        if any(self.headers.get(h) for h in PROXY_HEADERS):
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        return host not in LOCAL_HOSTS

    def _authorized(self) -> bool:
        """En local : libre. Par le tunnel : mot de passe obligatoire (DEMO_PASSWORD).

        Sans ça, n'importe qui avec le lien lance l'agent et dépense les crédits
        Holo, Gladia et Linkup. Sans mot de passe défini, l'accès distant est fermé.
        """
        if not self._is_remote():
            return True
        password = os.environ.get("DEMO_PASSWORD", "")
        if not password:
            _json(self, {"error": "accès distant fermé : définis DEMO_PASSWORD dans .env"}, 403)
            return False
        given = ""
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                given = base64.b64decode(auth[6:]).decode("utf-8").partition(":")[2]
            except (ValueError, UnicodeDecodeError):
                given = ""
        if given and hmac.compare_digest(given.encode(), password.encode()):
            return True
        # Le navigateur affiche sa boîte de connexion native, puis renvoie le mot de
        # passe tout seul sur chaque requête de la page (fetch inclus).
        body = b"mot de passe requis"
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Cerfa demo", charset="UTF-8"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def do_GET(self) -> None:
        if not self._authorized():
            return
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._file(ROOT / "demo" / "app.html", "text/html; charset=utf-8")
        if path == "/slides":
            return self._file(ROOT / "slides" / "index.html", "text/html; charset=utf-8")
        if path == "/state":
            state = RUNS / "state.json"
            data = {"status": "idle"}
            if state.exists():
                try:
                    data = json.loads(state.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            data["running"] = bool(_process and _process.poll() is None)
            # Auto-réparation : si plus aucun process ne tourne, un état "en attente"
            # est un fantôme (run tué, timeout, serveur redémarré). Sans ça, le bouton
            # reste désactivé et la boîte de dialogue tourne dans le vide.
            if not data["running"] and data.get("status") in ("running", "listening", "awaiting_confirmation", "awaiting_input"):
                data["previous_status"] = data["status"]
                data["status"] = "interrupted"
                data["awaiting"] = None
            return _json(self, data)
        if path == "/profile":
            return self._file(ROOT / "profile.json", "application/json; charset=utf-8")
        if path == "/live.png":
            shot = RUNS / "live.png"
            if not shot.exists():
                self.send_error(404)
                return
            body = shot.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def _file(self, path: Path, ctype: str) -> None:
        if not path.exists():
            self.send_error(404, f"{path.name} absent")
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- POST ----------

    def _refuse_foreign(self, path: str, body: bytes) -> str | None:
        """Bloque les requêtes venues d'une autre page web (CSRF).

        Sans ça, n'importe quelle page ouverte par l'agent pourrait faire
        `fetch("http://localhost:8765/confirm", {mode: "no-cors", ...})` et valider
        l'envoi à ta place. Un navigateur envoie toujours `Origin` sur un POST :
        s'il est absent, c'est un client hors navigateur (curl), pas une page web.
        """
        origin = self.headers.get("Origin")
        # Même origine que la page servie (localhost, ou l'adresse du tunnel) : OK.
        same_host = bool(origin) and urlparse(origin).netloc.lower() == (self.headers.get("Host") or "").lower()
        if origin and origin not in ALLOWED_ORIGINS and not same_host:
            return f"origine refusée : {origin}"
        # /transcribe reçoit de l'audio brut ; tout le reste doit être du JSON.
        # Un POST cross-origin en application/json déclenche un preflight CORS
        # que ce serveur ne valide jamais : double barrière.
        if body and path != "/transcribe":
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return "Content-Type application/json obligatoire"
        return None

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        if not self._authorized():
            return
        refused = self._refuse_foreign(path, body)
        if refused:
            return _json(self, {"error": refused}, 403)

        if path == "/transcribe":
            return self._transcribe(body)
        if path == "/start":
            return self._start(body)
        if path in ("/confirm", "/answer"):
            return self._answer(path, body)
        if path == "/stop":
            with _lock:
                stopped = _stop_agent()
            if stopped:
                return _json(self, {"stopped": True})
            return _json(self, {"stopped": False, "reason": "aucun run en cours"})
        if path == "/instruct":
            return self._instruct(body)
        if path == "/ask":
            return self._ask(body)
        if path == "/profile/remember":
            return self._remember(body)
        self.send_error(404)

    def _ask(self, body: bytes) -> None:
        """Question express : réponse sourcée Linkup, sans lancer l'agent ni de navigateur."""
        try:
            question = str(json.loads(body or b"{}").get("question", "")).strip()
        except json.JSONDecodeError:
            return _json(self, {"error": "json invalide"}, 400)
        if not question:
            return _json(self, {"error": "question vide"}, 400)
        try:
            from search import SearchError, answer

            started = time.monotonic()
            result = answer(question)
            result["seconds"] = round(time.monotonic() - started, 2)
            return _json(self, result)
        except SearchError as exc:
            return _json(self, {"error": str(exc)}, 503)
        except Exception as exc:  # noqa: BLE001
            return _json(self, {"error": f"{type(exc).__name__}: {exc}"}, 500)

    def _remember(self, body: bytes) -> None:
        """Ajoute au profil une réponse donnée à l'agent : il ne la redemandera plus."""
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return _json(self, {"error": "json invalide"}, 400)
        value = str(payload.get("value", "")).strip()
        key = profile_key(str(payload.get("key") or payload.get("question") or ""))
        if not value or not key:
            return _json(self, {"error": "clé ou valeur vide"}, 400)
        path = ROOT / "profile.json"
        with _lock:
            profile = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            profile[key] = value[:200]
            path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return _json(self, {"ok": True, "key": key, "value": profile[key], "profile": profile})

    def _instruct(self, body: bytes) -> None:
        """File d'attente de consignes pour l'agent en mode conversation."""
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return _json(self, {"error": "json invalide"}, 400)
        if not _process or _process.poll() is not None:
            return _json(
                self,
                {"error": "aucun agent en écoute — lance d'abord en mode conversation"},
                409,
            )
        RUNS.mkdir(exist_ok=True)
        (RUNS / "instruction.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return _json(self, {"queued": True, "task": payload.get("task", "")})

    def _transcribe(self, body: bytes) -> None:
        if not body:
            return _json(self, {"error": "audio vide"}, 400)
        suffix = ".webm"
        if body[:4] == b"RIFF":
            suffix = ".wav"
        RUNS.mkdir(exist_ok=True)
        # On garde le dernier audio reçu : si Gladia renvoie du vide, on peut l'écouter.
        audio = RUNS / f"last_audio{suffix}"
        audio.write_bytes(body)
        try:
            from voice import GladiaError, clean_command, model_name, transcribe

            started = time.monotonic()
            text = clean_command(transcribe(audio))
            took = time.monotonic() - started
            _log_gladia("ok", len(body), f"{took:.1f}s | " + (text[:120] or f"(texte vide — écoute {audio.name})"))
            return _json(self, {"text": text, "model": model_name(), "seconds": round(took, 2)})
        except GladiaError as exc:
            _log_gladia("erreur", len(body), str(exc))
            return _json(self, {"error": str(exc)}, 503)
        except Exception as exc:  # noqa: BLE001
            _log_gladia("exception", len(body), f"{type(exc).__name__}: {exc}")
            return _json(self, {"error": f"{type(exc).__name__}: {exc}"}, 500)

    def _start(self, body: bytes) -> None:
        global _process
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return _json(self, {"error": "json invalide"}, 400)

        with _lock:
            if _process and _process.poll() is None:
                return _json(self, {"error": "un run est déjà en cours"}, 409)

            task = (payload.get("task") or "").strip()
            if not payload.get("interactive") and not task:
                task = "Remplis ce formulaire de demande administrative avec mes informations."
            url = (payload.get("url") or "").strip() or (ROOT / "demo" / "test_form.html").as_uri()
            RUNS.mkdir(exist_ok=True)
            (RUNS / "answer.json").unlink(missing_ok=True)
            (RUNS / "state.json").unlink(missing_ok=True)

            cmd = [
                sys.executable,
                "-u",  # sortie non bufferisée : agent.log se remplit en direct
                str(ROOT / "agent.py"),
                "--demo",
                "--url",
                url,
                "--task",
                task,
                "--pause",
                str(payload.get("pause", 0.35)),
            ]
            if payload.get("mock"):
                cmd.append("--mock")
            if payload.get("headless"):
                cmd.append("--headless")
            # Garde-fou actif par défaut : il faut le demander explicitement pour le couper.
            if payload.get("no_confirm"):
                cmd.append("--no-confirm")
            if payload.get("model"):
                cmd.extend(["--model", str(payload["model"])])
            if payload.get("interactive"):
                cmd.append("--interactive")
            # Mode « site à côté » : position et taille de la fenêtre Chromium [x, y, largeur, hauteur].
            window = payload.get("window")
            if isinstance(window, list) and len(window) == 4:
                try:
                    cmd.extend(["--window", ",".join(str(int(v)) for v in window)])
                except (TypeError, ValueError):
                    return _json(self, {"error": "window invalide"}, 400)

            log = (RUNS / "agent.log").open("w", encoding="utf-8")
            _process = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
            return _json(self, {"started": True, "pid": _process.pid, "task": task, "url": url})

    def _answer(self, path: str, body: bytes) -> None:
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return _json(self, {"error": "json invalide"}, 400)
        RUNS.mkdir(exist_ok=True)
        # runner.py attend runs/answer.json
        (RUNS / "answer.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return _json(self, {"ok": True})


_STOP_WORDS = {
    "quel", "quelle", "quels", "quelles", "est", "sont", "votre", "vos", "ton", "ta", "tes", "mon", "ma",
    "le", "la", "les", "l", "de", "du", "des", "d", "un", "une", "pouvez", "vous", "peux", "tu", "me",
    "donner", "indiquer", "preciser", "communiquer", "merci", "s", "il", "plait", "qu", "que", "quoi",
    "c", "ce", "cette", "a", "au", "aux", "pour", "sur", "en", "et", "ou", "avez", "as", "actuel",
    "actuelle", "exact", "exacte", "svp",
}


def profile_key(text: str) -> str:
    """« Quel est votre numéro de permis de conduire ? » -> « numero_permis_conduire »."""
    import re
    import unicodedata

    plain = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").lower()
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", plain).split() if w not in _STOP_WORDS]
    return "_".join(words[:4])


def _stop_agent() -> bool:
    """Arrête l'agent ET son navigateur. Appeler sous `_lock`.

    `Popen.kill()` ne tue que le process Python : sous Windows, Playwright et les
    fenêtres Chromium peuvent lui survivre. On tue donc tout l'arbre.
    """
    global _process
    proc, _process = _process, None
    if not proc or proc.poll() is not None:
        return False
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    return True


def main() -> None:
    RUNS.mkdir(exist_ok=True)
    # Sous Windows, SO_REUSEADDR laisse DEUX serveurs écouter le même port : les
    # requêtes tombent au hasard sur l'un ou l'autre (vieux code, état différent).
    # On préfère une erreur claire au démarrage.
    if os.name == "nt":
        ThreadingHTTPServer.allow_reuse_address = False
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        print(f"Port {PORT} déjà utilisé : un autre serveur de démo tourne sans doute. ({exc})")
        sys.exit(1)
    print(f"Cerfa demo -> http://localhost:{PORT}")
    # Connexion à Gladia préchauffée : la première phrase ne paie pas DNS + TLS.
    from voice import keep_warm

    threading.Thread(target=keep_warm, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\narrêt")
    finally:
        # Ctrl+C sur le serveur ne doit pas laisser un navigateur orphelin.
        with _lock:
            _stop_agent()


if __name__ == "__main__":
    main()
