"""Real-time fan-out to dashboards over WebSockets.

Kafka (transactions.scored, cases.opened) -> Broadcaster -> one bounded queue per connected browser.
A slow client only drops its *own* oldest messages; it can never stall the stream for others.
Every instance reads all partitions without a consumer group, so each dashboard sees every event.
"""
import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError

from .config import Settings
from .metrics import WS_DROPPED

logger = logging.getLogger("realtime")
QUEUE_SIZE = 500


class Broadcaster:
    def __init__(self):
        self.queues: set[asyncio.Queue[str]] = set()
        self.dropped = 0

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self.queues.discard(queue)

    def publish(self, message: dict) -> None:
        data = json.dumps(message, default=str)
        for queue in self.queues:
            if queue.full():  # slow consumer: drop its oldest message rather than block everyone
                queue.get_nowait()
                self.dropped += 1
                WS_DROPPED.inc()
            queue.put_nowait(data)


def slim_transaction(event: dict) -> dict:
    """Only what the live feed needs — never the simulator's ground-truth fields."""
    score = event.get("score", {})
    return {
        "type": "txn",
        "txn_id": event["txn_id"],
        "customer_id": event["customer_id"],
        "amount": event["amount"],
        "merchant": event["merchant"],
        "merchant_category": event["merchant_category"],
        "city": event["city"],
        "channel": event["channel"],
        "timestamp": event["timestamp"],
        "fraud_score": score.get("fraud_score"),
        "risk_level": score.get("risk_level"),
        "is_flagged": score.get("is_flagged"),
        "reasons": score.get("reasons", []) if score.get("is_flagged") else [],
    }


async def run_fanout(settings: Settings, broadcaster: Broadcaster, state: dict) -> None:
    consumer = AIOKafkaConsumer(
        "transactions.scored", settings.cases_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=None, auto_offset_reset="latest", enable_auto_commit=False,
    )
    for attempt in range(1, 21):
        try:
            await consumer.start()
            break
        except KafkaConnectionError:
            await asyncio.sleep(min(2 * attempt, 10))
    else:
        raise RuntimeError("Could not connect to Kafka")
    state["realtime"] = "running"
    try:
        async for msg in consumer:
            try:
                event = json.loads(msg.value)
                if msg.topic == settings.cases_topic:
                    broadcaster.publish({"type": "case_opened", **{k: event.get(k) for k in
                                                                   ("case_id", "priority", "fraud_score", "customer_id")}})
                else:
                    broadcaster.publish(slim_transaction(event))
            except (ValueError, KeyError) as exc:
                logger.warning("Skipping malformed event on %s: %s", msg.topic, exc)
    finally:
        state["realtime"] = "stopped"
        await consumer.stop()
