"""La boucle : observe -> decide -> agit -> recommence, avec journal d'état pour la démo."""
from __future__ import annotations

import base64
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from controller import TERMINAL_TOOLS, PageController
from planner import HoloPlanner, MockPlanner

RUNS_DIR = Path(__file__).with_name("runs")

Confirmer = Callable[[str, str], "bool | str"]


@dataclass
class Step:
    n: int
    tool: str
    args: dict[str, Any]
    ok: bool
    detail: str
    seconds: float


@dataclass
class RunState:
    status: str = "running"  # running | awaiting_confirmation | awaiting_input | done | aborted | error
    step: int = 0
    task: str = ""
    url: str = ""
    model: str = ""
    mock: bool = False
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    thoughts: list[str] = field(default_factory=list)
    answer: str | None = None
    awaiting: str | None = None
    error: str | None = None
    screenshot: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _write_state(state: RunState) -> None:
    """Écrit l'état de façon résiliente.

    Windows interdit de remplacer un fichier qu'un autre process lit (le dashboard
    poll toutes les 600 ms) : on retente, puis on écrit en place en dernier recours.
    Sans ça, l'agent meurt en plein run pendant la démo.
    """
    RUNS_DIR.mkdir(exist_ok=True)
    payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2)
    target = RUNS_DIR / "state.json"
    tmp = RUNS_DIR / "state.json.tmp"
    tmp.write_text(payload, encoding="utf-8")

    for attempt in range(6):
        try:
            tmp.replace(target)
            return
        except PermissionError:
            time.sleep(0.04 * (attempt + 1))
        except OSError:
            time.sleep(0.04 * (attempt + 1))

    try:
        target.write_text(payload, encoding="utf-8")
    except OSError:
        pass  # dernier recours : on ne tue jamais le run pour un fichier d'état
    finally:
        tmp.unlink(missing_ok=True)


def set_status(
    page,
    status: str,
    model: str = "",
    mock: bool = False,
    message: str | None = None,
    keep: dict | None = None,
) -> None:
    """Publie un état sans lancer de run (ex: 'listening' entre deux consignes).

    `keep` permet de conserver le journal et la dernière réponse : sans ça, chaque
    nouvelle consigne efface le log affiché dans l'interface.
    """
    st = RunState(status=status, url=page.url, model=model, mock=mock)
    if keep:
        st.steps = keep.get("steps", []) or []
        st.thoughts = keep.get("thoughts", []) or []
        st.answer = keep.get("answer")
        st.task = keep.get("task", "") or ""
        st.screenshot = keep.get("screenshot")
    st.awaiting = message
    _write_state(st)


def run(
    page,
    task: str,
    profile: dict[str, Any],
    *,
    planner: Any,
    model_label: str = "",
    mock: bool = False,
    confirm: Confirmer,
    max_steps: int = 30,
    pause: float = 0.0,
    auto_confirm: bool = False,
) -> dict[str, Any]:
    """Exécute la boucle jusqu'à `answer`, confirmation refusée, ou limite de pas."""
    state = RunState(task=task, url=page.url, model=model_label, mock=mock)
    confirmed = {"value": auto_confirm}

    if auto_confirm:
        def asker(kind: str, text: str) -> bool | str:
            # Confirmation désactivée : on approuve sans pause. Les questions restent interactives.
            return True if kind == "confirm" else confirm(kind, text)
    else:
        asker = confirm

    controller = PageController(page, is_confirmed=lambda: confirmed["value"])
    _write_state(state)

    def record(n: int, tool: str, args: dict[str, Any], ok: bool, detail: str, seconds: float) -> None:
        state.steps.append(asdict(Step(n=n, tool=tool, args=args, ok=ok, detail=detail, seconds=round(seconds, 2))))
        state.step = n
        _write_state(state)
        arg_preview = json.dumps(args, ensure_ascii=False)
        if len(arg_preview) > 90:
            arg_preview = arg_preview[:87] + "..."
        print(f"[{n:02d}] {tool:<21} {arg_preview}  {'OK' if ok else 'KO'}  {detail[:70]}")

    try:
        for n in range(1, max_steps + 1):
            started = time.monotonic()
            calls = planner.next_tool_calls(controller, {"confirmed": confirmed["value"], "step": n})

            reasoning = getattr(planner, "last_reasoning", None)
            if reasoning:
                state.thoughts.append(str(reasoning)[:800])
                print(f"   pense : {str(reasoning)[:160]}")

            if not calls:
                record(n, "(aucun tool call)", {}, False, "le modèle a répondu sans action, on relance", time.monotonic() - started)
                continue

            results: list[tuple[dict[str, Any], str]] = []
            for call in calls:
                if call["name"] == "request_confirmation":
                    state.status = "awaiting_confirmation"
                    state.awaiting = call["args"].get("summary", "")
                    _write_state(state)
                elif call["name"] == "ask_user":
                    state.status = "awaiting_input"
                    state.awaiting = call["args"].get("question", "")
                    _write_state(state)

                result = controller.execute(call, asker)
                results.append((call, result))
                payload = json.loads(result) if result.startswith("{") else {"raw": result}

                # IMPORTANT : remettre l'état à jour AVANT d'écrire le journal.
                # Sinon le dashboard relit "awaiting_confirmation" et rouvre la boîte
                # en boucle alors que l'utilisateur a déjà répondu.
                if call["name"] == "request_confirmation":
                    confirmed["value"] = bool(payload.get("approved"))
                    state.awaiting = None
                    if not confirmed["value"]:
                        state.status = "aborted"
                        state.answer = "Action refusée par l'utilisateur."
                        state.finished_at = datetime.now(timezone.utc).isoformat()
                        _write_state(state)
                        return state.to_dict()
                    state.status = "running"
                elif call["name"] == "ask_user":
                    state.awaiting = None
                    state.status = "running"
                elif call["name"] in TERMINAL_TOOLS:
                    state.status = "done"
                    state.answer = call["args"].get("summary", "")
                    state.finished_at = datetime.now(timezone.utc).isoformat()

                detail = payload.get("message") or payload.get("blocked") or payload.get("typed") or payload.get("url") or ""
                record(n, call["name"], call["args"], bool(payload.get("ok", True)), str(detail), time.monotonic() - started)

                if call["name"] in TERMINAL_TOOLS:
                    _write_state(state)
                    planner.record(results)
                    return state.to_dict()

                if pause:
                    time.sleep(pause)

            planner.record(results)

            shot_b64, _, _ = controller.screenshot_b64()
            shot_path = RUNS_DIR / "live.png"
            shot_path.write_bytes(base64.b64decode(shot_b64))
            state.screenshot = str(shot_path)
            _write_state(state)

        state.status = "error"
        state.error = f"limite de {max_steps} pas atteinte sans `answer`"
        state.finished_at = datetime.now(timezone.utc).isoformat()
        _write_state(state)
        return state.to_dict()

    except Exception as exc:  # noqa: BLE001 - on veut l'état dans le dashboard
        state.status = "error"
        state.error = f"{type(exc).__name__}: {exc}"
        state.finished_at = datetime.now(timezone.utc).isoformat()
        _write_state(state)
        raise


# --------------------------------------------------------------------------- confirmeurs

def terminal_confirmer(kind: str, text: str) -> bool | str:
    if kind == "question":
        return input(f"\n[QUESTION] {text}\n> ").strip()
    answer = input(f"\n[CONFIRMATION] {text}\nEnvoyer ? [o/N] ").strip().lower()
    return answer in ("o", "oui", "y", "yes")


def make_file_confirmer(runs_dir: Path = RUNS_DIR, timeout: float = 180.0) -> Confirmer:
    """Mode démo : le dashboard écrit runs/answer.json, on attend qu'il apparaisse."""
    runs_dir.mkdir(exist_ok=True)
    answer_file = runs_dir / "answer.json"
    answer_file.unlink(missing_ok=True)

    def confirmer(kind: str, text: str) -> bool | str:
        answer_file.unlink(missing_ok=True)
        print(f"\n[EN ATTENTE UI] {text}")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if answer_file.exists():
                try:
                    payload = json.loads(answer_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    time.sleep(0.2)
                    continue
                answer_file.unlink(missing_ok=True)
                return bool(payload.get("approved", False)) if kind == "confirm" else str(payload.get("text", ""))
            time.sleep(0.15)
        print("[TIMEOUT] pas de réponse de l'interface")
        # Une question sans réponse ne doit pas bloquer la boucle : on renvoie du vide.
        return False if kind == "confirm" else ""

    return confirmer


def build_planner(task: str, profile: dict[str, Any], *, mock: bool, model: str | None = None, auto_confirm: bool = False):
    if mock:
        return MockPlanner(profile), "mock (hors-ligne)"
    from holo_client import HoloClient

    client = HoloClient(model=model)
    return HoloPlanner(client, task, profile, auto_confirm=auto_confirm), client.model
