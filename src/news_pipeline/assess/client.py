import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True)
class ChatAttempt:
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    error: str | None = None


@dataclass(frozen=True)
class ChatResult:
    content: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    attempts: tuple[ChatAttempt, ...] = field(default_factory=tuple)


class ChatRequestError(RuntimeError):
    def __init__(self, message: str, attempts: tuple[ChatAttempt, ...]) -> None:
        super().__init__(message)
        self.attempts = attempts


class ChatClient:
    """Reusable OpenAI-compatible client; model JSON validation belongs to the caller."""

    def __init__(self, api_key: str, base_url: str, timeout: float = 30.0) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def chat_json(self, *, model: str, system: str, user: str, max_tokens: int) -> ChatResult:
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        }
        attempts: list[ChatAttempt] = []
        started = time.perf_counter()
        for attempt in range(3):
            at = time.perf_counter()
            tokens_in = tokens_out = 0
            transient = False
            try:
                response = await self._http.post("chat/completions", json=body)
                if response.is_error:
                    transient = response.status_code == 429 or response.status_code >= 500
                    raise ValueError(f"HTTP {response.status_code}")
                payload = response.json()
                usage = payload.get("usage", {})
                tokens_in = max(int(usage.get("prompt_tokens", 0)), 0)
                tokens_out = max(int(usage.get("completion_tokens", 0)), 0)
                content: Any = payload["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("chat response content must be a string")
                attempts.append(ChatAttempt(tokens_in, tokens_out, self._elapsed(at)))
                return ChatResult(
                    content, tokens_in, tokens_out, self._elapsed(started), tuple(attempts)
                )
            except httpx.TransportError as error:
                transient = True
                message = type(error).__name__
            except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as error:
                message = str(error) if isinstance(error, ValueError) else type(error).__name__
            attempts.append(ChatAttempt(tokens_in, tokens_out, self._elapsed(at), message))
            if not transient or attempt == 2:
                raise ChatRequestError(message, tuple(attempts))
            await asyncio.sleep((2, 6)[attempt])
        raise AssertionError("unreachable")

    @staticmethod
    def _elapsed(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)

    async def close(self) -> None:
        await self._http.aclose()
