# tests/unit/archive/test_writer.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.archive.writer import ArchiveWriter


@pytest.mark.asyncio
async def test_write_uses_market_specific_client():
    us_client = MagicMock()
    us_client.append_record = AsyncMock(return_value="r1")
    cn_client = MagicMock()
    cn_client.append_record = AsyncMock(return_value="r2")
    w = ArchiveWriter(clients_by_market={"us": us_client, "cn": cn_client})
    rid = await w.write(market="us", row={"x": 1})
    assert rid == "r1"
    us_client.append_record.assert_awaited_once_with({"x": 1})


@pytest.mark.asyncio
async def test_write_failure_propagates():
    cli = MagicMock()
    cli.append_record = AsyncMock(side_effect=RuntimeError("boom"))
    w = ArchiveWriter(clients_by_market={"us": cli})
    with pytest.raises(RuntimeError):
        await w.write(market="us", row={})
