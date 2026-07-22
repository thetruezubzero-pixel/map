from __future__ import annotations

import logging

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings

logger = logging.getLogger("aether.openrouter")


class OpenRouterError(RuntimeError):
    pass


class OpenRouterClient:
    """Thin async wrapper around OpenRouter's chat completions endpoint with
    model routing and automatic failover when a model is rate-limited or
    down. OpenRouter fronts 400+ models across 70+ providers; we route by
    task rather than pinning to a single provider.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/thetruezubzero-pixel/map",
            "X-Title": "Aether Sovereign OS",
        }

    @retry(
        reraise=True,
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def _complete(self, model: str, messages: list[dict], **kwargs) -> dict:
        async with httpx.AsyncClient(base_url=self.settings.openrouter_base_url, timeout=30.0) as client:
            resp = await client.post(
                "/chat/completions",
                headers=self._headers(),
                json={"model": model, "messages": messages, **kwargs},
            )
            resp.raise_for_status()
            return resp.json()

    async def complete(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        fallback_models: list[str] | None = None,
        **kwargs,
    ) -> tuple[str, dict]:
        """Try `model`, then each fallback in order. Returns (model_used, response)."""
        candidates = [model or self.settings.openrouter_default_model, *(fallback_models or [])]
        last_error: Exception | None = None

        for candidate in candidates:
            try:
                response = await self._complete(candidate, messages, **kwargs)
                return candidate, response
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                logger.warning("openrouter model %s failed, trying next: %s", candidate, exc)
                last_error = exc
                continue

        raise OpenRouterError(f"all OpenRouter models exhausted: {last_error}")

    @staticmethod
    def extract_text(response: dict) -> str:
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            return ""


openrouter_client = OpenRouterClient()
