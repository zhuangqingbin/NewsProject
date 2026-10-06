# Troubleshooting

## 进程 unhealthy

检查 Compose 状态、日志及对应 heartbeat 文件。文件三分钟未更新表示进程/调度器不活跃，不是“最近没有新闻”。新闻和盯盘各自检查，冷日 K 初始化可能受上游延迟影响。

## 来源 down

查看 source_state 的 failing/silent 原因、last_error、成功与条目时间、paused_until。连续失败的退避最多 30 分钟；运行 smoke --no-report 验证当前服务器 IP 返回结构，运行 leak_check 分析真丢失。不要把结构异常改成 return [] 绕过告警。

## 没收到新闻或摘要

核对 pipeline.mode、规则候选、静默/新鲜度/突发降级、市场频道及密钥。shadow 新事件/摘要设计上不发送，旧路径仍发；运维卡片仍发。v2 检查 delivery pending/failed/expired、attempts 与 next_attempt_at，摘要只有全部频道成功才消费。

## LLM 不调用

默认 enabled=false。核对当前模式、候选资格、实际模型正数定价、供应商 key、日预算与熔断。旧 llm.tier* 或 watchlist.llm.enable 不控制新评估器。评估失败使用规则兜底，不代表消息必定被丢弃。

## SEC / 飞书配置失败

SEC 使用真实联系人和邮箱，未知 ticker 配置需修正。飞书核对 nested secrets 路径、启用频道和签名密钥，不把完整 URL 发到日志或 issue。修改新闻配置后重启 app。

## 回滚与复核

遵循 [部署回滚](../getting-started/deployment-current.md)，保留失败证据。B0 未审核 seed、单元测试与 startup probe 不能代替人工 gold set、授权模型评测和交易时段的实际验收。
