import pytest
from pydantic import ValidationError

from news_pipeline.config.schema import AppConfig


def test_app_config_minimal():
    cfg = AppConfig.model_validate({"pipeline": {"mode": "v2"}, "llm": {"enabled": False}})
    assert cfg.pipeline.mode == "v2"
    assert cfg.scheduler.digest.cn[0].at == "08:27"
    assert not cfg.llm.enabled


def test_app_config_rejects_bad_materiality_range():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"push": {"push_min_materiality": 6}})
