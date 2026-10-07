# B0 acceptance preparation

Continue the approved design §3.10 without bypassing its human review, paid-call confirmation or production observation gates. Existing A/B code is complete; the reviewed dataset and real model acceptance are not.

## Tasks

- [x] Preserve article provenance, market, timestamps, metadata and stable identifiers in the review CSV; round-trip corrected labels/tickers into JSONL without manufacturing human approval.
- [x] Validate reviewed rows, duplicates, labels, known-case coverage and the 50/50/30/20 strata. Persist a deterministic 120/30 train/holdout split so prompt tuning can exclude the final set.
- [x] Add an import/validation CLI and document the exact review workflow. Reject unreviewed or insufficient data as acceptance evidence while retaining the eight seed examples for regression.
- [x] Wire replay selection and reports to the split, dataset identity and the five design thresholds. Rules/seed reports must not claim LLM acceptance; holdout acceptance needs reviewed full-dataset evidence.
- [x] Inspect local upstream reachability using read-only requests where credentials are unnecessary; distinguish local observations from deployment-IP and trading-session acceptance.
- [x] Obtain independent specification review then code-quality review, run affected and full checks, commit and integrate into the user's feature branch.

Implementation and verification details are in the [verification report](../reviews/2026-10-07-b0-acceptance-verification.md). These completed preparation tasks do not mark the external B0 acceptance or production observation gates complete.

## External prerequisites

The initial checkpoint had no local news database. The follow-up located the documented production database and extracted a three-week read-only raw-news slice; the real 150-event review CSV is now available locally. See the [follow-up verification record](../reviews/2026-10-07-rollout-hardening-verification.md). Human review and explicit confirmation of concrete model/cost choices remain necessary before actual model benchmarking. No paid call, outbound message or production configuration switch is authorized by this preparation step. C1/C2 and D retain their one-/two-week observation gates.
