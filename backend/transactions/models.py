from django.db import models


class Customer(models.Model):
    customer_id = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120, blank=True)
    home_city = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.customer_id


class Transaction(models.Model):
    class Channel(models.TextChoices):
        POS = "POS", "Point of Sale"
        ONLINE = "ONLINE", "Online"
        ATM = "ATM", "ATM"

    class RiskLevel(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"

    txn_id = models.UUIDField(unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="transactions")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    merchant = models.CharField(max_length=120)
    merchant_category = models.CharField(max_length=64)
    city = models.CharField(max_length=64)
    lat = models.FloatField()
    lon = models.FloatField()
    channel = models.CharField(max_length=8, choices=Channel.choices)
    timestamp = models.DateTimeField()

    # Filled in by the ML scoring service
    fraud_score = models.FloatField()
    risk_level = models.CharField(max_length=8, choices=RiskLevel.choices)
    is_flagged = models.BooleanField(default=False)
    reasons = models.JSONField(default=list, blank=True)
    features = models.JSONField(default=dict, blank=True)
    model_version = models.CharField(max_length=32)
    scoring_latency_ms = models.FloatField(null=True)

    # Ground truth from the simulator — used ONLY for offline model evaluation, never for scoring
    label_is_fraud = models.BooleanField(null=True)
    fraud_pattern = models.CharField(max_length=32, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["-timestamp"]),
            models.Index(fields=["is_flagged", "-timestamp"]),
            models.Index(fields=["customer", "-timestamp"]),
        ]

    def __str__(self):
        return f"{self.txn_id} {self.amount} {self.currency}"
