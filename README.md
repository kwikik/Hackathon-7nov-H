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

cp .env.example .env      # puis renseigne HAI_API_KEY (portal.hcompany.ai) et GLADIA_API_KEY
```

```bash
python agent.py                          # formulaire local de test
python agent.py --mock --headless        # répétition hors-ligne, sans clé
python agent.py --url https://... --task "Remplis ma demande d'aide au permis et envoie-la"
```

## Interface de démo

```bash
python demo_server.py      # -> http://localhost:8765
```

La page prend la voix (micro du navigateur → Gladia), lance l'agent et affiche en direct :

- la transcription de la consigne,
- la capture de l'écran de l'agent (rafraîchie à chaque pas),
- le journal des actions (tool, arguments, résultat, durée),
- la demande de confirmation avant envoi.

Endpoints : `GET /state`, `GET /live.png`, `POST /transcribe`, `POST /start`, `POST /confirm`.
Le log brut de chaque run est écrit dans `runs/agent.log` et `runs/state.json`.

## Modèles Holo (nov. 2026)

| Modèle | Tier | Usage |
| --- | --- | --- |
| `holo3-1-35b-a3b` | **gratuit**, 10 req/min | défaut du projet |
| `holo4-35b-a3b` | payant | boucles interactives rapides |
| `holo4-27b` | payant | tâches longues et environnements inconnus |
| `holo3-122b-a10b` | payant | structured outputs uniquement |

`HOLO_MIN_INTERVAL` (défaut `6.05` s sur le free tier) espace automatiquement les appels pour
éviter les 429 en pleine démo. Passe-le à `0` avec une clé payante.

## Structure

```
agent.py          point d'entrée CLI
runner.py         boucle observe → décide → agit, journal d'état, confirmation
planner.py        HoloPlanner (function calling) + MockPlanner (hors-ligne)
holo_client.py    client Models API : throttle free tier, retries, grounding
controller.py     tools exposés au modèle + exécution Playwright + garde-fou d'envoi
voice.py          Gladia : audio → texte
demo_server.py    serveur de démo (stdlib) + API
demo/app.html     interface de contrôle
slides/index.html deck de pitch (flèches ← →)
test_form.html    formulaire local, pour développer sans dépendre d'un vrai site
profile.json      données personnelles utilisées par l'agent
```

## Limites assumées

- **CAPTCHA, 2FA, FranceConnect** : hors périmètre. L'agent s'arrête et rend la main.
- **Fiabilité** : un formulaire inconnu peut demander plusieurs pas. Plafond dur à 30 pas par tâche.
- **Latence** : le free tier impose 10 requêtes/minute ; la démo est volontairement lente et lisible.
- **Données** : le profil reste local. Seules les captures d'écran partent vers l'API du modèle.

## Vidéo et pitch

- `video/script.md` — script de la vidéo 30–45 s pour LinkedIn / X.
- `slides/index.html` — deck de pitch, 10 slides, navigation clavier.
