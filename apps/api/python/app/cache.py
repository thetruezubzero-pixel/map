from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta

import numpy as np
import redis.asyncio as redis

from app.config import get_settings

logger = logging.getLogger("aether.cache")

CACHE_INDEX_KEY = "langcache:index"
CACHE_TTL = timedelta(days=7)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class SemanticCache:
    """Redis-backed semantic cache for LLM responses. Caches by embedding
    similarity rather than exact string match, so paraphrased queries
    ("subsidiaries of Acme" vs "Acme's subsidiary companies") hit the same
    cache entry -- this is what drives the inference cost reduction.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._redis: redis.Redis | None = None
        self._model = None

    async def _get_redis(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(
                self.settings.redis_url,
                password=self.settings.redis_password or None,
                decode_responses=False,
            )
        return self._redis

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        return self._model

    def _embed(self, text: str) -> np.ndarray:
        model = self._get_model()
        return np.asarray(model.encode(text), dtype=np.float32)

    @staticmethod
    def _exact_key(text: str) -> str:
        return f"langcache:entry:{hashlib.sha256(text.encode()).hexdigest()}"

    async def get(self, query: str) -> dict | None:
        """Best-effort: a cache outage must never fail a research job, so
        any Redis/encoding error is logged and treated as a cache miss."""
        if not self.settings.redis_langcache_enabled:
            return None

        try:
            r = await self._get_redis()

            exact = await r.get(self._exact_key(query))
            if exact:
                return json.loads(exact)

            embedding = self._embed(query)
            keys = await r.smembers(CACHE_INDEX_KEY)

            best_score = 0.0
            best_payload = None
            for key in keys:
                cached = await r.hgetall(key)
                if not cached or b"embedding" not in cached:
                    continue
                cached_embedding = np.frombuffer(cached[b"embedding"], dtype=np.float32)
                score = _cosine_similarity(embedding, cached_embedding)
                if score > best_score:
                    best_score = score
                    best_payload = cached.get(b"response")

            if best_payload is not None and best_score >= self.settings.redis_semantic_threshold:
                logger.info("semantic cache hit (score=%.3f)", best_score)
                return json.loads(best_payload)

            return None
        except Exception as exc:  # noqa: BLE001 -- cache is best-effort
            logger.warning("semantic cache read failed, treating as miss: %s", exc)
            return None

    async def set(self, query: str, response: dict) -> None:
        if not self.settings.redis_langcache_enabled:
            return

        try:
            r = await self._get_redis()
            payload = json.dumps(response)

            await r.set(self._exact_key(query), payload, ex=CACHE_TTL)

            embedding = self._embed(query)
            entry_key = f"langcache:vec:{hashlib.sha256(query.encode()).hexdigest()}"
            await r.hset(entry_key, mapping={"embedding": embedding.tobytes(), "response": payload})
            await r.expire(entry_key, CACHE_TTL)
            await r.sadd(CACHE_INDEX_KEY, entry_key)
        except Exception as exc:  # noqa: BLE001 -- cache is best-effort
            logger.warning("semantic cache write failed, continuing without caching: %s", exc)


semantic_cache = SemanticCache()
