"""Tools the risk-analyst agent can call. Each is a fixed, parameterised, read-only query —
the LLM chooses *which* tool to call, never writes SQL here."""
import json
from typing import Any

from .db import Database

CASE_SQL = """
SELECT c.id AS case_id, c.status, c.priority, c.created_at,
       t.amount, t.currency, t.merchant, t.merchant_category, t.city, t.channel, t.timestamp,
       t.fraud_score, t.reasons, t.features, t.model_version,
       cu.customer_id, cu.name AS customer_name, cu.home_city
FROM cases_fraudcase c
JOIN transactions_transaction t ON t.id = c.transaction_id
JOIN transactions_customer cu ON cu.id = t.customer_id
WHERE c.id = %s
"""

PROFILE_SQL = """
SELECT count(*) AS transactions, round(avg(t.amount), 2) AS avg_amount,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY t.amount) AS median_amount,
       max(t.amount) AS max_amount, min(t.timestamp) AS first_seen,
       count(*) FILTER (WHERE t.is_flagged) AS flagged_transactions
FROM transactions_transaction t JOIN transactions_customer cu ON cu.id = t.customer_id
WHERE cu.customer_id = %s
"""

BREAKDOWN_SQL = """
SELECT {column} AS value, count(*) AS n
FROM transactions_transaction t JOIN transactions_customer cu ON cu.id = t.customer_id
WHERE cu.customer_id = %s GROUP BY {column} ORDER BY n DESC LIMIT 5
"""

RECENT_SQL = """
SELECT t.timestamp, t.amount, t.merchant, t.merchant_category, t.city, t.channel,
       round(t.fraud_score::numeric, 3) AS fraud_score, t.is_flagged
FROM transactions_transaction t JOIN transactions_customer cu ON cu.id = t.customer_id
WHERE cu.customer_id = %s ORDER BY t.timestamp DESC LIMIT %s
"""

PAST_CASES_SQL = """
SELECT c.id AS case_id, c.status, c.priority, c.resolution_note, c.created_at, t.amount, t.city
FROM cases_fraudcase c
JOIN transactions_transaction t ON t.id = c.transaction_id
JOIN transactions_customer cu ON cu.id = t.customer_id
WHERE cu.customer_id = %s AND c.id <> %s ORDER BY c.created_at DESC LIMIT 10
"""

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "get_customer_profile",
            "description": "Spending statistics for a customer: transaction count, average/median/max amount, "
                           "most frequent cities, categories and channels.",
            "parameters": {
                "type": "object",
                "properties": {"customer_id": {"type": "string"}},
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_transactions",
            "description": "The customer's most recent transactions, newest first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_past_cases",
            "description": "Previous fraud cases for this customer and how analysts resolved them.",
            "parameters": {
                "type": "object",
                "properties": {"customer_id": {"type": "string"}},
                "required": ["customer_id"],
            },
        },
    },
]


class Toolbox:
    """Tools are bound to one case: the agent may only look up that case's customer."""

    def __init__(self, db: Database):
        self.db = db
        self.case_id: int | None = None
        self.customer_id: str | None = None

    def bind(self, case_id: int, customer_id: str) -> None:
        self.case_id, self.customer_id = case_id, customer_id

    async def get_case(self, case_id: int) -> dict[str, Any] | None:
        rows = await self.db.fetch(CASE_SQL, (case_id,))
        return rows[0] if rows else None

    async def get_customer_profile(self, customer_id: str) -> dict[str, Any]:
        profile = (await self.db.fetch(PROFILE_SQL, (customer_id,)))[0]
        for column in ("city", "merchant_category", "channel"):
            profile[f"top_{column}"] = await self.db.fetch(BREAKDOWN_SQL.format(column=f"t.{column}"), (customer_id,))
        return profile

    async def get_recent_transactions(self, customer_id: str, limit: int = 10) -> list[dict[str, Any]]:
        return await self.db.fetch(RECENT_SQL, (customer_id, max(1, min(int(limit), 20))))

    async def get_past_cases(self, customer_id: str) -> list[dict[str, Any]]:
        return await self.db.fetch(PAST_CASES_SQL, (customer_id, self.case_id or 0))

    async def call(self, name: str, arguments: str) -> str:
        """Dispatch a model tool call. Errors are returned to the model as data, not raised."""
        handlers = {
            "get_customer_profile": self.get_customer_profile,
            "get_recent_transactions": self.get_recent_transactions,
            "get_past_cases": self.get_past_cases,
        }
        if name not in handlers:
            return json.dumps({"error": f"unknown tool {name}"})
        try:
            args = json.loads(arguments or "{}")
            if args.get("customer_id") != self.customer_id:
                return json.dumps({"error": "you may only query the customer of the case under investigation"})
            result = await handlers[name](**args)
        except (TypeError, ValueError) as exc:
            return json.dumps({"error": f"bad arguments: {exc}"})
        return json.dumps(result, default=str)[:6000]  # cap context usage
