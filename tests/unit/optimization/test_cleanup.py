"""Contracts for the staged single-path v0.7.1 pipeline."""

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect, select

from news_pipeline.config.schema import AppConfig, SourcesFile, WatchlistFile
from news_pipeline.ingest.store import ArticleStore
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.models import RawNews
from tests.unit.optimization.test_ingest_health import article

ROOT = Path(__file__).resolve().parents[3]
RETIRED_MODULES = (
    "news_pipeline.commands",
    "news_pipeline.charts",
    "news_pipeline.llm",
    "news_pipeline.classifier",
    "news_pipeline.dedup",
    "news_pipeline.router",
    "news_pipeline.events.sent_cache",
    "news_pipeline.storage.dao.entities",
    "news_pipeline.storage.dao.relations",
    "news_pipeline.storage.dao.audit_log",
    "news_pipeline.storage.dao.dead_letter",
    "news_pipeline.storage.dao.news_processed",
    "news_pipeline.storage.dao.digest_buffer",
    "news_pipeline.storage.dao.push_log",
    "shared.observability.weekly_report",
    "shared.push.common.message_builder",
    "news_pipeline.scrapers.cn.akshare_news",
    "news_pipeline.scrapers.cn.caixin_telegram",
    "news_pipeline.scrapers.cn.kr36",
    "news_pipeline.scrapers.cn.ths",
    "news_pipeline.scrapers.cn.xueqiu",
    "news_pipeline.scrapers.cn.tushare_news",
    "news_pipeline.scrapers.us.yfinance_news",
    "news_pipeline.scrapers.common.cookies",
    "news_pipeline.scrapers.common.ratelimit",
)
RETIRED_SOURCES = (
    "akshare_news",
    "caixin_telegram",
    "kr36",
    "ths",
    "xueqiu",
    "tushare_news",
    "yfinance_news",
)


@pytest.mark.parametrize("mode", ["legacy", "shadow"])
def test_retired_modes_are_rejected(mode):
    with pytest.raises(ValidationError):
        AppConfig(pipeline={"mode": mode})


def test_default_is_v2_with_llm_disabled_and_no_prices():
    app = AppConfig()
    assert app.pipeline.mode == "v2"
    assert not app.llm.enabled and app.llm.pricing == {}


@pytest.mark.parametrize(
    "settings",
    [
        {"runtime": {}},
        {"classifier": {}},
        {"dedup": {}},
        {"charts": {}},
        {"dead_letter": {}},
        {"retention": {}},
        {"scheduler": {"scrape": {}}},
        {"scheduler": {"llm": {}}},
        *(
            {"scheduler": {"digest": {field: "08:30"}}}
            for field in ("morning_cn", "evening_cn", "morning_us", "evening_us")
        ),
        *(
            {"llm": {field: "retired"}}
            for field in ("tier0_model", "tier1_model", "tier2_model", "tier3_model")
        ),
        {"llm": {"prompt_versions": {}}},
        {"llm": {"enable_prompt_cache": True}},
        {"llm": {"enable_batch": True}},
        {"push": {"per_channel_rate": "30/min"}},
        {"push": {"digest_max_items_per_section": 30}},
        {"push": {"dedup_window_hours": 6}},
    ],
)
def test_retired_app_fields_are_rejected(settings):
    with pytest.raises(ValidationError):
        AppConfig.model_validate(settings)


@pytest.mark.parametrize(
    "settings",
    [
        {"llm": {}},
        *(
            {"rules": {field: value}}
            for field, value in (
                ("enable", True),
                ("gray_zone_action", "digest"),
                ("matcher", "aho_corasick"),
                ("matcher_options", {}),
                ("keyword_list", {}),
                ("macro_keywords", {}),
                ("sector_keywords", {}),
            )
        ),
        *(
            {"rules": {"us": [{"ticker": "NVDA", "name": "NVIDIA", field: []}]}}
            for field in ("alerts", "macro_links")
        ),
    ],
)
def test_retired_watchlist_fields_are_rejected(settings):
    with pytest.raises(ValidationError):
        WatchlistFile.model_validate(settings)


def test_scheduler_registers_only_current_processing_jobs(tmp_path):
    from news_pipeline.main import register_jobs
    from news_pipeline.scrapers.registry import ScraperRegistry
    from shared.observability.heartbeat import Heartbeat
    from tests.unit.optimization.test_v2_runtime import snapshot

    runtime = MagicMock(mode="v2")
    runner = register_jobs(
        runtime,
        ScraperRegistry(),
        snapshot("v2"),
        Heartbeat(tmp_path / "heart.json"),
        tmp_path / "news.db",
        None,
    )
    jobs = {job.id for job in runner._sched.get_jobs()}
    assert {"cluster_events", "assess_events", "decide_events", "deliver_outbox"} <= jobs
    assert "process_pending" not in jobs
    from news_pipeline.runtime import PipelineRuntime

    assert not hasattr(PipelineRuntime, "process_legacy")


async def test_store_keeps_same_title_at_different_urls_and_stores_zero_simhash(db):
    raw = RawNewsDAO(db)
    store = ArticleStore(raw)
    assert await store.save([article(1), article(1), article(2)]) == 2
    async with db.session() as session:
        rows = list((await session.execute(select(RawNews).order_by(RawNews.id))).scalars())
    assert [row.status for row in rows] == ["pending", "pending"]
    assert [row.title_simhash for row in rows] == [0, 0]


async def test_raw_dao_stores_zero_at_its_boundary(db):
    dao = RawNewsDAO(db)
    rid = await dao.insert_article(article(1, simhash=12345))
    assert (await dao.get(rid)).title_simhash == 0


@pytest.mark.parametrize("module", RETIRED_MODULES)
def test_retired_modules_are_absent(module):
    source = ROOT / "src" / module.replace(".", "/")
    assert not source.exists() and not source.with_suffix(".py").exists()


def test_active_source_has_no_retired_imports_or_simhash_computation():
    prohibited = []
    for source in (ROOT / "src").rglob("*.py"):
        if "migrations" in source.parts:
            continue
        for node in ast.walk(ast.parse(source.read_text())):
            imports = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            )
            if any(
                module == old or module.startswith(old + ".")
                for module in imports
                for old in RETIRED_MODULES
            ):
                prohibited.append(str(source.relative_to(ROOT)))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "title_simhash"
            ):
                prohibited.append(str(source.relative_to(ROOT)))
    assert prohibited == []


@pytest.mark.parametrize("source", RETIRED_SOURCES)
def test_enabled_retired_source_is_an_explicit_configuration_error(source):
    from news_pipeline.config.schema import SecretsFile
    from news_pipeline.scrapers.factory import build_registry

    with pytest.raises(ValueError, match=source):
        build_registry(
            SourcesFile(sources={source: {"enabled": True}}), WatchlistFile(), SecretsFile()
        )


async def test_historical_tables_are_preserved(tmp_path):
    import asyncio

    from alembic import command
    from alembic.config import Config

    from news_pipeline.storage.db import Database

    path = tmp_path / "history.db"
    migration = Config("alembic.ini")
    migration.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path}")
    await asyncio.to_thread(command.upgrade, migration, "head")
    database = Database(f"sqlite+aiosqlite:///{path}")
    try:
        await database.initialize()
        async with database.engine.connect() as conn:
            tables = await conn.run_sync(lambda connection: inspect(connection).get_table_names())
        assert {
            "entities",
            "news_entities",
            "relations",
            "audit_log",
            "dead_letter",
            "news_processed",
            "digest_buffer",
            "push_log",
        } <= set(tables)
    finally:
        await database.close()


def _app_leaf_paths(model, prefix=()):
    """Walk nested models, including model-valued lists and dictionaries."""
    from typing import get_args, get_origin

    from pydantic import BaseModel

    leaves = set()
    model_paths = {
        base.__name__: {prefix}
        for base in model.__mro__
        if isinstance(base, type) and issubclass(base, BaseModel) and base is not BaseModel
    }
    for name, field in model.model_fields.items():
        path, annotation = (*prefix, name), field.annotation
        origin = get_origin(annotation)
        if origin in (list, dict):
            value_type = get_args(annotation)[-1]
            if isinstance(value_type, type) and issubclass(value_type, BaseModel):
                annotation, path = value_type, (*path, "*")
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            child_leaves, children = _app_leaf_paths(annotation, path)
            leaves.update(child_leaves)
            for child, paths in children.items():
                model_paths.setdefault(child, set()).update(paths)
        else:
            leaves.add(path)
    return leaves, model_paths


def _config_consumers(sources, model_paths):
    """Resolve qualified reads through typed roots, aliases and actual method calls.

    Shared model parameter annotations never credit every occurrence of that
    model. Calls must pass the specific configuration section to the helper.
    Unknown expressions fail closed, and declarations/comments are not reads.
    """
    consumers = set()

    def scan(nodes, bindings, literals, signatures=None, call_bindings=None):
        signatures = signatures if signatures is not None else {}
        call_bindings = call_bindings if call_bindings is not None else {}

        def annotation_paths(annotation):
            names = {node.id for node in ast.walk(annotation) if isinstance(node, ast.Name)}
            # A unique typed root is unambiguous. Repeated models need call provenance.
            return set().union(
                *(paths for name in names if len(paths := model_paths.get(name, set())) == 1)
            )

        def paths(expr):
            key = ast.unparse(expr)
            if key in bindings:
                return bindings[key]
            if isinstance(expr, ast.Attribute):
                result = {
                    ()
                    if value == ("ConfigSnapshot",) and expr.attr == "app"
                    else (*value, expr.attr)
                    for value in paths(expr.value)
                }
                consumers.update(result)
                return result
            if isinstance(expr, ast.Subscript):
                result = {(*value, "*") for value in paths(expr.value)}
                consumers.update(result)
                return result
            if isinstance(expr, ast.IfExp):
                test = expr.test
                if (
                    isinstance(test, ast.Call)
                    and isinstance(test.func, ast.Name)
                    and test.func.id == "isinstance"
                    and len(test.args) == 2
                    and isinstance(test.args[0], ast.Name)
                ):
                    variable = test.args[0].id
                    original = bindings.get(variable, set())
                    narrowed = annotation_paths(test.args[1])
                    bindings[variable] = original & narrowed
                    body = paths(expr.body)
                    bindings[variable] = original - narrowed
                    otherwise = paths(expr.orelse)
                    bindings[variable] = original
                    return body | otherwise
                return paths(expr.body) | paths(expr.orelse)
            if isinstance(expr, ast.Call):
                if (
                    isinstance(expr.func, ast.Name)
                    and expr.func.id == "getattr"
                    and len(expr.args) >= 2
                ):
                    attr = expr.args[1]
                    names = (
                        {attr.value}
                        if isinstance(attr, ast.Constant)
                        else literals.get(ast.unparse(attr), set())
                    )
                    result = {(*value, name) for value in paths(expr.args[0]) for name in names}
                    consumers.update(result)
                    return result
                if (
                    isinstance(expr.func, ast.Attribute)
                    and ast.unparse(expr.func.value) == "self"
                    and expr.func.attr in signatures
                ):
                    method = expr.func.attr
                    arguments = call_bindings.setdefault(method, {})
                    parameters = signatures[method]
                    for name, argument in zip(parameters, expr.args, strict=False):
                        arguments.setdefault(name, set()).update(paths(argument))
                    for argument in expr.keywords:
                        if argument.arg in parameters:
                            arguments.setdefault(argument.arg, set()).update(paths(argument.value))
            return set()

        def read(expression):
            for descendant in ast.walk(expression):
                if isinstance(descendant, (ast.Attribute, ast.Call)):
                    paths(descendant)

        for node in nodes:
            if isinstance(node, ast.ClassDef):
                methods = {
                    method.name: [arg.arg for arg in method.args.args if arg.arg != "self"]
                    for method in node.body
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                arguments = {}
                while True:
                    previous = repr(arguments)
                    scan(node.body, bindings.copy(), literals.copy(), methods, arguments)
                    if repr(arguments) == previous:
                        break
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local = bindings.copy()
                for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                    if arg.annotation:
                        local[arg.arg] = annotation_paths(arg.annotation)
                        if ast.unparse(arg.annotation) == "ConfigSnapshot":
                            local[arg.arg] = {("ConfigSnapshot",)}
                    local.setdefault(arg.arg, set()).update(
                        call_bindings.get(node.name, {}).get(arg.arg, set())
                    )
                scan(node.body, local, literals.copy(), signatures, call_bindings)
                if node.name == "__init__":
                    bindings.update(
                        {key: value for key, value in local.items() if key.startswith("self.")}
                    )
            elif isinstance(node, ast.Assign):
                read(node.value)
                value_paths = paths(node.value)
                if isinstance(node.value, ast.Name) and node.value.id in model_paths:
                    for target in node.targets:
                        model_paths[ast.unparse(target)] = model_paths[node.value.id]
                for target in node.targets:
                    bindings[ast.unparse(target)] = value_paths
            elif isinstance(node, ast.AnnAssign):
                if node.value:
                    read(node.value)
                bindings[ast.unparse(node.target)] = annotation_paths(node.annotation) or (
                    paths(node.value) if node.value else set()
                )
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                target = ast.unparse(node.target)
                bindings[target] = {(*value, "*") for value in paths(node.iter)}
                consumers.update(bindings[target])
                if isinstance(node.iter, (ast.Tuple, ast.List)):
                    literals[target] = {
                        item.value
                        for item in node.iter.elts
                        if isinstance(item, ast.Constant) and isinstance(item.value, str)
                    }
                scan(node.body, bindings, literals, signatures, call_bindings)
                scan(node.orelse, bindings, literals, signatures, call_bindings)
            else:
                read(node)
                for _, child in ast.iter_fields(node):
                    if isinstance(child, list):
                        scan(
                            [item for item in child if isinstance(item, ast.stmt)],
                            bindings,
                            literals,
                            signatures,
                            call_bindings,
                        )

    for source in sources:
        scan(ast.parse(source).body, {}, {})
    return consumers


def _unused_app_fields(model=AppConfig, sources=None):
    leaves, model_paths = _app_leaf_paths(model)
    if sources is None:
        sources = [
            source.read_text()
            for source in (ROOT / "src").rglob("*.py")
            if source.name != "schema.py" and "migrations" not in source.parts
        ]
    model_nodes = set().union(*model_paths.values()) - {()}
    consumers = _config_consumers(sources, model_paths)
    return {
        ".".join(path)
        for path in leaves
        if path not in consumers
        or any(path[: len(parent)] == parent and parent not in consumers for parent in model_nodes)
    }


def test_every_retained_app_leaf_has_a_qualified_runtime_consumer():
    assert _unused_app_fields() == set()


def test_config_consumer_check_rejects_unused_leaf_even_with_duplicate_name():
    from pydantic import Field

    from news_pipeline.config.schema import OpsCfg

    class ExtendedOps(OpsCfg):
        max_tokens: int = 10  # The same name is consumed under llm.assess/digest.

    class ExtendedApp(AppConfig):
        ops: ExtendedOps = Field(default_factory=ExtendedOps)

    unused = _unused_app_fields(ExtendedApp)
    assert unused == {"ops.max_tokens"}
    with pytest.raises(AssertionError, match=r"ops\.max_tokens"):
        assert not unused, f"Unconsumed app leaves: {sorted(unused)}"


def test_shared_config_model_consumers_do_not_cover_an_unread_section():
    from pydantic import Field

    from news_pipeline.config.schema import LLMCfg, LLMTaskCfg

    class ExtendedLLM(LLMCfg):
        unused_task: LLMTaskCfg = Field(default_factory=LLMTaskCfg)

    class ExtendedApp(AppConfig):
        llm: ExtendedLLM = Field(default_factory=ExtendedLLM)

    assert {
        "llm.unused_task.model",
        "llm.unused_task.max_tokens",
        "llm.unused_task.prompt_version",
    } <= _unused_app_fields(ExtendedApp)


def test_shared_task_fields_are_credited_only_to_the_actual_call_argument():
    _, model_paths = _app_leaf_paths(AppConfig)
    consumers = _config_consumers(
        [
            """
class Consumer:
    def __init__(self, cfg: LLMCfg):
        self.cfg = cfg

    def run(self):
        unrelated = self.cfg.digest
        self.use(self.cfg.assess)

    def use(self, task: LLMTaskCfg):
        return task.max_tokens
"""
        ],
        model_paths,
    )
    assert ("llm", "assess", "max_tokens") in consumers
    assert ("llm", "digest", "max_tokens") not in consumers


async def test_new_ingestion_preserves_historical_simhash_values(db):
    from sqlalchemy import update

    dao = RawNewsDAO(db)
    old_id = await dao.insert_article(article("history"))
    async with db.session() as session:
        await session.execute(
            update(RawNews).where(RawNews.id == old_id).values(title_simhash=9123)
        )
        await session.commit()
    await ArticleStore(dao).save([article("history"), article("new", simhash=456)])
    assert (await dao.get(old_id)).title_simhash == 9123
    assert (await dao.find_by_url_hash("new")).title_simhash == 0


def test_bundled_app_uses_v2_with_paid_calls_disabled():
    import yaml

    app = AppConfig.model_validate(yaml.safe_load((ROOT / "config/common/app.yml").read_text()))
    assert app.pipeline.mode == "v2"
    assert not app.llm.enabled and app.llm.pricing == {}
