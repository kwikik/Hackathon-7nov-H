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

SYSTEM_PROMPT = """You are Cerfa, an autonomous web agent that fills French administrative forms for a user.

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
2. Never click an irreversible control (Envoyer, Valider, Soumettre, Payer, Signer) before calling
   request_confirmation. The harness blocks such clicks.
3. A click on a form field must be immediately followed by a `type` call carrying the value.
4. Dismiss cookie banners or popups before touching the form.
5. Verify what you typed by reading the <page> block, then fill the next empty field.
6. If a page looks blank, if a click changes nothing, or if you took the wrong path: never repeat the
   same action. Use `wait` (2-3 s), then `go_back`, or `navigate` straight to the exact URL of the
   procedure. The <page> block always carries `visible_text`: read it before deciding the page is empty.
7. When the form is filled and the submission is confirmed, call `answer`. `answer` is the only way
   to stop: never stop without it.
"""


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
    """Convention H Company : max 3 captures dans le contexte, sinon la précision s'écroule."""
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
    def __init__(self, client, task: str, profile: dict[str, Any], max_images: int = 3, auto_confirm: bool = False):
        self.client = client
        self.max_images = max_images
        system = SYSTEM_PROMPT.format(
            task=task,
            profile=json.dumps(profile, ensure_ascii=False, indent=2),
        )
        if auto_confirm:
            system += (
                "\n# CONFIRMATION DISABLED\nThe user has turned confirmation off. Do NOT call request_confirmation. "
                "When the form is correctly filled, click the submit control directly and then call answer.\n"
            )
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        self.last_reasoning: str | None = None

    def next_tool_calls(self, controller, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        png_b64, _, _ = controller.screenshot_b64()
        digest = controller.describe()
        observation = {
            "role": "user",
            "content": [
                {"type": "text", "text": "<observation>\n"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
                {"type": "text", "text": f"\n<page>{_digest_text(digest)}</page>\n</observation>"},
            ],
        }
        self.messages.append(observation)
        _trim_images(self.messages, self.max_images)

        message = self.client.chat(self.messages, tools=TOOL_SPECS)

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
        return calls

    def record(self, results: list[tuple[dict[str, Any], str]]) -> None:
        for call, content in results:
            self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})


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
