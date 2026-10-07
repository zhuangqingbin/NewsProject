# tests/unit/config/test_loader.py
from pathlib import Path

import pytest

from news_pipeline.config.loader import ConfigLoader


@pytest.fixture
def cfg_dir(tmp_path: Path) -> Path:
    common = tmp_path / "common"
    common.mkdir()
    news = tmp_path / "news_pipeline"
    news.mkdir()
    qw = tmp_path / "quote_watcher"
    qw.mkdir()

    (common / "app.yml").write_text(_minimal_app_yml())
    (common / "channels.yml").write_text("channels: {}\n")
    (common / "secrets.yml").write_text(
        "llm: {}\npush: {}\nstorage: {}\noss: {}\nsources: {}\nalert: {}\n"
    )
    (news / "watchlist.yml").write_text("rules: {us: [], cn: []}\n")
    (news / "sources.yml").write_text("sources: {}\n")
    return tmp_path


def _minimal_app_yml() -> str:
    return "pipeline: {mode: v2}\nllm: {enabled: false, daily_cost_ceiling_cny: 5.0}\n"


def test_loader_loads_all(cfg_dir: Path) -> None:
    loader = ConfigLoader(cfg_dir)
    snap = loader.load()
    assert snap.app.llm.daily_cost_ceiling_cny == 5.0
    assert snap.watchlist.rules.us == []
    assert snap.channels.channels == {}
