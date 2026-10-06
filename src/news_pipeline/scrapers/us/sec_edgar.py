"""SEC submissions with ticker resolution and filing document metadata."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime

import httpx

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import ensure_utc, utc_now
from news_pipeline.scrapers.common.contract import (
    SourceContractError,
    require_json_list,
    require_json_mapping,
    require_json_path,
    require_json_string,
)
from news_pipeline.scrapers.common.http import make_async_client

DEFAULT_SEC_CIKS = {
    "NVDA": "1045810",
    "TSLA": "1318605",
    "AMD": "2488",
    "TSM": "1046179",
    "AVGO": "1730168",
    "META": "1326801",
    "GOOGL": "1652044",
}
ITEM_LABELS = {
    "1.01": "签订重大协议",
    "1.02": "终止重大协议",
    "2.01": "完成资产收购或处置",
    "2.02": "经营业绩与财务状况",
    "2.03": "新增重大债务",
    "2.05": "重组或裁撤相关成本",
    "2.06": "重大减值",
    "3.01": "退市或不符合上市标准的通知",
    "4.01": "更换审计机构",
    "4.02": "此前财报不可依赖",
    "5.02": "董事或高管变动",
    "5.07": "股东大会表决结果",
    "7.01": "Reg FD 披露",
    "8.01": "其他事项",
    "9.01": "财务报表及附件",
}
_RECENT_FIELDS = (
    "form",
    "filingDate",
    "acceptanceDateTime",
    "items",
    "primaryDocument",
    "primaryDocDescription",
    "accessionNumber",
)


class SecEdgarScraper:
    source_id = "sec_edgar"
    market = Market.US

    def __init__(
        self,
        *,
        tickers: list[str],
        user_agent: str,
        sec_ciks: Mapping[str, str] | None = None,
        company_names: Mapping[str, str] | None = None,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("sec_edgar: options.user_agent must include a real contact address")
        self._tickers = [ticker.upper() for ticker in tickers]
        self._user_agent = user_agent
        self._fallback_ciks = {**DEFAULT_SEC_CIKS, **(sec_ciks or {})}
        self._company_names = dict(company_names or {})
        self._ciks: dict[str, str] = {}
        self._cache_day: date | None = None

    async def initialize(self) -> None:
        """Validate configured tickers against the daily SEC ticker mapping."""
        async with make_async_client() as client:
            await self._resolve_ciks(client)

    async def _resolve_ciks(self, client: httpx.AsyncClient) -> None:
        today = utc_now().date()
        if self._cache_day == today:
            return
        try:
            response = await client.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers={"User-Agent": self._user_agent},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            ciks = dict(self._fallback_ciks)
        else:
            entries = require_json_mapping(response.json(), "", source=self.source_id)
            ciks = {}
            for entry in entries.values():
                ticker = require_json_string(entry, "ticker", source=self.source_id).upper()
                cik = require_json_path(entry, "cik_str", source=self.source_id)
                ciks[ticker] = str(int(cik))
        missing = [ticker for ticker in self._tickers if not ciks.get(ticker)]
        if missing:
            raise ValueError(f"sec_edgar: cannot resolve configured tickers {missing} to CIK")
        self._ciks = ciks
        self._cache_day = today

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        articles: list[RawArticle] = []
        async with make_async_client() as client:
            await self._resolve_ciks(client)
            for ticker in self._tickers:
                cik = self._ciks[ticker]
                response = await client.get(
                    f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json",
                    headers={"User-Agent": self._user_agent},
                )
                response.raise_for_status()
                payload = require_json_mapping(response.json(), "", source=self.source_id)
                recent = require_json_mapping(payload, "filings.recent", source=self.source_id)
                arrays = {
                    field: require_json_list(recent, field, source=self.source_id)
                    for field in _RECENT_FIELDS
                }
                lengths = {len(values) for values in arrays.values()}
                if len(lengths) != 1:
                    raise SourceContractError(
                        f"sec_edgar: filings.recent array lengths differ: {lengths}"
                    )
                now = utc_now()
                company_name = self._company_names.get(ticker) or payload.get("name", "")
                for index in range(min(len(arrays["form"]), 40)):
                    row = {field: values[index] for field, values in arrays.items()}
                    accepted = require_json_string(row, "acceptanceDateTime", source=self.source_id)
                    ts = ensure_utc(datetime.fromisoformat(accepted))
                    form = require_json_string(row, "form", source=self.source_id)
                    items = require_json_string(row, "items", source=self.source_id)
                    primary_doc = require_json_string(row, "primaryDocument", source=self.source_id)
                    description = require_json_string(
                        row, "primaryDocDescription", source=self.source_id
                    )
                    accession = require_json_string(row, "accessionNumber", source=self.source_id)
                    filing_date = require_json_string(row, "filingDate", source=self.source_id)
                    if ts < since:
                        continue
                    item_labels = "\N{FULLWIDTH SEMICOLON}".join(
                        f"{item.strip()} {ITEM_LABELS.get(item.strip(), '其他事项')}"
                        for item in items.split(",")
                        if item.strip()
                    )
                    company = f"{ticker} {company_name}".strip()
                    title = (
                        f"{company} {form}\N{FULLWIDTH COLON}{item_labels or description or form}"
                    )
                    link = (
                        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                        f"{accession.replace('-', '')}/{primary_doc}"
                    )
                    articles.append(
                        RawArticle(
                            source=self.source_id,
                            market=self.market,
                            fetched_at=now,
                            published_at=ts,
                            url=link,
                            url_hash=url_hash(link),
                            title=title,
                            title_simhash=title_simhash(title),
                            body=None,
                            raw_meta={
                                "ticker": ticker,
                                "cik": cik,
                                "form": form,
                                "items": items,
                                "accession": accession,
                                "primaryDocument": primary_doc,
                                "primaryDocDescription": description,
                                "filingDate": filing_date,
                            },
                        )
                    )
        return articles
