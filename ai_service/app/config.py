from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Any OpenAI-compatible endpoint. Default: Groq free tier. Local alternative:
    #   LLM_BASE_URL=http://host.docker.internal:11434/v1  LLM_MODEL=llama3.1  (Ollama)
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"      # on-demand investigations + analytics (quality)
    llm_fast_model: str = "openai/gpt-oss-20b"    # automatic investigations (higher free-tier limits)
    llm_requests_per_minute: int = 25               # stay under the free-tier RPM cap

    database_url: str = "postgresql://finguard_ro:finguard_ro@localhost:5432/finguard"  # read-only role
    backend_url: str = "http://localhost:8000"
    ai_service_token: str = ""
    jwt_secret: str = "dev-insecure-change-me"      # = Django SECRET_KEY, to verify user JWTs

    cors_origins: str = "http://localhost:3000"

    kafka_enabled: bool = True
    kafka_bootstrap_servers: str = "localhost:29092"
    cases_topic: str = "cases.opened"
    auto_investigate_priorities: str = "HIGH"       # comma-separated; "" disables auto-investigation
    # Free tier: ~200k tokens/day per model, ~2.5k per investigation. Auto-investigation may use at
    # most this many tokens/day of the fast model, leaving the rest for analysts' on-demand work.
    auto_investigate_daily_tokens: int = 100_000

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
