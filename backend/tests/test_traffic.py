from datetime import timedelta

import pytest
from django.utils import timezone

from transactions import traffic
from transactions.services import ingest_scored_event


@pytest.fixture
def history(monkeypatch):
    history = traffic.TrafficHistory("xgb-test")
    monkeypatch.setattr(traffic, "current", history)
    return history


def record(history, at, flagged=False, **extra):
    history.record(at, amount=100.0, city="Delhi", score=0.9 if flagged else 0.1,
                   risk="HIGH" if flagged else "LOW", flagged=flagged, **extra)


def test_stats_include_traffic_nobody_watched(history, analyst, client_for):
    now = timezone.now()
    record(history, now - timedelta(hours=5), flagged=True)
    record(history, now, latency_ms=4.0)
    data = client_for(analyst).get("/api/transactions/stats/").data
    assert (data["total"], data["flagged"], data["flag_rate"]) == (2, 1, 0.5)
    assert (data["volume"], data["flagged_volume"], data["avg_latency_ms"]) == (200.0, 100.0, 4.0)
    assert data["by_risk_level"] == {"HIGH": 1, "LOW": 1}
    assert data["top_flagged_cities"] == [{"city": "Delhi", "n": 1}]
    assert data["background_traffic"] is True


def test_timeseries_has_no_gaps_while_unwatched(history, analyst, client_for):
    now = timezone.now()
    for minutes in range(0, 7 * 60):
        record(history, now - timedelta(minutes=minutes), flagged=minutes % 10 == 0)
    points = client_for(analyst).get("/api/transactions/timeseries/?hours=6&bucket=10").data["points"]
    assert all(p["total"] == 10 and p["flagged"] == 1 for p in points[1:-1])


def test_longer_windows_still_read_the_database(history, analyst, client_for, make_event):
    record(history, timezone.now())
    ingest_scored_event(make_event())
    ingest_scored_event(make_event())
    assert client_for(analyst).get("/api/transactions/stats/?hours=48").data["total"] == 2


def test_stats_require_login(db, history, client_for):
    assert client_for(None).get("/api/transactions/stats/").status_code == 401


def test_window_and_retention(history):
    now = timezone.now()
    record(history, now - timedelta(hours=30))
    record(history, now - timedelta(hours=3))
    record(history, now)
    assert history.stats(now, 24)["total"] == 2
    assert history.stats(now, 1)["total"] == 1
    assert len(history._minutes) == 2  # the 30-hour-old minute was dropped
