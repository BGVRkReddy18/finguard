"""Data retention for long-running demos: delete old *unflagged* transactions.

Flagged transactions are kept (their fraud cases and audit trail reference them), so the case
history stays intact while the bulk of routine traffic is trimmed.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from transactions.models import Transaction


class Command(BaseCommand):
    help = "Delete unflagged transactions older than --hours (default 48)."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=48)

    def handle(self, *args, hours, **options):
        cutoff = timezone.now() - timedelta(hours=hours)
        deleted, _ = Transaction.objects.filter(timestamp__lt=cutoff, is_flagged=False, fraud_case__isnull=True).delete()
        self.stdout.write(f"Pruned {deleted} transactions older than {hours}h")
