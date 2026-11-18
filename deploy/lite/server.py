"""FinGuard Cloud Lite — the whole backend in one ASGI process, for free hosting without a card
(Render free web service: ~512 MB RAM, 0.1 CPU; Neon free Postgres).

It composes the *same* application code as the full stack and swaps only the infrastructure that
free tiers don't offer:

    Kafka topics       -> in-process asyncio queues     (same scoring, ingestion and agent code)
    Redis feature store -> in-memory feature store       (same feature code, warmed from history)
    3 services          -> 1 process: Django (ASGI) at /, AI FastAPI app at /ai, ML endpoints at /ml

Cost-aware by design: transactions are generated only while someone has the dashboard open (plus a
short grace period), and DB connections are closed when idle, so the serverless database can
scale to zero between visits and the demo stays inside free quotas.
"""
import asyncio
import heapq
import itertools
import json
import logging
import os
import random
import sys
import time
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

ROOT = Path(os.environ.get("FINGUARD_ROOT", "/srv"))
for path in (ROOT / "backend", ROOT / "lite", ROOT / "simulator"):
    sys.path.insert(0, str(path))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("finguard-lite")

# ---------------------------------------------------------------- configuration (env -> both apps)

def _readonly_url(owner_url: str, password: str) -> str:
    """Same database, least-privilege role (created by the cases.0003 migration)."""
    u = urlparse(owner_url)
    netloc = f"finguard_ro:{quote(password, safe='')}@{u.hostname}" + (f":{u.port}" if u.port else "")
    return urlunparse(u._replace(netloc=netloc))


HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "localhost")
FRONTEND = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_DEBUG", "false")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", f"{HOST},localhost,127.0.0.1")
os.environ.setdefault("CSRF_TRUSTED_ORIGINS", f"https://{HOST}")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", FRONTEND)  # Django
os.environ.setdefault("CORS_ORIGINS", FRONTEND)          # AI / ML FastAPI apps
os.environ.setdefault("JWT_SECRET", os.environ["DJANGO_SECRET_KEY"])
os.environ.setdefault("DATABASE_URL", _readonly_url(os.environ["DJANGO_DATABASE_URL"], os.environ["READONLY_DB_PASSWORD"]))
os.environ.setdefault("KAFKA_ENABLED", "false")

TPS = float(os.environ.get("SIM_TPS", 2))
# Keep each customer's transaction rate equal to training (5 tx/s over 5,000 customers): scaling the
# customer count with TPS keeps velocity/history features in-distribution (no train/serve skew).
CUSTOMERS = int(os.environ.get("SIM_CUSTOMERS", round(TPS * 1000)))
FRAUD_RATE = float(os.environ.get("SIM_FRAUD_RATE", 0.01))
WARM_HOURS = float(os.environ.get("WARM_HOURS", 24))
IDLE_GRACE_S = float(os.environ.get("SIM_IDLE_GRACE_S", 120))
AUTO_PRIORITIES = {p for p in os.environ.get("AUTO_INVESTIGATE_PRIORITIES", "HIGH").split(",") if p}
AUTO_DAILY_TOKENS = int(os.environ.get("AUTO_INVESTIGATE_DAILY_TOKENS", 40_000))

# ---------------------------------------------------------------- imports (after env is ready)
import django  # noqa: E402

django.setup()

from asgiref.sync import sync_to_async  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import InterfaceError, OperationalError, connections  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.routing import Mount  # noqa: E402

from aiapp.agent import RiskAnalystAgent  # noqa: E402
from aiapp.config import get_settings as ai_settings  # noqa: E402
from aiapp.db import Database  # noqa: E402
from aiapp.llm import LLMClient  # noqa: E402
from aiapp.main import create_app as create_ai_app  # noqa: E402
from aiapp.main import publish_report  # noqa: E402
from aiapp.metrics import INVESTIGATIONS, WS_CLIENTS  # noqa: E402
from aiapp.realtime import Broadcaster, slim_transaction  # noqa: E402
from aiapp.tools import Toolbox  # noqa: E402
from cases.models import FraudCase  # noqa: E402
from cases.services import attach_ai_report  # noqa: E402
from generator import make_customers, next_events  # noqa: E402
from mlapp.config import get_settings as ml_settings  # noqa: E402
from mlapp.features import InMemoryFeatureStore  # noqa: E402
from mlapp.schemas import TransactionIn  # noqa: E402
from mlapp.scoring import ScoringPipeline, load_scorer  # noqa: E402
from transactions.services import ingest_scored_event  # noqa: E402


def _reconnecting(fn, *args, **kwargs):
    """Run an ORM call; if Neon dropped the connection while it slept, reconnect and retry once.

    Django only refreshes connections around HTTP requests, but this process also does ORM work in
    background tasks. Retrying is safe: ingestion is idempotent on txn_id.
    """
    try:
        return fn(*args, **kwargs)
    except (OperationalError, InterfaceError):
        log.warning("Database connection was closed (database likely resumed from sleep); reconnecting")
        connections.close_all()
        return fn(*args, **kwargs)


def orm(fn, thread_sensitive: bool = True):
    """All ORM work runs on Django's single thread-sensitive executor, with reconnect-on-failure."""
    async def run(*args, **kwargs):
        return await sync_to_async(_reconnecting, thread_sensitive=thread_sensitive)(fn, *args, **kwargs)
    return run


class AsyncInMemoryStore(InMemoryFeatureStore):
    """In-memory feature store with the async interface the scoring pipeline expects."""

    async def compute_and_update(self, txn):  # type: ignore[override]
        return super().compute_and_update(txn)


class LocalBackend:
    """The AI agent's reports go straight to the Django service layer (same process, no HTTP hop)."""

    async def post_report(self, case_id: int, report) -> None:
        def save():
            attach_ai_report(FraudCase.objects.get(pk=case_id), report.model_dump())

        await orm(save, thread_sensitive=True)()

    async def close(self) -> None: ...


def _close_db_connections() -> None:
    connections.close_all()


# ---------------------------------------------------------------- the composed applications
state: dict = {"simulator": "warming up", "warm": None, "scored": 0, "investigated": 0}
store = AsyncInMemoryStore()
pipeline = ScoringPipeline(store, load_scorer("auto", ml_settings().model_dir))
broadcaster = Broadcaster()
raw_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=2000)
case_queue: asyncio.Queue[tuple[int, str]] = asyncio.Queue(maxsize=20)
warmed = asyncio.Event()

ai_db = Database(os.environ["DATABASE_URL"], min_size=0, max_idle=60)
llm = LLMClient(ai_settings()) if ai_settings().llm_enabled else None
backend = LocalBackend()
ai_app = create_ai_app(db=ai_db, llm=llm, backend=backend, start_worker=False)
agent = RiskAnalystAgent(llm, Toolbox(ai_db))

ml_app = FastAPI(title="FinGuard ML (lite)", docs_url=None, redoc_url=None, openapi_url=None)
ml_app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND], allow_methods=["GET"], allow_headers=["*"])


@ml_app.get("/model/info")
async def model_info():
    meta_path = ml_settings().model_dir / "model_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    if meta.get("version") != pipeline.scorer.version:
        meta = {}
    keys = ("trained_at", "rows", "test_metrics", "shap_importance")
    return {"version": pipeline.scorer.version, "flag_threshold": pipeline.flag_threshold, **{k: meta.get(k) for k in keys}}


@ml_app.get("/health")
async def ml_health():
    return {"status": "ok", "model_version": pipeline.scorer.version, "edition": "lite", **state,
            "viewers": len(broadcaster.queues)}


# ---------------------------------------------------------------- background tasks
def _warm_feature_store() -> int:
    customers, rng = make_customers(CUSTOMERS, 42), random.Random(43)
    end = datetime.now(UTC)
    clock, step = end - timedelta(hours=WARM_HOURS), timedelta(seconds=1 / TPS)
    pending, counter, n = [], itertools.count(), 0
    while clock < end:
        for delay, txn in next_events(customers, rng, clock, FRAUD_RATE):
            heapq.heappush(pending, (clock + timedelta(seconds=delay), next(counter), txn))
        while pending and pending[0][0] <= clock:
            due, _, txn = heapq.heappop(pending)
            txn["timestamp"] = due
            InMemoryFeatureStore.compute_and_update(store, TransactionIn.model_validate(txn))
            n += 1
        clock += step
    return n


async def warm() -> None:
    start = time.monotonic()
    n = await asyncio.to_thread(_warm_feature_store)
    state["warm"] = f"{n:,} transactions in {time.monotonic() - start:.0f}s"
    log.info("Feature store warmed: %s (%d customers)", state["warm"], CUSTOMERS)
    warmed.set()


async def simulator() -> None:
    """Streams transactions only while someone is watching (+ grace), so idle demos cost nothing."""
    await warmed.wait()
    customers, rng = make_customers(CUSTOMERS, 42), random.Random()
    pending: list = []
    counter = itertools.count()
    last_viewer = 0.0
    while True:
        now = time.monotonic()
        if broadcaster.queues:
            last_viewer = now
        if now - last_viewer > IDLE_GRACE_S:
            if state["simulator"] != "paused":
                state["simulator"] = "paused"
                await orm(_close_db_connections, thread_sensitive=True)()  # let Neon scale to zero
                log.info("No viewers: simulator paused")
            await asyncio.sleep(2)
            continue
        if state["simulator"] != "running":
            state["simulator"] = "running"
            log.info("Viewer connected: simulator running at %.1f tx/s", TPS)
        for delay, txn in next_events(customers, rng, datetime.now(UTC), FRAUD_RATE):
            heapq.heappush(pending, (time.time() + delay, next(counter), txn))
        while pending and pending[0][0] <= time.time():
            _, _, txn = heapq.heappop(pending)
            txn["timestamp"] = datetime.now(UTC).isoformat()
            with suppress(asyncio.QueueFull):
                raw_queue.put_nowait(txn)
        await asyncio.sleep(1 / TPS)


async def scorer() -> None:
    """transactions.raw -> score -> live feed -> persist (+ open case) — Kafka replaced by a queue."""
    while True:
        event = await raw_queue.get()
        try:
            result = await pipeline.score(TransactionIn.model_validate(event))
            scored = {**event, "score": result.model_dump()}
            broadcaster.publish(slim_transaction(scored))
            txn, created = await orm(ingest_scored_event, thread_sensitive=True)(scored)
            state["scored"] += 1
            if created and txn.is_flagged:
                case = await orm(FraudCase.objects.get, thread_sensitive=True)(transaction=txn)
                broadcaster.publish({"type": "case_opened", "case_id": case.id, "priority": case.priority,
                                     "fraud_score": txn.fraud_score, "customer_id": event["customer_id"]})
                with suppress(asyncio.QueueFull):  # never let the AI backlog slow scoring down
                    case_queue.put_nowait((case.id, case.priority))
        except Exception:
            log.exception("Failed to process transaction %s", event.get("txn_id"))


async def investigator() -> None:
    """Auto-investigate new high-priority cases with the fast model, inside a daily token budget."""
    while True:
        case_id, priority = await case_queue.get()
        if priority not in AUTO_PRIORITIES or (llm and llm.tokens_today(llm.fast_model) >= AUTO_DAILY_TOKENS):
            continue
        try:
            report, _ = await agent.investigate(case_id, fast=True)
            await backend.post_report(case_id, report)
            publish_report(ai_app, case_id, report)
            INVESTIGATIONS.labels("auto", "offline" if report.model.startswith("offline") else "llm",
                                  report.recommendation).inc()
            state["investigated"] += 1
        except Exception:
            log.exception("Auto-investigation of case %s failed", case_id)


async def janitor() -> None:
    """Free Postgres has 1 GB: keep flagged/case history, trim routine traffic older than a day."""
    while True:
        await asyncio.sleep(3600)
        with suppress(Exception):
            await orm(call_command, thread_sensitive=True)("prune_transactions", hours=24)


# ---------------------------------------------------------------- gateway
class HideInternal:
    """Block the AI app's ops endpoints (/metrics, docs) from the public internet."""

    BLOCKED = ("/ai/metrics", "/ai/docs", "/ai/redoc", "/ai/openapi.json")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and scope["path"].startswith(self.BLOCKED):
            if scope["type"] == "http":
                return await PlainTextResponse("Not found", 404)(scope, receive, send)
            return await send({"type": "websocket.close", "code": 1008})
        return await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(_app):
    # Mounted apps don't get lifespan events, so set up the AI app's state here
    await ai_db.open()
    ai_app.state.db, ai_app.state.llm, ai_app.state.backend = ai_db, llm, backend
    ai_app.state.broadcaster = broadcaster
    ai_app.state.worker_state = {"worker": "in-process", "realtime": "in-process"}
    WS_CLIENTS.set_function(lambda: len(broadcaster.queues))
    log.info("LLM: %s | model: %s | %d customers @ %.1f tx/s", "enabled" if llm else "offline (no LLM_API_KEY)",
             pipeline.scorer.version, CUSTOMERS, TPS)
    tasks = [asyncio.create_task(t()) for t in (warm, simulator, scorer, investigator, janitor)]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await ai_db.close()


app = HideInternal(Starlette(
    lifespan=lifespan,
    routes=[Mount("/ai", ai_app), Mount("/ml", ml_app), Mount("/", get_asgi_application())],
))
