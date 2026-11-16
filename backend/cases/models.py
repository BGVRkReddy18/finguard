from django.conf import settings
from django.db import models


class FraudCase(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        INVESTIGATING = "INVESTIGATING", "Investigating"
        CONFIRMED_FRAUD = "CONFIRMED_FRAUD", "Confirmed fraud"
        FALSE_POSITIVE = "FALSE_POSITIVE", "False positive"

    class Priority(models.TextChoices):
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"

    RESOLVED_STATUSES = {Status.CONFIRMED_FRAUD, Status.FALSE_POSITIVE}

    transaction = models.OneToOneField(
        "transactions.Transaction", on_delete=models.PROTECT, related_name="fraud_case"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.MEDIUM)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="cases"
    )
    resolution_note = models.TextField(blank=True)

    # Filled in by the AI risk-analyst agent. Advisory only — a human always makes the final decision.
    class AIRecommendation(models.TextChoices):
        BLOCK = "BLOCK", "Block card"
        VERIFY = "VERIFY", "Verify with customer"
        APPROVE = "APPROVE", "Likely legitimate"

    ai_summary = models.TextField(blank=True)
    ai_recommendation = models.CharField(max_length=16, choices=AIRecommendation.choices, blank=True)
    ai_confidence = models.FloatField(null=True, blank=True)
    ai_evidence = models.JSONField(default=list, blank=True)
    ai_next_steps = models.JSONField(default=list, blank=True)
    ai_model = models.CharField(max_length=64, blank=True)
    ai_generated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "priority", "-created_at"])]

    @property
    def is_resolved(self) -> bool:
        return self.status in self.RESOLVED_STATUSES

    def __str__(self):
        return f"Case #{self.pk} ({self.status})"


class AuditLog(models.Model):
    """Append-only record of every action — banks need this for regulatory compliance."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=64)
    entity_id = models.CharField(max_length=64)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Audit log entries are immutable")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit log entries cannot be deleted")
