from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    database_url: str = "postgres://aether:aether@localhost:5432/aether"
    bind_host: str = "0.0.0.0"
    bind_port: int = 8000
    allowed_origins: str = "http://localhost:5173,http://localhost:8080"

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_default_model: str = "anthropic/claude-3.5-sonnet"
    openrouter_fast_model: str = "anthropic/claude-3.5-haiku"
    openrouter_fallback_model: str = "openai/gpt-4o"

    # Data sources (public records only)
    newsapi_key: str = ""
    opencorporates_api_key: str = ""
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"

    # Redis semantic cache (LangCache-style)
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str = ""
    redis_langcache_enabled: bool = True
    redis_semantic_threshold: float = 0.92

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "aether_entities"

    # Elasticsearch (Phase 3 prep only -- see app/search/elasticsearch_setup.py)
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_username: str = ""
    elasticsearch_password: str = ""
    elasticsearch_api_key: str = ""

    # Streaming (Phase 4) -- see app/streaming/
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8082"
    ksqldb_url: str = "http://localhost:8088"
    flink_rest_url: str = "http://localhost:8081"

    # Weighted agent swarm (Phase 5) -- see app/agent_swarm/
    agent_swarm_enabled: bool = True
    heirloom_device_key: str = ""  # AES-256-GCM key for heirloom_sync.py; empty disables heirloom export

    # The Architect (Phase 5b) -- see app/agent_swarm/introspection.py and
    # app/agent_swarm/services/architect_committer.py. project_root must
    # point at a real git working tree (docker-compose mounts the repo
    # itself in dev) for introspection and the commit/PR pipeline to work;
    # absent that mount, snapshot-building degrades to DB-only and the
    # commit step raises a clear error rather than failing silently.
    project_root: str = "/repo"
    github_token: str = ""  # fine-grained PAT, contents:write + pull_requests:write on this repo only; empty disables the commit/PR step
    github_repo: str = "thetruezubzero-pixel/map"
    architect_auto_commit_enabled: bool = True
    jwt_secret: str = ""  # must match the gateway's JWT_SECRET; required to verify POST /architect/run callers

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
