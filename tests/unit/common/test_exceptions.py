# tests/unit/common/test_exceptions.py
import pytest

from news_pipeline.common.exceptions import (
    AntiCrawlError,
    CostCeilingExceeded,
    LLMError,
    PipelineError,
    PusherError,
    ScraperError,
)


def test_inheritance():
    assert issubclass(ScraperError, PipelineError)
    assert issubclass(AntiCrawlError, ScraperError)
    assert issubclass(LLMError, PipelineError)
    assert issubclass(PusherError, PipelineError)
    assert issubclass(CostCeilingExceeded, LLMError)


def test_can_raise_with_context():
    with pytest.raises(ScraperError) as exc:
        raise ScraperError("bad", source="finnhub")
    assert exc.value.source == "finnhub"
