from collections.abc import Sequence

from news_pipeline.common.contracts import RawArticle
from news_pipeline.storage.dao.raw_news import RawNewsDAO


class ArticleStore:
    """Persist every distinct URL; event clustering handles content overlap."""

    def __init__(self, raw: RawNewsDAO) -> None:
        self._raw = raw
        self.saved_count = 0

    async def save(self, items: Sequence[RawArticle], *, status: str = "pending") -> int:
        known = await self._raw.existing_url_hashes([article.url_hash for article in items])
        self.saved_count = 0
        for article in items:
            if article.url_hash in known:
                continue
            await self._raw.insert_article(article, status=status)
            self.saved_count += 1
            known.add(article.url_hash)
        return self.saved_count
