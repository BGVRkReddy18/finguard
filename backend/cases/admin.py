from django.contrib import admin

from .models import AuditLog, FraudCase


@admin.register(FraudCase)
class FraudCaseAdmin(admin.ModelAdmin):
    list_display = ["id", "transaction", "status", "priority", "assigned_to", "created_at"]
    list_filter = ["status", "priority"]
    raw_id_fields = ["transaction", "assigned_to"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor", "action", "entity_type", "entity_id"]
    list_filter = ["action", "entity_type"]

    # Audit logs are read-only, even for admins
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
