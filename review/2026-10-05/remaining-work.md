# Remaining work from the initial audit

**10 October follow-up:** This dated inventory is superseded where explicitly
updated by [FINALIZATION.md](../../FINALIZATION.md). The registry now contains
88 boards (81 enabled), suitable researched sources have been integrated,
protected same-vacancy fact refresh is connected, single-post X recovery is
implemented, and the distribution has been rebuilt. Historical reconciliation,
cohort lifecycle and complete operational acceptance are still open.

Status checked against the current remediation ledger on 6 October 2026. The original audit contains F01–F51; the merged external report adds F52–F67. Implemented runtime changes do not establish completion of historical repair, live coverage or operational verification. Some old ledger table labels are superseded by its newer verification notes.

## What remains now

Substantial work remains. The largest unfinished deliverables are:

1. **Complete vacancy updates/reopening:** connect the protected fact-refresh operation to the pipeline; distinguish a changed existing vacancy from a new recruitment cohort; implement refresh-budget rotation and avoid treating refreshed adverts as newly discovered vacancies.
2. **Activate source expansion:** 19 official candidate pages are researched, but zero are integrated/enabled. Each needs an adapter or verified existing adapter, fixtures, identity checks and transport validation.
3. **Finish extraction correctness:** deadline precision/timezones/review dates, location provenance and homonyms, required-versus-preferred qualifications/tools, JavaScript-shell rejection, aggregator contamination, discipline and PI inference.
4. **Repair historical outputs:** reconcile old IDs/hashes, suppressed duplicates, category decisions, deadlines, locations, salary/visa/summary facts and feedback associations. Runtime fixes alone have not repaired stored data.
5. **Finish network/cache/recovery boundaries:** robots by origin, public-network/redirect restrictions, uncertain reachability, cached-but-unprocessed items, case-sensitive fetched changes and single-404 closure handling.
6. **Finish bot/delivery/privacy guarantees:** partial/uncertain Telegram and X outcomes, replay retention, malformed private-state recovery, independent destination retries and preventing public exposure of personal marks.
7. **Finish UI/distribution/operations:** narrow-mobile audit, single-file build freshness, workflow budget/deadline alignment, remaining docs/policy obligations, and representative live source coverage/count reconciliation.
8. **Complete verification follow-through:** appropriate live/browser/adapter checks, migration/replay proofs and requirement-by-requirement closure. Local test success does not close these obligations.

Since the previous status report, Pages opt-in, shared pending-run queuing, memo endpoint/credential isolation and positive-worker/finite-budget validation have been fixed locally. Workday partial-result recovery has broader regression coverage. These are no longer wholly unimplemented issues; their remaining limits are listed below.

## Main unfinished areas

| Area | Remaining requirements | Findings |
|---|---|---|
| Vacancy updates and reopening | Connect fact refresh to verified same-vacancy decisions; handle renewed cohorts, closure/reopening and publication behavior. Suppress volatile age-label changes without suppressing meaningful updates. | F05 |
| Dates and geography | Preserve date-only versus timed deadlines and source timezone; separate priority/review dates from hard cutoffs; honor explicit month-first instructions; finish country-default provenance and ambiguous-location handling. | F03, F04, F34, F50; imported F56 |
| Extraction accuracy | Distinguish required versus preferred qualifications/tools; reject JavaScript shells; keep aggregator context from supplying false employers/application links. Remove boilerplate discipline tags and incorrect PI/title inference. | F14–F16; imported F54, F55 |
| Source health and coverage | Finish representative custom-adapter/live contracts, seasonal-empty policy and operational failure reporting. Reconcile configured/enabled/healthy coverage; verify live Workday pagination. | F06, F07, F19, F51 |
| Networking and recovery | Preserve reachability uncertainty; enforce robots by origin and preference; finish public-network/DNS/redirect boundaries. Prevent unchanged HTTP cache results from losing unprocessed items; preserve case-sensitive fetched-link changes. Avoid permanent closure based on one 404. | F20, F25, F26, F46, F47; imported F64 |
| Scheduling and limits | Complete the wider direct-caller/cap audit and align stage budgets with workflow deadlines. Verify deployed queue behavior; positive-worker validation and queue configuration are implemented locally. | F33, F48; imported F62 |
| Bot and personal state | Finish partial/uncertain message delivery, callback-history retention and recovery guarantees; audit malformed private-state handling and public exposure of application marks. | F27, F44; imported F61, F67 |
| Deduplication and migrations | Verify stdlib similarity fallback; migrate legacy listing IDs/URL hashes; replay historical suppressed duplicate decisions without losing feedback or delivery history. | F09, F21, F22, F37 |
| Website and distribution | Verify/fix narrow mobile navigation and overflow; regenerate and verify the stale single-file distribution. Pages opt-in is fixed locally, with remote behavior unexercised. | F31, F32, F38 |
| Configuration and operating docs | Finish remaining schedule/default/schema/build/policy documentation obligations. Memo endpoint isolation is fixed offline; live provider behavior remains untested. | Imported F66; associated audit obligations |

## Fixed in code, but follow-through remains

- Collection worker counts now reject zero/negative values and timing settings reject non-finite or invalid budgets, including later assignment. Direct discovery/link-check guards prevent zero-worker hangs. Broader limit/deadline alignment remains open.

- The memo alias now requires its own URL, model and key; unrelated custom defaults/credentials are not inherited. F66 configuration is fixed and tested offline; no live provider request was made.

- Both state-writing workflows now opt into GitHub's multiple-pending queue. F62's shared serialization is retained without default pending-run replacement; remote scheduling and the platform's 100-run overflow limit remain operational considerations. Documentation now matches the existing six-hour pipeline schedule.

- Pages deployment now requires `ENABLE_PAGES=true` for push, workflow completion and manual triggers alike. F32's configuration fix is local; a remote deployment was not exercised.

- Workday page-cap exhaustion now reports partial discovery, missing totals no longer stop a full first page, invalid/inconsistent totals report partial parsing, and failed search terms preserve others' results. Malformed individual entries and full-first-page recovery are covered by adapter/HTTP regressions. Live pagination coverage remains an F51 obligation.

- Changed board content and metadata now trigger reconsideration. A protected database fact-refresh operation exists, but it is **not connected to pipeline duplicate handling**. Existing facts therefore do not yet automatically refresh through that operation.
- Source verification now runs actual board/feed/portal parsing and reports partial failures. This does **not** verify every configured source or its current eligible vacancy coverage.
- Bot cursor retention, callback replay recovery and durable dashboard/feed retries are implemented and tested. Unknown delivery outcomes, partial command pages and replay-history limits remain.
- Historical outputs still need controlled reconciliation for changed category policy, locations, deadlines, deduplication, salaries, invisible-character normalization, visa claims and generated summaries. Relevant findings include F03/F04/F09/F21/F22/F34/F36/F49 and imported F58/F59/F63.
- Independent delivery-destination retries and uncertain X single-post outcomes remain associated obligations of the publishing fixes. Spreadsheet round-trip and broader browser/operational checks also remain where recorded in the ledger.

## Source expansion from the original request

**19 additional official pages have been researched; none has been activated.** CREST, Nuffield and LBS have deeper validation reports. Remaining work is adapter implementation/fixtures, identity reconciliation, real transport/parser validation and local activation of suitable monitors. Current local configuration is 74 boards (68 enabled, six disabled), plus two feeds and one portal; these are configuration counts, not independently healthy pages or employers.

## Verification limits

The most recent full suite reported **916 tests and 15 subtests passed in 59.10 seconds**, including the known-advert collector change. The test output reached 100% with the final success summary before the turn was interrupted; its process handle is now absent. The proposed separate refreshed/new source counters were not implemented before interruption and remain outstanding. Latest completed lint and whitespace checks passed. Those results do not prove the unfinished requirements above. No remote publication or deployment occurred.

The detailed evidence and outstanding obligations remain in [remediation-ledger.md](remediation-ledger.md). Source candidates are in [source-expansion.md](source-expansion.md).
