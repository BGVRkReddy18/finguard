"""Least-privilege Postgres role for the AI service.

The AI service runs LLM-generated SQL, so it connects as ``finguard_ro``, which:
  * can only SELECT, and only from transaction / customer / case tables — NOT accounts_user
    (password hashes) or the audit log, and not the ground-truth label columns;
  * is read-only at the session level and has a 3-second statement timeout.
SQL validation in the AI service is the first defence; this role is the second.
"""
from django.conf import settings
from django.db import migrations

ROLE = "finguard_ro"
READABLE_TABLES = ["transactions_customer", "cases_fraudcase"]
# Column-level grant: the simulator's ground-truth columns (label_is_fraud, fraud_pattern) are
# hidden from the AI service, so the agent can't "cheat" and analytics only see real-world data.
TRANSACTION_COLUMNS = [
    "id", "txn_id", "customer_id", "amount", "currency", "merchant", "merchant_category", "city", "lat", "lon",
    "channel", "timestamp", "fraud_score", "risk_level", "is_flagged", "reasons", "features", "model_version",
    "scoring_latency_ms", "created_at",
]


def create_role(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return  # SQLite (unit tests) has no roles
    password = settings.READONLY_DB_PASSWORD.replace("'", "''")
    db_name = schema_editor.connection.settings_dict["NAME"]
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN
                    CREATE ROLE {ROLE} LOGIN PASSWORD '{password}';
                END IF;
            END $$;
            """
        )
        cursor.execute(f'GRANT CONNECT ON DATABASE "{db_name}" TO {ROLE}')
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
        cursor.execute(f"GRANT SELECT ON {', '.join(READABLE_TABLES)} TO {ROLE}")
        cursor.execute(f"GRANT SELECT ({', '.join(TRANSACTION_COLUMNS)}) ON transactions_transaction TO {ROLE}")
        cursor.execute(f"ALTER ROLE {ROLE} SET default_transaction_read_only = on")
        cursor.execute(f"ALTER ROLE {ROLE} SET statement_timeout = '3s'")


def drop_role(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP OWNED BY {ROLE}")
        cursor.execute(f"DROP ROLE IF EXISTS {ROLE}")


class Migration(migrations.Migration):
    dependencies = [
        ("cases", "0002_ai_report_fields"),
        ("transactions", "0001_initial"),
    ]

    operations = [migrations.RunPython(create_role, drop_role)]
