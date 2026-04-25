# src/news_pipeline/llm/clients/dashscope.py
import httpx

from news_pipeline.llm.clients.base import (
    LLMRequest,
    LLMResponse,
    TokenUsage,
    parse_json_or_none,
)


class DashScopeClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def call(self, req: LLMRequest) -> LLMResponse:
        url = f"{self._base}/chat/completions"
        body: dict = {
            "model": req.model,
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.user},
            ],
            "max_tokens": req.max_tokens,
        }
        if req.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMResponse(
            text=text,
            json_payload=parse_json_or_none(text) if req.json_mode else None,
            usage=TokenUsage(
                input_tokens=int(usage.get("input_tokens", usage.get("prompt_tokens", 0))),
                output_tokens=int(
                    usage.get("output_tokens", usage.get("completion_tokens", 0))
                ),
            ),
            model=req.model,
        )
