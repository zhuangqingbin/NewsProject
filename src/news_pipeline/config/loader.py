# src/news_pipeline/config/loader.py
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from news_pipeline.config.schema import (
    AppConfig,
    ChannelsFile,
    HoldingsFile,
    QuoteWatchlistFile,
    SecretsFile,
    SourcesFile,
    WatchlistFile,
)
from quote_watcher.alerts.rule import AlertsFile
from shared.observability.log import get_logger

log = get_logger(__name__)


@dataclass
class ConfigSnapshot:
    app: AppConfig
    watchlist: WatchlistFile
    channels: ChannelsFile
    sources: SourcesFile
    secrets: SecretsFile
    quote_watchlist: QuoteWatchlistFile
    alerts: AlertsFile
    holdings: HoldingsFile = field(default_factory=HoldingsFile)


class _Handler(FileSystemEventHandler):
    def __init__(self, on_change: Callable[[FileSystemEvent], None]) -> None:
        self._on_change = on_change

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._on_change(event)


class ConfigLoader:
    def __init__(self, base_dir: Path, debounce_ms: int = 250) -> None:
        self._dir = Path(base_dir)
        self._debounce_ms = debounce_ms
        self._observer: Any = None
        self._lock = threading.Lock()
        self._last_event_at: float = 0.0
        self._callback: Callable[[ConfigSnapshot], None] | None = None

    def load(self) -> ConfigSnapshot:
        qw_path = self._dir / "quote_watcher" / "quote_watchlist.yml"
        quote_watchlist = (
            QuoteWatchlistFile.model_validate(
                yaml.safe_load(qw_path.read_text(encoding="utf-8")) or {}
            )
            if qw_path.exists()
            else QuoteWatchlistFile()
        )
        alerts_path = self._dir / "quote_watcher" / "alerts.yml"
        alerts = (
            AlertsFile.model_validate(
                yaml.safe_load(alerts_path.read_text(encoding="utf-8")) or {}
            )
            if alerts_path.exists()
            else AlertsFile()
        )
        holdings_path = self._dir / "quote_watcher" / "holdings.yml"
        holdings = (
            HoldingsFile.model_validate(
                yaml.safe_load(holdings_path.read_text(encoding="utf-8")) or {}
            )
            if holdings_path.exists()
            else HoldingsFile()
        )
        return ConfigSnapshot(
            app=AppConfig.model_validate(self._read("common", "app.yml")),
            watchlist=WatchlistFile.model_validate(self._read("news_pipeline", "watchlist.yml")),
            channels=ChannelsFile.model_validate(self._read("common", "channels.yml")),
            sources=SourcesFile.model_validate(self._read("news_pipeline", "sources.yml")),
            secrets=SecretsFile.model_validate(self._read("common", "secrets.yml")),
            quote_watchlist=quote_watchlist,
            alerts=alerts,
            holdings=holdings,
        )

    def _read(self, subdir: str, name: str) -> dict[str, object]:
        path = self._dir / subdir / name
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def start_watching(self, callback: Callable[[ConfigSnapshot], None]) -> None:
        self._callback = callback
        self._observer = Observer()
        self._observer.schedule(_Handler(self._on_event), str(self._dir), recursive=True)
        self._observer.start()

    def stop_watching(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None

    def _on_event(self, _event: FileSystemEvent) -> None:
        with self._lock:
            now = time.monotonic() * 1000
            if (now - self._last_event_at) < self._debounce_ms:
                return
            self._last_event_at = now
        try:
            snap = self.load()
        except Exception as e:
            log.error("config_reload_failed", error=str(e))
            return
        if self._callback is not None:
            self._callback(snap)
