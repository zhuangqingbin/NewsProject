# src/news_pipeline/common/exceptions.py
from typing import Any


class PipelineError(Exception):
    def __init__(self, message: str = "", **context: Any) -> None:
        super().__init__(message)
        self.context = context


class ScraperError(PipelineError):
    def __init__(self, message: str = "", *, source: str = "", **ctx: Any) -> None:
        super().__init__(message, source=source, **ctx)
        self.source = source


class AntiCrawlError(ScraperError):
    pass


class LLMError(PipelineError):
    pass


class CostCeilingExceeded(LLMError):
    pass


class PusherError(PipelineError):
    def __init__(self, message: str = "", *, channel: str = "", **ctx: Any) -> None:
        super().__init__(message, channel=channel, **ctx)
        self.channel = channel
