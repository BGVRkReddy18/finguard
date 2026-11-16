"""Integration check: the AI service's Postgres role must be least-privilege.

Run after migrations against a real Postgres (CI does this). Exits non-zero on any violation.
"""
import os
import sys

import psycopg

DSN = (
    f"host={os.environ.get('POSTGRES_HOST', 'localhost')} dbname={os.environ.get('POSTGRES_DB', 'finguard')} "
    f"user=finguard_ro password={os.environ.get('READONLY_DB_PASSWORD', 'finguard_ro')}"
)

ALLOWED = [
    "SELECT count(*) FROM transactions_transaction",
    "SELECT id, amount, fraud_score FROM transactions_transaction LIMIT 1",
    "SELECT count(*) FROM cases_fraudcase",
    "SELECT count(*) FROM transactions_customer",
]
FORBIDDEN = {
    "password hashes": "SELECT password FROM accounts_user LIMIT 1",
    "audit log": "SELECT count(*) FROM cases_auditlog",
    "ground-truth label": "SELECT label_is_fraud FROM transactions_transaction LIMIT 1",
    "SELECT * (includes hidden columns)": "SELECT * FROM transactions_transaction LIMIT 1",
    "write": "DELETE FROM cases_fraudcase",
    "DDL": "CREATE TABLE pwned (id int)",
    "long-running query": "SELECT pg_sleep(5)",
}

failures = []
with psycopg.connect(DSN, autocommit=True) as conn:
    for sql in ALLOWED:
        try:
            conn.execute(sql)
            print(f"  allowed  ok   {sql}")
        except psycopg.Error as exc:
            failures.append(f"should be allowed: {sql} ({exc})")
    for name, sql in FORBIDDEN.items():
        try:
            conn.execute(sql)
            failures.append(f"should be blocked: {name}")
        except psycopg.Error as exc:
            print(f"  blocked  ok   {name}: {str(exc).splitlines()[0]}")

if failures:
    print("\nFAILED:\n  " + "\n  ".join(failures))
    sys.exit(1)
print("\nRead-only role is least-privilege.")
