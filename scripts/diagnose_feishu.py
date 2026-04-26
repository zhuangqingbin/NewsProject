"""Diagnose Feishu bitable access issues.

Walks through:
  1. Get tenant_access_token (verify app_id/app_secret correct)
  2. List app's authorized scopes (verify bitable:app actually granted)
  3. Try GET app metadata (verify app can see the bitable at all)
  4. Try LIST table fields (verify can read this specific table)
  5. Try LIST permission members (see who has access)
  6. Print exact errcode for each step

Run:
    uv run python scripts/diagnose_feishu.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from news_pipeline.config.loader import ConfigLoader  # noqa: E402


async def main():
    snap = ConfigLoader(Path("config")).load()
    s = snap.secrets.storage

    app_id = s["feishu_app_id"]
    app_secret = s["feishu_app_secret"]
    app_token = s["feishu_app_token"]
    table_us = s["feishu_table_us"]

    print(f"app_id:    {app_id}")
    print(f"app_token: {app_token}  (the bitable file)")
    print(f"table_us:  {table_us}")
    print()

    async with httpx.AsyncClient(timeout=15) as c:

        # === Step 1: tenant_access_token ===
        print("=== Step 1: get tenant_access_token ===")
        r = await c.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        data = r.json()
        print(f"  HTTP {r.status_code}, code={data.get('code')}, msg={data.get('msg')}")
        if data.get("code") != 0:
            print(f"  ❌ FAIL: {data}")
            print(f"  → 检查 feishu_app_id / feishu_app_secret 是否正确")
            return
        token = data["tenant_access_token"]
        print(f"  ✅ token (first 20 chars): {token[:20]}...")
        print()

        H = {"Authorization": f"Bearer {token}"}

        # === Step 2: list app authorized scopes (best-effort, endpoint deprecated) ===
        print("=== Step 2: list authorized scopes (skip if endpoint deprecated) ===")
        try:
            r = await c.get(
                "https://open.feishu.cn/open-apis/application/v6/applications/self/scopes",
                headers=H,
            )
            data = r.json()
            if r.status_code == 200 and data.get("code") == 0:
                scopes = data.get("data", {}).get("scopes", [])
                bitable_scopes = [s for s in scopes if "bitable" in s.get("scope_name", "")]
                print(f"  total scopes: {len(scopes)}")
                print("  bitable-related:")
                for s_ in bitable_scopes:
                    print(f"    - {s_['scope_name']}: {s_.get('grant_status', '?')}")
            else:
                print(f"  (skipped — code={data.get('code')})")
        except Exception as e:
            print(f"  (skipped — endpoint returned non-JSON: {type(e).__name__})")
        print()

        # === Step 3: GET bitable app metadata ===
        print("=== Step 3: GET bitable app metadata ===")
        r = await c.get(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}",
            headers=H,
        )
        data = r.json()
        print(f"  HTTP {r.status_code}, code={data.get('code')}, msg={data.get('msg')}")
        if data.get("code") == 0:
            app = data["data"]["app"]
            print(f"  ✅ app name: {app.get('name')}")
            print(f"     revision: {app.get('revision')}")
            print(f"     is_advanced: {app.get('is_advanced')}")
        else:
            print(f"  ❌ {data}")
            if data.get("code") == 1254003:
                print("  → app_token wrong, OR app has no access. Verify the URL pattern:")
                print("     https://feishu.cn/base/<APP_TOKEN>?table=<TABLE_ID>&...")
        print()

        # === Step 4: LIST table fields (where the writes will go) ===
        print(f"=== Step 4: LIST fields in US table ({table_us}) ===")
        r = await c.get(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_us}/fields",
            headers=H,
            params={"page_size": 100},
        )
        data = r.json()
        print(f"  HTTP {r.status_code}, code={data.get('code')}, msg={data.get('msg')}")
        if data.get("code") == 0:
            items = data["data"]["items"]
            print(f"  ✅ existing fields ({len(items)}):")
            for f in items:
                print(f"    - {f['field_name']}  (type={f.get('type')})")
        else:
            print(f"  ❌ {data}")
            if data.get("code") == 99991661:
                print("  → app not found / not published")
            elif data.get("code") == 99991663:
                print("  → invalid token")
            elif data.get("code") == 99991668:
                print("  → no permission. Common causes:")
                print("    a) bitable:app scope not granted (check Step 2 above)")
                print("    b) app published version doesn't have current scopes — REDEPLOY")
                print("    c) bitable file is in a different tenant than the app")
            elif data.get("code") == 1254030:
                print("  → table not found. table_us value wrong.")
        print()

        # === Step 5: LIST permission members ===
        print(f"=== Step 5: LIST permission members on the bitable file ===")
        r = await c.get(
            f"https://open.feishu.cn/open-apis/drive/v1/permissions/{app_token}/members",
            headers=H,
            params={"type": "bitable"},
        )
        data = r.json()
        print(f"  HTTP {r.status_code}, code={data.get('code')}, msg={data.get('msg')}")
        if data.get("code") == 0:
            members = data["data"].get("items", [])
            print(f"  current members ({len(members)}):")
            for m in members:
                print(f"    - type={m.get('member_type')}, id={m.get('member_id')[:30]}..., perm={m.get('perm')}")
        else:
            print(f"  ❌ {data}")
            print("  → may need drive:drive scope to query this")


if __name__ == "__main__":
    asyncio.run(main())
