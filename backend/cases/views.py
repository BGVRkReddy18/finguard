from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import HasServiceToken, IsManagerOrAdmin

from .models import AuditLog, FraudCase
from .serializers import (
    AIReportSerializer,
    AssignSerializer,
    AuditLogSerializer,
    FraudCaseSerializer,
    ResolveSerializer,
)
from .services import CaseError, assign_case, attach_ai_report, resolve_case


class FraudCaseViewSet(viewsets.ReadOnlyModelViewSet):
    """Case queue. Analysts can claim and resolve their own cases; managers can assign and resolve any."""

    serializer_class = FraudCaseSerializer
    queryset = FraudCase.objects.select_related("transaction__customer", "assigned_to")
    filterset_fields = ["status", "priority", "assigned_to"]
    ordering_fields = ["created_at", "priority", "transaction__fraud_score"]

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        case = self.get_object()
        data = AssignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user_id = data.validated_data.get("user_id")

        if user_id is None or user_id == request.user.id:
            assignee = request.user
        elif request.user.is_manager:
            assignee = get_object_or_404(User, pk=user_id, is_active=True)
        else:
            raise PermissionDenied("Analysts can only assign cases to themselves.")

        try:
            assign_case(case, assignee, request.user)
        except CaseError as exc:
            raise ValidationError(str(exc)) from exc
        return Response(FraudCaseSerializer(case).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        case = self.get_object()
        if not request.user.is_manager and case.assigned_to_id != request.user.id:
            raise PermissionDenied("You can only resolve cases assigned to you.")
        data = ResolveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            resolve_case(case, data.validated_data["status"], data.validated_data["note"], request.user)
        except CaseError as exc:
            raise ValidationError(str(exc)) from exc
        return Response(FraudCaseSerializer(case).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="ai-report",
            authentication_classes=[], permission_classes=[HasServiceToken], throttle_classes=[])
    def ai_report(self, request, pk=None):
        """Called by the AI service (service token, not a user) to attach its investigation report."""
        case = get_object_or_404(FraudCase, pk=pk)
        data = AIReportSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        attach_ai_report(case, data.validated_data)
        return Response(FraudCaseSerializer(case).data)


class AuditLogViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsManagerOrAdmin]
    queryset = AuditLog.objects.select_related("actor")
    filterset_fields = ["action", "entity_type", "entity_id", "actor"]
