"""Build a daily system card from persisted metrics without sending it."""

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

from news_pipeline.storage.db import Database
from shared.common.contracts import Badge, CommonMessage
from shared.common.enums import Market
from shared.common.timeutil import ensure_utc, utc_now


def _json_list(value: object) -> list[Any]:
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    return value if isinstance(value, list) else []


async def build_ops_report(
    db: Database,
    *,
    db_path: Path,
    mode: str,
    now: datetime | None = None,
) -> CommonMessage:
    at = ensure_utc(now or utc_now()).replace(tzinfo=None)
    cutoff = at - timedelta(hours=24)
    params = {
        "cutoff": cutoff.isoformat(sep=" ", timespec="microseconds"),
        "now": at.isoformat(sep=" ", timespec="microseconds"),
    }
    async with db.session() as session:

        async def rows(query: str) -> list[dict[str, Any]]:
            result = await session.execute(text(query), params)
            return [dict(row) for row in result.mappings()]

        source_states = await rows("SELECT source,health,health_reason FROM source_state")
        raw = await rows(
            "SELECT id,source,status FROM raw_news WHERE fetched_at>=:cutoff AND fetched_at<=:now"
        )
        events = await rows(
            "SELECT * FROM events WHERE first_seen_at>=:cutoff AND first_seen_at<=:now"
        )
        decisions = await rows(
            "SELECT * FROM events WHERE decided_at>=:cutoff AND decided_at<=:now"
        )
        deliveries = await rows(
            "SELECT * FROM deliveries WHERE created_at>=:cutoff AND created_at<=:now"
        )
        llm_calls = await rows(
            "SELECT * FROM llm_calls WHERE created_at>=:cutoff AND created_at<=:now"
        )
    counts = Counter(row["source"] for row in raw)
    states = {row["source"]: row for row in source_states}
    sources = sorted(
        set(counts) | set(states),
        key=lambda source: (states.get(source, {}).get("health") != "down", source),
    )
    lines = [f"模式 {mode} · 过去24小时 · 入库 {len(raw)}"]
    for source in sources:
        state = states.get(source, {})
        reason = f" ({state['health_reason']})" if state.get("health_reason") else ""
        lines.append(f"{source}: {counts[source]} · {state.get('health', 'unknown')}{reason}")
    sent = {
        row["event_id"]
        for row in deliveries
        if row["kind"] == "immediate" and row["status"] == "sent"
    }
    reasons = Counter(row["decision_reason"] for row in decisions)
    dedup = reasons["repeat"]
    burst, stale = reasons["burst"], reasons["stale"]
    lines.append(f"候选 {len(events)} · 即时推送 {len(sent)}")
    lines.append(f"去重 {dedup} · 突发 {burst} · 新鲜度 {stale}")
    digest_items: dict[tuple[str | int, str | None], set[int]] = {}
    for row in deliveries:
        if row["kind"] == "digest" and row["status"] == "sent":
            slot = (row["digest_slot"] or row["id"], row["market"])
            digest_items.setdefault(slot, set()).update(_json_list(row["event_ids"]))
    items = sum(len(event_ids) for event_ids in digest_items.values())
    failures = sum(row["status"] == "failed" for row in deliveries)
    lines.append(f"简报 {len(digest_items)} 期 / {items} 条 · 推送失败 {failures}")
    cost = sum(float(row["cost_cny"]) for row in llm_calls)
    llm_failures = sum(not row["ok"] for row in llm_calls)
    fallback = sum(row["assess_status"] == "failed" for row in decisions)
    lines.append(
        f"LLM {len(llm_calls)} 次 · 费用 ¥{cost:.2f} · LLM失败 {llm_failures} · 退回规则 {fallback}"
    )
    size = sum(path.stat().st_size for path in [db_path, Path(f"{db_path}-wal")] if path.is_file())
    lines.append(f"数据库 {size / (1024**2):.2f} MB")
    return CommonMessage(
        title="系统日报",
        summary="\n".join(lines),
        source_label="系统统计",
        source_url="https://example.com/system",
        badges=[Badge(text=mode, color="blue")],
        chart_url=None,
        deeplinks=[],
        market=Market.CN,
    )
