"""Linkup : trouver la bonne page AVANT de naviguer.

Sans recherche, l'agent explore les menus d'un site à l'aveugle (9 pas mesurés sur
ANTS pour trouver « Vendre ou donner votre véhicule »). Avec Linkup, un appel
d'environ 1 s donne l'URL exacte, et l'agent y va directement.

Par défaut la recherche couvre tout le web. Pour une démarche administrative,
`official_only=True` la restreint aux sites officiels (`includeDomains`) : l'agent
ne peut pas atterrir sur un site qui imite l'administration.

Doc : https://docs.linkup.so — POST /v1/search

Test rapide :
    python search.py "déclarer la vente de mon véhicule"
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

API = "https://api.linkup.so/v1/search"

OFFICIAL_DOMAINS = [
    "service-public.gouv.fr",
    "ants.gouv.fr",
    "immatriculation.ants.gouv.fr",
    "permisdeconduire.ants.gouv.fr",
    "impots.gouv.fr",
    "caf.fr",
    "ameli.fr",
    "urssaf.fr",
    "autoentrepreneur.urssaf.fr",
    "francetravail.fr",
    "info-retraite.fr",
    "demarches-simplifiees.fr",
    "mesdemarches.gouv.fr",
    "franceconnect.gouv.fr",
    "interieur.gouv.fr",
    "economie.gouv.fr",
    "entreprendre.service-public.gouv.fr",
]

SNIPPET_CHARS = 220


class SearchError(RuntimeError):
    pass


def search(
    query: str, max_results: int = 5, depth: str = "fast", official_only: bool = False
) -> list[dict[str, str]]:
    """Renvoie [{title, url, snippet}]. `official_only` : sites officiels uniquement."""
    load_dotenv(Path(__file__).with_name(".env"))
    key = os.environ.get("LINKUP_API_KEY", "").strip()
    if not key:
        raise SearchError("LINKUP_API_KEY manquante dans .env (app.linkup.so)")

    body: dict[str, Any] = {
        "q": query,
        "depth": depth,
        "outputType": "searchResults",
        "maxResults": max_results,
    }
    if official_only:
        body["includeDomains"] = OFFICIAL_DOMAINS
    response = requests.post(
        API,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=20,
    )
    if response.status_code >= 300:
        raise SearchError(f"linkup {response.status_code}: {response.text[:200]}")

    results = []
    for item in response.json().get("results", []):
        if item.get("type", "text") != "text" or not item.get("url"):
            continue
        snippet = " ".join(str(item.get("content", "")).split())
        results.append({
            "title": str(item.get("name", ""))[:120],
            "url": item["url"],
            "snippet": snippet[:SNIPPET_CHARS],
        })
    return results[:max_results]


def answer(question: str, depth: str = "fast", official_only: bool = False) -> dict[str, Any]:
    """Question express : une réponse rédigée et sourcée, sans ouvrir de navigateur.

    Ex. « quels papiers pour vendre ma voiture ? » -> {answer, sources[{title, url, snippet}]}.
    Tout le web par défaut ; `official_only` : sites officiels uniquement.
    """
    load_dotenv(Path(__file__).with_name(".env"))
    key = os.environ.get("LINKUP_API_KEY", "").strip()
    if not key:
        raise SearchError("LINKUP_API_KEY manquante dans .env (app.linkup.so)")

    body: dict[str, Any] = {
        "q": question + " Réponds en français, en 3 phrases maximum, simplement.",
        "depth": depth,
        "outputType": "sourcedAnswer",
    }
    if official_only:
        body["includeDomains"] = OFFICIAL_DOMAINS
    response = requests.post(
        API,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    if response.status_code >= 300:
        raise SearchError(f"linkup {response.status_code}: {response.text[:200]}")
    data = response.json()
    sources = []
    seen = set()
    for src in data.get("sources", []):
        url = src.get("url")
        page = (url or "").split("?")[0].split("#")[0]  # « F1707 » et « F1707?lang=en » : même page
        if not url or page in seen:
            continue
        seen.add(page)
        url = page if "lang=" in url else url
        sources.append({
            "title": str(src.get("name", ""))[:120],
            "url": url,
            "snippet": " ".join(str(src.get("snippet", "")).split())[:SNIPPET_CHARS],
        })
    return {"answer": str(data.get("answer", "")).strip(), "sources": sources[:4]}


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "déclarer la vente de mon véhicule"
    try:
        started = time.monotonic()
        found = search(question)
        print(f"[linkup · {time.monotonic() - started:.1f} s] {len(found)} résultat(s) pour « {question} »")
        for r in found:
            print(f"- {r['title']}\n  {r['url']}\n  {r['snippet']}")
    except SearchError as exc:
        print(f"erreur: {exc}", file=sys.stderr)
        sys.exit(1)
