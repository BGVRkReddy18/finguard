"""Warm the Redis feature store with 24 h of simulated history (same generator + feature code as live).

Lightweight version of ml_service/training/backfill.py: streams events straight into the in-memory
store (no CSV, no pandas), then bulk-loads the customer profiles into Redis.
"""
import asyncio
import heapq
import itertools
import os
import random
import time
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis

from app.features import InMemoryFeatureStore
from app.schemas import TransactionIn
from generator import make_customers, next_events


def main(hours: float = 24, tps: float = 5.0, seed: int = 42) -> None:
    start = time.time()
    customers = make_customers(int(os.environ.get("NUM_CUSTOMERS", 5000)), seed)
    rng = random.Random(seed + 1)
    fraud_rate = float(os.environ.get("FRAUD_RATE", 0.01))
    store = InMemoryFeatureStore()
    end = datetime.now(UTC)
    clock, step = end - timedelta(hours=hours), timedelta(seconds=1 / tps)
    pending, counter, n = [], itertools.count(), 0
    while clock < end:
        for delay, txn in next_events(customers, rng, clock, fraud_rate):
            heapq.heappush(pending, (clock + timedelta(seconds=delay), next(counter), txn))
        while pending and pending[0][0] <= clock:
            due, _, txn = heapq.heappop(pending)
            txn["timestamp"] = due
            store.compute_and_update(TransactionIn.model_validate(txn))
            n += 1
        clock += step

    async def export() -> int:
        redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        try:
            return await store.export_to_redis(redis)
        finally:
            await redis.aclose()

    profiles = asyncio.run(export())
    print(f"[init] feature store warmed: {n:,} transactions -> {profiles:,} profiles in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main(tps=float(os.environ.get("TPS", 5)))
