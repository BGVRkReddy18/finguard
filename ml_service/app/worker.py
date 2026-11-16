"""Kafka stream processor: transactions.raw -> score -> transactions.scored."""
import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.errors import KafkaConnectionError
from prometheus_client import Gauge
from pydantic import ValidationError

from .config import Settings
from .schemas import TransactionIn
from .scoring import ScoringPipeline

logger = logging.getLogger("scoring-worker")

# Messages waiting in Kafka behind this consumer: the key "are we keeping up?" signal under load
CONSUMER_LAG = Gauge("finguard_consumer_lag", "Scoring consumer lag (messages)", ["partition"])


async def _start_with_retry(client, name: str, attempts: int = 20) -> None:
    for attempt in range(1, attempts + 1):
        try:
            await client.start()
            return
        except KafkaConnectionError:
            logger.warning("Kafka %s not ready (attempt %d/%d)", name, attempt, attempts)
            await asyncio.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"Could not connect Kafka {name}")


async def run_scoring_worker(settings: Settings, pipeline: ScoringPipeline, state: dict) -> None:
    consumer = AIOKafkaConsumer(
        settings.raw_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        acks="all",
        enable_idempotence=True,
        key_serializer=lambda k: k.encode(),
        value_serializer=lambda v: json.dumps(v).encode(),
    )
    await _start_with_retry(consumer, "consumer")
    await _start_with_retry(producer, "producer")
    state["worker"] = "running"
    logger.info("Scoring worker consuming %s -> %s", settings.raw_topic, settings.scored_topic)

    try:
        async for msg in consumer:
            try:
                event = json.loads(msg.value)
                txn = TransactionIn.model_validate(event)
            except (ValueError, ValidationError) as exc:
                logger.error("Skipping invalid message at offset %s: %s", msg.offset, exc)
                await consumer.commit()
                continue

            result = await pipeline.score(txn)
            await producer.send_and_wait(
                settings.scored_topic, {**event, "score": result.model_dump()}, key=txn.customer_id
            )
            # Commit only after the scored event is safely written — at-least-once delivery
            await consumer.commit()
            highwater = consumer.highwater(TopicPartition(msg.topic, msg.partition))
            if highwater is not None:
                CONSUMER_LAG.labels(str(msg.partition)).set(max(0, highwater - msg.offset - 1))
            state["processed"] = state.get("processed", 0) + 1
    finally:
        state["worker"] = "stopped"
        await consumer.stop()
        await producer.stop()
