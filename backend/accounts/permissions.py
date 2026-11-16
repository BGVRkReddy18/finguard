import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission


class IsManagerOrAdmin(BasePermission):
    """Allows access only to Risk Managers and Administrators."""

    message = "Only risk managers or administrators can perform this action."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_manager)


class HasServiceToken(BasePermission):
    """Service-to-service auth: the caller must present the shared ``X-Service-Token``."""

    message = "Invalid or missing service token."

    def has_permission(self, request, view):
        expected = settings.AI_SERVICE_TOKEN
        provided = request.headers.get("X-Service-Token", "")
        return bool(expected) and hmac.compare_digest(provided, expected)
