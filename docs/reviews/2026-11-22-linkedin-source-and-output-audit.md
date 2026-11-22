# LinkedIn source, checkpoint and output audit — 22 November 2026

**Evidence cutoff:** committed production `docs/data/health.json` generated at
`2026-11-22T06:39:14Z`, scheduled `predoc-pipeline` #44994015596.
Public `docs/data/listings.json` generated `2026-11-22T06:39:13Z`.
This is a **read-only evidence review**, not a live LinkedIn probe, a provider
authorization, or proof that any displayed opportunity remains open or funded.

## Policy and live source telemetry

| Measurement | `board:linkedin` economics | `life_linkedin` |
|---|---:|---:|
| Checkpointed query identities | 313 | 93 |
| Unfinished pending cursors | 274 | 78 |
| Cached replay candidates | 4 | 124 |
| Latest observed source status | skipped | skipped |
| Latest observed new provider requests | 0 | 0 |
| Provider cooldown at 06:39 UTC | active via peer checkpoint | active |
| Last recorded Life Sciences source success | n/a | 2026-11-15 21:08:04 UTC |

The economics portfolio contains 675 configured keyword/location combinations;
313 checkpoint identities are not 313 completed searches. Its last committed
provider block is `2026-11-20T07:10:55.933852+00:00`; the Life Sciences peer
block is `2026-11-22T07:11:23.031836+00:00`. The later peer block is read by
both adapters. An elapsed timestamp is **not** permission to bypass 403/429,
robots, account restrictions, or an authorization barrier.

The current production economics diagnostics report `requests=0`,
`completed_queries=0`, `replay_candidates=4`,
`provider_cooldown_active=true`. Specialist health reports
`status=skipped`, `vacancy_links=120`, `doctoral_candidates=83`,
`matched_candidates=0`; these counts include saved/replayed cards and
**do not establish a successful new discovery or funded vacancy**.
A green GitHub Actions workflow is separate from this ingestion outcome.

## Output provenance and quality

The committed academic journal contains 474 historical listings, including
116 LinkedIn-origin records. The public academic snapshot contains 220 rows,
including **77 LinkedIn-origin rows**. Of those 77, **55** have no recorded
deadline and **70** still use LinkedIn itself as their application destination.
All 77 have distinct source LinkedIn job IDs; unique URL identity alone
is not proof of distinct employer requisitions.

The separate `data/career_jobs.ndjson` has 94 retained rows, including
**8 `life_linkedin` entries**. Every one of those eight has
`funding_status=unverified`; four have deadlines before 2026-11-22.
The broader multi-discipline “Fully Funded PhD Positions” LinkedIn card is
an admission aggregation warning, not verification of a funded individual
research studentship. Preserve historical records and differentiate explicit
deadline expiry from a recent employer confirmation.

The authoritative `data/seen.ndjson` contains 289 LinkedIn decisions:
179 rejected, 76 accepted, and 34 duplicate decisions. **Two** historic
accepted decisions from 2026-10-03 have null `listing_url_hash` references.
This is a *traceability gap*, not proof that two public listings or two
Telegram receipts went missing. Reconcile only against canonical URL and
durable journals before repairing linkage.

## Confirmed non-actionable public application destinations

| Public ID | Generic destination | Handling |
|---:|---|---|
| 340 | `https://hrs.missouri.edu/find-a-job/academic` | Withhold from actionable projection |
| 341 | `https://careers.wvu.edu/career-opportunities` | Withhold from actionable projection |
| 353 | `https://careers.fiu.edu/` | Withhold from actionable projection |
| 441 | `https://jobs.illinois.edu/` | Withhold from actionable projection |

These are institution-level career indexes, not vacancy requisitions. A
corresponding **exact-host/path** regression and **public JSON/RSS**
correction are proposed in [PR #214](https://github.com/AmirrezaFarnamTaheri/Collegeum/pull/214).
Those changes should not edit `data/listings.ndjson`, the separate career
journal, permanent URL hashes, private subscriber marks, or Telegram receipts.

## Identity risk: UiT same-title cluster

There are now **six** publicly visible LinkedIn-origin records with the exact
title “Postdoctoral Research Fellow in Climate and Environmental Governance”
and institution-name variants of UiT:

| Collegeum ID | LinkedIn job ID |
|---:|---:|
| 222 | 4477002506 |
| 233 | 4477783880 |
| 235 | 4478230740 |
| 291 | 4481871120 |
| 327 | 4483945899 |
| 371 | 4485593855 |

The earlier [November 3 audit](../LINKEDIN_OUTPUT_QUALITY_AUDIT_2026-11-03.md)
identified five of these and a plausible official UiT Jobbnorge requisition
`309437` with November 15 closing date. **The per-LinkedIn-ID to
official-requisition crosswalk is still unverified**. Identical title plus
employer-name normalization does not authorize collapsing IDs, editing
publication state, or deleting Telegram acknowledgements.

Do not merge or suppress these six as one official requisition until an
independently verified ID crosswalk and closure evidence support that exact
operation. Conversely, do not advertise missing deadlines as confirmed
rolling/open applications.

## Work required for acceptance

1. Keep 403/429 access denials truthful and bounded; no UA/proxy/account
   rotation, further keyword probing after a Workday denial, or new LinkedIn
   traffic during provider cooldown. [PR #211](https://github.com/AmirrezaFarnamTaheri/Collegeum/pull/211)
   adds offline RED/GREEN regressions for the shared board client.
2. Apply and CI-verify the exact-link public projection correction in PR #214,
   then independently audit dashboard/RSS against the unchanged journals and
   delivery ledger.
3. Record future **permitted** LinkedIn source checks separately: requests,
   completed query windows, partial cursors, cached replay cards, accepted
   academic opportunities, and genuinely new notifications. Never count
   replay as fresh completed coverage.
4. Obtain employer-specific evidence before changing candidate availability,
   funding, generic application paths, or the six UiT identities. The two
   accepted decision entries with missing journal references require the
   same provenance discipline.
5. Independent schedule recovery remains subject to [issue #52](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues/52);
   EconJobMarket redistribution approval remains separate in
   [issue #150](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues/150).

**No production workflow dispatch, LinkedIn live fetch, policy-blocked retry,
private journal mutation, Telegram send, or receipt reset is part of this audit.**
