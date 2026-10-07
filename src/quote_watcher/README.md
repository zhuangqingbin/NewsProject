# quote_watcher

独立 A 股盯盘：腾讯个股快照（默认，Sina 可切换）与东财全市场/行业扫描 → tick 与日 K 缓存 → 阈值、指标、事件及持仓规则 → CN _alert 飞书频道。日 K 仍由 akshare 获取。

新闻清理不改变盯盘处理、独立 quotes.db 或 alerts reloader。alerts.yml 支持专用热加载；盯盘列表与持仓修改后重启 quote_watcher。

- [完整配置、环境变量与操作步骤](../../docs/quote_watcher/getting_started.md)
- [子系统说明](../../docs/subsystems/quote_watcher.md) · [配置目录](../../config/quote_watcher/README.md)
- [共用配置与密钥](../../config/common/README.md) · [部署与备份](../../docs/getting-started/deployment-current.md)

配置位于 config/quote_watcher，真实密钥模板是 config/common/secrets.yml.example。Compose 直接运行 Python；仅新闻 app 的启动入口执行新闻数据库迁移，不让盯盘重复迁移新闻库。
