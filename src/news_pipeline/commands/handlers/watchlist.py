from pathlib import Path
from typing import Any

import yaml

from news_pipeline.commands.dispatcher import CommandDispatcher


def _is_us(ticker: str) -> bool:
    return ticker.isalpha()


def register_watchlist_cmds(d: CommandDispatcher, *,
                              watchlist_path: Path) -> None:

    @d.register("watch")
    async def watch(args: list[str], ctx: dict[str, Any]) -> str:
        if not args:
            return "用法: /watch TICKER [...]"
        data = yaml.safe_load(watchlist_path.read_text(encoding="utf-8"))
        added: list[str] = []
        for t in args:
            key = "us" if _is_us(t) else "cn"
            existing = {e["ticker"] for e in data.get(key, [])}
            if t in existing:
                continue
            data.setdefault(key, []).append({"ticker": t, "alerts": []})
            added.append(t)
        watchlist_path.write_text(yaml.safe_dump(data, allow_unicode=True))
        return f"已加入: {', '.join(added)}" if added else "无变化"

    @d.register("unwatch")
    async def unwatch(args: list[str], ctx: dict[str, Any]) -> str:
        if not args:
            return "用法: /unwatch TICKER [...]"
        data = yaml.safe_load(watchlist_path.read_text(encoding="utf-8"))
        removed: list[str] = []
        for t in args:
            for key in ("us", "cn"):
                lst = data.get(key, [])
                new = [e for e in lst if e["ticker"] != t]
                if len(new) != len(lst):
                    data[key] = new
                    removed.append(t)
                    break
        watchlist_path.write_text(yaml.safe_dump(data, allow_unicode=True))
        return f"已移除: {', '.join(removed)}" if removed else "无变化"

    @d.register("list")
    async def list_(args: list[str], ctx: dict[str, Any]) -> str:
        data = yaml.safe_load(watchlist_path.read_text(encoding="utf-8"))
        us = ", ".join(e["ticker"] for e in data.get("us", []))
        cn = ", ".join(e["ticker"] for e in data.get("cn", []))
        macro = ", ".join(data.get("macro", []))
        sectors = ", ".join(data.get("sectors", []))
        return (f"美股: {us or '(空)'}\nA股: {cn or '(空)'}\n"
                f"宏观: {macro or '(空)'}\n板块: {sectors or '(空)'}")
