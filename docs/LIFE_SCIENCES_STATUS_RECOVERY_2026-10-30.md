# Life Sciences — 30 October 2026 audit and recovery plan

## Recorded output is not an active-vacancy register

The **225-source** catalogue includes **36 enabled** source definitions and **189 disabled candidates**. Enabled is not equivalent to passing live vacancy extraction. Committed `data/career_jobs.ndjson` holds **62 Life Sciences PhD rows**, including one more VIB PhD than the 29 October snapshot; all 62 are marked `availability=unknown` and `funding_status=unverified`. One historic economics/climate PhD title is excluded from exports without altering journal or Telegram receipts.

Six rows carry `research_priority=focus`; 56 have `related`. A lexical pass of titles finds 11 neuroscience, 7 molecular biology, 6 immunology, 5 bioinformatics, 4 RNA, 4 cell, 3 genetics, 1 epigenetics, and 1 chromatin matches. These overlap and do not substitute for full-text qualification. The archive may include expired or off-field records: all URLs, PhD entry requirements, biological focus, current application state, exact workplace and funding must be checked on employer-controlled pages before reporting **verified-open** results.

The exporter is intentionally read-only. Do **not** delete historical rows, fabricate funding statuses, confuse EURAXESS repeated search hits with unique positions, or change private delivery receipts. Country must be established from a specific posting, not guessed from a portal.

## Known recovery results and blockers

- **Linköping University** and **SLU** have already been repaired on main through PR #68: official public ReachMee recruitment pages produced 9 + 6 unique doctoral-title candidates in bounded live verification. Those are *not* 15 verified eligible biology PhDs.
- **University of Bern** remains enabled but incomplete. Its Prospective site returns a JavaScript bootstrap with zero visible vacancy links on the raw HTML; a 200 response is not a successful collector.
- **AcademicTransfer epigenomics** had 0 links on the first query but 1 on the third; the corrected multi-search probe caught this. **EURAXESS** repeated the same 10 URLs over four query shards; the number of requests is not a unique-vacancy count.
- **IBEC Barcelona** previously had a transient transport error, later reproduced 11 recognizable links; each needs a doctoral, biological-field, date and location check.
- **University of Copenhagen** is disabled after a robots-denied request. Do not retry through an alternate host to evade that policy.
- The 189 disabled specialist institutes, doctoral programmes and wider European universities are not approved functional feeds. Real employer vacancy identities, parser behavior and permitted access are required before promotion.

## Implemented in this branch

1. A separate bounded `data/life_sciences_health.json` outcome journal, independent of the economics dashboard, career-market health and private Telegram data.
2. Source-specific `last_checked_at`, `last_success_at`, discovered URLs, doctoral candidates, eligible matches, discovery faults and detail fetch faults. Unselected sources retain *historical* observations rather than being incorrectly refreshed.
3. `unverified_empty` when no vacancy was parsed; `verified_empty` only with an explicit configured empty marker. `partial` for fetch/detail faults, `failed` for scraper exceptions.
4. Cohort-style PhD calls without a current closing date are withheld; an explicit qualification requirement that applicants *already possess a completed PhD* is rejected. Unknown funding stays unknown.

The existing 12-sources-per-run, source interleaving, job identities, atomic career journal, and private subscription state are unchanged.

## Acceptance and next institutions

Run full Python 3.11/3.12 test, lint and type-check gates; inspect Life Sciences export workflow artifacts and fresh health output after merge. Use a read-only GitHub runner to inspect **Bern, EMBL, ETH D-BSSE, DKFZ, Vienna BioCenter, Helsinki, ISTA** for official individual vacancies. Keep programme-only and JS-only responses disabled or clearly failing; only promote when real job URLs and degree/field/deadline checks pass.

The separate **economics** 100-source roadmap in #56 remains: ESRI Ireland, LISER Luxembourg, IAB Germany; IFAU Sweden, VATT, Bank of Finland; HKUST/SMU; ANU/Sydney/Melbourne/Queensland; UNU-WIDER/SEO/CEPR; and Princeton RPDE/UCL/Brookings/IFS recovery. Do not add economic RA feeds into the Life Sciences PhD registry or miscount them as biology sources.
