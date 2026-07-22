"""NewsAPI + GDELT streaming producer -- keyword-filtered news mentions
with lightweight sentiment, published to aether.news_mentions.

Keyword filtering happens client-side against each subscription's
keyword list (see app.streaming.subscriptions) rather than per-request to
the source APIs, since NewsAPI/GDELT queries are already keyword-scoped
upstream (see data/pipelines/dags/newsapi_ingestion_dag.py and
gdelt_events_dag.py) -- this producer's job is to also score sentiment and
tag *which* subscribed keywords matched, which those batch DAGs don't do.

Dedup: by article URL (or GDELT id) in Redis, same TTL pattern as the
other streaming producers.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
import redis
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from app.config import get_settings
from app.streaming.kafka_client import EventProducer, TOPICS, ensure_topics

logger = logging.getLogger("aether.streaming.newsapi_stream")

DEFAULT_KEYWORDS = ["business acquisition", "corporate merger"]
SEEN_KEY_PREFIX = "streaming:seen:news:"
SEEN_TTL_SECONDS = 24 * 60 * 60

_sentiment = SentimentIntensityAnalyzer()


def _redis_client() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(settings.redis_url, password=settings.redis_password or None)


def _already_seen(r: redis.Redis, dedup_id: str) -> bool:
    key = f"{SEEN_KEY_PREFIX}{hashlib.sha256(dedup_id.encode()).hexdigest()}"
    return not r.set(key, "1", nx=True, ex=SEEN_TTL_SECONDS)


def _classify_sentiment(text: str) -> tuple[str, float]:
    scores = _sentiment.polarity_scores(text)
    compound = scores["compound"]
    if compound >= 0.2:
        return "POSITIVE", compound
    if compound <= -0.2:
        return "NEGATIVE", compound
    return "NEUTRAL", compound


def fetch_newsapi_articles(api_key: str, keywords: list[str]) -> list[dict]:
    articles = []
    with httpx.Client(timeout=15.0) as client:
        for keyword in keywords:
            try:
                resp = client.get(
                    "https://newsapi.org/v2/everything",
                    params={"q": keyword, "pageSize": 20, "sortBy": "publishedAt", "language": "en"},
                    headers={"X-Api-Key": api_key},
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("NewsAPI search failed for %r, skipping: %s", keyword, exc)
                continue

            for article in resp.json().get("articles", []):
                articles.append(
                    {
                        "keyword": keyword,
                        "title": article.get("title", keyword),
                        "url": article.get("url"),
                        "outlet": (article.get("source") or {}).get("name"),
                        "published_at": article.get("publishedAt"),
                    }
                )
    return articles


def fetch_gdelt_articles(keywords: list[str]) -> list[dict]:
    articles = []
    with httpx.Client(timeout=20.0) as client:
        for keyword in keywords:
            try:
                resp = client.get(
                    "https://api.gdeltproject.org/api/v2/doc/doc",
                    params={"query": keyword, "mode": "artlist", "format": "json", "maxrecords": 20},
                )
                resp.raise_for_status()
                if not resp.text.strip():
                    continue
                for article in resp.json().get("articles", []):
                    articles.append(
                        {
                            "keyword": keyword,
                            "title": article.get("title", keyword),
                            "url": article.get("url"),
                            "outlet": article.get("domain"),
                            "published_at": article.get("seendate"),
                        }
                    )
            except (httpx.HTTPError, ValueError) as exc:
                # GDELT rate-limits aggressively -- same fail-soft pattern
                # as data/pipelines/dags/gdelt_events_dag.py.
                logger.warning("GDELT search failed for %r, skipping: %s", keyword, exc)
                continue
    return articles


def run_once(keywords: list[str] = DEFAULT_KEYWORDS) -> int:
    settings = get_settings()
    ensure_topics()
    r = _redis_client()
    producer = EventProducer()
    published = 0

    if not settings.newsapi_key:
        logger.warning("NEWSAPI_KEY not set -- skipping NewsAPI leg (GDELT still runs)")

    all_articles: list[tuple[str, dict]] = []
    if settings.newsapi_key:
        for a in fetch_newsapi_articles(os.environ.get("NEWSAPI_KEY", settings.newsapi_key), keywords):
            all_articles.append(("newsapi", a))
    for a in fetch_gdelt_articles(keywords):
        all_articles.append(("gdelt", a))

    for source_name, article in all_articles:
        if not article.get("url") or _already_seen(r, article["url"]):
            continue

        sentiment, score = _classify_sentiment(article["title"])
        event = {
            "event_id": str(uuid.uuid4()),
            "source": source_name,
            "title": article["title"],
            "url": article.get("url"),
            "outlet": article.get("outlet"),
            "published_at": article.get("published_at"),
            "matched_keywords": [article["keyword"]],
            "sentiment": sentiment,
            "sentiment_score": score,
            "lat": None,
            "lon": None,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "license": "headline/snippet only, per source ToS",
        }
        producer.publish(TOPICS["news_mentions"], key=article["url"], value=event)
        published += 1

    producer.flush()
    logger.info("newsapi_stream: published %d new mentions", published)
    return published


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_once()
