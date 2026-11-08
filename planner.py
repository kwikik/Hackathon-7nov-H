"""Les yeux et le cerveau : deux planificateurs interchangeables.

- HoloPlanner : vrai agent, function calling sur Holo (Models API H Company).
- MockPlanner : hors-ligne, pilote la même boucle en lisant le DOM. Sert à tester
  le pipeline complet (coordonnées, garde-fou, confirmation) sans clé API.

Les deux exposent la même interface :
    next_tool_calls(controller, ctx) -> list[{"id", "name", "args"}]
    record(results)                  -> alimente l'historique du modèle
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from controller import TOOL_SPECS

SYSTEM_PROMPT = """You are Cerfa, an autonomous web agent that uses a real browser on behalf of a user.
You can do anything a person does on the web: find information and answer questions, research and
compare (prices, products, opening hours, reviews...), read and summarise pages, navigate any site,
and fill in forms (administrative procedures, sign-ups, bookings...). Answer in French.

# TASK
{task}

# USER DATA
The only personal data you are allowed to type:
{profile}

# HOW YOU WORK
After every action the harness sends you a fresh screenshot inside <observation> tags, followed by a
<page> block listing the visible form fields (name, label, current value) and buttons.
Decide the next step and call the tools.

# HARD RULES
1. Never invent personal data. If a required field has no value in USER DATA, call ask_user.
2. Never click an irreversible control (Envoyer, Valider, Soumettre, Payer, Acheter, Commander, Réserver,
   Signer, Publier, Supprimer) before calling request_confirmation. The harness blocks such clicks.
   Never buy, pay, book or publish anything the user did not explicitly ask for.
3. A click on a form field must be immediately followed by a `type` call carrying the value, IN THE SAME
   RESPONSE: return both tool calls together (click then type). When several empty fields are visible on
   the screenshot, fill them all in one response (click, type, click, type...). Each round trip costs
   seconds: batch every action whose target you can already see.
4. Dismiss cookie banners or popups before doing anything else on a page (refuse optional cookies).
5. When filling a form, verify what you typed by reading the <page> block, then fill the next empty field.
6. If a page looks blank, if a click changes nothing, or if you took the wrong path: never repeat the
   same action. Use `wait` (2-3 s), then `go_back`, or `navigate` straight to a better URL.
   The <page> block always carries `visible_text`: read it before deciding the page is empty.
7. If the current page is blank (about:blank) or unrelated to the TASK: if the user named a website, go
   there; if you know the exact URL, `navigate` to it; otherwise call `web_search` first, then `navigate`
   straight to the best result. Never explore menus blindly when one search can give you the page.
   For a French administrative procedure, set `official_only` to true so you land on a real
   government site (service-public.gouv.fr, ants.gouv.fr, impots.gouv.fr, caf.fr, ameli.fr...).
   Each new instruction may target another site.
8. When the TASK is a question or a research request, gather the facts on the pages themselves (the
   search snippets alone are not enough), compare several sources when it matters, then call `answer`
   with a short, concrete reply and the source URLs. Do not fill forms or log in unless asked.
9. When the TASK is done (question answered, page found, form filled and submission confirmed), call
   `answer`. `answer` is the only way to stop: never stop without it.
10. The user may give a follow-up instruction inside <new_instruction> tags. It replaces the TASK above,
   but everything you already did and saw stays valid context (same browser, same page, same session).
"""

NEW_INSTRUCTION = (
    "<new_instruction>\n{task}\n</new_instruction>\n"
    "This is the user's next instruction, on the page you are already on. "
    "Use what you learned from the previous instructions."
)


# Réflexion adaptative : naviguer n'en a pas besoin, remplir un formulaire ou comparer si.
# Consignes qui demandent de raisonner sur ce qu'on a lu (le remplissage, lui, est détecté à l'écran).
COMPLEX_TASK = re.compile(r"compar|r[ée]sum|analys|choisi|meilleur|moins cher|recommand|v[ée]rifie", re.IGNORECASE)
# Seuls les vrais champs de saisie comptent : les cases à cocher servent souvent aux menus (Wikipédia...).
_FILLABLE = {"", "text", "email", "tel", "number", "date", "datetime-local", "password", "url",
             "textarea", "select-one", "select-multiple"}
_SEARCH_HINT = re.compile(r"search|recherch|query|^q$|chercher", re.IGNORECASE)
STRUGGLE_STEPS = 10  # au-delà, l'agent tourne en rond : il a besoin de réfléchir


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _digest_text(digest: dict[str, Any]) -> str:
    fields = [
        {
            "name": f.get("name"),
            "label": f.get("label"),
            "type": f.get("type"),
            "value": f.get("value"),
            "required": f.get("required"),
            **({"options": f["options"]} if f.get("options") else {}),
        }
        for f in digest.get("fields", [])
        if f.get("type") not in ("hidden",)
    ]
    return json.dumps(
        {
            "url": digest.get("url"),
            "title": digest.get("title"),
            "fields": fields,
            "buttons": digest.get("buttons", []),
            "visible_text": digest.get("text", "")[:700],
        },
        ensure_ascii=False,
    )


def _trim_images(messages: list[dict[str, Any]], keep: int = 3) -> None:
    """Garde les `keep` dernières captures (H Company : 3 max, sinon la précision s'écroule ; 2 = plus rapide)."""
    seen = 0
    for message in reversed(messages):
        if message.get("role") != "user" or not isinstance(message.get("content"), list):
            continue
        for chunk in message["content"]:
            if chunk.get("type") != "image_url":
                continue
            seen += 1
            if seen > keep:
                chunk["type"] = "text"
                chunk["text"] = "[screenshot evicted]"
                chunk.pop("image_url", None)


class HoloPlanner:
    def __init__(self, client, task: str, profile: dict[str, Any], max_images: int = 2, auto_confirm: bool = False):
        self.client = client
        self.max_images = max_images
        self._first_task = task
        self._auto_confirm = auto_confirm
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": self._system(profile)}]
        self.last_reasoning: str | None = None
        self.last_thinking: tuple[bool, str] = (True, "")
        self._task = task
        self._task_steps = 0
        self._last_failed = False
        self._pending: list[str] = []  # tool calls émis mais pas encore soldés par `record`

    def _system(self, profile: dict[str, Any]) -> str:
        system = SYSTEM_PROMPT.format(
            task=self._first_task,
            profile=json.dumps(profile, ensure_ascii=False, indent=2),
        )
        if self._auto_confirm:
            system += (
                "\n# CONFIRMATION DISABLED\nThe user has turned confirmation off. Do NOT call request_confirmation. "
                "When the form is correctly filled, click the submit control directly and then call answer.\n"
            )
        return system

    def update_profile(self, profile: dict[str, Any]) -> None:
        """Le profil a gagné une donnée (réponse mémorisée) : le modèle la voit dès la consigne suivante."""
        self.messages[0] = {"role": "system", "content": self._system(profile)}

    def new_task(self, task: str) -> None:
        """Mode conversation : enchaîne une consigne sans effacer l'historique.

        Le modèle garde ce qu'il a fait et vu, donc « et maintenant envoie-le »
        a un sens. Les anciennes captures sont déjà évincées par `_trim_images`.
        """
        # Un run interrompu (refus, erreur, `answer` au milieu d'un lot) peut laisser des
        # tool calls sans réponse : l'API refuse alors tout l'historique. On les solde.
        for call_id in self._pending:
            self.messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps({"ok": False, "skipped": "run terminé avant cette action"}),
            })
        self._pending = []
        self._task, self._task_steps, self._last_failed = task, 0, False
        self.messages.append({"role": "user", "content": NEW_INSTRUCTION.format(task=task)})

    def _needs_thinking(self, digest: dict[str, Any]) -> tuple[bool, str]:
        """Réfléchir coûte plusieurs secondes par pas : seulement quand le pas le mérite."""
        mode = getattr(self.client, "thinking_mode", "on")
        if mode != "auto":
            return mode == "on", f"forcé ({mode})"
        if self._last_failed:
            return True, "l'action précédente a échoué"
        if self._task_steps >= STRUGGLE_STEPS:
            return True, f"{self._task_steps} pas sur cette consigne"
        fillable = [
            f for f in digest.get("fields", [])
            if f.get("type") in _FILLABLE
            and not _SEARCH_HINT.search(f"{f.get('name', '')} {f.get('label', '')}")
        ]
        # Formulaire à remplir : réfléchir tant qu'il reste des champs vides. Une fois rempli,
        # valider et cliquer « Envoyer » n'a pas besoin de réflexion.
        empty = [f for f in fillable if not str(f.get("value") or "").strip()]
        if len(fillable) >= 2 and empty:
            return True, f"formulaire à remplir ({len(empty)}/{len(fillable)} champs vides)"
        if len(fillable) >= 2:
            return False, "formulaire déjà rempli"
        if COMPLEX_TASK.search(self._task or ""):
            return True, "consigne qui demande de comparer ou de synthétiser"
        return False, "navigation"

    def next_tool_calls(self, controller, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        png_b64, _, _ = controller.screenshot_b64()
        digest = controller.describe()
        self.last_thinking = self._needs_thinking(digest)
        self._task_steps += 1
        print(f"   réflexion {'ON' if self.last_thinking[0] else 'OFF'} — {self.last_thinking[1]}")
        observation = {
            "role": "user",
            "content": [
                {"type": "text", "text": "<observation>\n"},
                {"type": "image_url", "image_url": {"url": f"data:{controller.image_mime};base64,{png_b64}"}},
                {"type": "text", "text": f"\n<page>{_digest_text(digest)}</page>\n</observation>"},
            ],
        }
        self.messages.append(observation)
        _trim_images(self.messages, self.max_images)

        message = self.client.chat(self.messages, tools=TOOL_SPECS, thinking=self.last_thinking[0])

        self.last_reasoning = getattr(message, "reasoning", None)

        calls: list[dict[str, Any]] = []
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            serialized = []
            for call in message.tool_calls:
                args_raw = call.function.arguments or "{}"
                try:
                    args = json.loads(args_raw)
                except json.JSONDecodeError:
                    args = {}
                calls.append({"id": call.id, "name": call.function.name, "args": args})
                serialized.append(
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.function.name, "arguments": args_raw},
                    }
                )
            assistant_msg["tool_calls"] = serialized
        # On ne renvoie jamais le raisonnement dans l'historique (doc H Company).
        self.messages.append(assistant_msg)
        self._pending = [c["id"] for c in calls]
        self._last_failed = not calls  # une réponse sans action compte comme un échec
        return calls

    def record(self, results: list[tuple[dict[str, Any], str]]) -> None:
        for call, content in results:
            try:
                if json.loads(content).get("ok") is False:
                    self._last_failed = True
            except (json.JSONDecodeError, AttributeError):
                pass
            self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
            if call["id"] in self._pending:
                self._pending.remove(call["id"])


# --------------------------------------------------------------------------- mock

SYNONYMS: dict[str, list[str]] = {
    "nom": ["nom", "lastname", "last name", "nom de famille", "surname"],
    "prenom": ["prenom", "firstname", "first name", "given name"],
    "email": ["email", "mail", "courriel"],
    "telephone": ["telephone", "tel", "phone", "mobile", "portable"],
    "adresse": ["adresse", "address", "rue", "street"],
    "code_postal": ["code postal", "postal", "zip", "cp"],
    "ville": ["ville", "city", "commune"],
    "pays": ["pays", "country"],
    "date_naissance": ["date de naissance", "naissance", "birth", "birthdate", "dob"],
    "lieu_naissance": ["lieu de naissance", "commune de naissance"],
    "nationalite": ["nationalite", "citoyennete"],
    "numero_secu": ["securite sociale", "secu", "nir", "ssn"],
    "situation": ["situation familiale", "marital"],
    "profession": ["profession", "metier", "emploi", "job"],
    "societe": ["societe", "entreprise", "company", "employeur"],
    "siret": ["siret", "siren"],
    "iban": ["iban"],
}


def match_value(field: dict[str, Any], profile: dict[str, Any]) -> str | None:
    haystack = strip_accents(f"{field.get('label', '')} {field.get('name', '')}").lower()
    for key, value in profile.items():
        if not isinstance(value, str) or not value:
            continue
        candidates = [strip_accents(key).lower().replace("_", " ")] + SYNONYMS.get(key, [])
        for cand in candidates:
            if re.search(rf"(?<![a-z0-9]){re.escape(cand)}(?![a-z0-9])", haystack):
                return value
        # Clés apprises depuis une question (« numero_permis_conduire ») : tous les mots
        # significatifs présents dans le libellé, même séparés par « de ».
        words = [w for w in strip_accents(key).lower().split("_") if len(w) >= 3]
        if len(words) >= 2 and all(re.search(rf"(?<![a-z0-9]){re.escape(w)}", haystack) for w in words):
            return value
    return None


class MockPlanner:
    """Rejoue un remplissage de formulaire en s'appuyant sur le DOM, sans réseau."""

    def __init__(self, profile: dict[str, Any]):
        self.profile = profile
        self.done_fields: set[str] = set()
        self.confirm_requested = False
        self.submit_clicked = False

    def record(self, results: list[tuple[dict[str, Any], str]]) -> None:
        return None

    def update_profile(self, profile: dict[str, Any]) -> None:
        self.profile = profile

    def new_task(self, task: str) -> None:
        # Nouvelle consigne : on rejoue le scénario sur la page courante.
        self.done_fields.clear()
        self.confirm_requested = False
        self.submit_clicked = False

    def next_tool_calls(self, controller, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ctx = ctx or {}
        digest = controller.describe()

        # 1. remplir les champs vides qui matchent le profil
        for field in digest.get("fields", []):
            name = field.get("name") or ""
            if not name or name in self.done_fields:
                continue
            if field.get("value") or field.get("type") in ("hidden", "file", "submit", "button", "checkbox", "radio"):
                continue
            if field.get("tag") == "select":
                continue
            value = match_value(field, self.profile)
            if not value:
                continue
            center = controller.center_of(f"input[name='{name}'], textarea[name='{name}']")
            if not center:
                center = controller.center_of(f"[name='{name}']")
            if not center:
                continue
            self.done_fields.add(name)
            return [
                {"id": f"mock-click-{name}", "name": "click", "args": {"x": center[0], "y": center[1]}},
                {"id": f"mock-type-{name}", "name": "type", "args": {"text": value}},
            ]

        # 2. confirmation obligatoire avant l'envoi
        if not self.confirm_requested:
            self.confirm_requested = True
            return [{
                "id": "mock-confirm",
                "name": "request_confirmation",
                "args": {"summary": "J'ai rempli le formulaire. J'envoie la demande ?"},
            }]

        # 3. clic sur le bouton d'envoi
        if not self.submit_clicked and ctx.get("confirmed"):
            target = None
            for button in digest.get("buttons", []):
                if re.search(r"envoyer|valider|soumettre|submit|send", button.get("text", ""), re.I):
                    target = controller.center_of_button(button["text"])
                    break
            self.submit_clicked = True
            if target:
                return [{"id": "mock-submit", "name": "click", "args": {"x": target[0], "y": target[1]}}]

        # 4. fin
        return [{
            "id": "mock-answer",
            "name": "answer",
            "args": {"summary": "Formulaire rempli et envoyé (scénario hors-ligne)."},
        }]
