"""Load test for the real-time scoring API.

    locust -f locustfile.py --host http://ml-service:8001 --headless -u 64 -r 16 -t 60s

Uses dedicated LT* customer IDs so real customer profiles in the feature store are not touched
(clean up afterwards: redis-cli --scan --pattern 'cust:LT*' | xargs redis-cli del).
"""
import os
import random
import uuid
from datetime import UTC, datetime

from locust import FastHttpUser, constant, constant_throughput, task

CITIES = [("Hyderabad", 17.385, 78.4867), ("Mumbai", 19.076, 72.8777), ("Delhi", 28.6139, 77.209),
          ("Bengaluru", 12.9716, 77.5946), ("Chennai", 13.0827, 80.2707)]
CATEGORIES = ["grocery", "restaurants", "fuel", "electronics", "fashion", "gift_cards"]


class ScoringClient(FastHttpUser):
    # Default: closed loop (each user fires as soon as the last request returns) -> finds max throughput.
    # RPS_PER_USER=N: fixed request rate per user -> measures latency at a steady, realistic load.
    rps_per_user = float(os.environ.get("RPS_PER_USER", 0))
    wait_time = constant_throughput(rps_per_user) if rps_per_user else constant(0)

    @task
    def score(self):
        city, lat, lon = random.choice(CITIES)
        self.client.post("/score", json={
            "txn_id": str(uuid.uuid4()),
            "customer_id": f"LT{random.randint(0, 4999):05d}",
            "amount": round(random.lognormvariate(7, 0.8), 2),
            "merchant": "LoadTest",
            "merchant_category": random.choice(CATEGORIES),
            "city": city, "lat": lat, "lon": lon,
            "channel": random.choice(["POS", "ONLINE", "ATM"]),
            "timestamp": datetime.now(UTC).isoformat(),
        }, name="POST /score")
