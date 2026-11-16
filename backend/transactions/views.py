from datetime import datetime, timedelta, timezone as dt_timezone

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncMinute
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from cases.models import FraudCase

from .models import Transaction
from .serializers import TransactionSerializer


def int_param(request, name: str, default: int, lo: int, hi: int) -> int:
    """Parse an integer query param, clamped to [lo, hi]; bad input falls back to the default."""
    try:
        value = int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(value, hi))


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TransactionSerializer
    queryset = Transaction.objects.select_related("customer", "fraud_case")
    filterset_fields = ["is_flagged", "risk_level", "channel", "city", "merchant_category", "customer__customer_id"]
    ordering_fields = ["timestamp", "amount", "fraud_score"]

    @action(detail=False)
    def stats(self, request):
        """Dashboard KPIs for the last N hours (default 24)."""
        hours = int_param(request, "hours", 24, 1, 24 * 30)
        since = timezone.now() - timedelta(hours=hours)
        qs = Transaction.objects.filter(timestamp__gte=since)

        totals = qs.aggregate(
            total=Count("id"),
            flagged=Count("id", filter=Q(is_flagged=True)),
            volume=Sum("amount"),
            flagged_volume=Sum("amount", filter=Q(is_flagged=True)),
            avg_score=Avg("fraud_score"),
            avg_latency_ms=Avg("scoring_latency_ms"),
        )
        total = totals["total"] or 0
        by_risk = dict(qs.values_list("risk_level").annotate(n=Count("id")))
        top_cities = list(
            qs.filter(is_flagged=True).values("city").annotate(n=Count("id")).order_by("-n")[:5]
        )
        cases = dict(FraudCase.objects.values_list("status").annotate(n=Count("id")))
        latest_model = qs.order_by("-timestamp").values_list("model_version", flat=True).first()
        return Response(
            {
                "window_hours": hours,
                **totals,
                "flag_rate": (totals["flagged"] / total) if total else 0.0,
                "by_risk_level": by_risk,
                "top_flagged_cities": top_cities,
                "cases_by_status": cases,
                "model_version": latest_model,
            }
        )

    @action(detail=False)
    def timeseries(self, request):
        """Transactions and alerts per bucket — feeds the throughput charts. Empty buckets are zero-filled."""
        hours = int_param(request, "hours", 6, 1, 72)
        bucket_minutes = int_param(request, "bucket", 10, 1, 60)
        bucket_s = bucket_minutes * 60
        now = timezone.now()
        start = int((now - timedelta(hours=hours)).timestamp()) // bucket_s * bucket_s

        per_minute = (
            Transaction.objects.filter(timestamp__gte=datetime.fromtimestamp(start, tz=dt_timezone.utc))
            .annotate(minute=TruncMinute("timestamp"))
            .values("minute")
            .annotate(total=Count("id"), flagged=Count("id", filter=Q(is_flagged=True)))
        )
        buckets = {t: {"total": 0, "flagged": 0} for t in range(start, int(now.timestamp()) + 1, bucket_s)}
        for row in per_minute:
            key = int(row["minute"].timestamp()) // bucket_s * bucket_s
            if key in buckets:
                buckets[key]["total"] += row["total"]
                buckets[key]["flagged"] += row["flagged"]
        points = [
            {"t": datetime.fromtimestamp(t, tz=dt_timezone.utc).isoformat(), **v}
            for t, v in sorted(buckets.items())
        ]
        return Response({"bucket_minutes": bucket_minutes, "points": points})
