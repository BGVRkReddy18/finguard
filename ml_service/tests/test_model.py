import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
import xgboost as xgb
from fakeredis import FakeAsyncRedis

from app.features import FeatureStore, InMemoryFeatureStore
from app.model import FEATURE_NAMES, XGBoostScorer, vectorize
from app.schemas import TransactionIn
from app.scoring import ScoringPipeline, load_scorer, risk_level

BASE = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)
CITIES = [(17.385, 78.4867), (28.6139, 77.2090), (19.076, 72.8777)]


def random_stream(n=300, seed=7):
    rng = random.Random(seed)
    t = BASE
    for _ in range(n):
        t += timedelta(seconds=rng.uniform(1, 900))
        lat, lon = rng.choice(CITIES)
        yield TransactionIn(
            txn_id=str(uuid.uuid4()), customer_id=f"C{rng.randint(1, 5)}", amount=rng.uniform(20, 20000),
            merchant="m", merchant_category=rng.choice(["grocery", "gift_cards", "electronics"]), city="x",
            lat=lat, lon=lon, channel=rng.choice(["POS", "ONLINE", "ATM"]), timestamp=t,
        )


async def test_training_and_serving_features_are_identical():
    """The offline (training) and Redis (serving) stores must produce the same features — no train/serve skew."""
    live, offline = FeatureStore(FakeAsyncRedis(decode_responses=True)), InMemoryFeatureStore()
    for txn in random_stream():
        assert await live.compute_and_update(txn) == offline.compute_and_update(txn)


async def test_backfill_warms_up_redis_profiles():
    offline = InMemoryFeatureStore()
    stream = list(random_stream(50))
    for txn in stream:
        offline.compute_and_update(txn)
    redis = FakeAsyncRedis(decode_responses=True)
    assert await offline.export_to_redis(redis) == len(offline.profiles)
    profile = await redis.hgetall(f"cust:{stream[0].customer_id}")
    assert int(profile["n"]) == offline.profiles[stream[0].customer_id].n


@pytest.fixture
def model_dir(tmp_path):
    """Train a tiny model where 'many transactions in 10 minutes' means fraud."""
    rng = np.random.default_rng(0)
    X = rng.uniform(0, 5, size=(2000, len(FEATURE_NAMES))).astype(np.float32)
    velocity = FEATURE_NAMES.index("txn_count_10m")
    y = (X[:, velocity] > 4).astype(int)
    booster = xgb.train({"objective": "binary:logistic", "max_depth": 3}, xgb.DMatrix(X, y, feature_names=FEATURE_NAMES), 30)
    booster.save_model(tmp_path / "model.json")
    (tmp_path / "model_meta.json").write_text(
        json.dumps({"version": "xgb-test", "threshold": 0.5, "feature_names": FEATURE_NAMES})
    )
    return tmp_path


async def test_xgboost_scorer_scores_and_explains(model_dir):
    scorer = load_scorer("auto", model_dir)
    assert isinstance(scorer, XGBoostScorer)
    pipeline = ScoringPipeline(FeatureStore(FakeAsyncRedis(decode_responses=True)), scorer)
    assert pipeline.flag_threshold == 0.5  # uses the model's tuned threshold

    result = None
    for i in range(6):  # burst -> txn_count_10m reaches 6
        txn = TransactionIn(txn_id=str(uuid.uuid4()), customer_id="C1", amount=99, merchant="m",
                            merchant_category="grocery", city="x", lat=17.4, lon=78.5, channel="POS",
                            timestamp=BASE + timedelta(seconds=30 * i))
        result = await pipeline.score(txn)
    assert result.is_flagged
    assert result.model_version == "xgb-test"
    assert "6 transactions in the last 10 minutes" in result.reasons


def test_auto_falls_back_to_rules_without_model(tmp_path):
    assert load_scorer("auto", tmp_path).version == "rules-v1"


def test_model_rejects_feature_mismatch(model_dir):
    meta = json.loads((model_dir / "model_meta.json").read_text())
    meta["feature_names"] = FEATURE_NAMES[:-1]
    (model_dir / "model_meta.json").write_text(json.dumps(meta))
    with pytest.raises(ValueError):
        XGBoostScorer(model_dir)


def test_vector_matches_feature_names():
    txn = next(random_stream(1))
    features = InMemoryFeatureStore().compute_and_update(txn)
    assert len(vectorize(txn, features)) == len(FEATURE_NAMES)


def test_reason_wording_depends_on_value_direction():
    from app.model import _reason

    txn = next(random_stream(1))
    small = {"amount": 35.0, "amount_ratio": 0.03, "history_count": 10.0}
    big = {"amount": 9000.0, "amount_ratio": 8.0, "history_count": 10.0}
    assert "small amount" in _reason("amount_log", txn, small)
    assert _reason("amount_ratio", txn, big) == "Amount is 8.0x the customer's average"


@pytest.mark.parametrize("score,threshold,expected", [
    (0.30, 0.35, "LOW"), (0.40, 0.35, "MEDIUM"), (0.90, 0.35, "HIGH"), (0.90, 0.95, "LOW"),
])
def test_risk_levels_follow_threshold(score, threshold, expected):
    assert risk_level(score, threshold, high_risk=0.85) == expected


def test_shipped_model_has_room_for_all_three_bands():
    scorer = XGBoostScorer(Path(__file__).parents[1] / "artifacts")
    assert scorer.threshold < scorer.high_risk < 1, "MEDIUM is empty: re-pick high_risk on validation data"
    middle = (scorer.threshold + scorer.high_risk) / 2
    levels = [risk_level(s, scorer.threshold, scorer.high_risk) for s in (0.5, middle, scorer.high_risk)]
    assert levels == ["LOW", "MEDIUM", "HIGH"]
