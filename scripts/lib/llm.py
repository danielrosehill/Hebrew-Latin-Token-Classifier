"""Provider-agnostic async chat client for the generation and annotation passes.

Two providers, because they are priced an order of magnitude apart and support
different structured-output mechanisms:

  deepseek    api.deepseek.com, DEEPSEEK_API_KEY
              cheapest by a wide margin. NO json_schema support — `response_format`
              of type json_schema is rejected with "This response_format type is
              unavailable now" (checked 2026-09-22). Falls back to json_object with
              the schema pasted into the system prompt, which works reliably.
              Peak/off-peak pricing: off-peak is half price, and peak is only
              01:00-04:00 and 06:00-10:00 UTC on weekdays. Run corpus jobs off-peak.
              Emits reasoning tokens even at effort="low" — they are billed as
              output and are roughly 2/3 of completion tokens on this workload, so
              budget output at ~3x the visible text.

  openrouter  openrouter.ai, OPENROUTER_API_KEY
              supports strict json_schema. `:batch` model variants cost half.

Every call records token usage to data/usage.jsonl so cost is measured rather than
guessed; see scripts/estimate_cost.py.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import pathlib
import random

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
USAGE_LOG = ROOT / "data" / "usage.jsonl"

PROVIDERS = {
    "deepseek": {
        "endpoint": "https://api.deepseek.com/chat/completions",
        "env": "DEEPSEEK_API_KEY",
        "structured": "json_object",
        "default_model": "deepseek-flash",
    },
    "openrouter": {
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "env": "OPENROUTER_API_KEY",
        "structured": "json_schema",
        "default_model": "anthropic/claude-sonnet-5:batch",
    },
}

# USD per 1M tokens. DeepSeek figures are OFF-PEAK; peak is double.
# Source: https://api-docs.deepseek.com/quick_start/pricing, read 2026-09-22.
PRICES = {
    "deepseek-flash": {"input": 0.15, "output": 0.60},
    "deepseek-v4-pro": {"input": 0.66, "output": 1.98},
    "anthropic/claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "anthropic/claude-sonnet-5:batch": {"input": 1.00, "output": 5.00},
    "google/gemini-3.8-flash": {"input": 0.30, "output": 3.75},
    "qwen/qwen3.8-flash": {"input": 0.15, "output": 0.47},
    "qwen/qwen3.8-27b": {"input": 0.42, "output": 3.00},
    # Together batch rate (50% of serverless). One of only two models
    # Together actually discounts on batch.
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": {"input": 0.52, "output": 0.52},
}

_LOG_LOCK = asyncio.Lock()


class LLMError(RuntimeError):
    pass


def provider_for(model: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    return "deepseek" if model.startswith("deepseek") else "openrouter"


def api_key(provider: str, override: str | None = None) -> str:
    if override:
        return override
    env = PROVIDERS[provider]["env"]
    key = os.environ.get(env)
    if not key:
        raise LLMError(f"{env} not set and no --api-key given")
    return key


def peak_now() -> bool:
    """DeepSeek peak: 01:00-04:00 and 06:00-10:00 UTC, weekdays."""
    now = datetime.datetime.now(datetime.timezone.utc)
    if now.weekday() >= 5:
        return False
    return 1 <= now.hour < 4 or 6 <= now.hour < 10


class Client:
    def __init__(self, model: str, *, provider: str | None = None, key: str | None = None,
                 concurrency: int = 8, timeout: float = 180.0, stage: str = "?"):
        self.model = model
        self.provider = provider_for(model, provider)
        self.stage = stage
        cfg = PROVIDERS[self.provider]
        self._endpoint = cfg["endpoint"]
        self._structured = cfg["structured"]
        self._sem = asyncio.Semaphore(concurrency)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key(self.provider, key)}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/danielrosehill/Hebrew-Latin-Token-Classifier",
                "X-Title": "Hebrew-Latin-Token-Classifier",
            },
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()

    def _payload(self, system: str, user: str, schema: dict, temperature: float) -> dict:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        if self._structured == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True, "schema": schema},
            }
        else:
            payload["messages"][0]["content"] += (
                "\n\nReply with JSON only, matching this JSON schema exactly:\n"
                + json.dumps(schema))
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def _record(self, usage: dict) -> None:
        if not usage:
            return
        row = {
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "stage": self.stage,
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "reasoning_tokens": (usage.get("completion_tokens_details") or {})
                                .get("reasoning_tokens", 0),
            "cached_tokens": usage.get("prompt_cache_hit_tokens", 0),
            "peak": peak_now() if self.provider == "deepseek" else None,
        }
        async with _LOG_LOCK:
            USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with USAGE_LOG.open("a") as fh:
                fh.write(json.dumps(row) + "\n")

    async def json_completion(self, system: str, user: str, schema: dict,
                              *, temperature: float = 1.0, attempts: int = 4) -> dict:
        payload = self._payload(system, user, schema, temperature)
        last = None
        for attempt in range(attempts):
            async with self._sem:
                try:
                    r = await self._client.post(self._endpoint, json=payload)
                except httpx.HTTPError as e:
                    last = e
                else:
                    if r.status_code == 200:
                        body = r.json()
                        if "error" in body:      # some providers report errors in-band
                            last = LLMError(str(body["error"])[:300])
                        else:
                            await self._record(body.get("usage") or {})
                            try:
                                return json.loads(body["choices"][0]["message"]["content"])
                            except (KeyError, IndexError, json.JSONDecodeError) as e:
                                last = e         # json_object mode can still drift
                    elif r.status_code in (408, 409, 429, 500, 502, 503, 504):
                        last = LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
                    else:
                        raise LLMError(f"HTTP {r.status_code}: {r.text[:400]}")
            await asyncio.sleep(min(2 ** attempt, 20) + random.random())
        raise LLMError(f"gave up after {attempts} attempts: {last}")
