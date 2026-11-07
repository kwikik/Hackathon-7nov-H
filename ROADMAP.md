# Roadmap – H Company × 42AI Computer Use Agents Hackathon

**Dates :** 7–8 nov 2026, Paris. Dépôt du projet dimanche **14h00**. Pitchs finaux 15h45, résultats 17h45.

## Concept : "Cerfa Agent" (admin FR par la voix)

L'utilisateur dit à voix haute ce qu'il veut ("remplis ma demande de ..."), l'agent ouvre le site,
remplit le formulaire en regardant l'écran, puis demande confirmation avant l'envoi.

```
Voix -> Gladia (STT) -> LLM (plan + données) -> Holo (où cliquer) -> Playwright (clic/saisie) -> résultat
```

Prix visés : podium (5k/3k/2k), Best Use of Gladia (1k), Best LinkedIn/X post (500 chacun).

## État au 7 nov, 11:30

> **Le moteur tourne avec le vrai Holo et le vrai Gladia.** Run complet : 11 étapes, formulaire rempli puis envoyé après confirmation. ~1 h 30 d'avance sur le planning.
> Reste : choisir le site cible, faire la vidéo, le pitch. Détail complet dans `AVANCEMENT.md`.


## Avant l'event
- [ ] Candidater sur Luma, rejoindre le Discord H Company, trouver 1–3 coéquipiers
- [x] Créer une clé sur Portal-H, tester `python agent.py` sur le formulaire local — **fait 7/11 11:26, 11 pas, formulaire envoyé**
- [x] Vérifier dans la doc (hub.hcompany.ai) : nom exact du modèle Holo, format de sortie, SDK éventuel — **fait : `holo3-1-35b-a3b` (gratuit), function calling + `tool_choice:"required"`, coords `[0,1000]`**
- [x] Créer un compte Gladia (clé API gratuite) — **fait, transcription validée sur WAV**
- [ ] Choisir UN site cible + UN scénario de démo — **⟵ SEUL POINT BLOQUANT RESTANT**
  - Mesuré le 7/11 : **ANTS fonctionne en navigateur visible** (headless = WAF qui bloque). L'agent trouve « Vendre ou donner votre véhicule » en 7 pas.
  - Remplissage/soumission ANTS = FranceConnect obligatoire → prévoir connexion manuelle via `--profile-dir` ou `--wait-login`.
  - Deux actes : (1) navigation ANTS sans login, (2) formulaire après connexion, arrêt avant Envoyer.

## Samedi 7 nov
| Heure | Objectif | État |
|---|---|---|
| 09:00–10:30 | Check-in, kickoff, demander crédits API + SDK aux mentors H | — |
| 10:30–13:00 | Boucle agent de base qui remplit le formulaire local (screenshot -> Holo -> clic) | ✅ **fait à 11:26** |
| 14:00–17:00 | Passer sur le vrai site cible, gérer les erreurs (retry, vérification par screenshot) | ⏳ prochain |
| 17:00–19:00 | Entrée voix : Gladia temps réel -> texte -> consigne de l'agent | 🟡 API validée sur fichier, micro live à tester |
| 19:00–21:00 | Profil utilisateur JSON, confirmation avant envoi, logs visibles pour la démo | ✅ **déjà fait** |

Fin de journée : démo complète qui marche une fois, même moche. Enregistrer une vidéo de secours.

## Dimanche 8 nov
| Heure | Objectif |
|---|---|
| 08:00–10:00 | Fiabilité : lancer le scénario 20 fois, corriger les échecs |
| 10:00–12:00 | UI de démo (écran partagé : voix + navigateur + log des actions) |
| 12:00–13:30 | Pitch (problème -> actions de l'agent -> résultat), vidéo 30 s, posts LinkedIn + X |
| **14:00** | **Dépôt du projet** (repo + README + démo) |
| 15:45 | Pitch final |

## Pitch en 3 minutes
1. Problème : l'administratif FR, tout le monde l'a vécu (20 s)
2. Démo live : voix -> agent remplit -> confirmation -> envoi (90 s)
3. Comment ça marche (Holo + Gladia + Playwright) et suite possible (40 s)
4. Plan B : vidéo enregistrée si le réseau ou le site plante

## Risques
- CAPTCHA / login : utiliser un site de test ou une session déjà ouverte
- Latence de l'API : afficher les actions en direct pour que l'attente reste lisible
- Format de sortie de Holo non standard : le parser est isolé dans `agent.py` (`parse_click`)
- Démo qui plante : vidéo de secours + scénario figé

## Architecture en couches (agent générique, démo ciblée)

Principe : le moteur marche sur n'importe quel formulaire web, mais la démo se fait sur 2–3 scénarios figés, répétés 20 fois.

1. **Moteur (samedi matin)** : boucle observer -> décider -> agir. Screenshot, le LLM choisit la prochaine action (cliquer, taper, scroller, terminer), Holo donne les coordonnées, Playwright exécute, nouveau screenshot, vérification, on boucle. Remplace les `STEPS` en dur de `agent.py`.
2. **Données (samedi après-midi)** : profil JSON, le LLM choisit la bonne valeur par champ, et pose une question à l'utilisateur si une info manque.
3. **Sécurité (samedi après-midi)** : confirmation obligatoire avant tout envoi, jamais de soumission seule. À montrer dans le pitch.
4. **Voix (samedi soir)** : Gladia (speech-to-text) pour la consigne. Réponse vocale optionnelle avec un TTS séparé (Gladia ne fait pas de TTS).
5. **PDF cerfa (option, dimanche matin)** : remplissage direct des champs AcroForm avec pypdf, sans Holo.
6. **Démo (dimanche)** : interface avec voix + navigateur + journal des actions, vidéo de secours, posts.

Limites à ne pas promettre : CAPTCHA, double authentification, FranceConnect (session déjà ouverte ou humain), fiabilité 100 %.

## Vidéo pour les posts LinkedIn / X (500 € chacun)

- Base : enregistrement écran de la vraie démo (courte, 30 à 45 s, sous-titrée). C'est la preuve que l'agent marche.
- Habillage possible par IA : voix off générée, intro ou transition animée de quelques secondes.
- Script : accroche en 3 s (problème), démo accélérée, résultat, appel à voir le repo.
- À faire samedi soir pour avoir une version prête avant le dépôt de 14h dimanche.

## Structure du repo
```
agent.py          boucle agent (Playwright + Holo)
test_form.html    formulaire local pour développer sans dépendre d'un site
requirements.txt
.env.example
```
