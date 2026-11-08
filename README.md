# Cerfa Agent

> ### 👉 Jury : essayer la démo
> **Tout est dans [`jury.pdf`](jury.pdf)** : le lien de la démo en ligne, l'identifiant, le mot de
> passe et un mode d'emploi en 4 étapes (parler à l'assistant, exemples de demandes).

**Ton agent web, à la voix.**

Tu dis ce que tu veux. L'agent ouvre un vrai navigateur, regarde l'écran et fait le travail :
chercher une info, comparer des prix, lire et résumer une page, trouver une démarche,
remplir un formulaire. Avant toute action irréversible (envoyer, payer, commander, réserver,
publier), il s'arrête et attend ton feu vert.

L'administratif français reste le cas d'usage phare de la démo, parce que c'est là que
remplir des formulaires fait le plus mal.

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
  l'écran et localise l'élément à cliquer. Le même code marche sur n'importe quel site.
- **Coordonnées normalisées `[0, 1000]`.** Convention Holo respectée de bout en bout, conversion en
  pixels CSS dans un seul module (`controller.py`).
- **Garde-fou des actions irréversibles.** Un clic sur « Envoyer », « Valider », « Payer »,
  « Acheter », « Commander », « Réserver », « Publier » ou « Supprimer » est **bloqué par le harnais** tant qu'une confirmation humaine n'a pas été donnée. Ce n'est pas une consigne au modèle :
  c'est une barrière dans le code.
- **Zéro invention de données.** Les valeurs saisies viennent d'un profil local (`profile.json`).
  Si une donnée obligatoire manque, l'agent appelle `ask_user` au lieu de remplir au hasard.
- **Il montre ce qu'il va envoyer.** Avant l'envoi, chaque champ du formulaire est relu à l'écran
  et comparé au profil : on valide ce qui part vraiment, pas ce que le modèle dit avoir tapé.
- **Il cherche avant de naviguer.** Un outil `web_search` (Linkup) trouve la bonne page sur tout
  le web ; pour une démarche administrative, l'agent le restreint aux sites officiels
  (`official_only`), pour ne jamais atterrir sur un site qui imite l'administration. Mesuré : « déclarer la vente de mon véhicule » en
  **3 pas** (recherche → page officielle → réponse) au lieu de 9 en explorant les menus.
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
# auto = réflexion seulement sur les formulaires, les consignes complexes et après un échec ;
# 1 = à chaque pas (plus lent) ; 0 = jamais (plus rapide, moins fiable)
HOLO_THINKING=auto

# Gladia — speech-to-text (docs.gladia.io)
GLADIA_API_KEY=...
# solaria-3 (défaut, le plus précis en français) ou solaria-1 (un peu plus rapide)
GLADIA_MODEL=solaria-3

# Linkup — recherche web pour agents (app.linkup.so)
LINKUP_API_KEY=...

# serveur de démo
DEMO_PORT=8765
```

```bash
python agent.py --task "..."             # part d'une page vide, va où on lui dit
python agent.py --mock --headless        # répétition hors-ligne, sans clé
python agent.py --url https://... --task "Remplis ma demande d'aide au permis et envoie-la"
python agent.py --interactive --demo     # mode conversation, piloté depuis l'interface
```

### Options de `agent.py`

| Option | Défaut | Effet |
|---|---|---|
| `--url URL` | page vide | Page sur laquelle le navigateur s'ouvre au départ. Sans elle, l'agent va lui-même sur le bon site. |
| `--task "..."` | aucune (obligatoire hors `--interactive`) | Consigne en langage naturel. En mode `--interactive`, seulement la première consigne. |
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
| `--window X,Y,L,H` | aucune | Place la fenêtre du navigateur à l'écran, et adapte la page à sa taille (mode « site ouvert à côté » de l'interface). |
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

**Ouvrir** (Windows) : double-clic sur `start_demo.bat`, ou dans un terminal à la racine :

```powershell
.\start_demo.bat
```

Le serveur démarre dans une fenêtre réduite « Cerfa demo » et le navigateur s'ouvre sur
http://localhost:8765. Si le serveur tourne déjà, le script ouvre juste la page.

**Fermer** : arrête le serveur, l'agent en cours et la fenêtre Chromium de l'agent
(tous les serveurs sur le port, y compris un vieux serveur oublié) :

```powershell
.\stop_demo.bat
```

Sans les scripts (macOS / Linux) : `python demo_server.py`, puis Ctrl+C pour arrêter.

**Ouvrir au jury (lien public)** : la démo tourne sur ton PC et un tunnel Cloudflare lui donne une
adresse `https://xxx.trycloudflare.com` (prérequis : `winget install --id Cloudflare.cloudflared`).

```powershell
.	unnel_demo.bat
```

Le lien s'affiche dans le terminal et change à chaque lancement. Par le tunnel, le navigateur
demande un mot de passe : identifiant libre (ex. `jury`), mot de passe = `DEMO_PASSWORD` du `.env`.
Sans `DEMO_PASSWORD`, l'accès distant est refusé. En local (`localhost`), pas de mot de passe.
Ctrl+C coupe le tunnel, la démo locale continue. Un seul run à la fois pour tout le monde, et la
fenêtre Chromium de l'agent s'ouvre sur ton PC : le jury suit l'écran de l'agent dans l'interface.

La page (`demo/app.html`, HTML/CSS/JS sans build) écoute la voix (micro du navigateur → Gladia),
lance l'agent et affiche en direct :

- **l'orbe vocale 3D** (Three.js depuis un CDN) : elle respire au repos, se déforme au rythme de ta
  voix quand tu maintiens Espace, tourbillonne quand l'agent travaille et
  passe en couleurs chaudes quand il attend ta validation. Elle sert aussi de bouton micro. Sans
  WebGL ou sans réseau, une sphère CSS prend le relais. Elle est petite au repos et grandit
  pendant que tu parles,
- la transcription de la consigne,
- l'écran de l'agent dans un cadre de navigateur (adresse de la page en cours), avec **le point de
  clic** : une onde à l'endroit exact où Holo a cliqué (coordonnées [0, 1000] replacées sur
  l'image) et le texte tapé en surimpression,
- **la frise des actions** : une icône par type d'action (recherche, page, clic, saisie,
  validation…), le détail, la durée, et la dernière pensée du modèle,
- la question de l'agent quand une donnée manque, et la demande de confirmation avant envoi,
  auxquelles on peut répondre à la voix (maintenir Espace, « oui », « vas-y ») ou par les boutons,
- **le récap avant envoi** : au moment de la confirmation, l'agent relit le formulaire *à l'écran*
  et l'interface montre chaque champ qui va partir, comparé au profil (✓ profil, ≠ profil avec la
  valeur attendue, hors profil, obligatoire vide).

L'agent ne parle pas : tout ce qu'il dit (questions, confirmations, réponses) s'affiche à l'écran.

**Mode conversation** (case cochée par défaut) : le navigateur reste ouvert entre deux consignes.
Chaque nouvelle phrase est envoyée à `/instruct` et l'agent la joue sur la même page, avec la
session et le formulaire en cours. Sans cette case, chaque consigne relance un navigateur neuf.

La confirmation avant envoi est **active par défaut**. La case « ne jamais demander de
confirmation » la coupe pour un run.

**Questions express** (case cochée par défaut) : une question (« quels papiers pour vendre ma
voiture ? », « combien coûte un passeport ? ») n'ouvre pas de navigateur. Linkup renvoie une
réponse rédigée et sourcée depuis le web en 2 à 3 s ; elle s'affiche en grand avec
ses sources cliquables. Une phrase qui demande une action
(« remplis », « trouve », « déclare »…) part toujours à l'agent.

**Il retient ce que tu lui dis** : quand l'agent te pose une question (donnée absente du profil),
tu réponds à la voix ou en tapant dans la feuille de question. L'interface propose ensuite
« Je le retiens pour la prochaine fois ? » : la réponse est ajoutée à `profile.json` sous une clé
tirée de la question (« Quel est votre numéro de permis de conduire ? » → `numero_permis_conduire`).
En mode conversation, l'agent relit le profil à chaque consigne : il ne la redemande plus. Dans le
panneau profil, les données sensibles (IBAN, n° de sécu, SIRET, permis…) sont masquées.

**Micro en push-to-talk** : maintiens **Espace** (ou le bouton micro) pendant que tu parles,
relâche pour envoyer. Pas de coupure automatique au silence. L'audio part à Gladia avec le
modèle **Solaria-3** (le plus précis en français, `GLADIA_MODEL`) et un vocabulaire imposé
(ANTS, Cerfa, FranceConnect…). Le serveur garde sa connexion à Gladia ouverte en permanence :
compter environ 3 s entre le relâchement et le texte. Le temps mesuré s'affiche sous le micro.

Le serveur refuse toute requête POST venue d'une autre origine que `localhost:8765`, et exige du JSON.

Endpoints : `GET /state`, `GET /live.png`, `GET /profile`, `GET /slides`, `POST /transcribe`,
`POST /start`, `POST /instruct`, `POST /stop`, `POST /confirm`, `POST /answer`, `POST /ask`
(question express), `POST /profile/remember` (ajout au profil).
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
search.py           Linkup : recherche web (option sites officiels uniquement)
demo_server.py      serveur de démo (stdlib) + API
start_demo.bat      ouvre la démo : serveur + navigateur (Windows)
stop_demo.bat       ferme la démo : serveur, agent, Chromium (Windows)
tunnel_demo.bat     lien public pour le jury : tunnel Cloudflare + mot de passe (Windows)
profile.json        données personnelles utilisées par l'agent
.env.example        modèle de configuration (copier en .env)

demo/
  app.html          interface de contrôle
  test_form.html    formulaire local, utilisé seulement par le mode hors-ligne (--mock)
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
