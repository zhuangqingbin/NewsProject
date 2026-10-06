import json
from datetime import datetime, timedelta
from pathlib import Path

from shared.common.timeutil import ensure_utc, utc_now


class Heartbeat:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.jobs: dict[str, str] = {}

    def complete(self, job: str) -> None:
        self.jobs[job] = utc_now().isoformat()

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"at": utc_now().isoformat(), "jobs": self.jobs}), encoding="utf-8"
        )
        temporary.replace(self.path)


def heartbeat_healthy(path: Path, *, now: datetime | None = None) -> bool:
    try:
        at = ensure_utc(datetime.fromisoformat(json.loads(path.read_text())["at"]))
        age = ensure_utc(now or utc_now()) - at
        return timedelta(seconds=-60) <= age <= timedelta(minutes=3)
    except (OSError, ValueError, KeyError, TypeError):
        return False
