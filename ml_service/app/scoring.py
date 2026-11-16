"""Fraud scorers.

Phase 1 ships an explainable rule-based baseline. Phase 2 adds an XGBoost model behind the same
``Scorer`` interface, so we can benchmark ML against this baseline on identical data.
"""
import logging
import math
import time
from pathlib import Path
from typing import Protocol

from prometheus_client import Counter, Histogram

from .features import FeatureStore
from .schemas import ScoreResult, TransactionIn

SCORE_LATENCY = Histogram(
    "finguard_scoring_latency_seconds", "End-to-end scoring latency",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25),
)
SCORED_TOTAL = Counter("finguard_transactions_scored_total", "Transactions scored", ["risk_level"])

logger = logging.getLogger(__name__)

HIGH_RISK_ONLINE_CATEGORIES = {"electronics", "jewellery", "gift_cards", "travel"}


class Scorer(Protocol):
    version: str
    threshold: float  # score at/above which a transaction is flagged

    def score(self, txn: TransactionIn, features: dict[str, float]) -> tuple[float, list[str]]: ...


class RuleBasedScorer:
    """Weighted rules combined through a logistic function. Each fired rule produces a human-readable reason."""

    version = "rules-v1"
    threshold = 0.7
    BIAS = -4.0

    def score(self, txn: TransactionIn, f: dict[str, float]) -> tuple[float, list[str]]:
        contributions: list[tuple[float, str]] = []

        ratio = f["amount_ratio"]
        if ratio >= 5:
            contributions.append((3.0, f"Amount is {ratio:.1f}x the customer's average"))
        elif ratio >= 3:
            contributions.append((1.5, f"Amount is {ratio:.1f}x the customer's average"))
        if f["amount_zscore"] >= 4:
            contributions.append((0.8, f"Amount is {f['amount_zscore']:.1f} std devs above normal"))

        if f["speed_kmh"] > 900 and f["km_from_last"] > 300:
            contributions.append(
                (3.5, f"Impossible travel: {f['km_from_last']:.0f} km in {f['minutes_since_last']:.0f} min")
            )
        elif f["km_from_last"] > 500:
            contributions.append((1.0, f"{f['km_from_last']:.0f} km from previous transaction location"))

        count = f["txn_count_10m"]
        if count >= 5:
            contributions.append((4.5, f"{count:.0f} transactions in the last 10 minutes"))
        elif count >= 3:
            contributions.append((1.2, f"{count:.0f} transactions in the last 10 minutes"))

        if f["is_night"]:
            contributions.append((0.8, f"Unusual hour ({f['hour']:.0f}:00 IST)"))
        if txn.channel == "ONLINE" and txn.merchant_category in HIGH_RISK_ONLINE_CATEGORIES:
            contributions.append((0.7, f"Online purchase in high-risk category '{txn.merchant_category}'"))
        if txn.channel == "ATM" and txn.amount > 20000:
            contributions.append((0.6, "Large ATM withdrawal"))

        z = self.BIAS + sum(w for w, _ in contributions)
        probability = 1.0 / (1.0 + math.exp(-z))
        reasons = [reason for _, reason in sorted(contributions, key=lambda c: -c[0])]
        return probability, reasons


HIGH_RISK_SCORE = 0.85


def risk_level(score: float, threshold: float) -> str:
    """Risk bands are tied to the flag threshold, so every flagged transaction is MEDIUM or HIGH."""
    if score >= max(HIGH_RISK_SCORE, threshold):
        return "HIGH"
    if score >= threshold:
        return "MEDIUM"
    return "LOW"


def load_scorer(kind: str, model_dir: Path) -> Scorer:
    """``auto`` uses the trained model when its artifacts exist, otherwise falls back to the rules."""
    if kind == "rules" or (kind == "auto" and not (model_dir / "model.json").exists()):
        logger.info("Using rule-based scorer")
        return RuleBasedScorer()
    from .model import XGBoostScorer  # imported lazily: rules-only deployments don't need xgboost loaded

    scorer = XGBoostScorer(model_dir)
    logger.info("Loaded model %s (threshold %.3f)", scorer.version, scorer.threshold)
    return scorer


class ScoringPipeline:
    def __init__(self, feature_store: FeatureStore, scorer: Scorer, flag_threshold: float | None = None):
        self.feature_store = feature_store
        self.scorer = scorer
        self.flag_threshold = flag_threshold if flag_threshold is not None else scorer.threshold

    async def score(self, txn: TransactionIn) -> ScoreResult:
        start = time.perf_counter()
        features = await self.feature_store.compute_and_update(txn)
        probability, reasons = self.scorer.score(txn, features)
        elapsed = time.perf_counter() - start

        level = risk_level(probability, self.flag_threshold)
        SCORE_LATENCY.observe(elapsed)
        SCORED_TOTAL.labels(risk_level=level).inc()
        return ScoreResult(
            fraud_score=round(probability, 4),
            risk_level=level,
            is_flagged=probability >= self.flag_threshold,
            reasons=reasons,
            features=features,
            model_version=self.scorer.version,
            latency_ms=round(elapsed * 1000, 3),
        )
