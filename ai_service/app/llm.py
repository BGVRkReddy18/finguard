"""Thin async wrapper over any OpenAI-compatible chat API (Groq, Ollama, OpenAI, ...)."""
import asyncio
import time
from collections import defaultdict, deque
from datetime import date

from openai import AsyncOpenAI

from .config import Settings


class RateLimiter:
    """Sliding-window limiter: at most ``rpm`` calls in any 60-second window."""

    def __init__(self, rpm: int):
        self.rpm = rpm
        self.calls: deque[float] = deque()
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self.lock:
            while True:
                now = time.monotonic()
                while self.calls and self.calls[0] <= now - 60:
                    self.calls.popleft()
                if len(self.calls) < self.rpm:
                    self.calls.append(now)
                    return
                await asyncio.sleep(self.calls[0] + 60 - now)


class LLMClient:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        self.settings = settings
        self.model = settings.llm_model
        self.fast_model = settings.llm_fast_model
        self.limiter = RateLimiter(settings.llm_requests_per_minute)
        self.usage: dict[tuple[date, str], int] = defaultdict(int)  # tokens used per (day, model)
        # The SDK retries 429/5xx with exponential backoff (respects Retry-After)
        self.client = client or AsyncOpenAI(
            base_url=settings.llm_base_url, api_key=settings.llm_api_key or "missing", max_retries=3, timeout=30
        )

    async def chat(self, messages: list[dict], *, model: str | None = None, tools: list[dict] | None = None,
                   json_mode: bool = False, temperature: float = 0.1):
        await self.limiter.acquire()
        kwargs: dict = {"model": model or self.model, "messages": messages, "temperature": temperature}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = await self.client.chat.completions.create(**kwargs)
        if response.usage:
            self.usage[(date.today(), kwargs["model"])] += response.usage.total_tokens
        return response

    def tokens_today(self, model: str) -> int:
        return self.usage[(date.today(), model)]
