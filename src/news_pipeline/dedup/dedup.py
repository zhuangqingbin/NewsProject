# src/news_pipeline/dedup/dedup.py
from dataclasses import dataclass

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.hashing import hamming
from news_pipeline.storage.dao.raw_news import RawNewsDAO


@dataclass
class DedupDecision:
    is_new: bool
    raw_id: int | None = None
    reason: str | None = None


class Dedup:
    def __init__(self, raw_dao: RawNewsDAO, *, title_distance_max: int = 4) -> None:
        self._dao = raw_dao
        self._dist = title_distance_max

    async def check_and_register(self, art: RawArticle) -> DedupDecision:
        existing = await self._dao.find_by_url_hash(art.url_hash)
        if existing is not None and existing.id is not None:
            return DedupDecision(is_new=False, raw_id=existing.id, reason="url_hash")
        for rid, sh in await self._dao.list_recent_simhashes(window_hours=24):
            if hamming(sh, art.title_simhash) <= self._dist:
                return DedupDecision(is_new=False, raw_id=rid, reason="simhash")
        new_id = await self._dao.insert(
            source=art.source,
            market=art.market.value,
            url=str(art.url),
            url_hash=art.url_hash,
            title=art.title,
            title_simhash=art.title_simhash,
            body=art.body,
            raw_meta=art.raw_meta,
            fetched_at_iso=art.fetched_at.isoformat(),
            published_at_iso=art.published_at.isoformat(),
        )
        return DedupDecision(is_new=True, raw_id=new_id)
