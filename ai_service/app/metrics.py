"""Prometheus metrics for the AI service (scraped at /metrics)."""
from prometheus_client import Counter, Gauge, Histogram

LLM_REQUESTS = Counter("finguard_llm_requests_total", "LLM API calls", ["model", "outcome"])
LLM_TOKENS = Counter("finguard_llm_tokens_total", "LLM tokens consumed (prompt + completion)", ["model"])
LLM_LATENCY = Histogram("finguard_llm_latency_seconds", "LLM API call latency", ["model"],
                        buckets=(0.25, 0.5, 1, 2, 4, 8, 16, 30))
INVESTIGATIONS = Counter("finguard_investigations_total", "Case investigations",
                         ["mode", "source", "recommendation"])  # mode: auto|on_demand, source: llm|offline
ASK_REQUESTS = Counter("finguard_ask_total", "Natural-language analytics requests", ["outcome"])
WS_CLIENTS = Gauge("finguard_ws_clients", "Connected live-dashboard WebSocket clients")
WS_DROPPED = Counter("finguard_ws_dropped_total", "Live events dropped for slow WebSocket clients")
