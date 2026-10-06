import logging
import subprocess
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import yaml

from quote_watcher.health import QuoteFeedHealth
from shared.common.timeutil import utc_now
from shared.observability.log import configure_logging


def test_http_clients_do_not_log_webhook_urls():
    configure_logging()
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


def test_entrypoint_only_app_migrates(tmp_path):
    compose = yaml.safe_load(Path("docker-compose.yml").read_text())
    assert compose["services"]["app"]["environment"]["RUN_MIGRATIONS"] == "1"
    assert "RUN_MIGRATIONS" not in compose["services"]["quote_watcher"]["environment"]
    assert compose["services"]["quote_watcher"]["healthcheck"]
    result = subprocess.run(
        ["sh", "docker/entrypoint.sh", "true"],
        capture_output=True,
        text=True,
        env={"PATH": "/bin:/usr/bin", "RUN_MIGRATIONS": "0"},
    )
    assert result.returncode == 0
    assert "alembic" not in result.stdout


async def test_quote_outage_only_alerts_on_transitions():
    bark = AsyncMock()
    health = QuoteFeedHealth(bark)
    now = utc_now()
    await health.observe(False, trading=True, now=now)
    await health.observe(False, trading=True, now=now + timedelta(minutes=5))
    await health.observe(False, trading=True, now=now + timedelta(minutes=6))
    assert bark.send.await_count == 1
    await health.observe(True, trading=True, now=now + timedelta(minutes=7))
    assert bark.send.await_count == 2
    await health.observe(False, trading=False, now=now + timedelta(hours=1))
    assert bark.send.await_count == 2
