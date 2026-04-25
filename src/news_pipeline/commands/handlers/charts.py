from typing import Any

from news_pipeline.charts.factory import ChartFactory, ChartRequest
from news_pipeline.commands.dispatcher import CommandDispatcher


def register_chart_cmds(d: CommandDispatcher, *, chart_factory: ChartFactory) -> None:

    @d.register("chart")
    async def chart(args: list[str], ctx: dict[str, Any]) -> str:
        if not args:
            return "用法: /chart TICKER [window=30d]"
        ticker = args[0]
        window = args[1] if len(args) > 1 else "30d"
        png = await chart_factory.render_kline(
            ChartRequest(ticker=ticker, kind="kline", window=window, params={})
        )
        return f"📈 {ticker} K线图已生成 ({len(png)} bytes)"

    @d.register("sentiment")
    async def sentiment(args: list[str], ctx: dict[str, Any]) -> str:
        if not args:
            return "用法: /sentiment TICKER [days=7]"
        ticker = args[0]
        days = args[1] if len(args) > 1 else "7"
        # Phase-2 fix: add render_sentiment on ChartFactory.
        # MVP: reuse render_kline with kind="sentiment"
        png = await chart_factory.render_kline(
            ChartRequest(ticker=ticker, kind="sentiment", window=f"{days}d", params={})
        )
        return f"📊 {ticker} 情绪曲线已生成 ({len(png)} bytes)"
