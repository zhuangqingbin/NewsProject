from datetime import UTC, datetime

import httpx
import pytest
import respx
from freezegun import freeze_time

from news_pipeline.scrapers.common.contract import SourceContractError
from news_pipeline.scrapers.us.sec_edgar import SecEdgarScraper

TABLE_URL = "https://www.sec.gov/files/company_tickers.json"
SUB_URL = "https://data.sec.gov/submissions/CIK0001318605.json"
UA = "NewsProject contact@example.org"
TABLE = {"0": {"ticker": "TSLA", "cik_str": 1318605, "title": "Tesla, Inc."}}


def recent(count=1):
    return {
        "name": "Tesla, Inc.",
        "filings": {
            "recent": {
                "form": ["8-K"] * count,
                "filingDate": ["2026-10-02"] * count,
                "acceptanceDateTime": ["2026-10-02T13:04:26.000Z"] * count,
                "items": ["2.02,9.01"] * count,
                "primaryDocument": ["tsla-20261002.htm"] * count,
                "primaryDocDescription": ["Current report"] * count,
                "accessionNumber": [f"0001628280-26-{64366 + i:06d}" for i in range(count)],
            }
        },
    }


def source(tickers=None, **kwargs):
    return SecEdgarScraper(tickers=tickers or ["TSLA"], user_agent=UA, **kwargs)


async def test_submissions_use_acceptance_time_main_document_and_item_labels():
    with respx.mock() as mock:
        table = mock.get(TABLE_URL).respond(200, json=TABLE)
        submission = mock.get(SUB_URL).respond(200, json=recent())
        items = await source().fetch(datetime(2026, 10, 1, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].published_at == datetime(2026, 10, 2, 13, 4, 26, tzinfo=UTC)
    assert "TSLA" in items[0].title and "Tesla" in items[0].title
    assert (
        "8-K\N{FULLWIDTH COLON}2.02 经营业绩与财务状况\N{FULLWIDTH SEMICOLON}9.01 财务报表及附件"
        in items[0].title
    )
    assert str(items[0].url) == (
        "https://www.sec.gov/Archives/edgar/data/1318605/000162828026064366/tsla-20261002.htm"
    )
    assert items[0].raw_meta == {
        "ticker": "TSLA",
        "cik": "1318605",
        "form": "8-K",
        "items": "2.02,9.01",
        "accession": "0001628280-26-064366",
        "primaryDocument": "tsla-20261002.htm",
        "primaryDocDescription": "Current report",
        "filingDate": "2026-10-02",
    }
    assert table.calls[0].request.headers["user-agent"] == UA
    assert submission.calls[0].request.headers["user-agent"] == UA


async def test_limit_first_40_filings_and_since_filter():
    with respx.mock() as mock:
        mock.get(TABLE_URL).respond(200, json=TABLE)
        mock.get(SUB_URL).respond(200, json=recent(42))
        scraper = source()
        assert len(await scraper.fetch(datetime(2026, 10, 1, tzinfo=UTC))) == 40
        assert await scraper.fetch(datetime(2030, 1, 1, tzinfo=UTC)) == []


async def test_ticker_table_cached_and_refreshed_daily():
    scraper = source()
    with respx.mock() as mock:
        table = mock.get(TABLE_URL).respond(200, json=TABLE)
        mock.get(SUB_URL).respond(200, json=recent())
        with freeze_time("2026-10-06 10:00:00"):
            await scraper.initialize()
            await scraper.fetch(datetime(2026, 10, 1, tzinfo=UTC))
            await scraper.fetch(datetime(2026, 10, 1, tzinfo=UTC))
            assert table.call_count == 1
        with freeze_time("2026-10-07 10:00:00"):
            await scraper.fetch(datetime(2026, 10, 1, tzinfo=UTC))
        assert table.call_count == 2


async def test_ticker_table_http_failure_uses_all_seven_fallback_ciks():
    ciks = {
        "NVDA": "1045810",
        "TSLA": "1318605",
        "AMD": "2488",
        "TSM": "1046179",
        "AVGO": "1730168",
        "META": "1326801",
        "GOOGL": "1652044",
    }
    with respx.mock() as mock:
        table = mock.get(TABLE_URL).respond(503)
        for cik in ciks.values():
            mock.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json").respond(
                200, json=recent(0)
            )
        scraper = source(list(ciks))
        assert await scraper.fetch(datetime(2020, 1, 1, tzinfo=UTC)) == []
        assert await scraper.fetch(datetime(2020, 1, 1, tzinfo=UTC)) == []
        assert table.call_count == 1


async def test_explicit_fallback_cik_is_used_when_table_unavailable():
    with respx.mock() as mock:
        mock.get(TABLE_URL).mock(side_effect=httpx.ConnectError("network unavailable"))
        route = mock.get("https://data.sec.gov/submissions/CIK0000000123.json").respond(
            200, json=recent(0)
        )
        await source(["NEW"], sec_ciks={"NEW": "123"}).fetch(datetime(2020, 1, 1, tzinfo=UTC))
        assert route.call_count == 1


async def test_unknown_ticker_is_configuration_error():
    with respx.mock() as mock:
        mock.get(TABLE_URL).respond(200, json=TABLE)
        with pytest.raises(ValueError, match=r"sec_edgar.*UNKNOWN"):
            await source(["UNKNOWN"]).initialize()


@pytest.mark.parametrize("user_agent", ["", " "])
def test_missing_sec_user_agent_is_configuration_error(user_agent):
    with pytest.raises(ValueError, match=r"sec_edgar.*user_agent"):
        SecEdgarScraper(tickers=["TSLA"], user_agent=user_agent)


@pytest.mark.parametrize("payload", [{}, {"filings": {"recent": {}}}, {"filings": {"recent": []}}])
async def test_missing_submissions_structure_raises(payload):
    with respx.mock() as mock:
        mock.get(TABLE_URL).respond(200, json=TABLE)
        mock.get(SUB_URL).respond(200, json=payload)
        with pytest.raises(SourceContractError):
            await source().fetch(datetime(2020, 1, 1, tzinfo=UTC))


async def test_mismatched_recent_array_lengths_raise():
    payload = recent()
    payload["filings"]["recent"]["items"] = []
    with respx.mock() as mock:
        mock.get(TABLE_URL).respond(200, json=TABLE)
        mock.get(SUB_URL).respond(200, json=payload)
        with pytest.raises(SourceContractError, match="length"):
            await source().fetch(datetime(2020, 1, 1, tzinfo=UTC))


async def test_submissions_http_error_propagates():
    with respx.mock() as mock:
        mock.get(TABLE_URL).respond(200, json=TABLE)
        mock.get(SUB_URL).respond(503)
        with pytest.raises(httpx.HTTPStatusError):
            await source().fetch(datetime(2020, 1, 1, tzinfo=UTC))


async def test_bad_ticker_table_structure_is_not_hidden_by_fallback():
    with respx.mock() as mock:
        mock.get(TABLE_URL).respond(200, json={"0": {"ticker": "TSLA"}})
        with pytest.raises(SourceContractError):
            await source().initialize()
