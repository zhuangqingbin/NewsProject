# Rollout hardening and real B0 preparation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Make the approved design's JSON calls and mode rollback reliable, obtain real B0 source data, and prepare a dated price/cost proposal without invoking models.

**Architecture:** Preserve ChatProtocol and existing caller budgets. The shared ChatClient sends `enable_thinking: false`; cached replay identities include this request setting so older provider-default results cannot be reused. Keep LLM disabled and default prices empty until actual model acceptance/configuration.

**Tech Stack:** Existing Python/httpx/Pydantic/pytest stack, official Alibaba Cloud documentation.

## Tasks

- [x] Write failing tests for explicit non-thinking requests for deepseek-v4.1-flash, deepseek-v4-flash, qwen3.8-flash and qwen-plus, including both assessment and digest token limits. Assert missing-flag historical cache files are not hits.
- [x] Add `enable_thinking: false` at the shared request boundary, include it in replay cache identity, and verify existing cache hits, retry/accounting and client closure remain correct. Do not add configurable thinking support or new dependencies.
- [x] Independently audit legacy/shadow/v2 runtime contracts and address only reproducible material defects.
- [x] Add red/green rollback tests and prevent legacy/shadow from dispatching old v2 news queues while allowing ops; restore old-path send deduplication from successful recent v2 immediate deliveries.
- [x] Extract the actual three-week raw-news slice in a single read-only SQLite transaction over the documented SSH target, verify a local snapshot and produce an unreviewed source-backed 150-event CSV with the required cases.
- [x] Record current public Beijing non-thinking list prices, DeepSeek peak pricing and the 4×120 training plus 1×30 final-holdout cost arithmetic. Distinguish estimates from hard limits and account-specific availability; do not request paid-call approval until the real dataset is reviewable.
- [ ] Obtain specification then quality review of the final patch. Attempts were blocked by review-subagent usage limits; no independent approval is claimed.
- [x] Complete root review and affected/full tests, Ruff, mypy and documentation/Compose checks. Results and limits are in the [verification record](../reviews/2026-10-07-rollout-hardening-verification.md).

Integration target: local commits in the isolated worktree, then fast-forward `feature/pipeline-optimization`; no push or production change. Retain the worktree for the pending independent review and later B0 acceptance.

## Evidence and prerequisites

Official deep-thinking documentation confirms that deepseek-v4.1-flash, deepseek-v4-flash and qwen3.8-flash default to thinking, and `max_tokens` only bounds final-answer tokens in that mode. See https://help.aliyun.com/zh/model-studio/deep-thinking and https://help.aliyun.com/zh/model-studio/qwen-structured-output. The existing client omits the mode flag while reservations assume only the configured answer-token allowance.

Initial inspection found no local news database and local Docker is not running. A project deployment plan supplied the existing SSH target; read-only SSH found `/opt/NewsProject/data/news.db` at migration 0003. Extract only a local sample slice, without changing services or migrating the production database. Human review, actual provider-account capability/region checks, paid-call confirmation and all production observation gates remain outstanding. This work sends no real model request or notification and changes no production mode.
