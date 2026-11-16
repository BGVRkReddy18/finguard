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


def test_prune_keeps_flagged_and_recent(make_event):
    from datetime import timedelta

    from django.core.management import call_command
    from django.utils import timezone

    old = (timezone.now() - timedelta(hours=100)).isoformat()
    ingest_scored_event(make_event(timestamp=old))                                    # old, legit -> pruned
    ingest_scored_event(make_event(timestamp=old, score=0.95, flagged=True, risk="HIGH"))  # old, flagged -> kept
    ingest_scored_event(make_event())                                                  # recent -> kept
    call_command("prune_transactions", hours=48)
    assert Transaction.objects.count() == 2
    assert Transaction.objects.filter(is_flagged=True).count() == 1
    assert FraudCase.objects.count() == 1


def test_database_url_parsing(monkeypatch):
    import importlib

    import config.settings as settings_module

    monkeypatch.setenv("DJANGO_DATABASE_URL", "postgresql://u%40x:p%2Fw@db.example.neon.tech:5433/neondb?sslmode=require")
    reloaded = importlib.reload(settings_module)
    db = reloaded.DATABASES["default"]
    parsed = (db["HOST"], db["PORT"], db["NAME"], db["USER"], db["PASSWORD"])
    assert parsed == ("db.example.neon.tech", "5433", "neondb", "u@x", "p/w")
    assert db["OPTIONS"] == {"sslmode": "require"} and db["CONN_MAX_AGE"] == 0
    monkeypatch.delenv("DJANGO_DATABASE_URL")
    importlib.reload(settings_module)
