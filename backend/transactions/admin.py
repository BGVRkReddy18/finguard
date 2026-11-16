from django.contrib import admin

from .models import Customer, Transaction


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["customer_id", "name", "home_city", "created_at"]
    search_fields = ["customer_id", "name"]


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ["txn_id", "customer", "amount", "city", "channel", "fraud_score", "risk_level", "is_flagged", "timestamp"]
    list_filter = ["is_flagged", "risk_level", "channel"]
    search_fields = ["txn_id", "customer__customer_id", "merchant"]
    raw_id_fields = ["customer"]
