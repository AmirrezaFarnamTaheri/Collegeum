# Collegeum open-issues acceptance register — 1 November 2026

This is a point-in-time, read-only evidence reconciliation for [#32](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues/32),
[#52](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues/52), [#56](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues/56), and [#80](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues/80).
GitHub PR/issue links are on
[Collegeum](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues).
This file does **not** claim that every vacancy is active, that scheduled
LinkedIn searches finished, or that GitHub cron delivered every tick.
Nothing here authorizes a blocked-provider retry or state migration.

## Current source-bearing production baseline

- [Production ingestion #41278362736](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41278362736):
  `docs/data/health.json.generated_at=2026-11-01T05:57:28Z`.
  Source-bearing check: **76 general sources: 66 successful, 8 expected-empty,
  0 failed, 1 partial, 1 skipped**. Workflow conclusion `success` while
  pipeline outcome **`partial`**; 302 ingested, 17 extracted, **5 newly published**
  and **one source error**. Do not substitute historical published counts for
  current application availability.
- **BIS recovered** in this newer production run: 7 official vacancy-feed
  items, zero source errors. The October 31 BIS DLQ incidents are superseded
  and must not be treated as the current blocker.
- **LinkedIn is the partial general source:** 119 replay/collection raw items
  and a failed request. The source-error record is **not proof of 119
  completed searches**. Read-only inspection of the persisted
  `data/linkedin_econ_search_state.json` shows 14 query rows (13 pending,
  one access-limited), 16 buffered candidates and a 429 access cooldown until
  **2026-11-03T05:50:37.969631Z**. Life Sciences checkpoint has 20 pending
  query rows and 155 buffered candidates, without a recorded self-cooldown.
  [PR #99](https://github.com/AmirrezaFarnamTaheri/Collegeum/pull/99)
  has merged cross-audience cooldown and HTTP 999 fail-closed handling.
  A new provider-compliant, **post-merge** production run is required to
  verify shared cooldown, cursor preservation, and later actual coverage.
- Archived [output-audit-41278362736](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41278362736):
  333 general journal rows, 186 published and currently publicly visible
  snapshot entries, 100 RSS entries, zero invalid public IDs or RSS links.
  Two historical *journal-only* quarantine candidates (IDs 25 error-page
  URL and 322 generic job-board search) remain excluded; no irreversible
  record change is justified. This archive's `source_failures=0` means
  **zero fully failed** sources, *not* zero partial/errors.
  The associated DLQ has **one sanitized entry**: discovery,
  `board:linkedin`, `Source request failed`, with no URL/payload.
  The additive audit fields proposed in the linked PR explicitly report
  partial-source counts and source errors.
- `data/life_sources_health.json` was checked
  **2026-11-01T05:53:51.534622Z**: 226 registered, 40 enabled,
  12 selected this rotation (12 discovered, no current selected errors).
  Across preserved *latest observations*, 39 source records are discovered
  and one (`life_euraxess_neuroepigenomics`) remains historically partial
  from October 31. Do **not** mistake unselected historic status for a new
  November 1 failure. Bern, AcademicTransfer, VIB and DKFZ have source
  discovery evidence, not universally verified open/funded doctoral posts.
- `data/career_jobs.ndjson` contains 85 historical Life Sciences PhD rows
  with **85 distinct source URLs**; 60 lack persisted deadlines, 28
  lack explicit country, 85 lack structured research fields and no row
  has verified current-open/funding evidence. Never present these historical
  discoveries as 85 currently open/funded jobs.

## Issue #52 — ingestion scheduler reliability

The configured schedule is `7 */4 * * *` UTC. From the GitHub Actions
scheduled-run creation history, a conservative 24-hour reconciliation ending
**2026-11-01 13:30 UTC** assigns:
- 31 October 16:07 -> run 41236294647 created 19:53:14;
  20:07 -> run 41251862847 created 23:16:59.
- 1 November 00:07 -> **no run observed** within the following 4 hours;
  04:07 -> run 41278362736 created 05:48:51;
  08:07 -> **no run observed** within the following 4 hours;
  12:07 -> **not yet mature at 13:30**, so not a missed tick.

Thus 6 nominal slots, 3 observed scheduled events (all >30 min late),
2 **unobserved mature slots**, and 1 unsettled. The longest observed
creation delay was 3h46m14s. A separately dispatched run must **never**
be relabeled a cron event. API event-created times cannot establish the
GitHub scheduler's internal queue/trigger cause, and a missing event does
not prove GitHub dropped an invocation.

[PR #53](https://github.com/AmirrezaFarnamTaheri/Collegeum/pull/53)
merged a guarded GitHub Actions freshness watchdog and
[PR #54](https://github.com/AmirrezaFarnamTaheri/Collegeum/pull/54)
merged an eight-hour dashboard warning. This PR adds **read-only**
scheduled-tick reconciliation to existing watchdog logs and job summaries,
without new GitHub API requests, credential exposure, or extra publishers.

**Unmet:** run a repeated multi-day audit, identify whether missing
observations are scheduler/queue/history limitations, and establish an
*independently hosted* freshness SLA if operationally required.
This cannot be proven by a green GitHub Actions workflow alone.

## Issue #80 — Life Sciences and collection integrity

Earlier Mannheim, VIB, AcademicTransfer, Bern, Helmholtz, DKFZ, EMBL
and BIS discovery defects have separate merged fixes and production
observations. Mannheim/Copenhagen and CREST endpoints were disabled
after recorded official access denials or upstream outage. Jobinja's
robots denial is a distinct career-source limitation, not a general
source parser defect. Do not bypass any access policy.

**Unmet:** employer-verified open/closed status, eligibility and funding;
precision/recall sampling; duplicated job-title identity checks; a fresh
post-#99 LinkedIn production checkpoint and read-only artifact review.
Retain immutable listing IDs, publication history, subscriber preferences
and Telegram receipts.

## Issue #32 — earlier degraded sources and listing identities

The production-verified repairs for BIS, ifo, ZEW, SOMMa, AcademicTransfer
and Workday should not be re-opened based solely on older failed snapshots.
EURAXESS general returned 10 items with zero errors on November 1, although
filter semantics and independent job-level eligibility still require checks.
Copenhagen (TCP/access denial), CREST (503/denial), and Jobinja
(robots-blocked) have no verified permitted replacement routes.
Explicitly avoid marking blocked searches verified empty.

**Unmet:** evidence-based cross-post identity checks for historical
UiT/King's College candidates and other same-title records, safe action
links and application verification, and the fresh post-#99 source coverage
acceptance.

## Issue #56 — official economics and predoc source expansion

Already integrated and not to be duplicated: Yale EGC, Wharton Workday,
WIFO, CEPS, IFAU as verified-empty, and the previously enabled employer
boards. A shared Federal Reserve Workday listing is a candidate source;
a generic shared tenant or geographic label does not prove the specific
employing Reserve Bank.

- **Access constrained** (remain disabled): Princeton RPDE and UCL
  Management returned HTTP 403 from GitHub runners; IFS/BeApplied has also
  returned 403. No retries via proxies or scraping restrictions.
- **Parser/identity work required before enabling**: Brookings iCIMS
  rendered an unusable list for the current parser. ESRI, LISER, IAB,
  VATT/Bank of Finland, UNU-WIDER, and other candidates need official,
  job-specific URLs, scope/degree checks and actual runner acceptance.
- **Not proven actionable**: LSE CEP internship/programme notices,
  generic SEO Netherlands open applications, and broad job directories.
  The US Center for Economic and Policy Research (`cepr.net`) is a
  different institution from the UK `cepr.org` entry and needs separate
  source validation.

Each **newly enabled source** needs official accessible employer-hosted
vacancy identities, robots-policy compliance, no false job counts,
offline RED/GREEN fixtures, a safe read-only GitHub-runner probe,
green exact-head CI, and later a newly selected production source
observation. Candidate URLs or HTTP 200 alone are not enough.

## Acceptance ledger (not automatic issue closure)

1. Confirm post-merge `main` CI and packaging on exact integrated commit;
   no historical journal, subscriber or Telegram acknowledgement changes.
2. At/after the **existing** LinkedIn access cooldown, observe provider-
   compliant production scheduling. Confirm the shared restriction is honored
   *before* it expires and no failed query gains a completed timestamp.
   A later unblocked run must show per-audience request/coverage outcomes;
   finite raw-card counts do not certify full search coverage.
3. Compare output-audit `source_failures`, `source_partials`,
   `source_errors`, and expected-empty/skipped independently; verify
   both general and Life Sciences cohort rotation without inventing
   current vacancy availability.
4. Keep #32, #56, #80 and #52 open until their independent external
   verification gates are met. Close only specific subproblems supported
   by production evidence, not broad umbrella issues on the basis of CI.

**Scope rule:** audit code/tests/docs only. No direct production dispatch,
provider request, data journal rewrite, historical notification backfill,
or Telegram Worker activation is part of this change.
