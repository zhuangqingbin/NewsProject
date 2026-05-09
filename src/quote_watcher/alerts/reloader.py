"""AlertsReloader: watch config/alerts.yml and hot-swap engine rules on change."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertsFile
from shared.observability.log import get_logger

log = get_logger(__name__)


class AlertsReloader:
    def __init__(self, *, alerts_path: Path, engine: AlertEngine) -> None:
        self._path = alerts_path
        self._engine = engine
        self._observer: Any | None = None

    def reload_now(self) -> bool:
        """Read alerts file once, validate, swap engine rules. Returns True on success."""
        if not self._path.exists():
            log.warning("alerts_file_missing", path=str(self._path))
            return False
        try:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8"))
            alerts = AlertsFile.model_validate(data) if data else AlertsFile()
        except Exception as e:
            log.warning("alerts_reload_failed", error=str(e), path=str(self._path))
            return False
        self._engine.update_rules(alerts.alerts)
        log.info("alerts_reloaded", count=len(alerts.alerts))
        return True

    def start(self) -> None:
        """Begin watching the parent directory for changes to alerts.yml."""
        if self._observer is not None:
            return
        handler = _ReloadHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self._path.parent), recursive=False)
        self._observer.start()

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=5)
        self._observer = None


class _ReloadHandler(FileSystemEventHandler):
    def __init__(self, reloader: AlertsReloader) -> None:
        self._reloader = reloader

    def on_modified(self, event: object) -> None:
        if isinstance(event, FileModifiedEvent):
            target = self._reloader._path.resolve()
            src = event.src_path
            if isinstance(src, bytes):
                src = src.decode()
            if Path(src).resolve() == target:
                self._reloader.reload_now()
