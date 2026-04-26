"""Add the self-built app as an editable collaborator on both bitable files.

Bypasses the UI entirely. Uses drive permission v2 API.
Requires the app to have `drive:drive` scope (read+write).

Run:
    uv run python scripts/add_app_collaborator.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from news_pipeline.config.loader import ConfigLoader  # noqa: E402


async def get_token(c: httpx.AsyncClient, app_id: str, app_secret: str) -> str:
    r = await c.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
    )
    return r.json()["tenant_access_token"]


async def list_members(c: httpx.AsyncClient, token: str, file_token: str) -> dict:
    r = await c.get(
        f"https://open.feishu.cn/open-apis/drive/v1/permissions/{file_token}/members",
        headers={"Authorization": f"Bearer {token}"},
        params={"type": "bitable"},
    )
    return r.json()


async def add_app_as_member(
    c: httpx.AsyncClient, token: str, file_token: str, app_id: str
) -> dict:
    """Try multiple member_type variants since Feishu's docs are inconsistent."""
    variants = [
        # Newest API (drive/v2): app as member
        {
            "member_type": "appid",
            "member_id": app_id,
            "perm": "edit",
            "type": "bitable",
        },
        # Sometimes "openchat" syntax wraps the app
        {
            "member_type": "openid",
            "member_id": app_id,
            "perm": "edit",
            "type": "bitable",
        },
    ]
    last = None
    for v in variants:
        body = {k: v[k] for k in ["member_type", "member_id", "perm", "type"]}
        r = await c.post(
            f"https://open.feishu.cn/open-apis/drive/v1/permissions/{file_token}/members",
            headers={"Authorization": f"Bearer {token}"},
            params={"need_notification": "false"},
            json=body,
        )
        data = r.json()
        last = data
        print(f"  try member_type={v['member_type']:>10}: code={data.get('code')}, msg={data.get('msg')}")
        if data.get("code") == 0:
            return data
    return last or {}


async def main():
    snap = ConfigLoader(Path("config")).load()
    s = snap.secrets.storage

    app_id = s["feishu_app_id"]
    app_secret = s["feishu_app_secret"]
    app_token = s["feishu_app_token"]

    print(f"App: {app_id}")
    print(f"Bitable file (app_token): {app_token}\n")

    async with httpx.AsyncClient(timeout=15) as c:
        token = await get_token(c, app_id, app_secret)
        print("✅ Got tenant_access_token\n")

        print("=== Current members ===")
        ms = await list_members(c, token, app_token)
        if ms.get("code") == 0:
            for m in ms["data"].get("items", []):
                print(f"  - type={m.get('member_type')}, id={m.get('member_id')[:30]}..., perm={m.get('perm')}")
        else:
            print(f"  ❌ list failed: code={ms.get('code')}, msg={ms.get('msg')}")
            print(f"  → app probably lacks drive:drive scope, or no permission to query")
        print()

        print("=== Adding app as editable collaborator on the BITABLE FILE ===")
        result = await add_app_as_member(c, token, app_token, app_id)
        if result.get("code") == 0:
            print("\n  ✅ ADDED! Now run scripts/init_feishu_table.py")
        else:
            print(f"\n  ❌ Failed: {result}")
            print("\n  Likely causes:")
            print("    1063004 / 1254010 → app has no drive:drive scope; add it + redeploy")
            print("    1062001 → wrong file_token (should be the bitable's app_token, not table_id)")
            print("    1063015 → can't share file (file owner is in different tenant)")
            print("    20100   → bitable / file does not allow app as collaborator")


if __name__ == "__main__":
    asyncio.run(main())
