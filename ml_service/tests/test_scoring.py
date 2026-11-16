import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fakeredis import FakeAsyncRedis
from fastapi.testclient import TestClient

from app.features import FeatureStore, haversine_km
from app.main import create_app
from app.schemas import TransactionIn
from app.scoring import RuleBasedScorer, ScoringPipeline

HYD = (17.385, 78.4867)
DELHI = (28.6139, 77.2090)
BASE_TIME = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)  # 11:30 IST — daytime


def make_txn(amount=1000.0, loc=HYD, minutes=0, channel="POS", category="grocery", customer="C1"):
    return TransactionIn(
        txn_id=str(uuid.uuid4()), customer_id=customer, amount=amount, merchant="Shop",
        merchant_category=category, city="X", lat=loc[0], lon=loc[1], channel=channel,
        timestamp=BASE_TIME + timedelta(minutes=minutes),
    )


@pytest.fixture
def pipeline():
    return ScoringPipeline(FeatureStore(FakeAsyncRedis(decode_responses=True)), RuleBasedScorer(), 0.7)


async def build_history(pipeline, n=5):
    for i in range(n):
        await pipeline.score(make_txn(amount=1000 + i * 50, minutes=i * 60 * 24))  # one txn per day


def test_haversine_hyderabad_delhi():
    assert 1240 < haversine_km(*HYD, *DELHI) < 1270


async def test_normal_transaction_is_low_risk(pipeline):
    await build_history(pipeline)
    result = await pipeline.score(make_txn(amount=1100, minutes=60 * 24 * 6))
    assert result.risk_level == "LOW"
    assert not result.is_flagged
    assert result.reasons == []


async def test_impossible_travel_with_large_amount_is_flagged(pipeline):
    await build_history(pipeline)
    await pipeline.score(make_txn(amount=900, minutes=60 * 24 * 6))
    result = await pipeline.score(make_txn(amount=15000, loc=DELHI, minutes=60 * 24 * 6 + 20))
    assert result.is_flagged
    assert result.risk_level == "HIGH"
    assert any("Impossible travel" in r for r in result.reasons)
    assert any("average" in r for r in result.reasons)


async def test_card_testing_burst_is_flagged(pipeline):
    await build_history(pipeline)
    start = 60 * 24 * 6
    result = None
    for i in range(6):
        result = await pipeline.score(make_txn(amount=99, minutes=start + i, channel="ONLINE", category="gift_cards"))
    assert result.is_flagged
    assert any("transactions in the last 10 minutes" in r for r in result.reasons)


async def test_new_customer_has_no_amount_signal(pipeline):
    result = await pipeline.score(make_txn(amount=50000, customer="NEW"))
    assert result.features["amount_ratio"] == 1.0


def test_score_endpoint_and_health(monkeypatch):
    monkeypatch.setenv("KAFKA_ENABLED", "false")
    monkeypatch.setenv("SCORER", "rules")
    from app.config import get_settings

    get_settings.cache_clear()
    app = create_app(redis_factory=lambda: FakeAsyncRedis(decode_responses=True))
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        resp = client.post("/score", content=make_txn().model_dump_json(), headers={"content-type": "application/json"})
        assert resp.status_code == 200
        assert resp.json()["model_version"] == "rules-v1"
        assert client.post("/score", json={"amount": -5}).status_code == 422
    get_settings.cache_clear()
