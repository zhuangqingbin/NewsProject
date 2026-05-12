# src/news_pipeline/pushers/factory.py
from collections.abc import Mapping

from news_pipeline.config.schema import ChannelsFile, SecretsFile
from shared.push.base import PusherProtocol
from shared.push.feishu import FeishuPusher
from shared.push.wecom import WecomPusher


def _lookup_push(secrets_push: Mapping[str, object], dotted: str) -> str:
    """Lookup a push secret by dotted path 'subsystem.key'.

    Supports both the new nested layout::

        push:
          news_pipeline:
            feishu_hook_cn: <token>

    and the legacy flat layout (migration window)::

        push:
          feishu_hook_cn: <token>

    Priority (highest first):
    1. Dotted path + nested secrets  → direct hit
    2. Dotted path + flat secrets    → try key+"_alert" (quote_watcher), then bare key
    3. Flat key passed directly      → scan all subsystem dicts
    """
    if "." in dotted:
        subsystem, key = dotted.split(".", 1)
        # case 1: new nested layout
        ns = secrets_push.get(subsystem)
        if isinstance(ns, dict) and key in ns:
            return str(ns[key])
        # case 2: dotted path but secrets.yml is still flat — flat fallback.
        # quote_watcher keys had an "_alert" suffix in the old flat layout
        # (e.g. feishu_hook_cn_alert), so check that FIRST to avoid accidentally
        # picking up the same-named news_pipeline key (e.g. feishu_hook_cn).
        if subsystem == "quote_watcher":
            alt = key + "_alert"
            val = secrets_push.get(alt)
            if isinstance(val, str):
                return val
        val = secrets_push.get(key)
        if isinstance(val, str):
            return val
        return ""  # missing → empty → pusher will fail at runtime with a clear error
    # case 3: old code passes a bare flat key (backwards compat)
    for ns in secrets_push.values():
        if isinstance(ns, dict) and dotted in ns:
            return str(ns[dotted])
    val = secrets_push.get(dotted)
    return val if isinstance(val, str) else ""


def build_pushers(
    channels: ChannelsFile,
    secrets: SecretsFile,
) -> dict[str, PusherProtocol]:
    out: dict[str, PusherProtocol] = {}
    for cid, c in channels.channels.items():
        if not c.enabled:
            continue
        opts = c.options
        s = secrets.push
        if c.type == "feishu":
            sign_key_path = opts.get("sign_key", "")
            sign_secret = _lookup_push(s, sign_key_path) if sign_key_path else None
            sign_secret = sign_secret or None  # empty string → None
            out[cid] = FeishuPusher(
                channel_id=cid,
                webhook=_lookup_push(s, opts["webhook_key"]),
                sign_secret=sign_secret,
            )
        elif c.type == "wecom":
            out[cid] = WecomPusher(
                channel_id=cid,
                webhook=_lookup_push(s, opts["webhook_key"]),
            )
    return out
