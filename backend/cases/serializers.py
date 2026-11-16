from rest_framework import serializers

from accounts.serializers import UserSerializer
from transactions.serializers import TransactionSerializer

from .models import AuditLog, FraudCase


class FraudCaseSerializer(serializers.ModelSerializer):
    transaction = TransactionSerializer(read_only=True)
    assigned_to = UserSerializer(read_only=True)

    class Meta:
        model = FraudCase
        fields = "__all__"
        read_only_fields = [f.name for f in FraudCase._meta.fields]


class AssignSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=False, help_text="Omit to assign the case to yourself.")


class ResolveSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=sorted(FraudCase.RESOLVED_STATUSES))
    note = serializers.CharField(allow_blank=True, default="")


class AIReportSerializer(serializers.Serializer):
    recommendation = serializers.ChoiceField(choices=FraudCase.AIRecommendation.choices)
    confidence = serializers.FloatField(min_value=0, max_value=1)
    summary = serializers.CharField(max_length=4000)
    key_evidence = serializers.ListField(child=serializers.CharField(max_length=500), max_length=10)
    next_steps = serializers.ListField(child=serializers.CharField(max_length=500), max_length=10)
    model = serializers.CharField(max_length=64)


class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.username", default="system", read_only=True)

    class Meta:
        model = AuditLog
        fields = "__all__"
