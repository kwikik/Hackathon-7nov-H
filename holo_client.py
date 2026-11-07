"""Client Holo (Models API H Company) : un appel chat/completions, avec throttle + retries.

Doc : https://hub.hcompany.ai/models-api/overview
Modèles servis (nov. 2026) :
  holo4-27b        payant, le plus capable          (function calling)
  holo4-35b-a3b    payant, le plus rapide           (function calling)
  holo3-1-35b-a3b  GRATUIT, 10 req/min              (function calling + structured outputs)
  holo3-122b-a10b  payant                           (structured outputs uniquement)
"""
from __future__ import annotations

import os
import time
from typing import Any

from openai import APIStatusError, OpenAI, RateLimitError

DEFAULT_BASE_URL = "https://api.hcompany.ai/v1/"
DEFAULT_MODEL = "holo4-35b-a3b"
# Le free tier est limité à 10 requêtes/minute : 6.05 s entre deux appels.
FREE_TIER_INTERVAL = 6.05


class HoloError(RuntimeError):
    pass


class HoloClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        min_interval: float | None = None,
    ):
        api_key = api_key or os.environ.get("HAI_API_KEY")
        if not api_key:
            raise HoloError(
                "HAI_API_KEY manquante. Crée une clé sur portal.hcompany.ai puis renseigne .env"
            )
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or os.environ.get("HAI_BASE_URL", DEFAULT_BASE_URL),
            timeout=120.0,
            max_retries=0,  # on gère les retries nous-mêmes (429 = free tier)
        )
        self.model = model or os.environ.get("HOLO_MODEL", DEFAULT_MODEL)
        if min_interval is None:
            raw = os.environ.get("HOLO_MIN_INTERVAL")
            min_interval = float(raw) if raw else (FREE_TIER_INTERVAL if self.model.startswith("holo3-1") else 0.0)
        self.min_interval = min_interval
        self._last_call = 0.0

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        thinking: bool = True,
        temperature: float | None = None,
        tool_choice: str | None = None,
        max_attempts: int = 5,
    ):
        """Un appel chat/completions. Retry exponentiel sur 429 et 5xx."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.8 if temperature is None else temperature,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": thinking}},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "required"

        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            self._throttle()
            try:
                response = self.client.chat.completions.create(**kwargs)
                return response.choices[0].message
            except RateLimitError as exc:
                last_error = exc
                wait = min(60.0, 2.0 ** attempt)
            except APIStatusError as exc:
                last_error = exc
                if exc.status_code not in (429, 500, 502, 503, 504):
                    raise
                wait = min(60.0, 2.0 ** attempt)
            except Exception as exc:  # réseau
                last_error = exc
                wait = min(30.0, 1.5 ** attempt)
            print(f"   [holo] appel échoué ({type(last_error).__name__}), retry {attempt}/{max_attempts} dans {wait:.1f}s")
            time.sleep(wait)

        raise HoloError(f"Holo n'a pas répondu après {max_attempts} tentatives : {last_error}")
