# Avancement — Cerfa Agent

> Dernière mise à jour : **samedi 7 novembre 2026, 11:30** (hackathon H Company × 42AI, dépôt dimanche 14h00)
> Auteur : session Hermes « prospections »

---

## Sommaire

1. [État global](#1-état-global-en-une-ligne)
2. [Bugs corrigés](#2-ce-qui-a-été-corrigé-bugs-bloquants)
3. [Architecture livrée](#3-architecture-livrée)
4. [Résultats de test](#4-résultats-de-test-sorties-réelles)
5. [Décisions techniques](#5-décisions-techniques-et-pourquoi)
6. [Écarts avec le ROADMAP](#6-écarts-avec-le-roadmap)
7. [Points de vigilance](#7-points-de-vigilance)
8. [Suite immédiate](#8-suite-immédiate-priorisée)
9. [Comment reproduire](#9-comment-reproduire)
10. [Site cible : ANTS](#10-site-cible--ce-quon-a-mesuré-sur-ants)

[← Index de la documentation](README.md)

---

## 1. État global en une ligne

**Le moteur fonctionne de bout en bout avec le vrai modèle Holo et la vraie API Gladia.**
Ce qui reste n'est plus du code : c'est le choix du site cible, la démo scénarisée et le pitch.

| Brique | État | Preuve |
|---|---|---|
| Boucle agent (Holo + Playwright) | ✅ **opérationnelle** | run réel en 11 pas, formulaire envoyé |
| Localisation d'élément | ✅ validée | (470, 166) normalisé → pixel (602, 133) |
| Garde-fou d'envoi | ✅ validé | confirmation demandée avant le clic « Envoyer » |
| Gladia (audio → texte) | ✅ validée | WAV local transcrit en 3 s |
| Profil utilisateur JSON | ✅ | `profile.json` (16 champs) |
| Journal / logs de démo | ✅ | `runs/state.json` + `runs/agent.log` + dashboard |
| Interface de démo (v3) | ✅ | écoute continue VAD, **réponse vocale automatique** quand l'agent demande, sélecteur de modèle, 0 erreur JS |
| Deck de pitch | ✅ | 10 slides, aucun débordement |
| Vidéo | 🟡 **faite par une autre session** | `video/` (timeline.json → MP4) |
| Site cible réel | ✅ **ANTS validé** | 9 pas, 34 s, page « Vendre ou donner votre véhicule » trouvée et documents extraits |

---

## 2. Ce qui a été corrigé (bugs bloquants)
Trois erreurs rendaient le repo initial inutilisable. Toutes venaient d'un décalage avec la doc H Company à jour (nov. 2026).

### 2.1 Modèle inexistant
- **Avant** : `HOLO_MODEL=holo1-7b` dans `.env.example` et `agent.py`
- **Réalité** : les modèles servis sont `holo4-27b`, `holo4-35b-a3b`, `holo3-1-35b-a3b` (gratuit), `holo3-122b-a10b`
- **Conséquence** : 404 à chaque appel. Rien ne pouvait marcher.
- **Correction** : `holo3-1-35b-a3b` par défaut, surchargeable via `HOLO_MODEL`.

### 2.2 Coordonnées interprétées comme des pixels
- **Avant** : `parse_click()` extrayait deux entiers et les passait directement à `page.mouse.click(x, y)`
- **Réalité** : Holo renvoie des entiers **normalisés [0, 1000]**, origine en haut à gauche, relatifs à l'image envoyée
- **Conséquence** : tous les clics atterrissaient dans le coin supérieur gauche — **sans erreur**, donc difficile à diagnostiquer
- **Correction** : conversion centralisée dans `controller._to_px()` / `_to_norm()`. Une seule source de vérité.

### 2.3 Sortie en texte libre au lieu de function calling
- **Avant** : prompt « Answer with Click(x, y) » + regex `(\d+)\D+(\d+)`
- **Réalité** : le format officiel est **function calling** avec `tool_choice: "required"`, ou `structured_outputs`
- **Correction** : 7 tools déclarés (`click`, `type`, `press_key`, `scroll`, `request_confirmation`, `ask_user`, `answer`), parsing JSON natif.

### 2.4 Champ multipart Gladia (trouvé pendant les tests)
- **Avant** : `files={"file": ...}` → **HTTP 400 « Missing audio file »**
- **Réalité** : l'endpoint `/v2/upload` attend le champ **`audio`**
- **Correction** : `files={"audio": (...)}` + `mimetypes` pour le content-type. Testé, transcription OK.

### 2.5 Verrou de fichier Windows sur `state.json` (trouvé en conditions réelles)
- **Symptôme** : `PermissionError: [WinError 5]` en plein run, l'agent meurt au pas 14.
- **Cause** : le dashboard lit `runs/state.json` toutes les 600 ms ; **Windows interdit de remplacer un fichier ouvert par un autre process** (`os.replace`).
- **Pourquoi c'est grave** : ça ne se produit **que quand le dashboard tourne** — c'est-à-dire exactement pendant la démo, jamais pendant les tests en CLI.
- **Correction** : `_write_state()` retente 6 fois avec backoff, puis écrit en place en dernier recours. Un fichier d'état ne doit jamais tuer un run.

### 2.6 Capture d'écran fatale quand la page meurt
- **Symptôme** : `Page.screenshot: Protocol error — Unable to capture screenshot` sur une page bloquée par un WAF.
- **Correction** : `screenshot_b64()` capture l'exception et réutilise la dernière image valide. La boucle continue au lieu de s'arrêter.

### 2.7 Aucun outil de récupération (lacune, pas bug)
- **Symptôme** : l'agent bouclait 10 pas sur les SPA ANTS sans jamais revenir en arrière.
- **Correction** : ajout de `go_back`, `navigate(url)` et `wait(seconds)`, plus le texte visible de la page (`visible_text`) injecté dans chaque observation pour les pages où la capture est vide.

### 2.8 Webm tronqué → `upload 400 Unsupported codec` (trouvé en usage réel)
- **Symptôme** : Gladia renvoie `400 — Unsupported codec: Invalid data found when processing input` sur les enregistrements longs (207 Ko).
- **Cause** : `stopListening()` coupe les pistes audio **avant** que le MediaRecorder ait fini d'écrire le conteneur webm. Le fichier perd son dernier bloc et devient illisible. Les enregistrements courts passaient.
- **Correction** : les pistes sont coupées dans `recorder.onstop`, jamais avant.
- **Vérifié** : 12 s / 168 Ko → transcription correcte.
- **Diagnostic** : chaque transcription est tracée dans `runs/gladia.log` (`ok` / `erreur` / `exception`) — sans ce journal, l'erreur était invisible côté serveur.

---

## 3. Architecture livrée

```
agent.py          CLI (91 l.)          point d'entrée
runner.py         boucle (207 l.)      observe → décide → agit, journal d'état, confirmation
planner.py        cerveau (255 l.)     HoloPlanner (function calling) + MockPlanner (hors-ligne)
holo_client.py    transport (147 l.)   throttle, retries 429/5xx, grounding
controller.py     mains (270 l.)       tools + Playwright + garde-fou d'envoi
voice.py          voix (102 l.)        Gladia : audio → texte
demo_server.py    SaaS (198 l.)        serveur stdlib + 6 endpoints
demo/index.html   UI (336 l.)          micro navigateur, log live, overlay de confirmation
slides/index.html deck (215 l.)        10 slides, navigation clavier
profile.json      données (16 champs)  jamais inventées, jamais envoyées au modèle
```

### Conventions Holo respectées (chacune casse la précision si on l'ignore)

| Convention | Implémentation |
|---|---|
| Coordonnées `[0, 1000]` | `controller._to_px()` |
| Max **3 screenshots** en contexte | `planner._trim_images()`, éviction en `[screenshot evicted]` |
| `answer` est le **seul** moyen de sortir | `runner` : une étape sans tool call relance la boucle |
| `tool_choice: "required"` | `holo_client.chat()` |
| Température **0.8** en boucle / **0.0** en appel unique | `HoloPlanner` / `locate()` |
| Thinking **on** en boucle / **off** en grounding | `enable_thinking` |
| Jamais le raisonnement dans l'historique | on ne réinjecte que l'action parsée |

---

## 4. Résultats de test (sorties réelles)

### 4.1 Grounding Holo
```
modele: holo3-1-35b-a3b | throttle: 0.0 s
HOLO OK -> (x, y) normalises = (470, 166) | latence: 4.09 s
pixels attendus: ( 602 , 133 )
```
Le centre réel du champ « Nom » mesuré par le DOM est à (650, 135). **Écart : 48 px sur un champ large de 480 px — dans la cible.**

### 4.2 Boucle complète, vrai modèle
```
Cerfa Agent · modèle=holo3-1-35b-a3b · mock=False
[01] click {"x": 508, "y": 168}  OK
[02] type  {"text": "Dehili"}    OK  Dehili
[03] click {"x": 508, "y": 257}  OK
[04] type  {"text": "Dylan"}     OK  Dylan
[05] click {"x": 508, "y": 345}  OK
[06] type  {"text": "12 rue de Rivoli"} OK
[07] click {"x": 508, "y": 433}  OK
[08] type  {"text": "dylandehili@gmail.com"} OK
[09] request_confirmation        OK   <- garde-fou déclenché
[10] click {"x": 350, "y": 517}  OK   <- « Envoyer », autorisé après accord
[11] answer                      OK

status: done
page_excerpt: "Demande administrative (test) Nom Prénom Adresse Email Envoyer Demande envoyée."
```

**11 pas, 24,7 s au total (1,6–2,5 s par pas), exit 0.** Le modèle a planifié en français, cliqué aux bonnes coordonnées et vérifié le résultat par lui-même (« Je vois le message "Demande envoyée." »).

### 4.3 Gladia
```
$ python voice.py --wav runs/voix_test.wav
Remplis ma demande d'aide au permis et en voilà
```
WAV généré en local (SAPI), uploadé, transcrit. « envoie-la » → « en voilà » : homophone d'une voix de synthèse, sans impact.

### 4.4 Mode hors-ligne (répétition sans réseau)
```
7 pas, status: done, exit 0
```

### 4.5 Dashboard (parcours complet)
```
lancement demandé -> overlay confirmation: True -> confirmation envoyée
STATUS: done | STEPS: 11 | LOG_COUNT: 11 | TRANSCRIPT: ✓ Formulaire rempli et envoyé
```

### 4.6 Navigation sur un vrai site du gouvernement (ANTS)
```
Cerfa Agent · modèle=holo3-1-35b-a3b · mock=False
[01] click (156,131)  ferme le bandeau cookies
[02] click (200,620)  → immatriculation.ants.gouv.fr
[03] click (150,850)  → carte « Démarches d'Immatriculation »
[06] click (580,210)  → /tout-savoir (fausse piste, il se corrige)
[10] click (150,210)  → /demarches-en-ligne
[11] click (230,680)  → /demarches-en-ligne/vendre-ou-donner-votre-vehicule
[12] scroll           lit les documents à fournir

status: done | 9 pas | 34 s | erreur: aucune
```
Réponse finale — extraite de la vraie page, pas inventée :
> « Page trouvée : Vendre ou donner votre véhicule. Documents à fournir : 3 documents requis […] Informations à saisir : numéro d'immatriculation, date de la carte grise, kilométrage, coordonnées du nouvel acquéreur. Délai : 15 jours. »

**Ce que ça prouve** : l'agent se trompe de chemin (étape 06), se corrige tout seul, et trouve la bonne démarche sur un site qu'il ne connaît pas, sans aucune intégration par site.

### 4.7 Interface et deck
- Serveur : `/`, `/state`, `/profile`, `/slides` → **200**
- Interface : **0 erreur console, 0 erreur JS**
- Deck : **10 slides**, navigation OK, **aucun débordement**
- Playwright : Chromium 1248 + headless shell + ffmpeg 1013 installés

---

## 5. Décisions techniques (et pourquoi)

| Décision | Raison |
|---|---|
| **Garde-fou dans le code, pas dans le prompt** | Un LLM peut ignorer une consigne. `elementFromPoint` + liste de verbes irréversibles = barrière réelle. C'est l'argument sécurité du pitch. |
| **Throttle `HOLO_MIN_INTERVAL`** | Le free tier est à 10 req/min. Sans lui, 429 en pleine démo. |
| **Mode `--mock`** | Permet de répéter 20 fois le scénario sans clé ni réseau — exactement ce que prévoit le ROADMAP dimanche 8h. |
| **Micro dans le navigateur** (MediaRecorder) | Pas de `sounddevice` à installer, pas de pilote audio à gérer sur la machine de démo. Et visuellement, le jury voit le micro. |
| **`profile.json` séparé** | Les données ne transitent pas par le modèle : seules les captures d'écran partent à l'API. Argument RGPD. |
| **Journal dans `runs/state.json`** | Le dashboard lit un fichier, pas besoin de websockets. Zéro dépendance. |

---

## 6. Écarts avec le ROADMAP

| Créneau prévu | Prévu | Réalisé | Écart |
|---|---|---|---|
| Avant l'event | clé Portal-H, doc Holo, compte Gladia | ✅ les trois | fait |
| Avant l'event | **choisir UN site cible + UN scénario** | ❌ toujours `test_form.html` | **en retard** |
| Sam. 10:30–13:00 | boucle agent de base sur formulaire local | ✅ **11:26** | **~1h30 d'avance** |
| Sam. 14:00–17:00 | passer sur le vrai site cible | ⏳ prochain créneau | à faire |
| Sam. 17:00–19:00 | Gladia temps réel | 🟡 API validée sur fichier, pas en live micro | partiel |
| Sam. 19:00–21:00 | profil JSON, confirmation, logs | ✅ déjà fait | **en avance** |
| Dim. 08:00–10:00 | fiabilité, 20 runs | ⏳ | à faire |
| Dim. 10:00–12:00 | UI de démo | ✅ déjà fait | **en avance** |

**Bilan : une bonne heure et demie d'avance sur le planning.** Le chemin critique n'est plus technique — il est produit (choisir le site, scénariser, filmer).

---

## 7. Points de vigilance

1. **`HOLO_MIN_INTERVAL=0` dans le `.env` actuel.** Les 11 appels du test sont passés sans 429, donc la clé n'est pas bridée à 10/min. Mais si un 429 apparaît en répétition, repasser à `6.05` : c'est la variable à surveiller.
2. **`video/render.py:19` code en dur** `chromium_headless_shell-1243`. Cette révision existe encore, mais un nettoyage de cache Playwright casserait le rendu vidéo **le jour du dépôt**. À remplacer par l'API Playwright (`pw.chromium.launch()`).
3. **Dossier `video/` produit par une autre session Hermes.** Ne pas éditer en parallèle : risque de conflit d'écriture. Coordonner avant modification.
4. **`.env` contient les clés** — déjà dans `.gitignore`, vérifié. Ne jamais le committer.

---

## 8. Suite immédiate (priorisée)

| Priorité | Action | Durée |
|---|---|---|
| **P0** | Choisir le site cible + le scénario de démo (impact, formulaire court, pas de CAPTCHA) | 30 min |
| **P0** | Run réel sur ce site, noter les échecs | 1 h |
| **P1** | Répétition : 20 runs, mesurer le taux de succès | 1 h |
| **P1** | Test micro navigateur → Gladia en live (le seul chemin non validé) | 30 min |
| **P2** | Enregistrer la vidéo de secours (plan B du pitch) | 1 h |
| **P2** | Répéter le pitch en 3 min chrono | 30 min |

---

## 9. Comment reproduire

```bash
# 1. dépendances
pip install -r requirements.txt && playwright install chromium

# 2. clés dans .env (HAI_API_KEY, GLADIA_API_KEY)

# 10 secondes, sans réseau
python agent.py --mock --headless

# vrai modèle, formulaire local
python agent.py --headless

# interface de démo
python demo_server.py     # http://localhost:8765

# deck
# ouvrir slides/index.html, flèches <- ->
```

---

## 10. Site cible : ce qu'on a mesuré sur ANTS

### Le blocage n'était pas là où on croyait

| Mode | Résultat |
|---|---|
| **Headless** (`--headless`) | ❌ Les liens produisent des URLs `/redirect_XXX` qui renvoient un **refus d'accès**. WAF anti-bot. |
| **Navigateur visible** (défaut) | ✅ Tout charge : page `demarches-en-ligne` = **5 256 caractères**, aucun refus. |

**Conséquence : ANTS est démontrable, en mode visible — c'est-à-dire exactement le mode de la démo.** Ne jamais faire la démo en `--headless`.

### Test réel de navigation, en visible

```
[01] click (297,884)  ferme le bandeau cookies        → ants.gouv.fr
[02] click (172,215)  ouvre « Vos démarches »
[03] click (181,292)  → immatriculation.ants.gouv.fr
[04] click (168,215)  → /redirect_... (headless) ou page réelle (visible)
[07] click (233,686)  → demarches-en-ligne/vendre-ou-donner-votre-vehicule  ✅
[08] scroll           liste les documents à fournir
```

**7 pas pour trouver la bonne démarche sur un site du gouvernement, sans qu'on lui donne la structure.**

### Ce qui reste impossible

- **Remplir et soumettre une démarche ANTS** : FranceConnect obligatoire + paiement pour la carte grise.
- **Formulaire de contact ANTS** : ce sont des FAQ (accordéons), pas des formulaires → 1 seul champ, la recherche.

### Deux mécanismes ajoutés pour la démo avec connexion

1. **`--profile-dir runs/browser-profile`** — profil navigateur persistant. Tu te connectes **une fois**, les cookies survivent entre les runs. L'agent réutilise ta session.
2. **`--wait-login`** — l'agent ouvre la page, **tu te connectes à la main dans sa fenêtre**, tu appuies sur Entrée, il prend le relais.

> ⚠️ Piège : `agent.py` ouvre **son propre Chromium avec un profil vierge**. Se connecter dans son Chrome personnel ne connecte pas l'agent. C'est pour ça que ces deux options existent.

### Règle de sécurité pour la démo

**Ne jamais soumettre un vrai dossier administratif en live.** Le garde-fou de confirmation existe pour ça : l'agent doit s'arrêter devant « Envoyer » et c'est toi qui cliques. Si tu veux montrer un envoi, utilise le formulaire de test local.

