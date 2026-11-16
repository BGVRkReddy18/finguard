from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379/0"
    kafka_bootstrap_servers: str = "localhost:29092"
    kafka_enabled: bool = True
    raw_topic: str = "transactions.raw"
    scored_topic: str = "transactions.scored"
    consumer_group: str = "fraud-scorer"
    scorer: Literal["auto", "rules", "xgboost"] = "auto"
    model_dir: Path = Path(__file__).resolve().parent.parent / "artifacts"
    flag_threshold: float | None = None  # override; by default each scorer uses its own tuned threshold


@lru_cache
def get_settings() -> Settings:
    return Settings()
