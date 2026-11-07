"""Contenu de la video Cerfa Agent (pitch hackathon H Company x 42AI).

Chaque scene : id (utilise par index.html), duree minimale, texte de narration.
"""

VOICE = "fr-FR-RemyMultilingualNeural"
RATE = "+8%"

SCENES = [
    {
        "id": "hook",
        "min": 4.4,
        "text": "La CAF. Les impôts. Les cerfas.",
    },
    {
        "id": "problem",
        "min": 9.4,
        "text": "Des heures perdues. Des champs incompréhensibles. Des erreurs, des relances. "
                "Et beaucoup de gens qui abandonnent en route.",
    },
    {
        "id": "reveal",
        "min": 6.2,
        "text": "Voici Cerfa Agent. Tu parles, il clique.",
    },
    {
        "id": "how",
        "min": 13.0,
        "text": "Tu dictes ta demande. Gladia la transcrit. Le modèle choisit la bonne donnée. "
                "Holo regarde l'écran et localise le champ. Playwright clique, tape, "
                "et le formulaire se remplit.",
    },
    {
        "id": "demo",
        "min": 12.6,
        "text": "L'agent ouvre le site, trouve le bon champ, et tape la bonne information. Sous tes yeux. "
                "Puis il s'arrête au récapitulatif : il attend ton feu vert.",
    },
    {
        "id": "trust",
        "min": 7.6,
        "text": "Rien n'est envoyé sans toi. Tout est journalisé. Et dès que ça bloque, l'agent te passe la main.",
    },
    {
        "id": "end",
        "min": 7.0,
        "text": "Cerfa Agent. L'administratif français, enfin sans friction.",
    },
]

HEAD_PAD = 0.45   # silence avant la voix dans chaque scene
TAIL_PAD = 0.85   # respiration apres la voix
