"""Feature engineering + online feature store.

The feature logic lives in two *pure* functions — ``compute_features`` and ``update_profile`` —
used by both backends:

* ``FeatureStore``         (Redis)     — live serving
* ``InMemoryFeatureStore`` (dicts)     — offline training replay and backfill

Same code path for training and serving means no train/serve skew.

Features are computed from the customer's profile *before* the current transaction updates it,
so a transaction is always compared against past behaviour (no leakage). Kafka messages are keyed
by customer_id, so one customer's transactions are processed in order by a single consumer.
"""
import math
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, fields
from datetime import timedelta, timezone

from redis.asyncio import Redis

from .schemas import TransactionIn

IST = timezone(timedelta(hours=5, minutes=30))
MIN_HISTORY = 3  # need a few transactions before amount statistics are meaningful
VELOCITY_WINDOW_S = 600
PROFILE_TTL_S = 60 * 60 * 24 * 30
EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass
class CustomerProfile:
    n: int = 0
    mean: float = 0.0           # running mean of amount (Welford)
    m2: float = 0.0             # running sum of squared deviations (Welford)
    home_lat: float = 0.0       # running mean location ≈ "home"
    home_lon: float = 0.0
    last_lat: float | None = None
    last_lon: float | None = None
    last_ts: float | None = None

    @classmethod
    def from_redis(cls, raw: dict[str, str]) -> "CustomerProfile":
        p = cls()
        for f in fields(cls):
            if f.name in raw:
                setattr(p, f.name, int(raw[f.name]) if f.name == "n" else float(raw[f.name]))
        return p

    def to_redis(self) -> dict[str, float]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def compute_features(p: CustomerProfile, recent_count: int, txn: TransactionIn) -> dict[str, float]:
    ts = txn.timestamp.timestamp()
    amount = float(txn.amount)
    has_history = p.n >= MIN_HISTORY
    std = math.sqrt(p.m2 / (p.n - 1)) if p.n > 1 else 0.0

    if p.last_ts is not None:
        km_last = haversine_km(p.last_lat, p.last_lon, txn.lat, txn.lon)
        minutes = max(ts - p.last_ts, 60.0) / 60.0  # floor at 1 min to avoid divide-by-~0
        speed = km_last / (minutes / 60.0)
    else:
        km_last, minutes, speed = 0.0, 0.0, 0.0

    hour = txn.timestamp.astimezone(IST).hour
    return {
        "amount": amount,
        "history_count": float(p.n),
        "amount_ratio": amount / p.mean if has_history and p.mean > 0 else 1.0,
        "amount_zscore": (amount - p.mean) / std if has_history and std > 0 else 0.0,
        "km_from_last": km_last,
        "km_from_home": haversine_km(p.home_lat, p.home_lon, txn.lat, txn.lon) if p.n else 0.0,
        "minutes_since_last": minutes,
        "speed_kmh": speed,
        "txn_count_10m": float(recent_count + 1),  # include the current transaction
        "hour": float(hour),
        "is_night": float(hour < 5),
    }


def update_profile(p: CustomerProfile, txn: TransactionIn) -> None:
    amount = float(txn.amount)
    p.n += 1
    delta = amount - p.mean
    p.mean += delta / p.n
    p.m2 += delta * (amount - p.mean)
    p.home_lat += (txn.lat - p.home_lat) / p.n
    p.home_lon += (txn.lon - p.home_lon) / p.n
    p.last_lat, p.last_lon, p.last_ts = txn.lat, txn.lon, txn.timestamp.timestamp()


def _round(features: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 4) for k, v in features.items()}


class FeatureStore:
    """Redis-backed store used in live serving."""

    def __init__(self, redis: Redis):
        self.redis = redis

    async def compute_and_update(self, txn: TransactionIn) -> dict[str, float]:
        profile_key, velocity_key = f"cust:{txn.customer_id}", f"vel:{txn.customer_id}"
        ts = txn.timestamp.timestamp()

        profile = CustomerProfile.from_redis(await self.redis.hgetall(profile_key))
        await self.redis.zremrangebyscore(velocity_key, 0, ts - VELOCITY_WINDOW_S)
        recent = await self.redis.zcount(velocity_key, ts - VELOCITY_WINDOW_S, ts)
        features = compute_features(profile, recent, txn)

        update_profile(profile, txn)
        pipe = self.redis.pipeline()
        pipe.hset(profile_key, mapping=profile.to_redis())
        pipe.expire(profile_key, PROFILE_TTL_S)
        pipe.zadd(velocity_key, {txn.txn_id: ts})
        pipe.expire(velocity_key, VELOCITY_WINDOW_S * 2)
        await pipe.execute()
        return _round(features)


class InMemoryFeatureStore:
    """Dict-backed store with identical semantics — used to replay history offline (fast, no I/O)."""

    def __init__(self):
        self.profiles: dict[str, CustomerProfile] = defaultdict(CustomerProfile)
        self.recent: dict[str, deque[float]] = defaultdict(deque)

    def compute_and_update(self, txn: TransactionIn) -> dict[str, float]:
        ts = txn.timestamp.timestamp()
        window = self.recent[txn.customer_id]
        while window and window[0] < ts - VELOCITY_WINDOW_S:
            window.popleft()
        profile = self.profiles[txn.customer_id]
        features = compute_features(profile, len(window), txn)
        update_profile(profile, txn)
        window.append(ts)
        return _round(features)

    async def export_to_redis(self, redis: Redis, batch: int = 1000) -> int:
        """Backfill: load every profile into Redis so live customers are not cold-start."""
        pipe, count = redis.pipeline(), 0
        for customer_id, profile in self.profiles.items():
            pipe.hset(f"cust:{customer_id}", mapping=profile.to_redis())
            pipe.expire(f"cust:{customer_id}", PROFILE_TTL_S)
            count += 1
            if count % batch == 0:
                await pipe.execute()
                pipe = redis.pipeline()
        await pipe.execute()
        return count
