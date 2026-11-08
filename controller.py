"""Les mains de l'agent : Playwright + les tools exposés à Holo.

Toutes les coordonnées échangées avec le modèle sont normalisées en [0, 1000]
(convention H Company), origine en haut à gauche. La conversion en pixels CSS
se fait ici, et nulle part ailleurs.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any, Callable

# Un clic sur un de ces libellés est considéré comme irréversible.
SUBMIT_WORDS = re.compile(
    r"\b(envoyer|valider|soumettre|submit|send|confirmer|payer|signer|déposer|deposer"
    r"|acheter|commander|réserver|reserver|buy|checkout|publier|supprimer)\b",
    re.IGNORECASE,
)

# kind = "confirm" -> bool, kind = "question" -> réponse texte
_CONFIRM = Callable[[str, str], "bool | str"]


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


_COORD = {
    "type": "integer",
    "minimum": 0,
    "maximum": 1000,
    "description": "Coordonnée normalisée 0-1000, origine en haut à gauche de la capture.",
}

TOOL_SPECS: list[dict[str, Any]] = [
    _tool(
        "click",
        "Clique sur un élément de la page. (x, y) sont normalisés 0-1000 sur la capture envoyée.",
        {"x": _COORD, "y": _COORD},
        ["x", "y"],
    ),
    _tool(
        "type",
        "Tape du texte au clavier dans l'élément qui a le focus (après un click).",
        {"text": {"type": "string", "description": "Texte exact à saisir."}},
        ["text"],
    ),
    _tool(
        "press_key",
        "Presse une touche du clavier : Enter, Tab, Escape, Backspace...",
        {"key": {"type": "string"}},
        ["key"],
    ),
    _tool(
        "scroll",
        "Fait défiler la page pour révéler des éléments hors écran.",
        {
            "direction": {"type": "string", "enum": ["up", "down"]},
            "amount": {"type": "integer", "minimum": 100, "maximum": 2000},
        },
        ["direction"],
    ),
    _tool(
        "request_confirmation",
        "OBLIGATOIRE avant toute action irréversible (envoyer, valider, payer, signer). "
        "Met la boucle en pause et demande l'accord explicite de l'utilisateur.",
        {"summary": {"type": "string", "description": "Ce que tu t'apprêtes à faire, en français."}},
        ["summary"],
    ),
    _tool(
        "ask_user",
        "Pose une question à l'utilisateur quand une donnée obligatoire manque au profil.",
        {"question": {"type": "string"}},
        ["question"],
    ),
    _tool(
        "go_back",
        "Revient à la page précédente. À utiliser quand une page est vide, en erreur, ou quand tu t'es trompé de chemin.",
        {},
        [],
    ),
    _tool(
        "navigate",
        "Va directement à une URL (http/https uniquement). À utiliser quand tu connais l'adresse exacte de la démarche.",
        {"url": {"type": "string"}},
        ["url"],
    ),
    _tool(
        "web_search",
        "Recherche web : renvoie titres, URL et extraits des meilleures pages. À utiliser AVANT de naviguer "
        "quand tu ne connais pas l'URL exacte, au lieu d'explorer les menus.",
        {
            "query": {"type": "string", "description": "Ce que tu cherches. Ex : « horaires piscine Pontoise », « déclarer la vente de mon véhicule »."},
            "official_only": {
                "type": "boolean",
                "description": "true pour une démarche administrative française : ne renvoie que des sites officiels (service-public, ANTS, impots, CAF, ameli...).",
            },
        },
        ["query"],
    ),
    _tool(
        "wait",
        "Attend que la page finisse de charger (utile sur les sites lents ou les redirections JavaScript).",
        {"seconds": {"type": "number", "minimum": 0.5, "maximum": 8}},
        ["seconds"],
    ),
    _tool(
        "answer",
        "Termine la tâche. C'est le SEUL moyen d'arrêter la boucle.",
        {"summary": {"type": "string", "description": "Compte rendu final, en français."}},
        ["summary"],
    ),
]

TERMINAL_TOOLS = {"answer"}

_DESCRIBE_JS = """
() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const labelOf = (el) => {
    if (el.labels && el.labels.length && el.labels[0].innerText) return el.labels[0].innerText.trim();
    return (el.getAttribute('aria-label') || el.placeholder || el.name || el.id || '').trim();
  };
  const fields = [...document.querySelectorAll('input, textarea, select')]
    .filter(visible)
    .map((el) => ({
      tag: el.tagName.toLowerCase(),
      type: (el.type || '').toLowerCase(),
      name: el.name || el.id || '',
      label: labelOf(el).slice(0, 120),
      value: el.value || '',
      required: !!el.required,
      checked: (el.type === 'checkbox' || el.type === 'radio') ? !!el.checked : undefined,
      options: el.tagName === 'SELECT' ? [...el.options].map((o) => o.text.trim()).slice(0, 25) : undefined,
    }));
  const buttons = [...document.querySelectorAll('button, input[type=submit], a[role=button]')]
    .filter(visible)
    .map((el) => ({
      text: ((el.innerText || el.value || '') + '').trim().slice(0, 80),
      type: (el.type || '').toLowerCase(),
    }))
    .filter((b) => b.text);
  return { url: location.href, title: document.title, fields, buttons,
           text: ((document.body && document.body.innerText) || '').replace(/\\s+/g, ' ').trim().slice(0, 900) };
}
"""

_HIT_JS = """
([x, y]) => {
  const el = document.elementFromPoint(x, y);
  if (!el) return null;
  const btn = el.closest('button, input[type=submit], a[role=button]');
  const field = el.closest('input, textarea, select');
  return {
    button: btn ? ((btn.innerText || btn.value || '') + '').trim().slice(0, 80) : null,
    field: field ? (field.name || field.id || '') : null,
    tag: el.tagName.toLowerCase(),
  };
}
"""

_CENTER_JS = """
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return null;
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}
"""

_CENTER_BUTTON_JS = """
(text) => {
  const norm = (s) => (s || '').toLowerCase().trim();
  const el = [...document.querySelectorAll('button, input[type=submit], a[role=button]')]
    .find((b) => norm(b.innerText || b.value).includes(norm(text)));
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}
"""


class PageController:
    """Exécute les tool calls du modèle sur une page Playwright."""

    # PNG 1x1 transparent : filet de sécurité si la capture échoue (page morte, crash GPU)
    _BLANK_PNG = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )

    def __init__(self, page, is_confirmed: Callable[[], bool] | None = None):
        self.page = page
        self._is_confirmed = is_confirmed or (lambda: False)
        self._last_png: bytes = self._BLANK_PNG
        # Vrai tant qu'une action a pu changer l'écran depuis la dernière capture.
        # Le runner capture après chaque lot d'actions (pour l'interface) ; le planner
        # réutilise cette image au lieu d'en refaire une : une capture par pas, pas deux.
        self._dirty = True

    # ---------- observation ----------

    def screenshot_b64(self, fresh: bool = False) -> tuple[str, int, int]:
        if fresh or self._dirty:
            try:
                self._last_png = self.page.screenshot(type="png")
                self._dirty = False
            except Exception as exc:  # page fermée, crash de rendu : on réutilise la dernière image
                print(f"   [capture] echec ({type(exc).__name__}), on garde la precedente")
        size = self.page.viewport_size or {"width": 1280, "height": 800}
        return base64.b64encode(self._last_png).decode(), size["width"], size["height"]

    def describe(self) -> dict[str, Any]:
        try:
            return self.page.evaluate(_DESCRIBE_JS)
        except Exception as exc:  # page en cours de navigation
            return {"url": self.page.url, "title": "", "fields": [], "buttons": [], "error": str(exc)}

    # ---------- géométrie ----------

    def _to_px(self, x: int, y: int) -> tuple[float, float]:
        size = self.page.viewport_size or {"width": 1280, "height": 800}
        px = max(0.0, min(size["width"] - 1, x / 1000 * size["width"]))
        py = max(0.0, min(size["height"] - 1, y / 1000 * size["height"]))
        return px, py

    def _to_norm(self, point: dict[str, float]) -> tuple[int, int]:
        size = self.page.viewport_size or {"width": 1280, "height": 800}
        return (
            int(round(point["x"] / size["width"] * 1000)),
            int(round(point["y"] / size["height"] * 1000)),
        )

    def center_of(self, selector: str) -> tuple[int, int] | None:
        point = self.page.evaluate(_CENTER_JS, selector)
        return self._to_norm(point) if point else None

    def center_of_button(self, text: str) -> tuple[int, int] | None:
        point = self.page.evaluate(_CENTER_BUTTON_JS, text)
        return self._to_norm(point) if point else None

    # ---------- exécution ----------

    def execute(self, call: dict[str, Any], confirm: _CONFIRM) -> str:
        """Exécute un tool call, retourne le contenu du message `tool` à renvoyer au modèle."""
        name = call["name"]
        args = call.get("args") or {}
        if name not in ("answer", "request_confirmation", "ask_user", "web_search"):
            self._dirty = True

        if name == "web_search":
            # Recherche hors navigateur : la page ne bouge pas, pas de nouvelle capture.
            from search import SearchError, search

            query = str(args.get("query", "")).strip()
            if not query:
                return json.dumps({"ok": False, "error": "query vide"}, ensure_ascii=False)
            try:
                results = search(query, official_only=bool(args.get("official_only")))
            except (SearchError, Exception) as exc:  # noqa: BLE001 - l'agent doit pouvoir naviguer sans
                return json.dumps(
                    {"ok": False, "error": f"recherche indisponible : {exc}. Navigue directement sur le site le plus pertinent."},
                    ensure_ascii=False,
                )
            top = results[0]["url"] if results else "aucun résultat"
            return json.dumps(
                {"ok": True, "message": f"{len(results)} résultat(s) — {top}", "results": results},
                ensure_ascii=False,
            )

        if name == "answer":
            return json.dumps({"ok": True, "finished": True}, ensure_ascii=False)

        if name == "request_confirmation":
            approved = confirm("confirm", args.get("summary", "Action irréversible"))
            return json.dumps(
                {"approved": approved, "note": "L'utilisateur a validé." if approved else "L'utilisateur a refusé."},
                ensure_ascii=False,
            )

        if name == "ask_user":
            answer = confirm("question", args.get("question", "Information manquante ?"))
            return json.dumps({"answer_from_user": answer}, ensure_ascii=False)

        if name == "click":
            px, py = self._to_px(int(args.get("x", 0)), int(args.get("y", 0)))
            hit = self.page.evaluate(_HIT_JS, [px, py]) or {}
            button = hit.get("button") or ""
            if button and SUBMIT_WORDS.search(button) and not self._is_confirmed():
                return json.dumps(
                    {
                        "ok": False,
                        "blocked": "submit_without_confirmation",
                        "message": (
                            f"Action bloquée : « {button} » est une action irréversible. "
                            "Appelle request_confirmation avant de cliquer dessus."
                        ),
                    },
                    ensure_ascii=False,
                )
            self.page.mouse.click(px, py)
            self.page.wait_for_timeout(350)
            return json.dumps({"ok": True, "hit": hit, "url": self.page.url}, ensure_ascii=False)

        if name == "type":
            self.page.keyboard.type(str(args.get("text", "")), delay=15)
            self.page.wait_for_timeout(150)
            return json.dumps({"ok": True, "typed": self.page.evaluate(
                "() => { const e = document.activeElement; return e ? (e.value || e.innerText || '') : ''; }"
            )}, ensure_ascii=False)

        if name == "press_key":
            self.page.keyboard.press(str(args.get("key", "Enter")))
            self.page.wait_for_timeout(300)
            return json.dumps({"ok": True, "url": self.page.url}, ensure_ascii=False)

        if name == "scroll":
            amount = int(args.get("amount", 600))
            self.page.mouse.wheel(0, amount if args.get("direction", "down") == "down" else -amount)
            self.page.wait_for_timeout(300)
            return json.dumps({"ok": True, "url": self.page.url}, ensure_ascii=False)

        if name == "go_back":
            try:
                self.page.go_back(wait_until="domcontentloaded", timeout=15000)
            except Exception as exc:  # noqa: BLE001
                return json.dumps({"ok": False, "error": f"retour impossible: {exc}"}, ensure_ascii=False)
            self.page.wait_for_timeout(600)
            return json.dumps({"ok": True, "url": self.page.url}, ensure_ascii=False)

        if name == "navigate":
            target = str(args.get("url", "")).strip()
            if not target.lower().startswith(("http://", "https://")):
                return json.dumps({"ok": False, "error": "seules les URLs http/https sont autorisées"}, ensure_ascii=False)
            try:
                self.page.goto(target, wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:  # noqa: BLE001
                return json.dumps({"ok": False, "error": f"navigation impossible: {exc}"}, ensure_ascii=False)
            self.page.wait_for_timeout(800)
            return json.dumps({"ok": True, "url": self.page.url}, ensure_ascii=False)

        if name == "wait":
            seconds = max(0.5, min(8.0, float(args.get("seconds", 2))))
            self.page.wait_for_timeout(int(seconds * 1000))
            return json.dumps({"ok": True, "waited": seconds, "url": self.page.url}, ensure_ascii=False)

        return json.dumps({"ok": False, "error": f"tool inconnu: {name}"}, ensure_ascii=False)
