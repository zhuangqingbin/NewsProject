"""AlertVerdict — what AlertEngine emits when a rule fires."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quote_watcher.alerts.rule import AlertRule
from quote_watcher.feeds.base import QuoteSnapshot


@dataclass(frozen=True)
class AlertVerdict:
    rule: AlertRule
    snapshot: QuoteSnapshot
    ctx_dump: dict[str, Any] = field(default_factory=dict)
