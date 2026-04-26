"""One-off: create the 17 columns the archive writer expects, in both US and CN tables.

Prerequisites:
  - feishu_app_id / feishu_app_secret / feishu_app_token / feishu_table_us / feishu_table_cn
    in config/secrets.yml
  - Self-built app is PUBLISHED and added as **editable** collaborator on both tables

Run:
    uv run python scripts/init_feishu_table.py

Idempotent: skips fields that already exist (matched by name).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

# Make src importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from news_pipeline.config.loader import ConfigLoader  # noqa: E402

# Feishu bitable field types: https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-field/guide
TYPE_TEXT = 1
TYPE_NUMBER = 2
TYPE_SINGLE_SELECT = 3
TYPE_MULTI_SELECT = 4
TYPE_DATE = 5
TYPE_CHECKBOX = 7
TYPE_URL = 15

FIELDS = [
    {"field_name": "news_id", "type": TYPE_NUMBER, "property": {"formatter": "0"}},
    {"field_name": "published_at", "type": TYPE_DATE,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},
    {"field_name": "market", "type": TYPE_SINGLE_SELECT,
     "property": {"options": [{"name": "美股"}, {"name": "A股"}]}},
    {"field_name": "source", "type": TYPE_SINGLE_SELECT, "property": {"options": [
        {"name": "finnhub"}, {"name": "sec_edgar"}, {"name": "yfinance_news"},
        {"name": "caixin_telegram"}, {"name": "akshare_news"}, {"name": "juchao"},
        {"name": "xueqiu"}, {"name": "ths"}, {"name": "tushare_news"},
    ]}},
    {"field_name": "tickers", "type": TYPE_MULTI_SELECT,
     "property": {"options": []}},  # populated dynamically as new tickers appear
    {"field_name": "event_type", "type": TYPE_SINGLE_SELECT, "property": {"options": [
        {"name": "earnings"}, {"name": "m_and_a"}, {"name": "policy"},
        {"name": "price_move"}, {"name": "downgrade"}, {"name": "upgrade"},
        {"name": "filing"}, {"name": "other"},
    ]}},
    {"field_name": "sentiment", "type": TYPE_SINGLE_SELECT, "property": {"options": [
        {"name": "🟢看涨", "color": 2},
        {"name": "🔴看跌", "color": 0},
        {"name": "⚪中性", "color": 14},
    ]}},
    {"field_name": "magnitude", "type": TYPE_SINGLE_SELECT, "property": {"options": [
        {"name": "高"}, {"name": "中"}, {"name": "低"},
    ]}},
    {"field_name": "score", "type": TYPE_NUMBER, "property": {"formatter": "0.0"}},
    {"field_name": "is_critical", "type": TYPE_CHECKBOX},
    {"field_name": "title", "type": TYPE_TEXT},
    {"field_name": "summary", "type": TYPE_TEXT},
    {"field_name": "key_quotes", "type": TYPE_TEXT},
    {"field_name": "url", "type": TYPE_URL},
    {"field_name": "chart_url", "type": TYPE_URL},
    {"field_name": "sent_to", "type": TYPE_MULTI_SELECT, "property": {"options": [
        {"name": "tg_us"}, {"name": "feishu_us"},
        {"name": "tg_cn"}, {"name": "feishu_cn"},
    ]}},
]


async def get_tenant_token(app_id: str, app_secret: str) -> str:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise SystemExit(f"Auth failed: {data}")
        return data["tenant_access_token"]


async def list_existing_fields(token: str, app_token: str, table_id: str) -> set[str]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            headers={"Authorization": f"Bearer {token}"},
            params={"page_size": 100},
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise SystemExit(f"List fields failed: {data}")
        return {f["field_name"] for f in data["data"]["items"]}


async def create_field(token: str, app_token: str, table_id: str, field: dict) -> bool:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            headers={"Authorization": f"Bearer {token}"},
            json=field,
        )
        data = r.json()
        if data.get("code") == 0:
            return True
        # 1254014: field already exists
        if data.get("code") == 1254014:
            return True
        print(f"  ❌ {field['field_name']}: {data}", flush=True)
        return False


async def setup_table(token: str, app_token: str, table_id: str, label: str) -> None:
    print(f"\n=== Setting up {label} table ({table_id}) ===")
    existing = await list_existing_fields(token, app_token, table_id)
    print(f"  Existing fields: {sorted(existing)}")
    for field in FIELDS:
        name = field["field_name"]
        if name in existing:
            print(f"  ⏭  {name} (already exists)")
            continue
        ok = await create_field(token, app_token, table_id, field)
        if ok:
            print(f"  ✅ {name}")


async def main():
    snap = ConfigLoader(Path("config")).load()
    s = snap.secrets.storage
    app_id = s["feishu_app_id"]
    app_secret = s["feishu_app_secret"]
    app_token = s["feishu_app_token"]
    table_us = s["feishu_table_us"]
    table_cn = s["feishu_table_cn"]

    print(f"App: {app_id}")
    print(f"App token: {app_token}")
    print(f"US table: {table_us}")
    print(f"CN table: {table_cn}")

    token = await get_tenant_token(app_id, app_secret)
    print(f"\n✅ Got tenant_access_token")

    await setup_table(token, app_token, table_us, "US")
    await setup_table(token, app_token, table_cn, "CN")

    print("\n✅ Done. Try running the pipeline now.")


if __name__ == "__main__":
    asyncio.run(main())
