# LLM Cost

新评估与摘要的模型价格配置在 `llm.pricing.<model>.input/output`，单位为人民币 / 百万 token。单次记录费用为 `(tokens_in × input + tokens_out × output) / 1,000,000`；每日费用使用北京时间当天 llm_calls 求和。

默认 enabled=false、pricing 为空，不产生新模型调用。开启时评估/摘要实际模型都要有控制台核对的正数价格。这里不提供会被误当作实际报价的价格表，不承诺月费或 benchmark 结果。

并发请求预留保守输入与最大输出成本；费用预算和四并发限制由评估与摘要共享，预算满后规则兜底并一天告警一次。调用记录包含内部 HTTP 重试与校验重试，不能只数最终成功响应。

只读 rules replay 与 `--eval --mode rules` 不花模型费用；`--mode llm` 或未显式指定 mode 的 `--eval --model ID` 进入付费路径，先取得授权。缓存命中复用此前结果，不再作为新付费调用。8 条 seed 未审核；150 条人工 gold set 与模型对比尚未完成。详见 [Assessment](../components/llm-pipeline.md)。

候选模型的公开价格核实与一轮训练/留出集费用估算见 [B0 模型准备](../operations/b0-model-proposal.md)。评估与摘要请求固定非思考模式，避免供应商默认思考增加未预留的输出费用；旧默认模式的回放缓存与新请求隔离。
