#!/usr/bin/env python3
"""One-off: migrate watchlist.yml from v0.1.7 flat format to v0.3.0 rules+llm format.

Old format (v0.1.7):
    us: [{ticker, alerts}, ...]
    cn: [{ticker, alerts}, ...]
    macro: [str, ...]
    sectors: [str, ...]

New format (v0.3.0): see docs/superpowers/specs/2026-04-26-watchlist-rules-design.md §2.1

After migration the user must manually:
  * Fill in `name` for each ticker
  * Add `aliases` per stock
  * Reference correct sector/macro_links from the global keyword lists
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml


def _is_cjk(s: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in s)


def migrate(path: Path) -> dict:
    old = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    if "rules" in old or "llm" in old:
        print("⚠ already in v0.3.0 format (has 'rules' or 'llm' top-level key); skipping")
        sys.exit(0)

    us_tickers = old.get("us", [])
    cn_tickers = old.get("cn", [])
    macros = old.get("macro", [])
    sectors = old.get("sectors", [])

    macros_us = [m for m in macros if not _is_cjk(m)]
    macros_cn = [m for m in macros if _is_cjk(m)]
    sectors_us = [s for s in sectors if not _is_cjk(s)]
    sectors_cn = [s for s in sectors if _is_cjk(s)]

    print(f"  migrating {len(us_tickers)} US tickers, {len(cn_tickers)} CN tickers")
    print(f"  macros: {len(macros_us)} → us, {len(macros_cn)} → cn")
    print(f"  sectors: {len(sectors_us)} → us, {len(sectors_cn)} → cn")

    def _entry(t: object) -> dict:
        if isinstance(t, dict):
            return {
                "ticker": str(t["ticker"]),
                "name": "TODO_FILL_NAME",
                "aliases": [],
                "sectors": [],
                "macro_links": [],
                "alerts": t.get("alerts", []),
            }
        return {
            "ticker": str(t),
            "name": "TODO_FILL_NAME",
            "aliases": [],
            "sectors": [],
            "macro_links": [],
            "alerts": [],
        }

    return {
        "rules": {
            "enable": True,
            "gray_zone_action": "digest",
            "matcher": "aho_corasick",
            "us": [_entry(t) for t in us_tickers],
            "cn": [_entry(t) for t in cn_tickers],
            "keyword_list": {"us": [], "cn": []},
            "macro_keywords": {"us": macros_us, "cn": macros_cn},
            "sector_keywords": {"us": sectors_us, "cn": sectors_cn},
        },
        "llm": {
            "enable": False,
            "us": [str(t["ticker"]) if isinstance(t, dict) else str(t) for t in us_tickers],
            "cn": [str(t["ticker"]) if isinstance(t, dict) else str(t) for t in cn_tickers],
            "macro": macros,
            "sectors": sectors,
        },
    }


def main() -> int:
    path = Path("config/watchlist.yml")
    if not path.exists():
        print(f"❌ {path} not found; run from project root")
        return 1

    backup = path.parent / f"watchlist.yml.v0_1_7.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"🔒 backing up to {backup}")
    shutil.copy2(path, backup)

    new = migrate(path)
    path.write_text(
        yaml.safe_dump(new, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )

    print(f"\n✅ migrated. Now MANUALLY edit {path} to:")
    print("   1. Replace TODO_FILL_NAME with each ticker's full name")
    print("   2. Add aliases per ticker (e.g., NVDA → 英伟达, 老黄家)")
    print("   3. Reference sector / macro names from the global keyword lists")
    print("   4. Optionally add keyword_list entries (Powell, recession, etc.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
