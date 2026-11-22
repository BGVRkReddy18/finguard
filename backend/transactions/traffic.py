"""Rolling 24 h of dashboard totals, kept in memory by the Cloud Lite edition.

Lite saves transactions only while someone is watching (so Neon can sleep), but it scores traffic all
the time. These per-minute totals keep the dashboard continuous without waking the database.
``current`` stays None in the full stack, where every transaction is in Postgres.
"""
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

MAX_HOURS = 24
KEEP_MINUTES = (MAX_HOURS + 1) * 60  # one spare hour: chart windows start on a bucket boundary


@dataclass
class Minute:
    total: int = 0
    flagged: int = 0
    volume: float = 0.0
    flagged_volume: float = 0.0
    score_sum: float = 0.0
    latency_sum: float = 0.0
    timed: int = 0  # history rebuilt at startup has no latency measurement
    risks: Counter = field(default_factory=Counter)
    cities: Counter = field(default_factory=Counter)


class TrafficHistory:
    def __init__(self, model_version: str):
        self.model_version = model_version
        self._minutes: dict[int, Minute] = {}
        self._newest = 0
        self._lock = threading.Lock()  # written by the event loop, read by Django's threads

    def record(self, at: datetime, *, amount: float, city: str, score: float, risk: str, flagged: bool,
               latency_ms: float | None = None) -> None:
        key = int(at.timestamp()) // 60
        with self._lock:
            if key > self._newest:
                self._newest = key
                for old in [k for k in self._minutes if k <= key - KEEP_MINUTES]:
                    del self._minutes[old]
            m = self._minutes.setdefault(key, Minute())
            m.total += 1
            m.volume += amount
            m.score_sum += score
            m.risks[risk] += 1
            if flagged:
                m.flagged += 1
                m.flagged_volume += amount
                m.cities[city] += 1
            if latency_ms is not None:
                m.latency_sum += latency_ms
                m.timed += 1

    def stats(self, now: datetime, hours: int) -> dict:
        first = int((now - timedelta(hours=hours)).timestamp()) // 60
        out, risks, cities = Minute(), Counter(), Counter()
        with self._lock:
            for key, m in self._minutes.items():
                if key <= first:
                    continue
                for name in ("total", "flagged", "volume", "flagged_volume", "score_sum", "latency_sum", "timed"):
                    setattr(out, name, getattr(out, name) + getattr(m, name))
                risks.update(m.risks)
                cities.update(m.cities)
        return {
            "total": out.total,
            "flagged": out.flagged,
            "volume": round(out.volume, 2),
            "flagged_volume": round(out.flagged_volume, 2),
            "avg_score": out.score_sum / out.total if out.total else None,
            "avg_latency_ms": out.latency_sum / out.timed if out.timed else None,
            "by_risk_level": dict(risks),
            "top_flagged_cities": [{"city": city, "n": n} for city, n in cities.most_common(5)],
            "model_version": self.model_version,
        }

    def per_minute(self, since: int) -> list[dict]:
        """Same row shape as the timeseries SQL query. ``since`` is a Unix timestamp on a minute boundary."""
        with self._lock:
            return [{"minute": datetime.fromtimestamp(key * 60, tz=dt_timezone.utc), "total": m.total, "flagged": m.flagged}
                    for key, m in self._minutes.items() if key * 60 >= since]


current: TrafficHistory | None = None
