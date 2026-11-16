import pytest

from cases.models import AuditLog, FraudCase
from transactions.models import Transaction
from transactions.services import ingest_scored_event

pytestmark = pytest.mark.django_db


def test_legit_transaction_is_stored_without_case(make_event):
    txn, created = ingest_scored_event(make_event())
    assert created
    assert not txn.is_flagged
    assert FraudCase.objects.count() == 0


def test_flagged_transaction_opens_case_and_audit_entry(make_event):
    txn, _ = ingest_scored_event(make_event(score=0.92, flagged=True, risk="HIGH"))
    case = FraudCase.objects.get(transaction=txn)
    assert case.priority == FraudCase.Priority.HIGH
    assert case.status == FraudCase.Status.OPEN
    assert AuditLog.objects.filter(action="case.opened", entity_id=str(case.pk)).exists()


def test_ingest_is_idempotent(make_event):
    event = make_event(score=0.75, flagged=True, risk="MEDIUM")
    ingest_scored_event(event)
    _, created = ingest_scored_event(event)  # Kafka redelivery
    assert not created
    assert Transaction.objects.count() == 1
    assert FraudCase.objects.count() == 1


def test_audit_log_is_immutable(make_event):
    ingest_scored_event(make_event(score=0.9, flagged=True, risk="HIGH"))
    entry = AuditLog.objects.first()
    entry.action = "tampered"
    with pytest.raises(ValueError):
        entry.save()
    with pytest.raises(ValueError):
        entry.delete()
