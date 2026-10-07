"""Read-only news replay and opt-in model evaluation.

The eight checked-in gold cases are unreviewed seeds. A 150-event CSV must be
reviewed by the user before model quality numbers can be treated as acceptance evidence.
"""

import argparse
import asyncio
import csv
import hashlib
import json
import os
import random
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from pydantic import ValidationError

from news_pipeline.assess.assessor import ChatProtocol
from news_pipeline.assess.client import ChatAttempt, ChatClient, ChatResult
from news_pipeline.assess.prompts import assess_system, utc_aware
from news_pipeline.assess.schema import EventAssessment, parse_assessment
from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.config.schema import AppConfig, FirstPartyConfig, ScoringConfig, WatchlistFile
from news_pipeline.events.similarity import Features, features, same_event, within_event_window
from news_pipeline.rules.engine import RulesEngine
from news_pipeline.rules.headline import headline
from news_pipeline.rules.verdict import RulesVerdict
from news_pipeline.tools.gold import dataset_report, load_dataset, select_split

_STRENGTH = {"drop": 0, "digest_lo": 1, "digest_hi": 2, "push": 3}
_SEED_PATH = Path(__file__).resolve().parents[3] / "tests" / "eval" / "gold_events.jsonl"


@dataclass
class ReplayEvent:
    id: int
    articles: list[RawArticle]
    verdict: RulesVerdict
    first_seen_at: datetime
    last_seen_at: datetime
    samples: list[Features] = field(default_factory=list)
    prediction: dict[str, Any] | None = None

    @property
    def title(self) -> str:
        return headline(self.articles[0].title, self.articles[0].body)

    @property
    def tagged_tickers(self) -> list[str]:
        return self.verdict.tagged_tickers


def load_articles(path: Path, from_date: str, to_date: str) -> list[RawArticle]:
    timezone = ZoneInfo("Asia/Shanghai")
    start = datetime.fromisoformat(from_date).replace(tzinfo=timezone).astimezone(UTC)
    end = (datetime.fromisoformat(to_date).replace(tzinfo=timezone) + timedelta(days=1)).astimezone(
        UTC
    )
    # URI mode=ro refuses all mutations and never invokes application migrations.
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM raw_news ORDER BY published_at, id")
        articles = []
        for row in rows:
            published = utc_aware(datetime.fromisoformat(row["published_at"]))
            if not start <= published < end:
                continue
            keys = set(row.keys())
            meta = json.loads(row["raw_meta"] or "{}") if "raw_meta" in keys else {}
            articles.append(
                RawArticle(
                    source=row["source"],
                    market=Market(row["market"]),
                    title=row["title"],
                    body=row["body"],
                    url=row["url"],
                    url_hash=row["url_hash"],
                    raw_meta=meta,
                    published_at=published,
                    fetched_at=utc_aware(datetime.fromisoformat(row["fetched_at"])),
                    title_simhash=row["title_simhash"] if "title_simhash" in keys else 0,
                )
            )
    return articles


def group_articles(articles: list[RawArticle], rules: RulesEngine) -> list[ReplayEvent]:
    groups: list[ReplayEvent] = []
    active: list[ReplayEvent] = []
    for article in sorted(articles, key=lambda item: item.published_at):
        verdict = rules.match(article)
        if not verdict.matched:
            continue
        at = utc_aware(article.published_at)
        candidate = features(headline(article.title, article.body), verdict.subject_tickers, at)
        active = [
            event
            for event in active
            if within_event_window(at, event.first_seen_at, event.last_seen_at)
        ]
        target = next(
            (
                event
                for event in active
                if any(same_event(candidate, sample) for sample in event.samples)
            ),
            None,
        )
        if target is None:
            target = ReplayEvent(len(groups) + 1, [article], verdict, at, at, [candidate])
            groups.append(target)
            active.append(target)
        else:
            target.articles.append(article)
            target.last_seen_at = max(target.last_seen_at, at)
            target.samples.append(candidate)
            if len(target.samples) > 8:
                target.samples = target.samples[:2] + target.samples[-6:]
            stronger = (
                verdict
                if _STRENGTH[verdict.decision] > _STRENGTH[target.verdict.decision]
                else target.verdict
            )
            target.verdict = RulesVerdict(
                decision=stronger.decision,
                reason=stronger.reason,
                subject_tickers=sorted(
                    set(target.verdict.subject_tickers) | set(verdict.subject_tickers)
                ),
                tagged_tickers=sorted(
                    set(target.verdict.tagged_tickers) | set(verdict.tagged_tickers)
                ),
                markets=sorted(set(target.verdict.markets) | set(verdict.markets)),
                importance_hint=max(target.verdict.importance_hint, verdict.importance_hint),
                rank_score=max(target.verdict.rank_score, verdict.rank_score),
            )
    return groups


def replay_report(groups: list[ReplayEvent]) -> dict[str, Any]:
    candidates = sum(len(group.articles) for group in groups)
    pushed = [
        group
        for group in groups
        if (group.prediction or {}).get("decision", group.verdict.decision) == "push"
    ]
    daily = Counter(
        group.first_seen_at.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        for group in pushed
    )
    return {
        "candidate_articles": candidates,
        "event_count": len(groups),
        "merge_ratio": candidates / len(groups) if groups else 0,
        "push_events": len(pushed),
        "daily_push_events": dict(sorted(daily.items())),
    }


def _stratum(group: ReplayEvent) -> str:
    if group.verdict.decision in {"push", "digest_hi"}:
        return group.verdict.decision
    return "mention" if group.verdict.tagged_tickers else "macro"


def export_samples(
    groups: list[ReplayEvent], path: Path, sample_size: int = 150, seed: int = 42
) -> list[ReplayEvent]:
    rng = random.Random(seed)
    buckets = {
        key: [group for group in groups if _stratum(group) == key]
        for key in ("push", "digest_hi", "mention", "macro")
    }
    for bucket in buckets.values():
        rng.shuffle(bucket)
    quotas = [round(sample_size * weight / 150) for weight in (50, 50, 30)]
    quotas.append(max(sample_size - sum(quotas), 0))
    chosen = []
    for (_key, bucket), quota in zip(buckets.items(), quotas, strict=True):
        chosen.extend(bucket[:quota])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        fields = [
            "id",
            "event_id",
            "stratum",
            "case",
            "title",
            "body",
            "source",
            "sources",
            "market",
            "published_at",
            "url",
            "raw_meta",
            "tickers",
            "rule_decision",
            "label",
            "annotation_status",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for group in chosen:
            representative = max(
                group.articles,
                key=lambda article: (
                    article.source in {"juchao", "sec_edgar"},
                    len(article.body or ""),
                    str(article.url),
                ),
            )
            evidence = json.dumps(sorted({str(article.url) for article in group.articles}))
            writer.writerow(
                {
                    "id": "event-" + hashlib.sha256(evidence.encode()).hexdigest(),
                    "event_id": group.id,
                    "stratum": _stratum(group),
                    "case": "",
                    "title": representative.title,
                    "body": representative.body or "",
                    "source": representative.source,
                    "sources": json.dumps(sorted({a.source for a in group.articles})),
                    "market": representative.market.value,
                    "published_at": representative.published_at.isoformat(),
                    "url": representative.url,
                    "raw_meta": json.dumps(representative.raw_meta, ensure_ascii=False),
                    "tickers": json.dumps(group.tagged_tickers),
                    "rule_decision": group.verdict.decision,
                    "label": "must_push" if group.verdict.decision == "push" else "digest",
                    "annotation_status": "unreviewed",
                }
            )
    return chosen


def load_gold(path: Path) -> list[dict[str, Any]]:
    return load_dataset(path)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def evaluation_metrics(
    gold: list[dict[str, Any]], predictions: list[dict[str, Any]]
) -> dict[str, float]:
    if len(gold) != len(predictions):
        raise ValueError("one prediction is required for each gold event")
    pushed = sum(row.get("decision") == "push" for row in predictions)
    must_push = sum(row.get("label") == "must_push" for row in gold)
    correct = sum(
        expected.get("label") == "must_push" and actual.get("decision") == "push"
        for expected, actual in zip(gold, predictions, strict=True)
    )
    wrong = sum(
        bool(set(actual.get("tickers", [])) - set(expected.get("tickers", [])))
        for expected, actual in zip(gold, predictions, strict=True)
    )
    latencies = [float(row.get("latency_ms", 0)) for row in predictions]
    count = len(gold)
    return {
        "push_precision": correct / pushed if pushed else 0,
        "must_push_recall": correct / must_push if must_push else 0,
        "wrong_ticker_rate": wrong / count if count else 0,
        "json_legal_rate": sum(bool(row.get("legal")) for row in predictions) / count
        if count
        else 0,
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "mean_cost_cny": sum(float(row.get("cost_cny", 0)) for row in predictions) / count
        if count
        else 0,
    }


def acceptance_report(
    dataset: dict[str, Any], metrics: dict[str, float], mode: str, split: str, count: int
) -> dict[str, Any]:
    limits = {
        "push_precision": ("min", 0.70),
        "must_push_recall": ("min", 0.90),
        "wrong_ticker_rate": ("max", 0.02),
        "json_legal_rate": ("min", 0.99),
        "latency_p95_ms": ("max", 8000),
    }
    thresholds = {}
    for key, (direction, limit) in limits.items():
        actual = metrics.get(key)
        thresholds[key] = {
            "actual": actual,
            direction: limit,
            "passed": actual is not None
            and (actual >= limit if direction == "min" else actual <= limit),
        }
    issues = list(dataset["acceptance_issues"])
    if not dataset["acceptance_ready"] and not issues:
        issues.append("dataset is not ready for acceptance")
    if mode != "llm":
        issues.append("LLM evaluation is required for model acceptance")
    if split != "holdout" or count != 30:
        issues.append("final acceptance requires the reserved 30-event holdout")
    return {
        "status": "not_eligible"
        if issues
        else "pass"
        if all(threshold["passed"] for threshold in thresholds.values())
        else "fail",
        "eligibility_issues": issues,
        "thresholds": thresholds,
    }


class CachedChatClient:
    def __init__(
        self, client: ChatProtocol, cache_dir: Path, prompt_version: str, provider: str = ""
    ) -> None:
        self.client, self.cache_dir, self.prompt_version = client, cache_dir, prompt_version
        self.provider = provider
        self.cache_hits = 0
        self.cache_misses = 0

    def _path(self, *, model: str, system: str, user: str, max_tokens: int) -> Path:
        complete_input = {
            "model": model,
            "system": system,
            "user": user,
            "max_tokens": max_tokens,
            "enable_thinking": False,
            "prompt_version": self.prompt_version,
            "provider": self.provider,
        }
        key = hashlib.sha256(
            json.dumps(
                complete_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        return self.cache_dir / f"{key}.json"

    def would_hit(self, *, model: str, system: str, user: str, max_tokens: int) -> bool:
        return self._path(model=model, system=system, user=user, max_tokens=max_tokens).exists()

    async def chat_json(self, *, model: str, system: str, user: str, max_tokens: int) -> ChatResult:
        path = self._path(model=model, system=system, user=user, max_tokens=max_tokens)
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.cache_hits += 1
            return ChatResult(
                stored["content"],
                stored["tokens_in"],
                stored["tokens_out"],
                stored["latency_ms"],
                tuple(ChatAttempt(**row) for row in stored["attempts"]),
            )
        result = await self.client.chat_json(
            model=model, system=system, user=user, max_tokens=max_tokens
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(result), ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        self.cache_misses += 1
        return result


def _configuration(directory: Path) -> tuple[AppConfig, WatchlistFile, RulesEngine]:
    def read(relative: str) -> dict[str, Any]:
        path = directory / relative
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}

    app = AppConfig.model_validate(read("common/app.yml"))
    watchlist = WatchlistFile.model_validate(read("news_pipeline/watchlist.yml"))
    rules = RulesEngine(
        watchlist.rules,
        scoring=ScoringConfig.model_validate(read("news_pipeline/scoring.yml")),
        first_party=FirstPartyConfig.model_validate(read("news_pipeline/first_party.yml")),
    )
    return app, watchlist, rules


def _api_key(directory: Path) -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        path = directory / "common" / "secrets.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}
        key = str(data.get("llm", {}).get("dashscope_api_key", "")).strip()
    if not key or key == "REPLACE_ME":
        raise ValueError("configure a DashScope API key before explicitly invoking LLM evaluation")
    return key


def _prediction(
    assessment: EventAssessment, rule: RulesVerdict, app: AppConfig, first_party: bool
) -> str:
    if assessment.novelty == "repeat" and assessment.same_as_event_id:
        return "drop"
    materiality = assessment.materiality
    if first_party:
        materiality = max(materiality, app.push.first_party_floor.get(rule.reason, 0))
    direct = any(holding.relation in {"subject", "counterparty"} for holding in assessment.holdings)
    wide = (
        assessment.scope in {"market", "sector"}
        and materiality >= app.push.push_min_materiality_macro
    )
    if (
        materiality >= app.push.push_min_materiality
        and (direct or wide)
        and assessment.confidence >= app.push.min_confidence
    ):
        return "push"
    return (
        "digest"
        if materiality >= app.push.digest_min_materiality or rule.decision == "push"
        else "drop"
    )


async def _evaluate(
    group: ReplayEvent,
    client: CachedChatClient,
    app: AppConfig,
    watchlist: WatchlistFile,
    recent: list[ReplayEvent],
    *,
    remaining_budget: float = float("inf"),
) -> dict[str, Any]:
    task = app.llm.assess
    body = max((article.body or "" for article in group.articles), key=len, default="")
    if len(body) > 1500:
        body = body[:1000] + "\u2026\u2026" + body[-500:]
    previous = [
        event
        for event in recent
        if event.id != group.id
        and set(event.tagged_tickers) & set(group.tagged_tickers)
        and group.first_seen_at - timedelta(hours=24) <= event.last_seen_at <= group.first_seen_at
        and (event.prediction or {}).get("decision", event.verdict.decision) != "drop"
    ][-8:]
    user = (
        f"## Event\nTime: {group.first_seen_at.isoformat()}\nTitle: {group.title}\nBody: {body}\n"
        f"Sources: {', '.join(sorted({a.source for a in group.articles}))}\n"
        f"Importance: {group.verdict.importance_hint}/3\n## Recent events\n"
        + (
            "\n".join(
                f"{event.id} | {event.first_seen_at.isoformat()} | {event.title}"
                for event in previous
            )
            or "None"
        )
    )
    known = set(watchlist.effective_us()) | set(watchlist.effective_cn())
    price = app.llm.pricing[task.model]
    cost = latency = new_cost = 0.0
    budget_fallback = False
    system = assess_system(watchlist)
    for attempt in range(2):
        hit = client.would_hit(
            model=task.model, system=system, user=user, max_tokens=task.max_tokens
        )
        reservation = (
            (len((system + user).encode("utf-8")) + 128) * price.input
            + task.max_tokens * price.output
        ) / 1_000_000
        if not hit and new_cost + reservation > remaining_budget:
            budget_fallback = True
            break
        try:
            result = await client.chat_json(
                model=task.model, system=system, user=user, max_tokens=task.max_tokens
            )
            billed = (
                (sum(row.tokens_in for row in result.attempts) or result.tokens_in) * price.input
                + (sum(row.tokens_out for row in result.attempts) or result.tokens_out)
                * price.output
            ) / 1_000_000
            cost += billed
            if not hit:
                new_cost += billed
            latency += result.latency_ms
            assessment = parse_assessment(result.content, known, {event.id for event in previous})
            raw = EventAssessment.model_validate(json.loads(result.content))
            return {
                "decision": _prediction(
                    assessment,
                    group.verdict,
                    app,
                    any(a.source in {"juchao", "sec_edgar"} for a in group.articles),
                ),
                "tickers": [holding.ticker for holding in raw.holdings],
                "legal": True,
                "latency_ms": latency,
                "cost_cny": cost,
                "new_cost_cny": new_cost,
                "budget_fallback": False,
                "assessment": assessment.model_dump(),
            }
        except (ValueError, ValidationError, TypeError) as error:
            if attempt == 0:
                user += f"\nOutput validation failed: {error}. Return corrected JSON."
                continue
        except Exception as error:
            for failed in getattr(error, "attempts", ()):
                billed = (
                    failed.tokens_in * price.input + failed.tokens_out * price.output
                ) / 1_000_000
                cost += billed
                new_cost += billed
                latency += failed.latency_ms
            break
    return {
        "decision": "push"
        if group.verdict.decision == "push"
        else "digest"
        if group.verdict.matched
        else "drop",
        "tickers": group.tagged_tickers,
        "legal": False,
        "latency_ms": latency,
        "cost_cny": cost,
        "new_cost_cny": new_cost,
        "budget_fallback": budget_fallback,
    }


def _seed_article(row: dict[str, Any], index: int) -> RawArticle:
    at = utc_aware(datetime.fromisoformat(row.get("published_at", "2026-10-06T00:00:00+00:00")))
    return RawArticle(
        source=row.get("source", "wire"),
        market=Market(row.get("market", "us")),
        title=row.get("title", ""),
        body=row.get("body", ""),
        url=row.get("url", f"https://example.com/gold/{index}"),
        url_hash=f"gold-{index}",
        raw_meta=row.get("raw_meta", {}),
        fetched_at=at,
        published_at=at,
    )


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    app, watchlist, rules = _configuration(args.config)
    groups = (
        group_articles(load_articles(args.db, args.from_date, args.to_date), rules)
        if args.db
        else []
    )
    result: dict[str, Any] = replay_report(groups)
    if args.export:
        exported = export_samples(groups, args.export, args.sample_size)
        result["exported_count"] = len(exported)
        result["exported_strata"] = dict(Counter(_stratum(group) for group in exported))
        result["export_shortfall"] = args.sample_size - len(exported)
        result["annotation_status"] = "unreviewed"
    full_gold = (
        load_gold(args.eval) if args.eval else load_gold(_SEED_PATH) if _SEED_PATH.exists() else []
    )
    gold = full_gold
    split = "all"
    if args.eval:
        dataset = dataset_report(full_gold)
        split = args.split or ("train" if any("split" in row for row in full_gold) else "all")
        gold = select_split(full_gold, split)
        if not gold:
            raise ValueError(f"no evaluation events in split {split!r}")
        result["dataset"] = dataset
        result["evaluated_split"] = split
    result["known_case_decisions"] = {
        row.get("case", str(index)): rules.match(_seed_article(row, index)).decision
        for index, row in enumerate(gold)
    }
    result["mode"] = args.mode
    if args.eval:
        result["gold_sample_count"] = len(gold)
        result["annotation_status"] = sorted(
            {row.get("annotation_status", "unknown") for row in gold}
        )
        if args.mode == "rules":
            predictions = []
            for index, row in enumerate(gold):
                verdict = rules.match(_seed_article(row, index))
                predictions.append(
                    {
                        "decision": "push"
                        if verdict.decision == "push"
                        else "digest"
                        if verdict.matched
                        else "drop",
                        "tickers": verdict.tagged_tickers,
                    }
                )
            metrics = evaluation_metrics(gold, predictions)
            result["metrics"] = {
                key: metrics[key]
                for key in ("push_precision", "must_push_recall", "wrong_ticker_rate")
            }
            result["acceptance"] = acceptance_report(
                dataset, result["metrics"], args.mode, split, len(gold)
            )
    if args.mode == "llm":
        raw_llm = app.llm.model_dump()
        raw_llm["enabled"] = True
        if args.model:
            raw_llm["assess"]["model"] = args.model
        raw_llm["digest"]["model"] = raw_llm["assess"]["model"]
        # Validating an enabled config enforces real positive prices before any request.
        app = app.model_copy(update={"llm": type(app.llm).model_validate(raw_llm)})
        result["model"] = app.llm.assess.model
        result["prompt_version"] = app.llm.assess.prompt_version
        result["provider"] = app.llm.base_url
        client = ChatClient(_api_key(args.config), app.llm.base_url)
        cached = CachedChatClient(
            client, args.cache_dir, app.llm.assess.prompt_version, app.llm.base_url
        )
        try:
            recent: list[ReplayEvent] = []
            spent = 0.0
            budget_fallbacks = 0
            for group in groups:
                eligible = (
                    bool(group.tagged_tickers)
                    or group.verdict.importance_hint >= 2
                    or any(article.source in {"juchao", "sec_edgar"} for article in group.articles)
                )
                if not eligible:
                    recent.append(group)
                    continue
                group.prediction = await _evaluate(
                    group,
                    cached,
                    app,
                    watchlist,
                    recent,
                    remaining_budget=app.llm.daily_cost_ceiling_cny - spent,
                )
                spent += group.prediction["new_cost_cny"]
                budget_fallbacks += bool(group.prediction.get("budget_fallback"))
                recent.append(group)
            result.update(replay_report(groups))
            if args.eval:
                predictions = []
                for index, row in enumerate(gold):
                    article = _seed_article(row, index)
                    verdict = rules.match(article)
                    group = ReplayEvent(
                        index + 1, [article], verdict, article.published_at, article.published_at
                    )
                    prediction = await _evaluate(
                        group,
                        cached,
                        app,
                        watchlist,
                        [],
                        remaining_budget=app.llm.daily_cost_ceiling_cny - spent,
                    )
                    predictions.append(prediction)
                    spent += prediction["new_cost_cny"]
                    budget_fallbacks += bool(prediction.get("budget_fallback"))
                result["metrics"] = evaluation_metrics(gold, predictions)
                result["acceptance"] = acceptance_report(
                    dataset, result["metrics"], args.mode, split, len(gold)
                )
                result["annotation_status"] = sorted(
                    {row.get("annotation_status", "unknown") for row in gold}
                )
            result["cache_hits"], result["cache_misses"] = cached.cache_hits, cached.cache_misses
            result["new_cost_cny"] = spent
            result["budget_fallback_events"] = budget_fallbacks
        finally:
            await client.close()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--from", dest="from_date", default="2026-09-14")
    parser.add_argument("--to", dest="to_date", default="2026-10-06")
    parser.add_argument("--mode", choices=("rules", "llm"))
    parser.add_argument("--eval", type=Path)
    parser.add_argument("--split", choices=("train", "holdout", "all"))
    parser.add_argument("--model")
    parser.add_argument("--config", type=Path, default=Path("config"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/replay-cache"))
    parser.add_argument("--export", type=Path)
    parser.add_argument("--sample-size", type=int, default=150)
    args = parser.parse_args(argv)
    if args.mode is None:
        args.mode = "llm" if args.eval and args.model else "rules"
    if not args.db and not args.eval:
        parser.error("provide --db or --eval")
    if args.split and not args.eval:
        parser.error("--split requires --eval")
    if args.export and not args.db:
        parser.error("--export requires --db")
    if args.sample_size <= 0:
        parser.error("--sample-size must be positive")
    if args.from_date > args.to_date:
        parser.error("--from must not be after --to")
    try:
        print(json.dumps(asyncio.run(_run(args)), ensure_ascii=False, indent=2))
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
