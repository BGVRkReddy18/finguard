"""Business logic for ingesting scored transactions. Kept out of views/commands so it is easy to test."""
import logging
from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils.dateparse import parse_datetime

from cases.events import publish_case_opened
from cases.models import FraudCase
from cases.services import log_action

from .models import Customer, Transaction

logger = logging.getLogger(__name__)


@db_transaction.atomic
def ingest_scored_event(event: dict) -> tuple[Transaction, bool]:
    """Persist one scored transaction and open a fraud case if it was flagged.

    Idempotent on ``txn_id``: Kafka gives at-least-once delivery, so the same event can arrive twice.
    Returns ``(transaction, created)``.
    """
    existing = Transaction.objects.filter(txn_id=event["txn_id"]).first()
    if existing:
        return existing, False

    customer, _ = Customer.objects.get_or_create(
        customer_id=event["customer_id"],
        defaults={"name": event.get("customer_name", ""), "home_city": event.get("home_city", "")},
    )
    score = event["score"]
    txn = Transaction.objects.create(
        txn_id=event["txn_id"],
        customer=customer,
        amount=Decimal(str(event["amount"])),
        currency=event.get("currency", "INR"),
        merchant=event["merchant"],
        merchant_category=event["merchant_category"],
        city=event["city"],
        lat=event["lat"],
        lon=event["lon"],
        channel=event["channel"],
        timestamp=parse_datetime(event["timestamp"]),
        fraud_score=score["fraud_score"],
        risk_level=score["risk_level"],
        is_flagged=score["is_flagged"],
        reasons=score.get("reasons", []),
        features=score.get("features", {}),
        model_version=score["model_version"],
        scoring_latency_ms=score.get("latency_ms"),
        label_is_fraud=event.get("label_is_fraud"),
        fraud_pattern=event.get("fraud_pattern", ""),
    )

    if txn.is_flagged:
        priority = (
            FraudCase.Priority.HIGH if txn.risk_level == txn.RiskLevel.HIGH else FraudCase.Priority.MEDIUM
        )
        case = FraudCase.objects.create(transaction=txn, priority=priority)
        log_action(None, "case.opened", case, {"fraud_score": txn.fraud_score, "reasons": txn.reasons})
        publish_case_opened(case)

    return txn, True
