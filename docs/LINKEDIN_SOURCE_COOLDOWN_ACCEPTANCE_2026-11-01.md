# LinkedIn source access-cooldown acceptance — 1 November 2026

This document describes a source-health classification correction, **not a
recovery or permission to resume blocked provider access**.

## Reproduction

The post-#99/#102 production pipeline
[run #41313993910](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41313993910)
checkpointed `docs/data/health.json` at **2026-11-01T14:06:42Z**.
It attempted 75 general sources (65 successful, 8 benign empty,
**one failed**, one skipped); the workflow was green, application
`outcome=partial`, with one source error.

The failed source was **`board:linkedin`**. Its scheduler diagnostics
explicitly show `provider_cooldown_active=true`,
`requests=0`, `plan_size=0`, `completed_queries=0` and no raw
new cards or new HTTP fetch failures. The previous LinkedIn access
restriction was recorded until **2026-11-03T05:50:37.969631Z**.
The collector's unconditional `discovery_limits.append` for a
known policy cooldown converted this intentional *no-request* interval
into `failure_stage=limit`, `status=failed`, an additional source error,
and a discovery DLQ row. This obscured the distinction between a new
HTTP failure and a previously observed restriction.

The read-only Life Sciences health at
**2026-11-01T14:04:56Z** recorded `life_linkedin` as `partial`
even though its new search was correctly deferred by the same
cross-audience provider restriction. Archived candidate replay (up to
120 linked cards) is **not a successful new search**.

## Fix and boundaries

- `LinkedInScraper.intentionally_deferred` is true only for
  checkpointed search with **zero actual requests** and an active
  provider block **or** no due query in the ordinary 48-hour rotation,
  and **no** discovery fetch, parse, or limit errors. It does **not**
  relabel an actual attempted HTTP 403/429/999.
- The general collector treats this precise result as **skipped**,
  with `fetched=0`, `errors=0` and a sanitized public diagnostic.
  A replay buffer remains accessible for ordinary field, degree and
  URL checks. This prevents false network-failure DLQ rows while
  leaving the incomplete source coverage clearly visible.
- Life Sciences selected health uses **skipped** for a clean deferred
  checkpoint and retains `partial` for actual discover/detail errors.
  Historical cards are not presented as employer-verified live jobs.
- Known `access_blocked_until`, pending query offsets, previous
  `last_complete_at`, cached replay, durable general and Life Sciences
  listing identities, and subscriber/Telegram receipts are left
  untouched. **No active provider request is made by these tests.**
- A new real HTTP 429 remains **failed** with an atomic ledger
  cooldown and no completed-query timestamp. Active cooldown and
  successful query coverage are distinct states.

## Regression checks

Offline fakes reproduce the original wrong `failed` / `partial`
statuses (RED before patch) for zero-request and replay cases.
Green tests cover: source skipped with and without cached cards;
no new HTTP calls; sanitized public counts and message; no bogus
source error or discovery DLQ; no-due 48-hour query rotation;
real first HTTP 429 remains failed; independent Life Sciences
source-health skipped; cross-audience restriction and journal
checkpoint preservation. Full Python 3.11/3.12 CI and Telegram Worker
remain required merge gates.

## Production acceptance still required

1. Verify an **actually persisted, source-bearing run on merged main**
   reports `board:linkedin.status=skipped` and a Life Sciences selected
   `life_linkedin.status=skipped` when the prior cooldown still applies.
   Confirm the run issues **zero** new LinkedIn requests, has **zero
   associated new discovery DLQ**, and remains truthful about
   other independent collection and Jobinja robots limitations.
2. **Do not attempt new LinkedIn access before its recorded
   policy cooldown expires**. A later permitted source-bearing run
   must independently check query coverage, bounded paging, resume
   offsets, and relevant employer-level application links.
3. A clean adapter fix cannot establish that any historical LinkedIn
   title is a currently-open or funded vacancy. Continue separate
   official employer and recruiting-identity checks.

Keep broad issues #32 and #80 open until these external acceptance gates
are demonstrably met, and issue #52 open for independently observable
scheduling/liveness.
