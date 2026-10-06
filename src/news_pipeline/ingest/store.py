from collections.abc import Sequence

from news_pipeline.common.contracts import RawArticle
from news_pipeline.storage.dao.raw_news import RawNewsDAO


class ArticleStore:
    def __init__(
        self, raw: RawNewsDAO, *, title_distance_max: int = 4, mode: str = "legacy"
    ) -> None:
        self._raw = raw
        self._dist = title_distance_max
        self._mode = mode

    async def save(self, items: Sequence[RawArticle], *, status: str = "pending") -> int:
        known = await self._raw.existing_url_hashes([a.url_hash for a in items])
        title_dedup = self._mode != "v2" and status != "seeded"
        recent = await self._raw.list_recent_simhashes() if title_dedup else []
        count = 0
        self.saved_count = 0
        for article in items:
            if article.url_hash in known:
                continue
            duplicate = next(
                (
                    rid
                    for rid, sh in recent
                    if sh
                    and article.title_simhash
                    and ((sh ^ article.title_simhash) & ((1 << 64) - 1)).bit_count() <= self._dist
                ),
                None,
            )
            rid = await self._raw.insert_article(
                article,
                status="duplicate" if duplicate is not None else status,
                extra_meta={"dup_of": duplicate} if duplicate is not None else None,
            )
            self.saved_count += 1
            known.add(article.url_hash)
            if title_dedup:
                recent.append((rid, article.title_simhash))
            count += duplicate is None
        return count
