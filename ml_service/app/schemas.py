from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TransactionIn(BaseModel):
    # Ignore extra fields (e.g. the simulator's ground-truth label) — the scorer must never see them.
    model_config = ConfigDict(extra="ignore")

    txn_id: str
    customer_id: str
    amount: float = Field(gt=0)
    currency: str = "INR"
    merchant: str
    merchant_category: str
    city: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    channel: Literal["POS", "ONLINE", "ATM"]
    timestamp: datetime


class ScoreResult(BaseModel):
    fraud_score: float
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    is_flagged: bool
    reasons: list[str]
    features: dict[str, float]
    model_version: str
    latency_ms: float
