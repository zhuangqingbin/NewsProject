# src/news_pipeline/pushers/factory.py
from news_pipeline.config.schema import ChannelsFile, SecretsFile
from news_pipeline.pushers.base import PusherProtocol
from news_pipeline.pushers.feishu import FeishuPusher
from news_pipeline.pushers.wecom import WecomPusher


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
            sign_key = opts.get("sign_key", "")
            out[cid] = FeishuPusher(
                channel_id=cid,
                webhook=s[opts["webhook_key"]],
                sign_secret=s.get(sign_key) or None,
            )
        elif c.type == "wecom":
            out[cid] = WecomPusher(
                channel_id=cid,
                webhook=s[opts["webhook_key"]],
            )
    return out
