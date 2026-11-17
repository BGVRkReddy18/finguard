import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from openai.types.chat import ChatCompletion

from app.agent import OFFLINE_MODEL, RiskAnalystAgent
from app.tools import Toolbox

CASE = {
    "case_id": 7, "status": "OPEN", "priority": "HIGH", "created_at": "2026-11-16T10:00:00Z",
    "amount": 18500.0, "currency": "INR", "merchant": "Croma", "merchant_category": "electronics", "city": "Delhi",
    "channel": "POS", "timestamp": "2026-11-16T10:00:00Z", "fraud_score": 0.99,
    "reasons": ["1250 km from the customer's usual location", "Amount is 9.1x the customer's average"],
    "features": {"history_count": 84}, "model_version": "xgb-test", "customer_id": "C00042",
    "customer_name": "Asha Rao", "home_city": "Hyderabad",
}


class FakeDB:
    """Answers the toolbox's fixed queries with canned rows."""

    def __init__(self):
        self.queries: list[str] = []

    async def open(self): ...
    async def close(self): ...

    async def fetch(self, sql, params=None):
        self.queries.append(sql)
        if "FROM cases_fraudcase c" in sql and "WHERE c.id = %s" in sql:
            return [dict(CASE)] if params == (7,) else []
        if "count(*) AS transactions" in sql:
            return [{"transactions": 84, "avg_amount": 2030.5, "median_amount": 1500, "max_amount": 9000,
                     "first_seen": "2026-11-15", "flagged_transactions": 0}]
        if "GROUP BY" in sql:
            return [{"value": "Hyderabad", "n": 80}]
        return []


def completion(content=None, tool_calls=None) -> ChatCompletion:
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": int(time.time()), "model": "fake",
        "choices": [{"index": 0, "finish_reason": "tool_calls" if tool_calls else "stop",
                     "message": {"role": "assistant", "content": content, "tool_calls": tool_calls}}],
    })


def tool_call(name, args, call_id="call_1"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class FakeLLM:
    model, fast_model = "big-model", "fast-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self.responses.pop(0)


GOOD_REPORT = json.dumps({
    "recommendation": "BLOCK", "confidence": 0.92,
    "summary": "Large electronics purchase in Delhi, 1,250 km from the customer's home city of Hyderabad.",
    "key_evidence": ["9.1x average amount", "All 80 prior transactions in Hyderabad"],
    "next_steps": ["Block the card", "Call the customer"],
})


async def test_agent_uses_tools_then_writes_validated_report():
    llm = FakeLLM([
        completion(tool_calls=[tool_call("get_customer_profile", {"customer_id": "C00042"})]),
        completion(content="Customer always shops in Hyderabad; this is far outside normal behaviour."),
        completion(content=GOOD_REPORT),
    ])
    report, trace = await RiskAnalystAgent(llm, Toolbox(FakeDB())).investigate(7)
    assert report.recommendation == "BLOCK"
    assert report.model == "big-model"
    assert [c["tool"] for c in trace["tool_calls"]] == ["get_customer_profile"]
    assert llm.calls[-1]["json_mode"] is True


async def test_fast_model_used_for_auto_investigation():
    llm = FakeLLM([completion(content="analysis"), completion(content=GOOD_REPORT)])
    report, _ = await RiskAnalystAgent(llm, Toolbox(FakeDB())).investigate(7, fast=True)
    assert report.model == "fast-model"
    assert all(call["model"] == "fast-model" for call in llm.calls)


async def test_agent_cannot_query_other_customers():
    db = FakeDB()
    llm = FakeLLM([
        completion(tool_calls=[tool_call("get_recent_transactions", {"customer_id": "C99999"})]),
        completion(content="analysis"),
        completion(content=GOOD_REPORT),
    ])
    _, trace = await RiskAnalystAgent(llm, Toolbox(db)).investigate(7)
    assert "only query the customer" in trace["evidence"][0]["result"]
    assert not any("ORDER BY t.timestamp DESC" in q for q in db.queries)


async def test_invalid_report_is_retried_once():
    llm = FakeLLM([
        completion(content="analysis"),
        completion(content='{"recommendation": "NUKE_IT", "confidence": 5}'),
        completion(content=GOOD_REPORT),
    ])
    report, _ = await RiskAnalystAgent(llm, Toolbox(FakeDB())).investigate(7)
    assert report.recommendation == "BLOCK"


async def test_falls_back_to_template_when_llm_keeps_failing():
    bad = completion(content="not json")
    llm = FakeLLM([completion(content="analysis"), bad, bad])
    report, _ = await RiskAnalystAgent(llm, Toolbox(FakeDB())).investigate(7)
    assert report.model.startswith(OFFLINE_MODEL)
    assert report.recommendation == "BLOCK"  # score 0.99


async def test_offline_mode_without_llm():
    report, _ = await RiskAnalystAgent(None, Toolbox(FakeDB())).investigate(7)
    assert report.model.startswith(OFFLINE_MODEL)
    assert "₹18,500" in report.summary


async def test_unknown_case():
    with pytest.raises(LookupError):
        await RiskAnalystAgent(None, Toolbox(FakeDB())).investigate(404)


class FakeBackend:
    def __init__(self):
        self.reports = []

    async def post_report(self, case_id, report):
        self.reports.append((case_id, report))

    async def close(self): ...


def make_token(secret=None, token_type="access"):
    from app.config import get_settings

    secret = secret or get_settings().jwt_secret
    return jwt.encode({"user_id": 1, "token_type": token_type, "exp": int(time.time()) + 300}, secret, algorithm="HS256")


def test_investigate_endpoint_requires_valid_jwt_and_saves_report():
    from app.main import create_app

    backend = FakeBackend()
    app = create_app(db=FakeDB(), llm=None, backend=backend, start_worker=False)
    with TestClient(app) as client:
        assert client.post("/investigate/7").status_code == 401
        assert client.post("/investigate/7", headers={"Authorization": f"Bearer {make_token('wrong')}"}).status_code == 401
        refresh = make_token(token_type="refresh")
        assert client.post("/investigate/7", headers={"Authorization": f"Bearer {refresh}"}).status_code == 401

        resp = client.post("/investigate/7", headers={"Authorization": f"Bearer {make_token()}"})
        assert resp.status_code == 200
        assert backend.reports[0][0] == 7
        assert client.get("/health").json()["llm"] == "offline"
        assert client.post("/ask", json={"question": "fraud by city?"},
                           headers={"Authorization": f"Bearer {make_token()}"}).status_code == 503


def test_websocket_rejects_bad_token_and_streams_events():
    from starlette.websockets import WebSocketDisconnect

    from app.main import create_app

    app = create_app(db=FakeDB(), llm=None, backend=FakeBackend(), start_worker=False)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/live?token=bogus") as ws:
                ws.receive_text()
        with client.websocket_connect(f"/ws/live?token={make_token()}") as ws:
            assert client.get("/health").json()["live_clients"] == 1
            # publish on the app's event loop (asyncio queues aren't thread-safe), as the Kafka fan-out does
            client.portal.call(app.state.broadcaster.publish, {"type": "case_opened", "case_id": 1})
            assert json.loads(ws.receive_text()) == {"type": "case_opened", "case_id": 1}


def test_slow_client_drops_oldest_not_blocks():
    from app.realtime import QUEUE_SIZE, Broadcaster

    b = Broadcaster()
    q = b.subscribe()
    for i in range(QUEUE_SIZE + 10):
        b.publish({"i": i})
    assert q.qsize() == QUEUE_SIZE and b.dropped == 10
    assert json.loads(q.get_nowait())["i"] == 10  # oldest 10 dropped


def test_live_feed_never_leaks_ground_truth():
    from app.realtime import slim_transaction

    event = {"txn_id": "t", "customer_id": "c", "amount": 1, "merchant": "m", "merchant_category": "x", "city": "y",
             "channel": "POS", "timestamp": "now", "label_is_fraud": True, "fraud_pattern": "card_testing",
             "score": {"fraud_score": 0.9, "risk_level": "HIGH", "is_flagged": True, "reasons": ["r"]}}
    slim = slim_transaction(event)
    assert "label_is_fraud" not in slim and "fraud_pattern" not in slim


def _rate_limit_error():
    import httpx
    from openai import RateLimitError

    req = httpx.Request("POST", "https://x/chat/completions")
    return RateLimitError("quota", response=httpx.Response(429, request=req), body=None)


async def test_ask_reports_quota_exhaustion_cleanly():
    from app.analytics import LLMUnavailableError, ask

    class QuotaLLM(FakeLLM):
        async def chat(self, messages, **kwargs):
            raise _rate_limit_error()

    with pytest.raises(LLMUnavailableError):
        await ask("fraud by city", QuotaLLM([]), FakeDB())


async def test_ask_returns_data_when_only_summary_fails():
    from app.analytics import ask

    class SummaryFails(FakeLLM):
        async def chat(self, messages, **kwargs):
            if kwargs.get("json_mode"):
                sql = "SELECT city, count(*) AS n FROM transactions_transaction GROUP BY city"
                return completion(content=json.dumps({"sql": sql, "chart": "bar", "title": "t"}))
            raise _rate_limit_error()

    result = await ask("fraud by city", SummaryFails([]), FakeDB())
    assert result.rows == [{"value": "Hyderabad", "n": 80}]
    assert "summary is unavailable" in result.answer


def test_llm_client_counts_tokens_per_model():
    from types import SimpleNamespace

    from app.config import Settings
    from app.llm import LLMClient

    class FakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(usage=SimpleNamespace(total_tokens=1200), choices=[])

    client = LLMClient(Settings(llm_api_key="k", llm_requests_per_minute=100),
                       client=SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())))
    import asyncio
    asyncio.run(client.chat([{"role": "user", "content": "hi"}], model="m1"))
    asyncio.run(client.chat([{"role": "user", "content": "hi"}], model="m1"))
    assert client.tokens_today("m1") == 2400 and client.tokens_today("m2") == 0


def test_per_user_rate_limit_on_llm_endpoints(monkeypatch):
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("USER_INVESTIGATE_PER_HOUR", "2")
    get_settings.cache_clear()
    try:
        app = create_app(db=FakeDB(), llm=None, backend=FakeBackend(), start_worker=False)
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {make_token()}"}
            assert client.post("/investigate/7", headers=headers).status_code == 200
            assert client.post("/investigate/7", headers=headers).status_code == 200
            blocked = client.post("/investigate/7", headers=headers)
            assert blocked.status_code == 429
            assert int(blocked.headers["Retry-After"]) > 0
    finally:
        get_settings.cache_clear()


def test_prompt_explains_feature_store_vs_database_history():
    from app.agent import SYSTEM_PROMPT

    assert "FULL history" in SYSTEM_PROMPT and "history_count" in SYSTEM_PROMPT
