"""Measure live detection quality per model version, using the simulator's ground-truth labels.

In production, labels arrive later (chargebacks, analyst decisions); here the simulator provides
them immediately, so we can monitor the model the way a bank's model-risk team would.
"""
from django.core.management.base import BaseCommand
from django.db.models import Count, Q, Sum

from transactions.models import Transaction


class Command(BaseCommand):
    help = "Print live precision / recall / fraud amount caught per model version."

    def handle(self, *args, **options):
        labelled = Transaction.objects.exclude(label_is_fraud=None)
        for version in labelled.values_list("model_version", flat=True).distinct().order_by("model_version"):
            qs = labelled.filter(model_version=version)
            s = qs.aggregate(
                total=Count("id"),
                tp=Count("id", filter=Q(is_flagged=True, label_is_fraud=True)),
                fp=Count("id", filter=Q(is_flagged=True, label_is_fraud=False)),
                fn=Count("id", filter=Q(is_flagged=False, label_is_fraud=True)),
                fraud_amt=Sum("amount", filter=Q(label_is_fraud=True)),
                caught_amt=Sum("amount", filter=Q(is_flagged=True, label_is_fraud=True)),
            )
            legit = s["total"] - s["tp"] - s["fn"]
            precision = s["tp"] / max(s["tp"] + s["fp"], 1)
            recall = s["tp"] / max(s["tp"] + s["fn"], 1)
            amount_caught = float(s["caught_amt"] or 0) / float(s["fraud_amt"] or 1)
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{version}  ({s['total']:,} transactions)"))
            self.stdout.write(
                f"  precision {precision:.3f} | recall {recall:.3f} | fraud amount caught {amount_caught:.3f} | "
                f"false alerts / 1k legit {1000 * s['fp'] / max(legit, 1):.1f}"
            )
            patterns = (
                qs.filter(label_is_fraud=True)
                .values("fraud_pattern")
                .annotate(n=Count("id"), caught=Count("id", filter=Q(is_flagged=True)))
                .order_by("fraud_pattern")
            )
            for p in patterns:
                self.stdout.write(f"    {p['fraud_pattern']:<20} recall {p['caught'] / p['n']:.3f}  (n={p['n']})")
