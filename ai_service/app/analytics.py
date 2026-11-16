"""Natural-language analytics: question -> SQL (LLM) -> guard -> read-only execution -> answer (LLM)."""
import json
import logging
from typing import Any, Literal

from openai import APIError, RateLimitError
from pydantic import BaseModel

from .db import Database
from .llm import LLMClient
from .sql_guard import UnsafeSQLError, validate_sql

logger = logging.getLogger(__name__)

SCHEMA = """PostgreSQL tables (amounts in INR, timestamps are timestamptz in UTC; India is UTC+5:30):

transactions_transaction(id, txn_id, customer_id -> transactions_customer.id, amount numeric, currency,
  merchant, merchant_category  -- grocery|restaurants|fuel|electronics|fashion|travel|jewellery|gift_cards|utilities
  city, lat, lon, channel  -- POS|ONLINE|ATM
  timestamp, fraud_score float 0-1, risk_level  -- LOW|MEDIUM|HIGH
  is_flagged bool, reasons jsonb (list of strings), model_version, scoring_latency_ms, created_at)

transactions_customer(id, customer_id text e.g. 'C00042', name, home_city, created_at)

cases_fraudcase(id, transaction_id -> transactions_transaction.id,
  status  -- OPEN|INVESTIGATING|CONFIRMED_FRAUD|FALSE_POSITIVE
  priority  -- MEDIUM|HIGH
  assigned_to_id, resolution_note, ai_recommendation  -- BLOCK|VERIFY|APPROVE
  ai_confidence, created_at, resolved_at)

Notes: "fraud" usually means is_flagged = true (model alerts) or status = 'CONFIRMED_FRAUD' (analyst-confirmed).
Never use SELECT *; name the columns."""

SQL_PROMPT = """You translate fraud-analytics questions into a single PostgreSQL SELECT query.
{schema}

Return JSON: {{"sql": "...", "chart": "bar" | "line" | "table" | "number", "title": "short chart title"}}.
Use clear column aliases. If the question cannot be answered from these tables, return {{"sql": "", "chart": "table", "title": "unanswerable"}}."""

ANSWER_PROMPT = """Question: {question}
SQL result ({n} rows, first rows shown): {rows}
Answer the question in 1-2 sentences using the numbers above. Do not speculate beyond the data."""


class AskResponse(BaseModel):
    question: str
    sql: str
    chart: Literal["bar", "line", "table", "number"]
    title: str
    columns: list[str]
    rows: list[dict[str, Any]]
    answer: str
    model: str


class AnalyticsError(Exception):
    pass


class LLMUnavailableError(Exception):
    pass


async def ask(question: str, llm: LLMClient, db: Database) -> AskResponse:
    try:
        response = await llm.chat(
            [{"role": "system", "content": SQL_PROMPT.format(schema=SCHEMA)}, {"role": "user", "content": question}],
            json_mode=True, temperature=0,
        )
    except RateLimitError as exc:
        raise LLMUnavailableError("The AI provider's free-tier quota is used up for now — try again later.") from exc
    except APIError as exc:
        raise LLMUnavailableError(f"The AI provider is unavailable ({type(exc).__name__}).") from exc
    try:
        plan = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError as exc:
        raise AnalyticsError("The model did not return valid JSON") from exc
    if not plan.get("sql"):
        raise AnalyticsError("That question can't be answered from the fraud data available.")

    try:
        sql = validate_sql(plan["sql"])
    except UnsafeSQLError as exc:
        logger.warning("Rejected generated SQL for %r: %s | %s", question, exc, plan["sql"])
        raise AnalyticsError(f"Generated query was rejected by the SQL guard: {exc}") from exc

    try:
        rows = await db.fetch(sql)
    except Exception as exc:  # syntax errors, timeouts, permission denied
        raise AnalyticsError(f"Query failed: {type(exc).__name__}: {str(exc).splitlines()[0]}") from exc

    rows = [{k: (float(v) if hasattr(v, "is_finite") else v) for k, v in r.items()} for r in rows]  # Decimal -> float
    try:  # the summary is a nice-to-have: if it fails, still return the data
        answer_resp = await llm.chat(
            [{"role": "user", "content": ANSWER_PROMPT.format(question=question, n=len(rows),
                                                               rows=json.dumps(rows[:20], default=str))}],
            model=llm.fast_model, temperature=0,
        )
        answer = (answer_resp.choices[0].message.content or "").strip()
    except APIError:
        answer = f"Query returned {len(rows)} row(s); the AI summary is unavailable right now."
    chart = plan.get("chart") if plan.get("chart") in {"bar", "line", "table", "number"} else "table"
    return AskResponse(
        question=question, sql=sql, chart=chart, title=str(plan.get("title", ""))[:120],
        columns=list(rows[0].keys()) if rows else [], rows=rows,
        answer=answer, model=llm.model,
    )
