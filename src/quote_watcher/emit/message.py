"""Build CommonMessage from AlertVerdict — single rule and burst (multi-rule same ticker)."""
from __future__ import annotations

from quote_watcher.alerts.verdict import AlertVerdict
from shared.common.contracts import Badge, CommonMessage, Deeplink
from shared.common.enums import Market


def _deeplinks_for_ticker(ticker: str, market: str) -> list[Deeplink]:
    market_lc = "sh" if market == "SH" else "sz" if market == "SZ" else "bj"
    return [
        Deeplink(
            label="东财 K 线",
            url=f"https://quote.eastmoney.com/{market_lc}{ticker}.html",
        ),
        Deeplink(label="雪球", url=f"https://xueqiu.com/S/{market}{ticker}"),
    ]


def _arrow(pct: float) -> str:
    if pct < 0:
        return "🔻"
    if pct > 0:
        return "🚀"
    return "⚡"


def build_alert_message(v: AlertVerdict) -> CommonMessage:
    snap = v.snapshot
    pct = v.ctx_dump.get("pct_change_intraday", snap.pct_change)
    vol_ratio = v.ctx_dump.get("volume_ratio")

    summary_lines = [
        f"⚡ 触发: {v.rule.id}({v.rule.expr})",
        f"当前价: {snap.price:.2f}  ({pct:+.2f}%)",
        f"今日量: {snap.volume / 10000:.1f}万手",
    ]
    if vol_ratio:
        summary_lines.append(f"量比: {vol_ratio:.2f}")
    summary_lines.append(f"⏱ {snap.ts.strftime('%H:%M:%S')}")

    badges = [
        Badge(text=f"#{snap.ticker}", color="blue"),
        Badge(text="alert", color="red" if pct < 0 else "green"),
    ]
    arrow = _arrow(pct)
    market_lc = "sh" if snap.market == "SH" else "sz"

    return CommonMessage(
        title=f"{arrow} {snap.name} ({snap.ticker}) {v.rule.id}",
        summary="\n".join(summary_lines),
        source_label="quote_watcher",
        source_url=f"https://quote.eastmoney.com/{market_lc}{snap.ticker}.html",
        badges=badges,
        deeplinks=_deeplinks_for_ticker(snap.ticker, snap.market),
        chart_url=None,
        market=Market.CN,
        kind="alert",
    )


def build_burst_message(verdicts: list[AlertVerdict]) -> CommonMessage:
    assert verdicts, "verdicts must be non-empty"
    snap = verdicts[0].snapshot
    pct = snap.pct_change
    arrow = _arrow(pct)

    lines = [f"✓ {v.rule.id}: {v.rule.expr}" for v in verdicts]
    lines.append(f"当前价: {snap.price:.2f}  ({pct:+.2f}%)")
    lines.append(f"⏱ {snap.ts.strftime('%H:%M:%S')}")

    badges = [
        Badge(text=f"#{snap.ticker}", color="blue"),
        Badge(text=f"多规则x{len(verdicts)}", color="yellow"),
        Badge(text="alert", color="red" if pct < 0 else "green"),
    ]
    market_lc = "sh" if snap.market == "SH" else "sz"

    return CommonMessage(
        title=f"{arrow} {snap.name} ({snap.ticker}) 多规则触发(x{len(verdicts)})",
        summary="\n".join(lines),
        source_label="quote_watcher",
        source_url=f"https://quote.eastmoney.com/{market_lc}{snap.ticker}.html",
        badges=badges,
        deeplinks=_deeplinks_for_ticker(snap.ticker, snap.market),
        chart_url=None,
        market=Market.CN,
        kind="alert_burst",
    )
