from pathlib import Path

import pytest
from pydantic import ValidationError

from news_pipeline.config.loader import ConfigLoader
from news_pipeline.config.schema import AppConfig, SourceDef, WatchlistFile

from .test_loader import cfg_dir as cfg_dir


def test_typed_source_defaults() -> None:
    source = SourceDef()
    assert source.lookback_min == 360
    assert source.fetch_timeout_sec == 45
    assert source.max_silence_min is None
    assert source.max_silence_off_min is None


def test_app_v2_defaults_disable_paid_calls() -> None:
    cfg = AppConfig()
    assert cfg.pipeline.mode == "v2"
    assert cfg.llm.enabled is False
    assert cfg.llm.assess.max_tokens == 400
    assert cfg.llm.digest.max_tokens == 1500
    assert cfg.push.max_age_min == 90
    assert cfg.digest.max_items == 20
    assert cfg.digest.max_age_hours == 24
    assert cfg.ops.report_at == "08:20"
    assert cfg.push.push_min_materiality == 4
    assert cfg.push.push_min_materiality_macro == 5
    assert cfg.push.digest_min_materiality == 3
    assert cfg.push.min_confidence == 0.5


@pytest.mark.parametrize(
    "pricing",
    [{}, {"qwen-plus": {"input": 0, "output": 1}}, {"qwen-plus": {"input": 1, "output": 0}}],
)
def test_enabled_llm_requires_positive_prices(pricing: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="pricing"):
        AppConfig(llm={"enabled": True, "pricing": pricing})


def test_separate_llm_models_must_both_have_pricing() -> None:
    with pytest.raises(ValidationError, match="other-model"):
        AppConfig(
            llm={
                "enabled": True,
                "digest": {"model": "other-model"},
                "pricing": {"qwen-plus": {"input": 1, "output": 2}},
            }
        )
    cfg = AppConfig(llm={"enabled": True, "pricing": {"qwen-plus": {"input": 1, "output": 2}}})
    assert cfg.llm.pricing["qwen-plus"].input == 1


def test_new_digest_schedule_has_local_timezones() -> None:
    cfg = AppConfig(
        scheduler={
            "digest": {
                "cn": [{"at": "08:27", "tz": "Asia/Shanghai"}],
                "us": [{"at": "08:27", "tz": "America/New_York"}],
            }
        }
    )
    assert cfg.scheduler.digest.cn[0].at == "08:27"
    assert cfg.scheduler.digest.us[0].tz == "America/New_York"


def test_short_chinese_alias_requires_allowlist() -> None:
    with pytest.raises(ValidationError, match="short_alias_allow"):
        WatchlistFile(rules={"cn": [{"ticker": "688981", "name": "中芯国际", "aliases": ["中芯"]}]})
    assert WatchlistFile(
        rules={
            "short_alias_allow": ["三花"],
            "cn": [{"ticker": "002050", "name": "三花智控", "aliases": ["三花"]}],
        }
    )


def test_alias_ownership_is_case_insensitive() -> None:
    with pytest.raises(ValidationError, match=r"alias.*two"):
        WatchlistFile(
            rules={
                "us": [
                    {"ticker": "ONE", "name": "one", "aliases": ["Shared"]},
                    {"ticker": "TWO", "name": "two", "aliases": ["shared"]},
                ]
            }
        )


def test_exclusion_must_contain_an_alias_of_its_owner() -> None:
    with pytest.raises(ValidationError, match="exclude"):
        WatchlistFile(
            rules={"us": [{"ticker": "AVGO", "name": "Broadcom", "exclude": ["无关公司"]}]}
        )
    cfg = WatchlistFile(
        rules={
            "short_alias_allow": ["博通"],
            "us": [
                {"ticker": "AVGO", "name": "Broadcom", "aliases": ["博通"], "exclude": ["博通集成"]}
            ],
        }
    )
    assert cfg.rules.us[0].exclude == ["博通集成"]


def test_v2_sectors_are_context_without_keyword_refs() -> None:
    cfg = WatchlistFile(
        rules={"us": [{"ticker": "NVDA", "name": "NVIDIA", "sectors": ["context"]}]}
    )
    assert cfg.rules.us[0].sectors == ["context"]


def test_repository_configuration_loads_new_vocabularies() -> None:
    config = Path(__file__).parents[3] / "config"
    assert (config / "news_pipeline" / "scoring.yml").exists()
    assert (config / "news_pipeline" / "first_party.yml").exists()


def test_optional_vocabularies_keep_old_loader_fixtures(cfg_dir: Path) -> None:
    snap = ConfigLoader(cfg_dir).load()
    assert "回购" in snap.scoring.strong_events
    assert "10-K" in snap.first_party.sec.high.forms


def test_invalid_keyword_regex_is_rejected_at_configuration_load() -> None:
    from news_pipeline.config.schema import ScoringConfig

    with pytest.raises(ValidationError, match="regular expression"):
        ScoringConfig(keywords={"macro": ["re:["]})


def test_optional_vocabulary_files_are_loaded_when_present(cfg_dir: Path) -> None:
    (cfg_dir / "news_pipeline" / "scoring.yml").write_text("big_move_pct: 7.0\n")
    (cfg_dir / "news_pipeline" / "first_party.yml").write_text("juchao:\n  merge_max_items: 3\n")
    snap = ConfigLoader(cfg_dir).load()
    assert snap.scoring.big_move_pct == 7.0
    assert snap.first_party.juchao.merge_max_items == 3
