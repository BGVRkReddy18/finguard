"""Train the XGBoost fraud model and benchmark it against the rule baseline.

    python -m training.train --data /data/history.csv.gz

Key choices:
* Time-based split (train 70% / validation 15% / test 15%) — random splits leak future
  behaviour into training and overstate performance.
* ``scale_pos_weight`` handles class imbalance (~3% fraud); early stopping on validation PR-AUC.
* Decision threshold tuned on validation for max F1, then reported once on the untouched test set.
* Metrics that matter to a bank: recall, precision, fraud *amount* caught, and analyst workload
  (false alerts per 1,000 genuine transactions).
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, f1_score, precision_recall_curve, precision_score, \
    recall_score, roc_auc_score
import xgboost as xgb
from xgboost import XGBClassifier

from app.model import FEATURE_NAMES
from app.scoring import RuleBasedScorer

from .dataset import build_dataset

PARAMS = {
    "n_estimators": 600,
    "max_depth": 5,
    "learning_rate": 0.05,
    "subsample": 0.9,
    "colsample_bytree": 0.9,
    "min_child_weight": 3,
    "reg_lambda": 1.0,
    "tree_method": "hist",
    "eval_metric": "aucpr",
    "early_stopping_rounds": 40,
}


def evaluate(name: str, y: np.ndarray, score: np.ndarray, threshold: float, frame: pd.DataFrame) -> dict:
    pred = score >= threshold
    legit = y == 0
    amount = frame["amount"].to_numpy()
    by_pattern = {
        pattern: float(pred[(frame["fraud_pattern"] == pattern).to_numpy()].mean())
        for pattern in sorted(p for p in frame["fraud_pattern"].unique() if p)
    }
    return {
        "name": name,
        "threshold": round(float(threshold), 4),
        "roc_auc": roc_auc_score(y, score),
        "pr_auc": average_precision_score(y, score),
        "precision": precision_score(y, pred, zero_division=0),
        "recall": recall_score(y, pred),
        "f1": f1_score(y, pred),
        "fraud_amount_caught": float(amount[pred & (y == 1)].sum() / amount[y == 1].sum()),
        "false_alerts_per_1k": float(pred[legit].mean() * 1000),
        "recall_by_pattern": by_pattern,
    }


def best_f1_threshold(y: np.ndarray, score: np.ndarray) -> float:
    precision, recall, thresholds = precision_recall_curve(y, score)
    f1 = 2 * precision * recall / np.clip(precision + recall, 1e-9, None)
    return float(thresholds[np.argmax(f1[:-1])])


def print_report(results: list[dict]) -> None:
    keys = ["roc_auc", "pr_auc", "precision", "recall", "f1", "fraud_amount_caught", "false_alerts_per_1k"]
    print(f"\n{'metric':<22}" + "".join(f"{r['name']:>14}" for r in results))
    for key in keys:
        print(f"{key:<22}" + "".join(f"{r[key]:>14.3f}" for r in results))
    print("recall by pattern:")
    for pattern in results[0]["recall_by_pattern"]:
        print(f"  {pattern:<20}" + "".join(f"{r['recall_by_pattern'][pattern]:>14.3f}" for r in results))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("/data/history.csv.gz"))
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "artifacts")
    parser.add_argument("--mlflow-uri", default="file:///mlruns")
    args = parser.parse_args()

    t0 = time.time()
    ds = build_dataset(args.data)
    print(f"Replayed {len(ds.y):,} transactions through the feature store in {time.time() - t0:.1f}s "
          f"({ds.y.mean():.2%} fraud)")

    n = len(ds.y)
    train_end, val_end = int(n * 0.70), int(n * 0.85)
    splits = {"train": slice(0, train_end), "val": slice(train_end, val_end), "test": slice(val_end, n)}
    X, y = ds.X, ds.y
    pos = y[splits["train"]].sum()
    params = {**PARAMS, "scale_pos_weight": float((len(y[splits["train"]]) - pos) / pos)}

    mlflow.set_tracking_uri(args.mlflow_uri)
    mlflow.set_experiment("finguard-fraud")
    with mlflow.start_run() as run:
        t0 = time.time()
        model = XGBClassifier(**params)
        model.fit(X[splits["train"]], y[splits["train"]], eval_set=[(X[splits["val"]], y[splits["val"]])], verbose=False)
        train_seconds = time.time() - t0

        val_score = model.predict_proba(X[splits["val"]])[:, 1]
        threshold = best_f1_threshold(y[splits["val"]], val_score)

        test = splits["test"]
        test_frame = ds.frame.iloc[test]
        xgb_result = evaluate("xgboost", y[test], model.predict_proba(X[test])[:, 1], threshold, test_frame)
        rules_result = evaluate("rules-v1", y[test], ds.rules_score[test], RuleBasedScorer.threshold, test_frame)
        print_report([rules_result, xgb_result])

        booster = model.get_booster()
        shap = booster.predict(xgb.DMatrix(X[test], feature_names=FEATURE_NAMES), pred_contribs=True)
        importance = dict(sorted(zip(FEATURE_NAMES, np.abs(shap[:, :-1]).mean(axis=0).round(4).tolist()),
                                 key=lambda kv: -kv[1]))
        print("\nmean |SHAP| (global feature importance):")
        for name, value in list(importance.items())[:8]:
            print(f"  {name:<22}{value:.3f}")

        version = f"xgb-{datetime.now(timezone.utc):%Y%m%d}-{run.info.run_id[:6]}"
        args.out.mkdir(parents=True, exist_ok=True)
        booster.save_model(args.out / "model.json")
        meta = {
            "version": version,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "feature_names": FEATURE_NAMES,
            "threshold": threshold,
            "best_iteration": int(model.best_iteration),
            "rows": {k: int(s.stop - s.start) for k, s in splits.items()},
            "test_metrics": {"xgboost": xgb_result, "rules-v1": rules_result},
            "shap_importance": importance,
            "mlflow_run_id": run.info.run_id,
        }
        (args.out / "model_meta.json").write_text(json.dumps(meta, indent=2, default=float))

        mlflow.log_params({k: v for k, v in params.items() if k != "eval_metric"} | {"threshold": threshold})
        for prefix, result in (("test", xgb_result), ("rules_test", rules_result)):
            mlflow.log_metrics({f"{prefix}_{k}": float(v) for k, v in result.items() if isinstance(v, float)})
        mlflow.log_metric("train_seconds", train_seconds)
        mlflow.log_artifacts(str(args.out), artifact_path="model")
        mlflow.set_tag("model_version", version)

    print(f"\nSaved {version} to {args.out} (threshold {threshold:.3f}, {model.best_iteration} trees, "
          f"trained in {train_seconds:.1f}s)")


if __name__ == "__main__":
    main()
