"""Event-driven auto-investigation: consume ``cases.opened`` and attach an AI report to each case.

Free-tier LLM budget is limited, so only configured priorities are investigated automatically
(default: HIGH) with the fast model, capped per day. Everything else can be investigated on demand.
"""
import asyncio
import json
import logging

import httpx
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError

from .agent import InvestigationReport, RiskAnalystAgent
from .config import Settings

logger = logging.getLogger("ai-worker")


class BackendClient:
    """Posts reports to Django, authenticated with the shared service token."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.client = client or httpx.AsyncClient(base_url=settings.backend_url, timeout=10)
        self.token = settings.ai_service_token

    async def post_report(self, case_id: int, report: InvestigationReport) -> None:
        payload = report.model_dump()
        payload["next_steps"] = payload["next_steps"][:10]
        resp = await self.client.post(f"/api/cases/{case_id}/ai-report/", json=payload,
                                      headers={"X-Service-Token": self.token})
        resp.raise_for_status()

    async def close(self) -> None:
        await self.client.aclose()


async def run_auto_investigator(settings: Settings, agent: RiskAnalystAgent, backend: BackendClient, state: dict,
                                on_report=None) -> None:
    priorities = {p.strip() for p in settings.auto_investigate_priorities.split(",") if p.strip()}
    budget = settings.auto_investigate_daily_tokens
    consumer = AIOKafkaConsumer(
        settings.cases_topic, bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="ai-investigator", enable_auto_commit=False, auto_offset_reset="latest",
    )
    for attempt in range(1, 21):
        try:
            await consumer.start()
            break
        except KafkaConnectionError:
            logger.warning("Kafka not ready (attempt %d)", attempt)
            await asyncio.sleep(min(2 * attempt, 10))
    else:
        raise RuntimeError("Could not connect to Kafka")

    state["worker"] = "running"
    logger.info("Auto-investigating %s cases (daily budget %d tokens)", sorted(priorities) or "no", budget)
    try:
        async for msg in consumer:
            event = json.loads(msg.value)
            if event.get("priority") in priorities:
                llm = agent.llm
                if llm is None or llm.tokens_today(llm.fast_model) < budget:
                    try:
                        report, trace = await agent.investigate(event["case_id"], fast=True)
                        await backend.post_report(event["case_id"], report)
                        if on_report:
                            on_report(event["case_id"], report)
                        state["investigated"] = state.get("investigated", 0) + 1
                        logger.info("Case %s -> %s (%.2f) via %s, %d tool calls", event["case_id"],
                                    report.recommendation, report.confidence, report.model, len(trace["tool_calls"]))
                    except Exception:
                        logger.exception("Auto-investigation of case %s failed", event["case_id"])
                else:
                    state["skipped_budget"] = state.get("skipped_budget", 0) + 1
            await consumer.commit()
    finally:
        state["worker"] = "stopped"
        await consumer.stop()
