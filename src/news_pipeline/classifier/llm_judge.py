# src/news_pipeline/classifier/llm_judge.py
from news_pipeline.common.contracts import EnrichedNews
from news_pipeline.llm.clients.base import LLMClient, LLMRequest

JUDGE_SYSTEM = """\
你是判定器。给定一条新闻摘要 + 用户 watchlist, 判断是否值得"立即推送"\
（is_critical=true/false）。输出 JSON {"is_critical": bool, "reason": str}.\
判定准则: 涉及用户 watchlist 中股票的实质性事件（业绩/重大变更/政策影响）→ true; \
噪音/普通市场评论/无关公司 → false.\
"""

JUDGE_USER = """\
摘要: {summary}
关联标的: {tickers}
事件类型: {event_type}
情绪: {sentiment} / 量级: {magnitude}
Watchlist: {watchlist}
"""


class LLMJudge:
    def __init__(self, *, client: LLMClient, model: str) -> None:
        self._client = client
        self._model = model

    async def judge(
        self,
        e: EnrichedNews,
        *,
        watchlist_tickers: list[str],
    ) -> tuple[bool, str]:
        req = LLMRequest(
            model=self._model,
            system=JUDGE_SYSTEM,
            user=JUDGE_USER.format(
                summary=e.summary,
                tickers=",".join(e.related_tickers),
                event_type=e.event_type.value,
                sentiment=e.sentiment.value,
                magnitude=e.magnitude.value,
                watchlist=",".join(watchlist_tickers),
            ),
            json_mode=True,
            output_schema={
                "type": "object",
                "required": ["is_critical", "reason"],
                "properties": {
                    "is_critical": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
            },
            max_tokens=200,
        )
        resp = await self._client.call(req)
        payload = resp.json_payload or {"is_critical": False, "reason": ""}
        return bool(payload["is_critical"]), str(payload.get("reason", ""))
