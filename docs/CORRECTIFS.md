# Correctifs — suivi

> Issu de l'audit du 7 nov 2026. Coche au fur et à mesure.
> Légende : ✅ fait · ⏸️ volontairement reporté · ⬜ à faire

[← Index de la documentation](README.md)

## Sommaire

1. [Sécurité du garde-fou](#1-sécurité-du-garde-fou)
2. [Holo](#2-holo)
3. [Gladia](#3-gladia) · [Linkup](#3-bis-linkup-recherche-web)
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
| G1 | ~~STT temps réel (WebSocket, Solaria-1)~~ : retiré. Coupait les phrases à la première pause (endpointing) et transcrivait moins bien que Solaria-3 | ❌ abandonné | — |
| G2 | **Push-to-talk** : on maintient Espace (ou le bouton micro) pour parler, on relâche pour envoyer. Plus de coupure automatique au silence | ✅ | `demo/app.html` — `pressTalk`, `releaseTalk` |
| G3 | **Vocabulaire personnalisé** : ANTS, Cerfa, FranceConnect, CAF, URSSAF, carte grise… | ✅ | `voice.py` — `VOCABULARY` |
| G4 | Modèle **Solaria-3** (le plus précis de Gladia en français, pre-recorded uniquement), réglable `GLADIA_MODEL` | ✅ | `voice.py` |
| G5 | Temps de transcription affiché sous le micro | ✅ | `demo/app.html` — `#latency` |
| G6 | **Connexion préchauffée** : session HTTPS réutilisée + ping toutes les 25 s. La 1ʳᵉ requête coûtait ~1,6 s de DNS + TLS | ✅ | `voice.py` — `_session`, `keep_warm` |
| G7 | Micro ouvert une seule fois et gardé (pas de syllabe mangée à chaque appui) ; `noiseSuppression` coupée (abîme la voix) | ✅ | `demo/app.html` — `ensureMic` |
| G8 | Tester au vrai micro, en salle bruyante | ⬜ | — |

Mesures (réseau du 7 nov) : connexion froide 7,9 s entre le relâchement et le texte ; connexion
chaude **2,8 s**. Détail : envoi du fichier 0,4 s, Solaria-3 ~2,3 s (Solaria-1 ~1,8 s, mais
moins précis : « en voilà » au lieu de « envoie-la » sur le même enregistrement).
Test (vérifié) : Chromium avec micro simulé, appui court ignoré, maintien 4 s puis relâche →
consigne remplie, 0 erreur JS.

## 3 bis. Linkup (recherche web)

| # | Amélioration | État | Où |
|---|---|---|---|
| L1 | Outil **`web_search`** pour Holo : trouve la page exacte d'une démarche avant de naviguer | ✅ | `search.py`, `controller.py` |
| L2 | Recherche limitée aux **sites officiels** (`includeDomains` : service-public, ANTS, impots, CAF, ameli, URSSAF, France Travail…). Legifrance retiré (textes de loi, pas des démarches) | ✅ | `search.py` — `OFFICIAL_DOMAINS` |
| L3 | Prompt : chercher plutôt qu'explorer les menus ; si la recherche échoue, l'agent navigue lui-même | ✅ | `planner.py` — règle 7 |
| L4 | Mode hors-ligne : `web_search` n'est pas simulé (le mock remplit le formulaire local sans chercher) | ⏸️ | — |
| L5 | Limiter aussi `navigate` aux domaines officiels (couvrirait S5) | ⬜ | `controller.py` |

Mesures (vérifié) : `depth: "fast"`, 1,2 à 1,7 s par recherche. Run réel Holo « trouve la page
officielle pour déclarer la vente de mon véhicule » : `web_search` → `navigate` vers la fiche
F1707 de service-public → `answer`, **3 pas** (9 pas sans recherche, mesure ANTS du 7 nov).

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
| B8 | `start_demo.bat` n'ouvre pas le navigateur malgré son commentaire. Réécrit : attend le serveur puis ouvre la page ; nouveau `stop_demo.bat` pour tout fermer | ✅ | `start_demo.bat`, `stop_demo.bat` |
| B9 | Deux serveurs pouvaient partager le port 8765 sous Windows (requêtes réparties au hasard) | ✅ | `demo_server.py` — `main` |

## 5. Hygiène du repo

| # | Correctif | État |
|---|---|---|
| R1 | Doc rangée dans `docs/`, README avec sommaire, `.env.example` | ✅ |
| R2 | `AVANCEMENT.md` et `DEMO.md` périmés (modèle par défaut, lancement en ligne de commande) | ⬜ |
| R3 | Tests pytest : garde-fou, `match_value`, run mock complet | ⬜ |
| R4 | Versions figées dans `requirements.txt` | ⬜ |
| R5 | `profile.json` commité — données factices, conservé volontairement pour la démo | ⏸️ |
