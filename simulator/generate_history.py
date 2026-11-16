"""Build a labelled historical dataset by running the generator on a simulated clock.

The history ends "now", so after backfilling the feature store the live stream continues
seamlessly from where the history stopped.

Usage: python generate_history.py --hours 24 --tps 5 --out /data/history.csv.gz
"""
import argparse
import csv
import gzip
import heapq
import itertools
import os
import random
from datetime import datetime, timedelta, timezone

from generator import make_customers, next_events

FIELDS = ["txn_id", "timestamp", "customer_id", "customer_name", "home_city", "amount", "currency", "merchant",
          "merchant_category", "city", "lat", "lon", "channel", "label_is_fraud", "fraud_pattern"]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=float, default=24)
    p.add_argument("--tps", type=float, default=float(os.environ.get("TPS", 5)))
    p.add_argument("--customers", type=int, default=int(os.environ.get("NUM_CUSTOMERS", 5000)))
    p.add_argument("--fraud-rate", type=float, default=float(os.environ.get("FRAUD_RATE", 0.01)))
    p.add_argument("--seed", type=int, default=int(os.environ.get("SEED", 42)))
    p.add_argument("--out", default="/data/history.csv.gz")
    args = p.parse_args()

    customers = make_customers(args.customers, args.seed)
    rng = random.Random(args.seed + 1)
    end = datetime.now(timezone.utc)
    clock = end - timedelta(hours=args.hours)
    step = timedelta(seconds=1.0 / args.tps)

    pending: list[tuple[datetime, int, dict]] = []
    counter = itertools.count()
    rows, frauds = 0, 0
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with gzip.open(args.out, "wt", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        while clock < end:
            for delay, txn in next_events(customers, rng, clock, args.fraud_rate):
                heapq.heappush(pending, (clock + timedelta(seconds=delay), next(counter), txn))
            while pending and pending[0][0] <= clock:
                due, _, txn = heapq.heappop(pending)
                txn["timestamp"] = due.isoformat()
                writer.writerow(txn)
                rows += 1
                frauds += txn["label_is_fraud"]
            clock += step

    print(f"Wrote {rows:,} transactions ({frauds:,} fraud, {frauds / rows:.2%}) over {args.hours}h to {args.out}")


if __name__ == "__main__":
    main()
