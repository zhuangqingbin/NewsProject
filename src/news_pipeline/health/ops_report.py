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
        legacy = await rows(
            "SELECT p.raw_id,p.summary,l.status FROM push_log l JOIN news_processed p ON "
            "p.id=l.news_id WHERE l.sent_at>=:cutoff AND l.sent_at<=:now"
        )
        processed = await rows(
            "SELECT id,push_status FROM news_processed "
            "WHERE extracted_at>=:cutoff AND extracted_at<=:now"
        )
        links = await rows(
            "SELECT a.event_id,a.raw_id FROM event_articles a JOIN events e ON e.id=a.event_id "
            "WHERE e.decided_at>=:cutoff AND e.decided_at<=:now"
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
    shadow = {
        row["event_id"]
        for row in deliveries
        if row["kind"] == "immediate" and row["status"] == "shadow"
    }
    legacy_sent = {row["raw_id"] for row in legacy if row["status"] in {"sent", "ok"}}
    reasons = Counter(row["decision_reason"] for row in decisions)
    raw_duplicates = sum(row["status"] == "duplicate" for row in raw)
    if mode == "legacy":
        legacy_statuses = Counter(row["push_status"] for row in processed)
        dedup = legacy_statuses["dup"] + raw_duplicates
        burst, stale = legacy_statuses["burst_digest"], legacy_statuses["stale_digest"]
    else:
        dedup = reasons["repeat"] + raw_duplicates
        burst, stale = reasons["burst"], reasons["stale"]
    candidate_count = len(processed) if mode == "legacy" else len(events)
    push_count = len(legacy_sent) if mode == "legacy" else len(sent)
    lines.append(f"候选 {candidate_count} · 即时推送 {push_count} · 影子推送 {len(shadow)}")
    lines.append(f"去重 {dedup} · 突发 {burst} · 新鲜度 {stale}")
    digest_kind = "legacy_digest" if mode == "legacy" else "digest"
    digest_items: dict[tuple[str | int, str | None], set[int]] = {}
    for row in deliveries:
        if row["kind"] == digest_kind and row["status"] == "sent":
            slot = (row["digest_slot"] or row["id"], row["market"])
            digest_items.setdefault(slot, set()).update(_json_list(row["event_ids"]))
    items = sum(len(event_ids) for event_ids in digest_items.values())
    failures = sum(row["status"] in {"failed", "legacy_failed"} for row in deliveries)
    if mode == "legacy":
        failures += sum(row["status"] == "failed" for row in legacy)
    lines.append(f"简报 {len(digest_items)} 期 / {items} 条 · 推送失败 {failures}")
    cost = sum(float(row["cost_cny"]) for row in llm_calls)
    llm_failures = sum(not row["ok"] for row in llm_calls)
    fallback = sum(row["assess_status"] == "failed" for row in decisions)
    lines.append(
        f"LLM {len(llm_calls)} 次 · 费用 ¥{cost:.2f} · LLM失败 {llm_failures} · 退回规则 {fallback}"
    )
    size = sum(path.stat().st_size for path in [db_path, Path(f"{db_path}-wal")] if path.is_file())
    lines.append(f"数据库 {size / (1024**2):.2f} MB")
    if mode == "shadow":
        new_push = {row["id"] for row in decisions if row["decision"] == "push"}
        push_raw = {row["raw_id"] for row in links if row["event_id"] in new_push}
        new_only = {
            row["event_id"]
            for row in links
            if row["event_id"] in new_push and row["raw_id"] not in legacy_sent
        }
        matched_events = {
            row["event_id"]
            for row in links
            if row["event_id"] in new_push and row["raw_id"] in legacy_sent
        }
        new_only -= matched_events
        old_only = legacy_sent - push_raw
        lines.append(
            f"新旧对比: 共同 {len(matched_events)} · 新路径独有 {len(new_only)} "
            f"· 旧路径独有 {len(old_only)}"
        )
        for row in [row for row in decisions if row["id"] in new_only][:5]:
            lines.append(f"新路径独有: {row['headline'][:60]}")
        missing_legacy = {
            row["raw_id"]: row
            for row in legacy
            if row["raw_id"] in old_only and row["status"] in {"sent", "ok"}
        }
        for row in list(missing_legacy.values())[:5]:
            lines.append(f"旧路径独有: {row['summary'][:60]}")
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
