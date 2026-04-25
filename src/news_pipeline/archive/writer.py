# src/news_pipeline/archive/writer.py
from typing import Any

from news_pipeline.archive.feishu_table import FeishuBitableClient


class ArchiveWriter:
    def __init__(
        self,
        *,
        clients_by_market: dict[str, FeishuBitableClient],
    ) -> None:
        self._clients = clients_by_market

    async def write(self, *, market: str, row: dict[str, Any]) -> str:
        cli = self._clients.get(market)
        if cli is None:
            raise KeyError(f"no archive client for market={market}")
        return await cli.append_record(row)
