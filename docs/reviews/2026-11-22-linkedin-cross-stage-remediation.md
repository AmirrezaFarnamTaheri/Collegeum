# LinkedIn cross-stage remediation and immutable-record reconciliation
Evidence date: 2026-11-22 (UTC); read-only baseline run [44994015596](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/44994015596) at 06:39 UTC.

## Verified baseline (no fresh provider requests made for this review)

- The retained health-history job logs contain 134 direct LinkedIn `/jobs/view/<id>` HTTP-999 responses over 29 distinct runs, while some `board:linkedin` entries report discovery skipped. These calls occurred via generic published-link rechecking, outside the LinkedIn search adapter.
- Economics checkpoint: 313 query identities (39 marked complete; 274 incomplete) of 675 configured pairs; four cached replay cards. Life Sciences: 93 queries (15 complete; 78 incomplete) and 124 replay cards. Recent replay does not mean recent LinkedIn discovery.
- The committed public snapshot contains 216 records, 73 LinkedIn-origin records, 70 linking back to LinkedIn and 53 without a structured deadline. This is not proof applications remain open.
- Historical decisions and public listing lifecycles can disagree. A later `rejected` latest seen decision is not itself proof that an earlier published posting has been withdrawn.

## Implemented in PR #216

1. Generic `check_links()` suppresses requests to any HTTP(S) LinkedIn-owned hostname (including mobile, legacy URLs, and nonnumeric advert slugs) and records them as provider-deferred. Only the LinkedIn-specific adapter may handle access-restricted discovery and eligible details under shared cooldown. Unverified provider-deferred candidates remain pending rather than proceeding to a new Telegram send.
2. Published provider-deferred LinkedIn URLs are excluded from the bounded generic recheck selection, preventing stale blocked records from starving employer-page checks without rewriting `last_checked_at`. An unreadable/empty detail is never tagged as successfully reached. `last_checked_at` remains the bounded scheduling-attempt timestamp for non-deferred requests; new nullable `last_verified_at` records only a successful, non-closed detail fetch. This is *reachability evidence, not independent proof applications are open*. The field is migrated and merged conservatively without inventing historical success.
3. Python private career matching now excludes passed explicit deadlines, after applying previously authorized Bern false-deadline overlays. Date-only deadlines remain valid until the end of the UTC date. Historical career rows and subscriber receipts are not changed.
4. Dashboard cards and detail modals explicitly identify LinkedIn-origin records as availability-unverified.
5. The read-only `tools.audit_source_quality` report now exposes LinkedIn public/journal decision disagreements, mirror review groups, checkpoint coverage and stale observations as review queues. No automatic deletion or private delivery occurs.

## Requisition-level review — cannot safely auto-merge

- UiT #222, #233, #235, #291, #327, #371: overlapping LinkedIn titles and RiverPulse project summaries. The institution's [Jobbnorge advert 309415](https://www.jobbnorge.no/en/available-jobs/joblisting/pdf/309415) describes four complementary postdoctoral roles and deadline 15 Nov 2026; it is **not sufficient** to prove six LinkedIn IDs represent one requisition. Map each to a genuine employer ATS ID before hiding or merging anything.
- King's College London #264 and #426: similar evaluation titles with materially overlapping responsibilities, but no independently established canonical requisition. Keep distinct pending employer evidence.
- Rejected-seen but currently public #246, #347, #378, #395, #408, #429: preserve listing IDs, immutable publication and Telegram receipts; investigate each source decision and its effective timestamp before any operator-approved status change.

## Verification and rollout

- Offline MockTransport regression: zero generic LinkedIn HTTP requests, normal official employer links still tested, null response never verifies success.
- Durable SQL journal export/import conserves new reachability timestamps and old delivery receipts.
- Existing Bern false-deadline overlay remains effective; passed true deadlines cannot be privately matched.
- Run `python -m tools.audit_source_quality --strict` in the repo's locked test environment. Inspect the new `linkedin` section separately from source-adapter search diagnostics.
- After an approved merge, verify the *next scheduled production run* shows zero generic direct LinkedIn job-page HTTP 999s and exposes `published_recheck_summary`/`pre_send_link_checks` deferred counts. CI alone cannot establish provider recovery.

Do not backfill claimed successful rechecks, mass-close old postings, delete duplicate candidates, modify Telegram delivery receipts, or circumvent provider access restrictions.
