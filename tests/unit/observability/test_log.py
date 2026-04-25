# tests/unit/observability/test_log.py
import json
import logging

from news_pipeline.observability.log import configure_logging, get_logger


def test_configure_logging_emits_json(capsys):
    configure_logging(level="INFO", json_output=True)
    log = get_logger("test")
    log.info("hello", k1="v1", k2=42)
    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "hello"
    assert payload["k1"] == "v1"
    assert payload["k2"] == 42
    assert payload["level"] == "info"


def test_configure_logging_text_mode(capsys):
    configure_logging(level="INFO", json_output=False)
    log = get_logger("test")
    log.info("readable", x=1)
    captured = capsys.readouterr()
    assert "readable" in captured.out
