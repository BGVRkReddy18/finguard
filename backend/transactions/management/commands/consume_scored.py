"""Kafka consumer: reads scored transactions and persists them.

Delivery semantics: offsets are committed only AFTER the DB write succeeds (at-least-once),
and ingestion is idempotent on txn_id — together this gives effectively-once processing.
"""
import json
import logging
import signal

from confluent_kafka import Consumer, KafkaError
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from transactions.services import ingest_scored_event

logger = logging.getLogger("ingest-worker")


class Command(BaseCommand):
    help = "Consume scored transactions from Kafka and store them in PostgreSQL."

    def handle(self, *args, **options):
        consumer = Consumer(
            {
                "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                "group.id": "finguard-ingest",
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        consumer.subscribe([settings.KAFKA_SCORED_TOPIC])
        running = True

        def stop(*_):
            nonlocal running
            running = False

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        logger.info("Consuming from %s", settings.KAFKA_SCORED_TOPIC)

        stored = 0
        try:
            while running:
                msg = consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        logger.error("Kafka error: %s", msg.error())
                    continue

                close_old_connections()
                try:
                    event = json.loads(msg.value())
                    _, created = ingest_scored_event(event)
                except (ValueError, KeyError, TypeError) as exc:
                    # Malformed message: log and skip so one bad event can't block the partition.
                    # (A dead-letter topic is the production-grade upgrade.)
                    logger.exception("Skipping bad message at offset %s: %s", msg.offset(), exc)
                    created = False

                consumer.commit(message=msg, asynchronous=False)
                if created:
                    stored += 1
                    if stored % 100 == 0:
                        logger.info("Stored %d transactions", stored)
        finally:
            consumer.close()
            logger.info("Consumer closed")
