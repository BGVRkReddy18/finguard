"""Bootstrap the live Redis feature store from history, so existing customers aren't cold-start.

    python -m training.backfill --data /data/history.csv.gz

Run while the stream is paused (``make ml-bootstrap`` handles this), otherwise live updates
could interleave with the backfill.
"""
import argparse
import asyncio
import os
from pathlib import Path

from redis.asyncio import Redis

from .dataset import build_dataset


async def run(data: Path, redis_url: str) -> None:
    store = build_dataset(data).store
    redis = Redis.from_url(redis_url, decode_responses=True)
    try:
        count = await store.export_to_redis(redis)
    finally:
        await redis.aclose()
    print(f"Backfilled {count:,} customer profiles into Redis")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("/data/history.csv.gz"))
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    args = parser.parse_args()
    asyncio.run(run(args.data, args.redis_url))


if __name__ == "__main__":
    main()
