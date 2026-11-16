from rest_framework import serializers

from .models import Transaction


class TransactionSerializer(serializers.ModelSerializer):
    customer_id = serializers.CharField(source="customer.customer_id", read_only=True)
    case_id = serializers.IntegerField(source="fraud_case.id", read_only=True, default=None)

    class Meta:
        model = Transaction
        exclude = ["customer"]
