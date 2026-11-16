"""XGBoost fraud model: feature vector, scorer, and SHAP-based explanations.

``vectorize`` is the single definition of the model input, imported by both the training
script and the live scorer.

Explanations use TreeSHAP computed natively by XGBoost (``pred_contribs=True``). The SHAP values
sum exactly to the model's log-odds, so one predict call returns both the score and the
explanation — no extra ``shap`` dependency or latency in serving.
"""
import json
import math
from pathlib import Path

import numpy as np
import xgboost as xgb

from .schemas import TransactionIn

HIGH_RISK_CATEGORIES = {"electronics", "jewellery", "gift_cards", "travel"}

FEATURE_NAMES = [
    "amount_log", "amount_ratio", "amount_zscore", "history_count", "km_from_last", "km_from_home",
    "minutes_since_last", "speed_kmh_log", "txn_count_10m", "hour", "is_night",
    "channel_online", "channel_atm", "high_risk_category", "gift_card",
]


def vectorize(txn: TransactionIn, f: dict[str, float]) -> list[float]:
    category = txn.merchant_category
    return [
        math.log1p(f["amount"]),
        f["amount_ratio"],
        f["amount_zscore"],
        f["history_count"],
        f["km_from_last"],
        f["km_from_home"],
        min(f["minutes_since_last"], 60 * 24 * 7),
        math.log1p(f["speed_kmh"]),
        f["txn_count_10m"],
        f["hour"],
        f["is_night"],
        float(txn.channel == "ONLINE"),
        float(txn.channel == "ATM"),
        float(category in HIGH_RISK_CATEGORIES),
        float(category == "gift_cards"),
    ]


CHANNEL_LABELS = {"POS": "In-store", "ONLINE": "Online", "ATM": "ATM"}
SMALL_PROBE_AMOUNT = 300  # ₹ — fraudsters test stolen cards with tiny purchases
HIGH_ABSOLUTE_AMOUNT = 10_000  # ₹


def _reason(feature: str, txn: TransactionIn, f: dict[str, float]) -> str | None:
    """Turn a feature that pushed the score UP into analyst-friendly language.

    SHAP says *how much* a feature raised the risk, not in which direction the value is unusual
    (a tiny amount can be as suspicious as a huge one), so the wording depends on the actual value.
    """
    if feature in {"amount_ratio", "amount_zscore", "amount_log"}:
        if f["amount"] < SMALL_PROBE_AMOUNT:
            return f"Very small amount (₹{f['amount']:,.0f}) — typical of card-testing probes"
        if f["history_count"] >= 3 and f["amount_ratio"] >= 1.5:
            return f"Amount is {f['amount_ratio']:.1f}x the customer's average"
        if feature == "amount_log" and f["amount"] >= HIGH_ABSOLUTE_AMOUNT:
            return f"High amount (₹{f['amount']:,.0f})"
        return None
    if feature == "km_from_home":
        return f"{f['km_from_home']:.0f} km from the customer's usual location"
    if feature in {"speed_kmh_log", "km_from_last"} and f["km_from_last"] > 50:
        return f"Impossible travel: {f['km_from_last']:.0f} km in {f['minutes_since_last']:.0f} min"
    if feature == "txn_count_10m" and f["txn_count_10m"] > 1:
        return f"{f['txn_count_10m']:.0f} transactions in the last 10 minutes"
    if feature == "minutes_since_last" and f["history_count"] > 0:
        return f"Only {f['minutes_since_last']:.0f} min since the previous transaction"
    if feature in {"is_night", "hour"} and f["is_night"]:
        return f"Unusual hour ({f['hour']:.0f}:00 IST)"
    if feature in {"gift_card", "high_risk_category", "channel_online"} and txn.merchant_category in HIGH_RISK_CATEGORIES:
        return f"{CHANNEL_LABELS[txn.channel]} purchase in high-risk category '{txn.merchant_category}'"
    if feature == "channel_online" and txn.channel == "ONLINE":
        return "Card-not-present (online) transaction"
    if feature == "history_count" and f["history_count"] < 3:
        return "Customer has little transaction history"
    if feature == "channel_atm" and txn.channel == "ATM":
        return "ATM withdrawal"
    return None


class XGBoostScorer:
    MIN_CONTRIBUTION = 0.3  # log-odds; smaller pushes are noise to an analyst
    MAX_REASONS = 4
    EXPLAIN_FLOOR = 0.2  # SHAP only for transactions risky enough for an analyst to look at

    def __init__(self, artifact_dir: Path):
        meta = json.loads((artifact_dir / "model_meta.json").read_text())
        if meta["feature_names"] != FEATURE_NAMES:
            raise ValueError("Model was trained with a different feature set — retrain it")
        self.booster = xgb.Booster()
        self.booster.load_model(artifact_dir / "model.json")
        # Single-row scoring: spinning up a thread pool per call costs more than the prediction itself
        self.booster.set_param({"nthread": 1})
        self.version: str = meta["version"]
        self.threshold: float = meta["threshold"]

    def score(self, txn: TransactionIn, f: dict[str, float]) -> tuple[float, list[str]]:
        row = np.asarray([vectorize(txn, f)], dtype=np.float32)
        # Fast path: in-place prediction (no DMatrix) for the ~97% of transactions that are clearly fine
        margin = float(self.booster.inplace_predict(row, predict_type="margin")[0])
        probability = 1.0 / (1.0 + math.exp(-margin))
        if probability < self.EXPLAIN_FLOOR:
            return probability, []

        x = xgb.DMatrix(row, feature_names=FEATURE_NAMES)
        contribs = self.booster.predict(x, pred_contribs=True)[0]  # last column is the bias term

        reasons: list[str] = []
        for idx in np.argsort(-contribs[:-1]):
            if contribs[idx] < self.MIN_CONTRIBUTION or len(reasons) == self.MAX_REASONS:
                break
            reason = _reason(FEATURE_NAMES[idx], txn, f)
            if reason and reason not in reasons:
                reasons.append(reason)
        return probability, reasons
