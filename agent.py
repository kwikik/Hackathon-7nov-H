"""Cerfa Agent — l'administratif français par la voix.

L'agent regarde l'écran, décide de l'action suivante et la joue dans un vrai
navigateur. Les coordonnées viennent de Holo (H Company), l'exécution de Playwright.

Usage
-----
    python agent.py                                   # formulaire local de test
    python agent.py --url https://... --task "..."    # vrai site
    python agent.py --mock --headless                 # répétition hors-ligne, sans clé API
    python agent.py --demo                            # confirmation via le dashboard
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from runner import build_planner, make_file_confirmer, run, set_status, terminal_confirmer

ROOT = Path(__file__).parent
DEFAULT_URL = (ROOT / "demo" / "test_form.html").as_uri()
DEFAULT_TASK = (
    "Remplis ce formulaire de demande administrative avec mes informations "
    "personnelles, vérifie que chaque champ est correct, puis envoie-le."
)


def load_profile(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def conversation(page, profile: dict, args, confirm, model_label: str) -> dict:
    """Mode conversation : le navigateur reste ouvert, l'agent attend les consignes.

    Chaque consigne écrite dans `runs/instruction.json` par l'interface déclenche
    un run sur la MÊME page. Le contexte (URL courante, session, formulaire à moitié
    rempli) est donc conservé d'une consigne à l'autre.
    """
    instruction = ROOT / "runs" / "instruction.json"
    instruction.parent.mkdir(exist_ok=True)
    instruction.unlink(missing_ok=True)

    print(f"\n[conversation] navigateur ouvert sur {page.url}")
    print("[conversation] en attente de consignes…")
    last: dict = {"status": "listening", "final_url": page.url}
    planner = None
    label = model_label

    # Consigne de départ éventuelle (saisie dans l'interface avant le lancement)
    first = (args.task or "").strip()
    if first and first != DEFAULT_TASK:
        instruction.write_text(json.dumps({"task": first}, ensure_ascii=False), encoding="utf-8")

    while True:
        set_status(page, "listening", model=model_label, keep=last)
        payload = None
        while payload is None:
            if instruction.exists():
                try:
                    payload = json.loads(instruction.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    time.sleep(0.2)
                    continue
                instruction.unlink(missing_ok=True)
            else:
                time.sleep(0.3)

        if payload.get("quit"):
            print("[conversation] arrêt demandé")
            return last

        task = (payload.get("task") or "").strip()
        if not task:
            continue

        # Un seul planner pour toute la conversation : le modèle se souvient des
        # consignes précédentes. Après une erreur, on repart d'un historique propre.
        if planner is None:
            planner, label = build_planner(
                task, profile, mock=args.mock, model=args.model, auto_confirm=args.no_confirm
            )
        else:
            planner.new_task(task)
        print(f"\n[conversation] consigne : {task}")
        try:
            last = run(
                page,
                task,
                profile,
                planner=planner,
                model_label=label,
                mock=args.mock,
                confirm=confirm,
                max_steps=args.max_steps,
                pause=args.pause,
                auto_confirm=args.no_confirm,
            )
            last["page_excerpt"] = " ".join(page.inner_text("body").split())[:300]
            last["final_url"] = page.url
        except Exception as exc:  # noqa: BLE001 - une consigne qui casse ne doit pas fermer le navigateur
            print(f"[conversation] erreur : {type(exc).__name__}: {exc}")
            planner = None
            last = {"status": "error", "error": f"{type(exc).__name__}: {exc}", "final_url": page.url}


def main() -> int:
    parser = argparse.ArgumentParser(description="Cerfa Agent")
    parser.add_argument("--url", default=DEFAULT_URL, help="page de départ")
    parser.add_argument("--task", default=DEFAULT_TASK, help="consigne en langage naturel")
    parser.add_argument("--profile", default=str(ROOT / "profile.json"), help="profil utilisateur JSON")
    parser.add_argument("--mock", action="store_true", help="pilote la boucle sans appeler Holo")
    parser.add_argument("--headless", action="store_true", help="navigateur invisible")
    parser.add_argument("--demo", action="store_true", help="confirmation via le dashboard web")
    parser.add_argument("--model", default=None, help="ID de modèle Holo (défaut: HOLO_MODEL du .env, sinon holo4-35b-a3b)")
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--pause", type=float, default=0.0, help="secondes entre deux actions (lisibilité démo)")
    parser.add_argument(
        "--profile-dir",
        default=None,
        help="profil navigateur persistant : garde cookies et sessions entre les runs (ex: runs/browser-profile)",
    )
    parser.add_argument(
        "--wait-login",
        action="store_true",
        help="met en pause pour que tu te connectes à la main dans la fenêtre, avant que l'agent démarre",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="ne jamais demander de confirmation avant une action irréversible (démo)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="mode conversation : le navigateur reste ouvert et l'agent attend les consignes une par une",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    profile = load_profile(Path(args.profile))

    planner, model_label = build_planner(
        args.task, profile, mock=args.mock, model=args.model, auto_confirm=args.no_confirm
    )
    confirm = make_file_confirmer() if args.demo else terminal_confirmer

    print(f"Cerfa Agent · modèle={model_label} · mock={args.mock} · confirmation={'OFF' if args.no_confirm else 'ON'}")
    print(f"tâche : {args.task}\n")

    from playwright.sync_api import sync_playwright

    viewport = {"width": 1280, "height": 800}
    with sync_playwright() as pw:
        if args.profile_dir:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(Path(args.profile_dir).expanduser().resolve()),
                headless=args.headless,
                viewport=viewport,
                locale="fr-FR",
            )
            page = context.pages[0] if context.pages else context.new_page()
            closer = context.close
        else:
            browser = pw.chromium.launch(headless=args.headless)
            page = browser.new_page(viewport=viewport, locale="fr-FR")
            closer = browser.close

        page.goto(args.url)
        page.wait_for_load_state("domcontentloaded")

        if args.wait_login:
            print("\n" + "=" * 60)
            print("CONNEXION MANUELLE : identifie-toi dans la fenêtre du navigateur.")
            print("Quand tu es sur la page où l'agent doit commencer, reviens ici.")
            print("=" * 60)
            input("Entrée pour lancer l'agent... ")

        try:
            if args.interactive:
                result = conversation(page, profile, args, confirm, model_label)
            else:
                result = run(
                    page,
                    args.task,
                    profile,
                    planner=planner,
                    model_label=model_label,
                    mock=args.mock,
                    confirm=confirm,
                    max_steps=args.max_steps,
                    pause=args.pause,
                    auto_confirm=args.no_confirm,
                )
                result["page_excerpt"] = " ".join(page.inner_text("body").split())[:300]
                result["final_url"] = page.url
        finally:
            if not args.headless:
                page.wait_for_timeout(1200)
            closer()

    print("\n--- résultat ---")
    print(json.dumps({k: result.get(k) for k in ("status", "step", "answer", "error", "final_url", "page_excerpt")}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
