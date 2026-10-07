# Monitoring

观察进程心跳、来源健康与消息投递三个维度，详见 [Observability](../components/observability.md)。默认日志通过 Docker Compose 获取。

```bash
docker compose ps
docker compose logs --tail=200 app quote_watcher
```

每日系统卡片汇总过去 24 小时来源、拦截、成功推送、摘要展示、失败与模型费用。旧新影子对比已移除，运维卡片继续发送。未收到日报先查 heartbeat 和 ops delivery，而不是只看最近有无新闻。

Datasette 仅本机 `127.0.0.1:8001`，远程经 SSH 隧道。查询 events、deliveries、llm_calls；历史旧路径证据可查询 news_processed/push_log 和 legacy_digest 审计。消费候选数不等于展示条数，pending 不等于已发送。

没有本次改造已经达到线上重复率、召回或实际费用门槛的结论。记录真实部署和授权模型实验结果后才能作验收判断。
