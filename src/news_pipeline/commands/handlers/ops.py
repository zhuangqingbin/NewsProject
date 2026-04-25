from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from news_pipeline.commands.dispatcher import CommandDispatcher
from news_pipeline.common.timeutil import utc_now
from news_pipeline.llm.cost_tracker import CostTracker
from news_pipeline.storage.dao.source_state import SourceStateDAO


def register_ops_cmds(
    d: CommandDispatcher, *,
    cost: CostTracker,
    state_dao: SourceStateDAO,
    digest_runner: Callable[[], Awaitable[int]],
) -> None:

    @d.register("cost")
    async def cost_today(args: list[str], ctx: dict[str, Any]) -> str:
        return (f"今日 LLM 成本: {cost.today_cost_cny():.2f} CNY"
                f"\n剩余预算: {cost.remaining_today():.2f} CNY")

    @d.register("pause")
    async def pause(args: list[str], ctx: dict[str, Any]) -> str:
        if not args:
            return "用法: /pause SOURCE [minutes=30]"
        src = args[0]
        mins = int(args[1]) if len(args) > 1 else 30
        await state_dao.set_paused(
            src,
            until=utc_now().replace(tzinfo=None) + timedelta(minutes=mins),
            error="manual_pause",
        )
        return f"已暂停 {src} {mins} 分钟"

    @d.register("digest")
    async def digest(args: list[str], ctx: dict[str, Any]) -> str:
        if not args or args[0] != "now":
            return "用法: /digest now"
        n = await digest_runner()
        return f"已发送 digest, 含 {n} 条"

    @d.register("health")
    async def health(args: list[str], ctx: dict[str, Any]) -> str:
        return "OK (详情见 healthcheck endpoint)"
