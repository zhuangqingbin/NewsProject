def test_smoke_report_includes_leak_and_contract_failures():
    from news_pipeline.health.smoke import build_smoke_report

    message = build_smoke_report(
        [
            {
                "source_id": "wire",
                "ok": True,
                "count": 10,
                "leak": {"checked": 8, "present": 5, "title_duplicates": 1, "missing": 2},
            },
            {"source_id": "broken", "ok": False, "count": 0, "error_type": "MissingColumn"},
        ]
    )
    assert "检查 8" in message.summary and "丢失 2" in message.summary
    assert "标题重复 1" in message.summary and "MissingColumn" in message.summary


async def test_manual_smoke_sends_report_unless_no_report_is_selected(tmp_path, monkeypatch):
    import sys
    from unittest.mock import AsyncMock, MagicMock

    from news_pipeline.health import smoke
    from shared.push.base import SendResult
    from tests.unit.optimization.test_v2_runtime import snapshot

    snap = snapshot("v2")
    snap.app.ops.report_channel = "feishu_us"
    monkeypatch.setenv("NEWS_PIPELINE_DB", str(tmp_path / "missing.db"))
    monkeypatch.setattr(smoke, "cli_registry", lambda: (snap, MagicMock()))
    monkeypatch.setattr(
        smoke, "run_smoke", AsyncMock(return_value=[{"source_id": "wire", "ok": True, "count": 3}])
    )
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value={"feishu_us": SendResult(ok=True)})
    monkeypatch.setattr("shared.push.factory.build_pushers", lambda *args: {})
    monkeypatch.setattr("shared.push.dispatcher.PusherDispatcher", lambda *args: dispatcher)
    monkeypatch.setattr(sys, "argv", ["smoke"])
    await smoke._main()
    dispatcher.dispatch.assert_awaited_once()
    monkeypatch.setattr(sys, "argv", ["smoke", "--no-report"])
    await smoke._main()
    assert dispatcher.dispatch.await_count == 1


async def test_startup_and_weekly_probes_enqueue_ops_report_even_in_shadow(db):
    from news_pipeline.main import enqueue_smoke_report
    from news_pipeline.runtime import PipelineRuntime
    from shared.push.dispatcher import PusherDispatcher
    from tests.unit.optimization.test_v2_runtime import snapshot

    snap = snapshot("shadow")
    snap.app.ops.report_channel = "feishu_us"
    runtime = PipelineRuntime(db, snap, PusherDispatcher({}))
    try:
        await enqueue_smoke_report(
            runtime, snap, [{"source_id": "wire", "ok": True, "count": 2}], "startup@fixture"
        )
        row = await runtime.deliveries.get(1)
        assert row.kind == "ops" and row.status == "pending"
        assert row.channel == "feishu_us" and row.payload["title"] == "源冒烟检查"
    finally:
        await runtime.close()
