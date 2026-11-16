"""Validate LLM-generated SQL before it touches the database.

Defence in depth for text-to-SQL:
  1. This guard (parse with sqlglot, allow-list the AST)  <- here
  2. Read-only transaction
  3. Least-privilege Postgres role: SELECT on 3 tables, ground-truth columns hidden, 3 s timeout
"""
import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {"transactions_transaction", "transactions_customer", "cases_fraudcase"}
MAX_ROWS = 200
FORBIDDEN_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink")
FORBIDDEN_FUNCTIONS = {"set_config", "current_setting", "query_to_xml", "version", "inet_server_addr"}
# Resolved by name so the guard works across sqlglot versions (some node types are newer)
FORBIDDEN_NODES = tuple(getattr(exp, name) for name in (
    "Insert", "Update", "Delete", "Drop", "Create", "Alter", "Command", "Merge", "TruncateTable", "Grant", "Into",
    "Copy", "Set", "Lock",
) if hasattr(exp, name))


class UnsafeSQLError(ValueError):
    pass


def validate_sql(sql: str) -> str:
    """Return a safe, LIMIT-ed version of ``sql`` or raise UnsafeSQLError."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise UnsafeSQLError(f"Could not parse SQL: {exc}") from exc
    if len(statements) != 1:
        raise UnsafeSQLError("Exactly one statement is allowed")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union)):
        raise UnsafeSQLError("Only SELECT queries are allowed")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise UnsafeSQLError(f"Forbidden operation: {node.key}")
        if isinstance(node, exp.Func):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if name.startswith(FORBIDDEN_FUNCTION_PREFIXES) or name in FORBIDDEN_FUNCTIONS:
                raise UnsafeSQLError(f"Function not allowed: {name}")

    cte_names = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    tables = {t.name for t in tree.find_all(exp.Table)} - cte_names
    if not tables:
        raise UnsafeSQLError("Query must read from at least one table")
    if disallowed := tables - ALLOWED_TABLES:
        raise UnsafeSQLError(f"Table(s) not allowed: {', '.join(sorted(disallowed))}")

    limit = tree.args.get("limit")
    if limit is None or not isinstance(limit.expression, exp.Literal) or int(limit.expression.this) > MAX_ROWS:
        tree = tree.limit(MAX_ROWS)
    return tree.sql(dialect="postgres")
