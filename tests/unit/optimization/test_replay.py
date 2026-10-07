import csv
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from news_pipeline.assess.client import ChatResult
from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.config.schema import RulesSection, TickerEntry
from news_pipeline.rules.engine import RulesEngine
from news_pipeline.tools.replay import (
    CachedChatClient,
    evaluation_metrics,
    export_samples,
    group_articles,
    load_articles,
    load_gold,
    replay_report,
)

AT = datetime(2026, 10, 6, tzinfo=UTC)


def article(title, n=0, **updates):
    return RawArticle(
        source="wire",
        market=Market.US,
        title=title,
        body="",
        url=f"https://example.com/{n}",
        url_hash=str(n),
        fetched_at=AT,
        published_at=updates.get("published_at", AT),
    )


def engine():
    return RulesEngine(
        RulesSection(us=[TickerEntry(ticker="NVDA", name="NVIDIA", aliases=["英伟达"])])
    )


def test_grouping_reuses_similarity_and_time_windows():
    groups = group_articles(
        [
            article("英伟达\uff1a将股票回购授权规模增加1500亿美元", 1),
            article("英伟达宣布将股票回购授权规模提高1500亿美元", 2),
            article(
                "英伟达宣布将股票回购授权规模提高1500亿美元",
                3,
                published_at=AT + timedelta(hours=7),
            ),
            article("无关政治新闻", 4),
        ],
        engine(),
    )
    assert [len(group.articles) for group in groups] == [2, 1]
    report = replay_report(groups)
    assert report["candidate_articles"] == 3
    assert report["event_count"] == 2
    assert report["merge_ratio"] == 1.5
    assert report["daily_push_events"] == {"2026-10-06": 2}


def test_sqlite_input_is_opened_read_only_and_not_migrated(tmp_path):
    path = tmp_path / "copy news.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE raw_news(id INTEGER,source TEXT,market TEXT,title TEXT,body TEXT,"
        "url TEXT,url_hash TEXT,fetched_at TEXT,published_at TEXT,raw_meta TEXT)"
    )
    connection.execute(
        "INSERT INTO raw_news VALUES(1,'wire','us','NVDA reports','','https://example.com/1',"
        "'hash','2026-10-06T01:00:00+00:00','2026-10-06T01:00:00+00:00','{}')"
    )
    connection.commit()
    connection.close()
    before = path.read_bytes()
    rows = load_articles(path, "2026-10-06", "2026-10-06")
    assert len(rows) == 1 and rows[0].title == "NVDA reports"
    assert path.read_bytes() == before
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
        ("raw_news",)
    ]
    connection.close()


async def test_response_cache_hash_covers_complete_request(tmp_path):
    client = AsyncMock()
    client.chat_json.return_value = ChatResult("{}", 100, 10, 12)
    cached = CachedChatClient(client, tmp_path, "assess_v1")
    kwargs = dict(model="qwen-plus", system="system", user="user", max_tokens=400)
    first = await cached.chat_json(**kwargs)
    assert await cached.chat_json(**kwargs) == first
    assert client.chat_json.await_count == 1
    await cached.chat_json(**(kwargs | {"system": "different prompt"}))
    await cached.chat_json(**(kwargs | {"max_tokens": 401}))
    await CachedChatClient(client, tmp_path, "assess_v2").chat_json(**kwargs)
    assert client.chat_json.await_count == 4
    assert all(len(path.stem) == 64 for path in tmp_path.iterdir())
    assert cached.cache_hits == 1


def test_metrics_count_wrong_tickers_legal_json_and_latency():
    gold = [
        dict(label="must_push", tickers=["NVDA"]),
        dict(label="digest", tickers=[]),
        dict(label="must_push", tickers=["TSLA"]),
    ]
    predictions = [
        dict(decision="push", tickers=["NVDA"], legal=True, latency_ms=100, cost_cny=0.01),
        dict(decision="push", tickers=["WRONG"], legal=True, latency_ms=200, cost_cny=0.02),
        dict(decision="digest", tickers=["TSLA"], legal=False, latency_ms=300, cost_cny=0.03),
    ]
    metrics = evaluation_metrics(gold, predictions)
    assert metrics["push_precision"] == 0.5
    assert metrics["must_push_recall"] == 0.5
    assert metrics["wrong_ticker_rate"] == pytest.approx(1 / 3)
    assert metrics["json_legal_rate"] == pytest.approx(2 / 3)
    assert metrics["latency_p50_ms"] == 200
    assert metrics["latency_p95_ms"] == pytest.approx(290)
    assert metrics["mean_cost_cny"] == 0.02


def test_export_stratifies_and_marks_labels_as_unreviewed(tmp_path):
    rows = []
    for n in range(160):
        title = (
            "英伟达回购股票"
            if n < 60
            else "英伟达推出新产品"
            if n < 120
            else "黄仁勋谈新产品"
            if n < 140
            else "美联储官员讲话"
        )
        # Distinct evidence numbers avoid merging candidate rows.
        rows.append(article(title + str(n) + "亿元", n, published_at=AT + timedelta(hours=13 * n)))
    rules = RulesSection(
        us=[TickerEntry(ticker="NVDA", name="NVIDIA", aliases=["英伟达"], people=["黄仁勋"])]
    )
    groups = group_articles(rows, RulesEngine(rules))
    path = tmp_path / "review.csv"
    selected = export_samples(groups, path, sample_size=150)
    assert len(selected) == 140
    with path.open() as handle:
        exported = list(csv.DictReader(handle))
    assert len(exported) == 140
    assert all(row["annotation_status"] == "unreviewed" for row in exported)
    counts = {
        name: sum(row["stratum"] == name for row in exported)
        for name in ["push", "digest_hi", "mention", "macro"]
    }
    assert counts == {"push": 50, "digest_hi": 50, "mention": 20, "macro": 20}


def test_review_export_preserves_evidence_and_stable_ids_without_overwriting(tmp_path):
    evidence = article("英伟达回购股票", 9).model_copy(
        update={"body": "Original evidence", "raw_meta": {"symbols": ["NVDA"]}}
    )
    groups = group_articles([evidence], engine())
    path = tmp_path / "review.csv"
    export_samples(groups, path)
    with path.open() as handle:
        row = next(csv.DictReader(handle))
    assert row["market"] == "us"
    assert row["source"] == evidence.source
    assert row["url"] == str(evidence.url)
    assert row["published_at"] == evidence.published_at.isoformat()
    assert json.loads(row["raw_meta"]) == evidence.raw_meta
    assert json.loads(row["sources"]) == ["wire"]
    assert row["case"] == ""
    groups[0].id = 100
    second = tmp_path / "second.csv"
    export_samples(groups, second)
    with second.open() as handle:
        assert next(csv.DictReader(handle))["id"] == row["id"]
    with pytest.raises(FileExistsError):
        export_samples(groups, path)


def test_export_review_import_replay_preserves_human_corrections(tmp_path, capsys):
    from news_pipeline.tools import replay
    from news_pipeline.tools.gold import import_reviewed_csv, load_dataset

    original = article("英伟达回购股票", 9).model_copy(update={"raw_meta": {"level": "B"}})
    source, reviewed, output = (
        tmp_path / name for name in ("export.csv", "review.csv", "gold.jsonl")
    )
    export_samples(group_articles([original], engine()), source)
    before = source.read_bytes()
    with source.open() as handle:
        rows = list(csv.DictReader(handle))
    rows[0].update(label="drop", tickers="[]", annotation_status="reviewed")
    with reviewed.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = import_reviewed_csv(reviewed, output)
    row = load_dataset(output)[0]
    assert row["raw_meta"] == original.raw_meta
    assert row["url"] == str(original.url)
    assert row["label"] == "drop"
    assert row["tickers"] == []
    assert source.read_bytes() == before
    assert report["acceptance_ready"] is False
    replay.main(["--eval", str(output), "--mode", "rules"])
    report = json.loads(capsys.readouterr().out)
    assert report["evaluated_split"] == "train"
    assert report["gold_sample_count"] == 1
    assert report["acceptance"]["status"] == "not_eligible"


def test_acceptance_requires_reviewed_holdout_and_all_five_thresholds():
    from news_pipeline.tools.replay import acceptance_report

    dataset = {"acceptance_ready": True, "acceptance_issues": []}
    metrics = dict(
        push_precision=0.7,
        must_push_recall=0.9,
        wrong_ticker_rate=0.02,
        json_legal_rate=0.99,
        latency_p95_ms=8000,
    )
    assert acceptance_report(dataset, metrics, "llm", "holdout", 30)["status"] == "pass"
    bad = metrics | {"latency_p95_ms": 8001}
    report = acceptance_report(dataset, bad, "llm", "holdout", 30)
    assert report["status"] == "fail"
    assert report["thresholds"]["latency_p95_ms"]["passed"] is False
    for mode, split, count in [("rules", "holdout", 30), ("llm", "train", 120)]:
        assert acceptance_report(dataset, metrics, mode, split, count)["status"] == "not_eligible"
    dataset = {"acceptance_ready": False, "acceptance_issues": ["unreviewed"]}
    assert acceptance_report(dataset, metrics, "llm", "holdout", 30)["status"] == "not_eligible"


def test_seed_gold_is_eight_documented_cases_not_reviewed_annotations():
    path = Path(__file__).parents[2] / "eval" / "gold_events.jsonl"
    gold = load_gold(path)
    assert len(gold) == 8
    assert all(row["annotation_status"] == "seed_unreviewed" for row in gold)
    assert {row["case"] for row in gold} >= {"nvda_buyback", "yaoming_junuo", "ningde_city"}


async def test_replay_reserves_worst_case_cost_before_a_paid_request(tmp_path):
    from news_pipeline.config.schema import AppConfig, WatchlistFile
    from news_pipeline.tools.replay import _evaluate

    client = AsyncMock()
    cached = CachedChatClient(client, tmp_path, "assess_v1")
    cfg = AppConfig(llm={"enabled": True, "pricing": {"qwen-plus": {"input": 1, "output": 2}}})
    group = group_articles([article("英伟达回购股票")], engine())[0]
    prediction = await _evaluate(group, cached, cfg, WatchlistFile(), [], remaining_budget=0.00001)
    client.chat_json.assert_not_awaited()
    assert prediction["budget_fallback"] is True
    assert prediction["new_cost_cny"] == 0


async def test_replaying_cached_responses_does_not_charge_budget_twice(tmp_path):
    from news_pipeline.config.schema import AppConfig, WatchlistFile
    from news_pipeline.tools.replay import _evaluate

    client = AsyncMock()
    client.chat_json.return_value = ChatResult(
        json.dumps(
            {
                "event_type": "capital_action",
                "scope": "company",
                "holdings": [],
                "materiality": 4,
                "novelty": "new",
                "summary": "英伟达增加回购额度",
                "so_what": "增加回报",
                "confidence": 0.9,
            }
        ),
        100,
        20,
        10,
    )
    cached = CachedChatClient(client, tmp_path, "assess_v1")
    cfg = AppConfig(llm={"enabled": True, "pricing": {"qwen-plus": {"input": 1, "output": 2}}})
    group = group_articles([article("英伟达回购股票")], engine())[0]
    first = await _evaluate(group, cached, cfg, WatchlistFile(), [], remaining_budget=5)
    second = await _evaluate(group, cached, cfg, WatchlistFile(), [], remaining_budget=0)
    assert first["new_cost_cny"] == pytest.approx(0.00014)
    assert second["new_cost_cny"] == 0
    assert second["legal"] is True
    assert client.chat_json.await_count == 1


def test_replay_dates_use_the_same_shanghai_day_as_daily_reports(tmp_path):
    path = tmp_path / "news.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE raw_news(id INTEGER,source TEXT,market TEXT,title TEXT,body TEXT,"
        "url TEXT,url_hash TEXT,fetched_at TEXT,published_at TEXT,raw_meta TEXT)"
    )
    for n, at in enumerate(["2026-10-05T16:30:00+00:00", "2026-10-06T16:30:00+00:00"]):
        connection.execute(
            "INSERT INTO raw_news VALUES(?,?,?,?,?,?,?,?,?,?)",
            (n, "wire", "us", "NVDA reports", "", f"https://example.com/{n}", str(n), at, at, "{}"),
        )
    connection.commit()
    connection.close()
    rows = load_articles(path, "2026-10-06", "2026-10-06")
    assert [row.url_hash for row in rows] == ["0"]


def test_explicit_rules_evaluation_never_enables_or_constructs_llm(monkeypatch, capsys):
    from news_pipeline.tools import replay

    def forbidden(*args, **kwargs):
        raise AssertionError("Rules evaluation must not construct an LLM client")

    monkeypatch.setattr(replay, "ChatClient", forbidden)
    assert replay.main(["--eval", "tests/eval/gold_events.jsonl", "--mode", "rules"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "rules"
    assert report["gold_sample_count"] == 8
    assert report["annotation_status"] == ["seed_unreviewed"]
    assert "push_precision" in report["metrics"]
    assert "json_legal_rate" not in report["metrics"]
    assert report["dataset"]["acceptance_ready"] is False
    assert report["evaluated_split"] == "all"
    assert report["acceptance"]["status"] == "not_eligible"


def test_replay_uses_persisted_split_and_defaults_to_training(monkeypatch, tmp_path, capsys):
    from news_pipeline.tools import replay

    path = tmp_path / "gold.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": str(n),
                    "title": "英伟达回购股票",
                    "body": "",
                    "source": "wire",
                    "market": "us",
                    "label": "must_push",
                    "tickers": ["NVDA"],
                    "annotation_status": "reviewed",
                    "split": "train" if n < 120 else "holdout",
                }
            )
            for n in range(150)
        )
    )
    # This test isolates replay selection; full provenance/strata validation is tested in gold.
    monkeypatch.setattr(
        replay,
        "dataset_report",
        lambda rows: {
            "acceptance_ready": True,
            "acceptance_issues": [],
            "dataset_hash": "full-dataset",
        },
    )
    replay.main(["--eval", str(path), "--mode", "rules"])
    report = json.loads(capsys.readouterr().out)
    assert report["evaluated_split"] == "train"
    assert report["gold_sample_count"] == 120
    assert report["dataset"]["dataset_hash"] == "full-dataset"
    assert report["acceptance"]["status"] == "not_eligible"
    replay.main(["--eval", str(path), "--mode", "rules", "--split", "holdout"])
    report = json.loads(capsys.readouterr().out)
    assert report["evaluated_split"] == "holdout"
    assert report["gold_sample_count"] == 30
    assert report["acceptance"]["status"] == "not_eligible"
    monkeypatch.setattr(
        replay,
        "dataset_report",
        lambda rows: {
            "acceptance_ready": False,
            "acceptance_issues": ["missing known case"],
            "dataset_hash": "full-dataset",
        },
    )
    replay.main(["--eval", str(path), "--mode", "rules"])
    report = json.loads(capsys.readouterr().out)
    assert report["evaluated_split"] == "train"
    assert report["gold_sample_count"] == 120


def test_empty_split_fails_before_constructing_llm(monkeypatch, tmp_path):
    from news_pipeline.tools import replay

    def forbidden(*args, **kwargs):
        raise AssertionError("empty split must be rejected before creating an LLM client")

    monkeypatch.setattr(replay, "ChatClient", forbidden)
    with pytest.raises(SystemExit) as error:
        replay.main(
            ["--eval", "tests/eval/gold_events.jsonl", "--mode", "llm", "--split", "holdout"]
        )
    assert error.value.code == 2


@pytest.mark.parametrize("budget_fallback", [False, True])
def test_llm_evaluates_only_holdout_and_counts_gold_budget_fallbacks(
    monkeypatch, tmp_path, capsys, budget_fallback
):
    from news_pipeline.config.schema import AppConfig, WatchlistFile
    from news_pipeline.tools import replay

    path = tmp_path / "gold.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": str(n),
                    "title": f"英伟达回购股票 {n}",
                    "body": "",
                    "source": "wire",
                    "market": "us",
                    "label": "must_push",
                    "tickers": ["NVDA"],
                    "annotation_status": "reviewed",
                    "split": "train" if n < 120 else "holdout",
                }
            )
            for n in range(150)
        )
    )
    cfg = AppConfig(llm={"enabled": True, "pricing": {"qwen-plus": {"input": 1, "output": 2}}})
    client = AsyncMock()
    monkeypatch.setattr(
        replay, "_configuration", lambda directory: (cfg, WatchlistFile(), engine())
    )
    monkeypatch.setattr(replay, "_api_key", lambda directory: "test-key")
    monkeypatch.setattr(replay, "ChatClient", lambda *args: client)
    monkeypatch.setattr(
        replay,
        "dataset_report",
        lambda rows: {
            "acceptance_ready": True,
            "acceptance_issues": [],
            "dataset_hash": "full-dataset",
        },
    )
    evaluated = []

    async def evaluate(group, *args, **kwargs):
        evaluated.append(group.title)
        fallback = budget_fallback and len(evaluated) == 1
        return dict(
            decision="push",
            tickers=["NVDA"],
            legal=not fallback,
            latency_ms=100,
            cost_cny=0,
            new_cost_cny=0,
            budget_fallback=fallback,
        )

    monkeypatch.setattr(replay, "_evaluate", evaluate)
    replay.main(["--eval", str(path), "--mode", "llm", "--split", "holdout"])
    report = json.loads(capsys.readouterr().out)
    assert evaluated == [f"英伟达回购股票 {n}" for n in range(120, 150)]
    assert report["gold_sample_count"] == 30
    assert report["budget_fallback_events"] == int(budget_fallback)
    assert report["acceptance"]["status"] == ("fail" if budget_fallback else "pass")
    assert report["model"] == cfg.llm.assess.model
    assert report["prompt_version"] == cfg.llm.assess.prompt_version
    client.close.assert_awaited_once()
    client.chat_json.assert_not_awaited()
