"""Turn the raw history into a model-ready dataset by replaying it through the live feature code."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from app.features import InMemoryFeatureStore
from app.model import FEATURE_NAMES, vectorize
from app.schemas import TransactionIn
from app.scoring import RuleBasedScorer

TXN_FIELDS = list(TransactionIn.model_fields)


@dataclass
class Dataset:
    frame: pd.DataFrame        # raw columns + label + timestamp
    X: pd.DataFrame            # model features (FEATURE_NAMES)
    y: np.ndarray
    rules_score: np.ndarray    # baseline score on the exact same features
    store: InMemoryFeatureStore


def load_history(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"customer_id": str})
    df["label_is_fraud"] = df["label_is_fraud"].astype(str).str.lower().eq("true").astype(int)
    df["fraud_pattern"] = df["fraud_pattern"].fillna("")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    return df.sort_values("timestamp", kind="stable").reset_index(drop=True)


def build_dataset(path: Path) -> Dataset:
    df = load_history(path)
    store, rules = InMemoryFeatureStore(), RuleBasedScorer()
    rows, rule_scores = [], []
    for record in df[TXN_FIELDS].to_dict("records"):
        txn = TransactionIn.model_validate(record)
        features = store.compute_and_update(txn)
        rows.append(vectorize(txn, features))
        rule_scores.append(rules.score(txn, features)[0])
    X = pd.DataFrame(rows, columns=FEATURE_NAMES, dtype=np.float32)
    return Dataset(df, X, df["label_is_fraud"].to_numpy(), np.asarray(rule_scores), store)
