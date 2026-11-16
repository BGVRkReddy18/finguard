import asyncio
import json
import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app
from redis.asyncio import Redis

from .config import get_settings
from .features import FeatureStore
from .schemas import ScoreResult, TransactionIn
from .scoring import ScoringPipeline, load_scorer
from .worker import run_scoring_worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ml-service")


def create_app(redis_factory: Callable[[], Redis] | None = None) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        redis = redis_factory() if redis_factory else Redis.from_url(settings.redis_url, decode_responses=True)
        app.state.redis = redis
        scorer = load_scorer(settings.scorer, settings.model_dir)
        app.state.pipeline = ScoringPipeline(FeatureStore(redis), scorer, settings.flag_threshold)
        app.state.worker_state = {"worker": "disabled", "processed": 0}

        task = None
        if settings.kafka_enabled:
            app.state.worker_state["worker"] = "starting"
            task = asyncio.create_task(run_scoring_worker(settings, app.state.pipeline, app.state.worker_state))
            task.add_done_callback(_log_worker_exit)
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await redis.aclose()

    app = FastAPI(
        title="FinGuard ML Service",
        description="Real-time fraud scoring with an online Redis feature store.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.mount("/metrics", make_asgi_app())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/model/info")
    async def model_info(request: Request):
        """Model card for the dashboard: version, threshold, offline test metrics, SHAP importance."""
        pipeline = request.app.state.pipeline
        meta_path = settings.model_dir / "model_meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        if meta.get("version") != pipeline.scorer.version:
            meta = {}  # artifacts on disk don't match the model being served
        return {
            "version": pipeline.scorer.version,
            "flag_threshold": pipeline.flag_threshold,
            "trained_at": meta.get("trained_at"),
            "rows": meta.get("rows"),
            "test_metrics": meta.get("test_metrics"),
            "shap_importance": meta.get("shap_importance"),
        }

    @app.get("/health")
    async def health(request: Request):
        redis_ok = await request.app.state.redis.ping()
        pipeline = request.app.state.pipeline
        return {
            "status": "ok" if redis_ok else "degraded",
            "model_version": pipeline.scorer.version,
            "flag_threshold": round(pipeline.flag_threshold, 4),
            **request.app.state.worker_state,
        }

    @app.post("/score", response_model=ScoreResult)
    async def score(txn: TransactionIn, request: Request) -> ScoreResult:
        """Synchronous scoring endpoint — used by load tests and other services."""
        return await request.app.state.pipeline.score(txn)

    return app


def _log_worker_exit(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        logger.error("Scoring worker crashed", exc_info=task.exception())


app = create_app()
