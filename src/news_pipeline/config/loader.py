# src/news_pipeline/config/loader.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from news_pipeline.config.schema import (
    AppConfig,
    ChannelsFile,
    FirstPartyConfig,
    HoldingsFile,
    QuoteWatchlistFile,
    ScoringConfig,
    SecretsFile,
    SourcesFile,
    WatchlistFile,
)
from quote_watcher.alerts.rule import AlertsFile


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
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    first_party: FirstPartyConfig = field(default_factory=FirstPartyConfig)


class ConfigLoader:
    def __init__(self, base_dir: Path) -> None:
        self._dir = Path(base_dir)

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
            AlertsFile.model_validate(yaml.safe_load(alerts_path.read_text(encoding="utf-8")) or {})
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
            scoring=ScoringConfig.model_validate(
                self._read_optional("news_pipeline", "scoring.yml")
            ),
            first_party=FirstPartyConfig.model_validate(
                self._read_optional("news_pipeline", "first_party.yml")
            ),
        )

    def _read_optional(self, subdir: str, name: str) -> dict[str, object]:
        if not (self._dir / subdir / name).exists():
            return {}
        return self._read(subdir, name)

    def _read(self, subdir: str, name: str) -> dict[str, object]:
        path = self._dir / subdir / name
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
