"""Le "SaaS" de démo : une page web qui prend la voix, lance l'agent et suit ses actions.

Zéro dépendance : http.server + le dossier runs/ écrit par runner.py.

    python demo_server.py            -> http://localhost:8765

Endpoints
    GET  /            page de contrôle (demo/app.html)
    GET  /slides      deck de pitch
    GET  /state       état courant de l'agent (JSON)
    GET  /profile     profil utilisateur (JSON)
    GET  /live.png    dernière capture de l'écran
    POST /live/init   ouvre une session Gladia temps réel -> {id, url} (WebSocket)
    POST /transcribe  audio (webm) -> texte via Gladia (secours, mode fichier)
    POST /start       {task, url, interactive, ...} -> lance agent.py --demo
    POST /instruct    {task} ou {quit} -> consigne suivante en mode conversation
    POST /stop        tue le run en cours
    POST /confirm     {approved} -> répond à la demande de confirmation
    POST /answer      {text}     -> répond à ask_user
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
RUNS = ROOT / "runs"
PORT = int(os.environ.get("DEMO_PORT", "8765"))

ALLOWED_ORIGINS = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}

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

    def do_GET(self) -> None:
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
        if origin and origin not in ALLOWED_ORIGINS:
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

        refused = self._refuse_foreign(path, body)
        if refused:
            return _json(self, {"error": refused}, 403)

        if path == "/live/init":
            return self._live_init()
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
        self.send_error(404)

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

    def _live_init(self) -> None:
        """Ouvre une session Gladia temps réel et renvoie l'URL WebSocket au navigateur.

        La clé API reste côté serveur : le navigateur ne reçoit que l'URL de session.
        """
        try:
            from voice import GladiaError, init_live_session

            session = init_live_session()
            _log_gladia("live", 0, f"session {session.get('id', '?')}")
            return _json(self, session)
        except GladiaError as exc:
            _log_gladia("erreur", 0, f"live: {exc}")
            return _json(self, {"error": str(exc)}, 503)
        except Exception as exc:  # noqa: BLE001
            _log_gladia("exception", 0, f"live: {type(exc).__name__}: {exc}")
            return _json(self, {"error": f"{type(exc).__name__}: {exc}"}, 500)

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
            from voice import GladiaError, clean_command, transcribe

            text = clean_command(transcribe(audio))
            _log_gladia("ok", len(body), text[:120] or f"(texte vide — écoute {audio.name})")
            return _json(self, {"text": text})
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
