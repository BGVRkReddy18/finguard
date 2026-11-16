"""Live transaction stream -> Kafka (wall-clock time). See generator.py for the data model."""
import heapq
import itertools
import json
import logging
import os
import random
import time
from datetime import datetime, timezone

from confluent_kafka import Producer

from generator import make_customers, next_events

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s simulator: %(message)s")
log = logging.getLogger()


def main() -> None:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092")
    topic = os.environ.get("RAW_TOPIC", "transactions.raw")
    tps = float(os.environ.get("TPS", 5))
    fraud_rate = float(os.environ.get("FRAUD_RATE", 0.01))
    seed = int(os.environ.get("SEED", 42))
    customers = make_customers(int(os.environ.get("NUM_CUSTOMERS", 5000)), seed)
    rng = random.Random()  # live events are not reproducible on purpose (different from the history)

    producer = Producer({"bootstrap.servers": bootstrap, "enable.idempotence": True, "linger.ms": 5})
    log.info("Streaming to %s at %.1f TPS (%d customers, fraud rate %.1f%%)", topic, tps, len(customers), fraud_rate * 100)

    pending: list[tuple[float, int, dict]] = []  # (due_unix_time, tiebreak, txn) — delayed events in a heap
    counter = itertools.count()
    sent, interval = 0, 1.0 / tps
    while True:
        now = time.time()
        for delay, txn in next_events(customers, rng, datetime.now(timezone.utc), fraud_rate):
            heapq.heappush(pending, (now + delay, next(counter), txn))

        while pending and pending[0][0] <= now:
            _, _, txn = heapq.heappop(pending)
            txn["timestamp"] = datetime.now(timezone.utc).isoformat()
            # Key by customer: all of a customer's events land on one partition, preserving order
            producer.produce(topic, key=txn["customer_id"], value=json.dumps(txn))
            sent += 1
            if sent % 500 == 0:
                log.info("Sent %d transactions", sent)
        producer.poll(0)
        time.sleep(interval)


if __name__ == "__main__":
    main()
