from django.db import transaction as db_transaction
from django.utils import timezone

from .models import AuditLog, FraudCase


class CaseError(Exception):
    """Raised for invalid case-workflow operations (mapped to HTTP 400)."""


def log_action(actor, action: str, entity, details: dict | None = None) -> AuditLog:
    return AuditLog.objects.create(
        actor=actor if (actor and actor.is_authenticated) else None,
        action=action,
        entity_type=entity._meta.label,
        entity_id=str(entity.pk),
        details=details or {},
    )


@db_transaction.atomic
def assign_case(case: FraudCase, assignee, actor) -> FraudCase:
    if case.is_resolved:
        raise CaseError("Cannot assign a resolved case.")
    case.assigned_to = assignee
    if case.status == FraudCase.Status.OPEN:
        case.status = FraudCase.Status.INVESTIGATING
    case.save(update_fields=["assigned_to", "status", "updated_at"])
    log_action(actor, "case.assigned", case, {"assignee": assignee.username})
    return case


@db_transaction.atomic
def resolve_case(case: FraudCase, status: str, note: str, actor) -> FraudCase:
    if status not in FraudCase.RESOLVED_STATUSES:
        raise CaseError(f"Status must be one of {sorted(FraudCase.RESOLVED_STATUSES)}.")
    if case.is_resolved:
        raise CaseError("Case is already resolved.")
    case.status = status
    case.resolution_note = note
    case.resolved_at = timezone.now()
    case.save(update_fields=["status", "resolution_note", "resolved_at", "updated_at"])
    log_action(actor, "case.resolved", case, {"status": status, "note": note})
    return case


@db_transaction.atomic
def attach_ai_report(case: FraudCase, report: dict) -> FraudCase:
    case.ai_recommendation = report["recommendation"]
    case.ai_confidence = report["confidence"]
    case.ai_summary = report["summary"]
    case.ai_evidence = report["key_evidence"]
    case.ai_next_steps = report["next_steps"]
    case.ai_model = report["model"]
    case.ai_generated_at = timezone.now()
    case.save(update_fields=["ai_recommendation", "ai_confidence", "ai_summary", "ai_evidence", "ai_next_steps",
                             "ai_model", "ai_generated_at", "updated_at"])
    log_action(None, "case.ai_report", case,
               {"model": report["model"], "recommendation": report["recommendation"], "confidence": report["confidence"]})
    return case
