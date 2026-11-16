import pytest

from app.sql_guard import MAX_ROWS, UnsafeSQLError, validate_sql


@pytest.mark.parametrize("sql", [
    "SELECT city, count(*) AS n FROM transactions_transaction WHERE is_flagged GROUP BY city",
    "SELECT c.status, count(*) FROM cases_fraudcase c JOIN transactions_transaction t ON t.id = c.transaction_id GROUP BY 1",
    "WITH f AS (SELECT city FROM transactions_transaction WHERE is_flagged) SELECT city, count(*) FROM f GROUP BY city",
    "SELECT date_trunc('hour', timestamp) AS h, avg(fraud_score) FROM transactions_transaction GROUP BY 1 ORDER BY 1",
])
def test_allows_safe_analytics_queries(sql):
    assert "LIMIT" in validate_sql(sql).upper()


@pytest.mark.parametrize("sql,why", [
    ("DELETE FROM transactions_transaction", "write"),
    ("UPDATE cases_fraudcase SET status = 'FALSE_POSITIVE'", "write"),
    ("DROP TABLE cases_fraudcase", "ddl"),
    ("SELECT 1; DROP TABLE cases_fraudcase", "stacked statements"),
    ("SELECT username, password FROM accounts_user", "table not allowed (password hashes)"),
    ("SELECT * FROM cases_auditlog", "table not allowed"),
    ("SELECT pg_sleep(10) FROM transactions_transaction", "dangerous function"),
    ("SELECT pg_read_file('/etc/passwd')", "dangerous function"),
    ("SELECT set_config('statement_timeout', '0', false) FROM cases_fraudcase", "settings tampering"),
    ("SELECT city INTO stolen FROM transactions_transaction", "select into"),
    ("SELECT 1", "no table"),
    ("this is not sql at all )(", "unparseable"),
])
def test_rejects_unsafe_queries(sql, why):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


def test_caps_large_limits():
    sql = validate_sql("SELECT amount FROM transactions_transaction LIMIT 100000")
    assert f"LIMIT {MAX_ROWS}" in sql


def test_keeps_small_limits():
    assert "LIMIT 5" in validate_sql("SELECT amount FROM transactions_transaction ORDER BY amount DESC LIMIT 5")
