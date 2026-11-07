# Démo — feuille de répétition

> Pitch final : dimanche 8 nov, 15h45. Dépôt du projet : 14h00.
> Durée visée : 3 minutes, dont 90 s de démo live.

---

## Le scénario en 3 actes

### Acte 1 — « Il trouve » (30 s, aucun login, risque zéro)

**Ce que tu dis au jury :**
> « On lui parle. Il ne connaît pas le site. Il le découvre. »

**Ce que tu tapes :**
```bash
py -3.13 agent.py --url "https://ants.gouv.fr/" --pause 0.4
```
Consigne : *« Trouve la page pour déclarer la vente de mon véhicule et liste les documents à fournir. »*

**Ce que le public voit :** le bandeau cookies se ferme, le menu s'ouvre, il se trompe de page, il revient, il trouve. **9 pas, ~35 s.**

**La phrase qui tue :** « Il s'est trompé à l'étape 6. Il s'est corrigé tout seul. On ne lui a donné aucune carte du site. »

### Acte 2 — « Il remplit » (40 s, après connexion)

**Avant de monter sur scène :**
```bash
py -3.13 agent.py --profile-dir runs/browser-profile --url "https://ants.gouv.fr/"
```
→ tu te connectes FranceConnect **une fois** dans la fenêtre de l'agent, tu fermes.
Pour les runs suivants, la session est réutilisée : plus besoin de te reconnecter.

**Pendant la démo :** tu lances l'agent sur la démarche, il remplit les champs depuis `profile.json`.

### Acte 3 — « Il s'arrête » (20 s, c'est le moment qui rassure)

Devant le bouton « Valider », l'agent **ne peut pas** cliquer :
```
[09] click {"x":353,"y":519}  KO  blocked: submit_without_confirmation
```

**La phrase qui tue :** « La sécurité n'est pas une promesse du modèle. C'est une barrière dans le code : le clic est refusé au niveau du harnais. C'est moi qui décide. »

---

## Checklist 30 minutes avant

- [ ] `py -3.13 demo_server.py` lancé, `http://localhost:8765` répond
- [ ] Connexion FranceConnect faite dans `runs/browser-profile` (session fraîche)
- [ ] Un run complet de l'acte 1, réussi
- [ ] Un run complet de l'acte 2, réussi
- [ ] Vidéo de secours sur le bureau, prête à être lancée
- [ ] Batterie à 100 %, mode avion sur le téléphone
- [ ] `HOLO_MIN_INTERVAL` = `0` (ta clé ne semble pas bridée) — si 429, remets `6.05`

---

## Les 5 choses qui peuvent casser

| Risque | Signe | Plan B |
|---|---|---|
| **429 rate limit** | `retry 1/5 dans 2.0s` en boucle | Remets `HOLO_MIN_INTERVAL=6.05`, ou passe en `--mock` |
| **Session FranceConnect expirée** | L'agent voit un écran de connexion | Reconnecte-toi à la main (`--wait-login`), ou passe à l'acte 1 seulement |
| **Site ANTS lent / WAF** | Page vide, l'agent scrolle | `go_back` est là, mais mieux : lance la vidéo |
| **Wifi du lieu** | Tout gèle | `--mock` : le scénario complet tourne sans réseau en 3 s |
| **Holo renvoie du texte au lieu d'un tool call** | `(aucun tool call)` dans le log | La boucle relance automatiquement ; sinon `--mock` |

---

## Ce qu'il ne faut PAS promettre

- ❌ « Ça marche sur tous les sites » → ça marche sur celui-là, aujourd'hui.
- ❌ « Zéro erreur » → il s'est trompé de chemin à l'étape 6 et s'est corrigé. **Dis-le, c'est plus crédible.**
- ❌ « Il gère FranceConnect » → **non**, c'est toi qui t'authentifies. L'agent prend le relais après.
- ❌ « On envoie un vrai dossier » → **jamais en live.** Le garde-fou s'arrête avant.

---

## Chiffres à réciter

| Mesure | Valeur |
|---|---|
| Navigation ANTS | **9 pas, 34 s** |
| Remplissage formulaire local | **11 pas, 24,7 s** |
| Latence Holo | **1,6–2,5 s / pas** |
| Scripts par site | **0** |
| Modules | **7** |

---

## Répartition du temps de parole (3 min)

| Temps | Contenu |
|---|---|
| 0:00–0:20 | Le problème : personne n'a envie de remplir un cerfa |
| 0:20–1:50 | **Démo live** (actes 1 → 2 → 3) |
| 1:50–2:30 | Comment ça marche : Holo regarde, Playwright agit, garde-fou |
| 2:30–3:00 | Business + suite : B2C, mutuelles/syndics, API |

Le reste du deck (`slides/index.html`) est là pour les slides de contexte, pas pour être lu.
