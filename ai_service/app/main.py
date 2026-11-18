import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
from pydantic import BaseModel, Field

from .agent import InvestigationReport, RiskAnalystAgent
from .analytics import AnalyticsError, AskResponse, LLMUnavailableError, ask
from .auth import AuthError, current_user_id, decode_user_id
from .config import get_settings
from .db import Database
from .llm import LLMClient
from .metrics import ASK_REQUESTS, INVESTIGATIONS, WS_CLIENTS
from .ratelimit import UserRateLimiter
from .realtime import Broadcaster, run_fanout
from .tools import Toolbox
from .worker import BackendClient, run_auto_investigator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ai-service")


class CatchUnhandled:
    """Turn unexpected exceptions into a logged JSON 500 *inside* the CORS layer.

    Starlette's default 500 is produced outside CORSMiddleware, so the browser can't read it and the
    UI wrongly reports "backend unreachable". Only the exception's type is returned (no internals).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def tracking_send(message):
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            logger.exception("Unhandled error on %s %s", scope.get("method"), scope.get("path"))
            if started:
                raise
            body = {"detail": f"Internal error ({type(exc).__name__}). It has been logged."}
            await JSONResponse(body, status_code=500)(scope, receive, send)


class InvestigationResponse(BaseModel):
    case_id: int
    report: InvestigationReport
    tool_calls: list[dict]


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


_DEFAULT = object()  # distinguishes "not passed" (build from settings) from an explicit None (offline mode)


def create_app(db: Database | None = None, llm: LLMClient | None | object = _DEFAULT,
               backend: BackendClient | None = None, start_worker: bool | None = None) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = db or Database(settings.database_url)
        await app.state.db.open()
        if llm is _DEFAULT:
            app.state.llm = LLMClient(settings) if settings.llm_enabled else None
        else:
            app.state.llm = llm
        app.state.backend = backend or BackendClient(settings)
        app.state.worker_state = {"worker": "disabled", "realtime": "disabled"}
        app.state.broadcaster = Broadcaster()
        WS_CLIENTS.set_function(lambda: len(app.state.broadcaster.queues))
        if app.state.llm is None:
            logger.warning("LLM_API_KEY not set — running in offline mode (template reports, no /ask)")

        tasks = []
        run_worker = settings.kafka_enabled if start_worker is None else start_worker
        if run_worker:
            agent = RiskAnalystAgent(app.state.llm, Toolbox(app.state.db))
            notify = lambda case_id, report: publish_report(app, case_id, report)  # noqa: E731
            tasks.append(asyncio.create_task(run_auto_investigator(
                settings, agent, app.state.backend, app.state.worker_state, on_report=notify)))
            tasks.append(asyncio.create_task(run_fanout(settings, app.state.broadcaster, app.state.worker_state)))
        yield
        for task in tasks:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await app.state.backend.close()
        await app.state.db.close()

    app = FastAPI(title="FinGuard AI Service", version="0.1.0", lifespan=lifespan,
                  description="LLM risk-analyst agent, natural-language fraud analytics and live event stream.")
    ask_limit = UserRateLimiter(settings.user_ask_per_hour)
    investigate_limit = UserRateLimiter(settings.user_investigate_per_hour)
    app.mount("/metrics", make_asgi_app())
    app.add_middleware(CatchUnhandled)  # added first = innermost, so CORS headers wrap its responses
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

    @app.websocket("/ws/live")
    async def live(websocket: WebSocket, token: str = ""):
        """Live transactions, new cases and AI reports. Auth: ?token=<access JWT> (browsers can't set WS headers)."""
        try:
            decode_user_id(token, settings)
        except AuthError:
            await websocket.close(code=1008)  # policy violation
            return
        await websocket.accept()
        queue = websocket.app.state.broadcaster.subscribe()

        async def pump():
            while True:
                await websocket.send_text(await queue.get())

        async def watch_disconnect():
            # A quiet stream would otherwise never notice the client left -> leaked queue and task
            while (await websocket.receive())["type"] != "websocket.disconnect":
                pass

        tasks = [asyncio.create_task(pump()), asyncio.create_task(watch_disconnect())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            websocket.app.state.broadcaster.unsubscribe(queue)

    @app.get("/health")
    async def health(request: Request):
        llm_client = request.app.state.llm
        return {
            "status": "ok",
            "llm": "enabled" if llm_client else "offline",
            "model": llm_client.model if llm_client else None,
            "fast_model": llm_client.fast_model if llm_client else None,
            "tokens_today": {m: llm_client.tokens_today(m) for m in (llm_client.model, llm_client.fast_model)}
            if llm_client else {},
            **request.app.state.worker_state,
            "live_clients": len(request.app.state.broadcaster.queues),
        }

    @app.post("/investigate/{case_id}", response_model=InvestigationResponse)
    async def investigate(case_id: int, request: Request, user_id: int = Depends(current_user_id)):
        """On-demand investigation with the high-quality model; the report is saved to the case."""
        investigate_limit.check(user_id)
        agent = RiskAnalystAgent(request.app.state.llm, Toolbox(request.app.state.db))
        try:
            report, trace = await agent.investigate(case_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        await request.app.state.backend.post_report(case_id, report)
        publish_report(request.app, case_id, report)
        source = "offline" if report.model.startswith("offline") else "llm"
        INVESTIGATIONS.labels("on_demand", source, report.recommendation).inc()
        logger.info("User %s investigated case %s -> %s", user_id, case_id, report.recommendation)
        return InvestigationResponse(case_id=case_id, report=report, tool_calls=trace["tool_calls"])

    @app.post("/ask", response_model=AskResponse)
    async def ask_question(body: AskRequest, request: Request, user_id: int = Depends(current_user_id)):
        """Ask a question about fraud data in plain English."""
        ask_limit.check(user_id)
        if request.app.state.llm is None:
            ASK_REQUESTS.labels("unavailable").inc()
            raise HTTPException(503, "Natural-language analytics needs an LLM: set LLM_API_KEY")
        try:
            result = await ask(body.question, request.app.state.llm, request.app.state.db)
        except AnalyticsError as exc:
            ASK_REQUESTS.labels("rejected").inc()
            raise HTTPException(422, str(exc)) from exc
        except LLMUnavailableError as exc:
            ASK_REQUESTS.labels("unavailable").inc()
            raise HTTPException(503, str(exc)) from exc
        ASK_REQUESTS.labels("ok").inc()
        return result

    return app


def publish_report(app: FastAPI, case_id: int, report: InvestigationReport) -> None:
    app.state.broadcaster.publish({"type": "ai_report", "case_id": case_id, "recommendation": report.recommendation,
                                   "confidence": report.confidence, "model": report.model})


app = create_app()
