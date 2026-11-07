# Correctifs — suivi

> Issu de l'audit du 7 nov 2026. Coche au fur et à mesure.
> Légende : ✅ fait · ⏸️ volontairement reporté · ⬜ à faire

[← Index de la documentation](README.md)

## Sommaire

1. [Sécurité du garde-fou](#1-sécurité-du-garde-fou)
2. [Holo](#2-holo)
3. [Gladia](#3-gladia)
4. [Bugs et fragilités](#4-bugs-et-fragilités)
5. [Hygiène du repo](#5-hygiène-du-repo)

---

## 1. Sécurité du garde-fou

| # | Correctif | État | Où |
|---|---|---|---|
| S1 | La touche **Entrée** envoie un formulaire sans confirmation (`press_key` n'est pas bloqué) | ⏸️ reporté | `controller.py` — `press_key` |
| S2 | Une validation reste valable pour tout le run : un 2ᵉ « Payer » passe sans question. Rendre la validation à usage unique | ⬜ | `runner.py` — `confirmed["value"]` |
| S3 | **CSRF** : n'importe quelle page pouvait appeler `/confirm`, `/instruct`, `/start`. Refus si `Origin` ≠ `localhost:8765` / `127.0.0.1:8765`, et `Content-Type: application/json` obligatoire (sauf `/transcribe`, audio brut) | ✅ | `demo_server.py` — `_refuse_foreign` |
| S4 | Le garde-fou ne voit pas les boutons dans une **iframe**, les `<a>Payer</a>`, les `input type=button`, les boutons icône | ⬜ | `controller.py` — `_HIT_JS` |
| S5 | `navigate` accepte toutes les URL : risque de fuite du profil via la query string. Liste blanche de domaines | ⬜ | `controller.py` — `navigate` |
| S6 | Le texte de la page (`visible_text`) n'est pas signalé au modèle comme non fiable (injection) | ⬜ | `planner.py` — `SYSTEM_PROMPT` |
| S7 | Confirmation vocale : toute phrase avec « ok » ou « oui » valide | ⬜ | `demo/app.html` — `isYes` |

Test S3 (vérifié) : origine étrangère → `403`, `text/plain` → `403`, même origine en JSON → `200`.

## 2. Holo

| # | Amélioration | État | Où |
|---|---|---|---|
| H1 | Température 0.8 → **0.3** par défaut, réglable via `HOLO_TEMPERATURE` | ✅ | `holo_client.py` |
| H2 | Raisonnement (`enable_thinking`) réglable via `HOLO_THINKING=0/1` (défaut 1). À mesurer : `0` = pas plus rapides | ✅ | `holo_client.py` |
| H3 | Prompt : `click` + `type` dans la **même réponse**, et tous les champs visibles en un lot | ✅ | `planner.py` — règle 3 |
| H4 | Mode conversation : **un seul planner** pour toute la conversation, chaque consigne arrive en `<new_instruction>` — le modèle se souvient de ce qu'il a fait | ✅ | `agent.py` — `conversation`, `planner.py` — `new_task` |
| H5 | Tool calls laissés sans réponse (refus, `answer` au milieu d'un lot) soldés avant la consigne suivante, sinon l'API rejette l'historique | ✅ | `planner.py` — `_pending` |
| H6 | **Une capture par pas** au lieu de deux : le planner réutilise celle prise par le runner si rien n'a bougé | ✅ | `controller.py` — `_dirty` |
| H7 | Mesurer en vrai l'effet de H1–H3 sur ANTS (nombre de pas, durée) | ⬜ | — |

## 3. Gladia

| # | Amélioration | État | Où |
|---|---|---|---|
| G1 | **STT temps réel** : WebSocket Gladia (`POST /v2/live`, modèle `solaria-1`, PCM 16 kHz). Le texte s'écrit pendant qu'on parle | ✅ | `voice.py` — `init_live_session`, `demo_server.py` — `/live/init`, `demo/app.html` — `startLive` |
| G2 | Fin de phrase détectée par Gladia (`endpointing`, défaut 0.6 s, réglable `GLADIA_ENDPOINTING`) au lieu de notre VAD à 850 ms + upload + polling | ✅ | `voice.py` |
| G3 | **Vocabulaire personnalisé** : ANTS, Cerfa, FranceConnect, CAF, URSSAF, carte grise… | ✅ | `voice.py` — `VOCABULARY` |
| G4 | Repli automatique en mode fichier si le temps réel échoue, sans perdre la phrase en cours. Case « Gladia temps réel » dans l'interface | ✅ | `demo/app.html` |
| G5 | Latence affichée sous le micro | ✅ | `demo/app.html` — `#latency` |
| G6 | Garder une seule session ouverte toute la démo (jusqu'à 3 h) au lieu d'une par phrase | ⬜ | `demo/app.html` |
| G7 | Tester au vrai micro, en salle bruyante ; ajuster `GLADIA_ENDPOINTING` (0.4–0.8) | ⬜ | — |

Test G1 (vérifié) : Chromium avec micro simulé sur `runs/voix_test.wav` → 4 transcriptions partielles affichées,
consigne finale remplie, 0 erreur JS. La latence affichée pendant ce test n'est pas représentative
(le fichier simulé tourne en boucle, il n'y a jamais de vrai silence).

## 4. Bugs et fragilités

| # | Correctif | État | Où |
|---|---|---|---|
| B1 | `type` ajoute au texte existant au lieu de le remplacer (ctrl+A avant de taper) | ⬜ | `controller.py` — `type` |
| B2 | Aucune détection de boucle (même action 3 fois) | ⬜ | `runner.py` |
| B3 | Après un clic, 350 ms d'attente sans attendre le chargement de la page | ⬜ | `controller.py` — `click` |
| B4 | Mock sans terminal : `EOFError` à la confirmation → traiter comme un refus | ⬜ | `runner.py` — `terminal_confirmer` |
| B5 | `discard` pouvait rester levé et avaler la consigne suivante | ✅ | `demo/app.html` — `reply`, `leaveAnswerMode` |
| B6 | Le micro se rouvrait pendant la transcription / juste après l'envoi d'une consigne en mode conversation | ✅ | `demo/app.html` — `render` |
| B7 | `agent.log` ouvert à chaque run et jamais fermé | ⬜ | `demo_server.py` — `_start` |
| B8 | `start_demo.bat` n'ouvre pas le navigateur malgré son commentaire | ⬜ | `start_demo.bat` |

## 5. Hygiène du repo

| # | Correctif | État |
|---|---|---|
| R1 | Doc rangée dans `docs/`, README avec sommaire, `.env.example` | ✅ |
| R2 | `AVANCEMENT.md` et `DEMO.md` périmés (modèle par défaut, lancement en ligne de commande) | ⬜ |
| R3 | Tests pytest : garde-fou, `match_value`, run mock complet | ⬜ |
| R4 | Versions figées dans `requirements.txt` | ⬜ |
| R5 | `profile.json` commité — données factices, conservé volontairement pour la démo | ⏸️ |
