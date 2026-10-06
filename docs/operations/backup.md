# Backup

新闻与盯盘 SQLite 都启用 WAL。活动数据库不能只复制 `.db`，否则备份可能缺少未 checkpoint 的写入。使用 SQLite backup API 生成一致副本；部署前推荐停止 app/quote_watcher 写入，并保存配置与旧镜像。

可直接执行的 Compose 备份命令见 [部署指南](../getting-started/deployment-current.md)。备份位于宿主 `data/backups`，该目录随 data volume 持久化；含密钥的配置归档限制权限并另做离机副本。

恢复前停止写入，先在隔离副本检查 integrity_check、迁移版本与数据量，保留当前库和 WAL，再决定替换。普通模式回滚不恢复数据库、不运行 downgrade；误用恢复会丢掉备份后的新闻、费用和发送记录。

每月 VACUUM 是空间回收，不是备份。执行前确认临时空间；保留任务会删除超过期限的无引用数据，不能依赖它实现历史归档。详见 [存储](../components/storage.md)。
