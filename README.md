# Cerfa Agent

**L'administratif français, par la voix.**

Tu dis ce que tu veux. L'agent ouvre le site, regarde l'écran, remplit le formulaire,
te montre ce qu'il a écrit — et attend ton feu vert avant d'envoyer.

Projet du hackathon **H Company × 42AI — Computer Use Agents**, 7–8 novembre 2026.

```
Voix  ──▶ Gladia (STT)  ──▶ consigne
                                │
                                ▼
                     Holo (H Company)  ──▶  "click(x, y)"
                     voit la capture,          sur l'écran
                     décide l'action                │
                                ▲                  ▼
                                └────  Playwright exécute
                                       nouvelle capture
```

## Sommaire

1. [Ce qui rend ce projet différent](#ce-qui-rend-ce-projet-différent)
2. [Démarrage](#démarrage) — installation, `.env`, options de `agent.py`
3. [Interface de démo](#interface-de-démo) — voix, capture live, journal, confirmation
4. [Modèles Holo](#modèles-holo-nov-2026)
5. [Structure du dépôt](#structure)
6. [Limites assumées](#limites-assumées)
7. [Documentation détaillée](#documentation-détaillée) — démo, avancement, roadmap
8. [Vidéo et pitch](#vidéo-et-pitch)

---

## Ce qui rend ce projet différent

- **Aucun script par site.** Le moteur ne parse pas le DOM pour deviner les champs : il *regarde*
  l'écran et localise l'élément à cliquer. Le même code marche sur n'importe quel formulaire.
- **Coordonnées normalisées `[0, 1000]`.** Convention Holo respectée de bout en bout, conversion en
  pixels CSS dans un seul module (`controller.py`).
- **Garde-fou d'envoi.** Un clic sur « Envoyer » / « Valider » / « Payer » est **bloqué par le
  harnais** tant qu'une confirmation humaine n'a pas été donnée. Ce n'est pas une consigne au modèle :
  c'est une barrière dans le code.
- **Zéro invention de données.** Les valeurs saisies viennent d'un profil local (`profile.json`).
  Si une donnée obligatoire manque, l'agent appelle `ask_user` au lieu de remplir au hasard.
- **Mode hors-ligne.** `--mock` rejoue le scénario complet sans clé API, pour répéter avant la scène.

## Démarrage

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # puis renseigne tes clés
```

Crée un fichier `.env` à la racine (il n'est jamais commité) :

```ini
# H Company — Models API (portal.hcompany.ai)
HAI_API_KEY=...
HAI_BASE_URL=https://api.hcompany.ai/v1/
HOLO_MODEL=holo4-35b-a3b
# espacement des appels en secondes : 0 avec des crédits, 6.05 sur le free tier
HOLO_MIN_INTERVAL=0
# 0.3 par défaut : un agent qui clique doit être constant
HOLO_TEMPERATURE=0.3
# 1 = raisonnement à chaque pas (plus fiable), 0 = plus rapide
HOLO_THINKING=1

# Gladia — speech-to-text (docs.gladia.io)
GLADIA_API_KEY=...
# silence (s) qui termine une phrase en mode temps réel
GLADIA_ENDPOINTING=0.6

# serveur de démo
DEMO_PORT=8765
```

```bash
python agent.py                          # formulaire local de test
python agent.py --mock --headless        # répétition hors-ligne, sans clé
python agent.py --url https://... --task "Remplis ma demande d'aide au permis et envoie-la"
python agent.py --interactive --demo     # mode conversation, piloté depuis l'interface
```

### Options de `agent.py`

| Option | Défaut | Effet |
|---|---|---|
| `--url URL` | `demo/test_form.html` | Page sur laquelle le navigateur s'ouvre au départ. |
| `--task "..."` | « Remplis ce formulaire… puis envoie-le » | Consigne en langage naturel. En mode `--interactive`, seulement la première consigne. |
| `--profile FICHIER` | `profile.json` | Données personnelles que l'agent a le droit de taper. |
| `--model ID` | `HOLO_MODEL` du `.env`, sinon `holo4-35b-a3b` | Modèle Holo utilisé. |
| `--mock` | non | Hors-ligne : n'appelle pas Holo, remplit en lisant la page. Pour répéter sans clé ni réseau. |
| `--headless` | non | Navigateur invisible. |
| `--demo` | non | Confirmations et questions passent par l'interface web au lieu du terminal. |
| `--interactive` | non | Mode conversation : le navigateur reste ouvert, les consignes arrivent une par une sur la même page. |
| `--no-confirm` | non | Supprime la confirmation avant envoi : l'agent clique sur « Envoyer » sans demander. À éviter. |
| `--max-steps N` | `30` | Nombre maximum d'actions avant abandon. |
| `--pause SECONDES` | `0` | Pause entre deux actions, pour une démo lisible (l'interface envoie `0.35`). |
| `--profile-dir DOSSIER` | aucun | Profil navigateur persistant : cookies et sessions gardés entre deux runs (ex. `runs/browser-profile`). |
| `--wait-login` | non | Pause au démarrage pour te connecter à la main, puis Entrée dans le terminal. Ne marche pas depuis l'interface web. |

Vrai site, en gardant la session et en se connectant à la main la première fois :

```bash
python agent.py --url "https://ants.gouv.fr/" --profile-dir runs/browser-profile --wait-login --task "Trouve la page pour déclarer la vente de mon véhicule"
```

Ce que lance l'interface au démarrage (mode conversation) :

```bash
python agent.py --demo --interactive --pause 0.35 --model holo4-35b-a3b
```

## Interface de démo

```bash
python demo_server.py      # -> http://localhost:8765  (ou start_demo.bat)
```

La page (`demo/app.html`) écoute la voix (micro du navigateur → Gladia), lance l'agent et affiche en direct :

- la transcription de la consigne,
- la capture de l'écran de l'agent (rafraîchie à chaque pas),
- le journal des actions (tool, arguments, résultat, durée),
- la question de l'agent quand une donnée manque, et la demande de confirmation avant envoi,
  auxquelles on peut répondre à la voix (« oui », « vas-y ») ou par les boutons.

**Mode conversation** (case cochée par défaut) : le navigateur reste ouvert entre deux consignes.
Chaque nouvelle phrase est envoyée à `/instruct` et l'agent la joue sur la même page, avec la
session et le formulaire en cours. Sans cette case, chaque consigne relance un navigateur neuf.

La confirmation avant envoi est **active par défaut**. La case « ne jamais demander de
confirmation » la coupe pour un run.

**Transcription temps réel** (case cochée par défaut) : le micro part en continu sur un WebSocket
Gladia, le texte s'écrit pendant que tu parles et Gladia coupe tout seul à la fin de la phrase
(`GLADIA_ENDPOINTING`). Un vocabulaire personnalisé (ANTS, Cerfa, FranceConnect…) est envoyé à
l'ouverture. Si la session échoue, l'interface repasse en mode fichier sans perdre la phrase.

Le serveur refuse toute requête POST venue d'une autre origine que `localhost:8765`, et exige du JSON.

Endpoints : `GET /state`, `GET /live.png`, `GET /profile`, `GET /slides`, `POST /live/init`, `POST /transcribe`,
`POST /start`, `POST /instruct`, `POST /stop`, `POST /confirm`, `POST /answer`.
Le log brut de chaque run est écrit dans `runs/agent.log` et `runs/state.json`.

## Modèles Holo (nov. 2026)

| Modèle | Tier | Usage |
| --- | --- | --- |
| `holo4-35b-a3b` | payant | **défaut du projet**, boucles interactives rapides |
| `holo4-27b` | payant | tâches longues et environnements inconnus |
| `holo3-1-35b-a3b` | gratuit, 10 req/min | secours sans crédits |
| `holo3-122b-a10b` | payant | structured outputs uniquement (non utilisable ici) |

Le modèle se choisit dans `.env` (`HOLO_MODEL`), avec `--model`, ou dans le sélecteur de l'interface.
Sur le modèle gratuit, mets `HOLO_MIN_INTERVAL=6.05` pour éviter les 429 en pleine démo.

## Structure

```
agent.py            point d'entrée CLI
runner.py           boucle observe → décide → agit, journal d'état, confirmation
planner.py          HoloPlanner (function calling) + MockPlanner (hors-ligne)
holo_client.py      client Models API : throttle free tier, retries
controller.py       tools exposés au modèle + exécution Playwright + garde-fou d'envoi
voice.py            Gladia : audio → texte
demo_server.py      serveur de démo (stdlib) + API
start_demo.bat      lance le serveur de démo (Windows)
profile.json        données personnelles utilisées par l'agent
.env.example        modèle de configuration (copier en .env)

demo/
  app.html          interface de contrôle
  test_form.html    formulaire local, pour développer sans dépendre d'un vrai site
slides/index.html   deck de pitch (flèches ← →)
video/              génération de la vidéo (script.md, timeline.json, render.py, mux.py)
docs/               DEMO, AVANCEMENT, ROADMAP, IDEA — voir l'index docs/README.md
runs/               sorties de runs (captures, logs, état) — ignoré par git
```

## Limites assumées

- **CAPTCHA, 2FA, FranceConnect** : hors périmètre. L'agent s'arrête et rend la main.
- **Fiabilité** : un formulaire inconnu peut demander plusieurs pas. Plafond dur à 30 pas par tâche.
- **Latence** : 1,5 à 2,5 s par pas avec holo4 ; bien plus sur le free tier (10 requêtes/minute).
- **Données** : `profile.json` est envoyé à l'API Holo dans le prompt système, avec une capture
  d'écran à chaque pas. N'y mets que ce dont la démarche a besoin.

## Documentation détaillée

| Document | Pour quoi faire |
|---|---|
| [docs/DEMO.md](docs/DEMO.md) | Feuille de répétition : scénario en 3 actes, checklist, ce qui peut casser |
| [docs/AVANCEMENT.md](docs/AVANCEMENT.md) | Journal technique complet : bugs corrigés, résultats de test, décisions |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Planning du hackathon, risques, architecture en couches |
| [docs/CORRECTIFS.md](docs/CORRECTIFS.md) | Suivi des correctifs de l'audit : fait, reporté, à faire |
| [docs/README.md](docs/README.md) | Index de toute la documentation |

## Vidéo et pitch

- [`video/script.md`](video/script.md) — script de la vidéo 30–45 s pour LinkedIn / X.
- [`slides/index.html`](slides/index.html) — deck de pitch, 10 slides, navigation clavier.
