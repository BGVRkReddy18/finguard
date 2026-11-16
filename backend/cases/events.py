"""Domain events published to Kafka.

Events are sent with ``transaction.on_commit`` so consumers never see a case that was rolled back.
(The fully durable version of this is the transactional-outbox pattern — a natural next upgrade.)
"""
import json
import logging
from functools import lru_cache

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _producer():
    from confluent_kafka import Producer

    return Producer({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS, "enable.idempotence": True})


def publish_case_opened(case) -> None:
    if not settings.KAFKA_PUBLISH_EVENTS:
        return
    payload = {
        "event": "case.opened",
        "case_id": case.pk,
        "priority": case.priority,
        "fraud_score": case.transaction.fraud_score,
        "customer_id": case.transaction.customer.customer_id,
    }

    def send():
        try:
            producer = _producer()
            producer.produce(settings.KAFKA_CASES_TOPIC, key=str(case.pk), value=json.dumps(payload))
            producer.poll(0)
        except Exception:  # never let event publishing break ingestion
            logger.exception("Failed to publish case.opened for case %s", case.pk)

    transaction.on_commit(send)
