import asyncio
from datetime import timedelta

import httpx
import requests
from curl_cffi.curl import CurlError

from news_pipeline.common.timeutil import utc_now
from news_pipeline.config.schema import SourceDef
from news_pipeline.ingest.store import ArticleStore
from news_pipeline.scrapers.base import ScraperProtocol
from news_pipeline.storage.dao.metrics import MetricsDAO
from news_pipeline.storage.dao.source_state import SourceStateDAO
from shared.observability.alert import BarkAlerter
from shared.observability.log import get_logger

log = get_logger(__name__)

_TRANSIENT_EXC = (
    httpx.TimeoutException,
    httpx.ConnectError,
    # akshare uses `requests` — same kind of transient
    # network errors need the same treatment (retry next tick, no alert).
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
    # akshare's modern transport is curl_cffi (TLS fingerprint impersonation);
    # raw curl-level failures like CURLE_OPERATION_TIMEDOUT (28) surface as
    # CurlError("Failed to perform, curl: (28) Operation timed out...") and
    # are network transients, not bugs.
    CurlError,
)


def _is_transient(exc: BaseException) -> bool:
    """Return True if the exception is a known transient network error."""
    return isinstance(exc, _TRANSIENT_EXC) or (
        isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500
    )


async def scrape_one_source(
    *,
    scraper: ScraperProtocol,
    state_dao: SourceStateDAO,
    store: ArticleStore,
    cfg: SourceDef | None = None,
    metrics: MetricsDAO | None = None,
    bark: BarkAlerter | None = None,
) -> int:
    source_cfg = cfg or SourceDef()
    sid = scraper.source_id
    if await state_dao.is_paused(sid):
        return 0
    since = utc_now() - timedelta(minutes=source_cfg.lookback_min)
    try:
        items = await asyncio.wait_for(scraper.fetch(since), timeout=source_cfg.fetch_timeout_sec)
        state = await state_dao.get(sid)
        first = state is None or state.last_success_at is None
        count = await store.save(items, status="seeded" if first else "pending")
    except Exception as error:
        await state_dao.record_failure(
            sid,
            error=repr(error),
            structural=not _is_transient(error),
            base_interval=source_cfg.interval_sec or 60,
        )
        log.warning("scrape_failed", source=sid, error=repr(error))
        return 0
    await state_dao.record_success(sid, new_items=store.saved_count)
    if metrics is not None:
        await metrics.increment(
            date_iso=utc_now().date().isoformat(),
            name="scrape_new",
            dimensions=f"source={sid}",
            delta=count,
        )
    log.info("scrape_done", source=sid, new=count, total=len(items), seeded=first)
    return count
