"""Minimal async OpenRouter client shared by the generation and annotation passes.

Reads OPENROUTER_API_KEY from the environment but takes an override, because the
exported value has historically belonged to a dead account. Verify once with:

    curl -s https://openrouter.ai/api/v1/key -H "Authorization: Bearer $OPENROUTER_API_KEY"

A live key returns non-null `creator_user_id`; a dead account returns
401 {"message":"User not found"} regardless of which key you try.
"""
from __future__ import annotations

import asyncio
import json
import os
import random

import httpx

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
REFERER = "https://github.com/danielrosehill/Hebrew-Latin-Token-Classifier"


class OpenRouterError(RuntimeError):
    pass


def api_key(override: str | None = None) -> str:
    key = override or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise OpenRouterError("no OPENROUTER_API_KEY in environment and no --api-key given")
    return key


class Client:
    def __init__(self, model: str, key: str, concurrency: int = 8, timeout: float = 180.0):
        self.model = model
        self._sem = asyncio.Semaphore(concurrency)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": REFERER,
                "X-Title": "Hebrew-Latin-Token-Classifier",
            },
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()

    async def json_completion(self, system: str, user: str, schema: dict,
                              *, temperature: float = 1.0, attempts: int = 4) -> dict:
        """One chat completion constrained to `schema`, with retry on transient failure."""
        payload = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True, "schema": schema},
            },
        }
        last = None
        for attempt in range(attempts):
            async with self._sem:
                try:
                    r = await self._client.post(ENDPOINT, json=payload)
                except httpx.HTTPError as e:            # network, timeout
                    last = e
                else:
                    if r.status_code == 200:
                        body = r.json()
                        if "error" in body:             # OpenRouter reports some errors in-band
                            last = OpenRouterError(str(body["error"])[:300])
                        else:
                            try:
                                return json.loads(body["choices"][0]["message"]["content"])
                            except (KeyError, IndexError, json.JSONDecodeError) as e:
                                last = e
                    elif r.status_code in (408, 409, 429, 500, 502, 503, 504):
                        last = OpenRouterError(f"HTTP {r.status_code}: {r.text[:200]}")
                    else:                               # 401/402/403/404 will not improve
                        raise OpenRouterError(f"HTTP {r.status_code}: {r.text[:400]}")
            await asyncio.sleep(min(2 ** attempt, 20) + random.random())
        raise OpenRouterError(f"gave up after {attempts} attempts: {last}")
