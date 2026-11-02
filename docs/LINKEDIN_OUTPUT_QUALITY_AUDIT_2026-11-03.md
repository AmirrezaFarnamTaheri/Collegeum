# LinkedIn output quality and recovery audit — 3 November 2026

**Status:** Evidence-backed data-quality assessment; not an authorization to contact a policy-blocked provider, modify historic identities, or infer that cached jobs remain open.

**Snapshot:** Committed Collegeum state at **2026-11-02 18:25 UTC** (latest publication export available for this assessment). Evaluation date: 2026-11-03. All timestamps are UTC. Query-level coverage and content acceptance must not be conflated with the count of published vacancies.

## 1. Source lineage and grain

| Artifact | Unit of observation | What it proves / does not prove |
|---|---|---|
| `data/linkedin_econ_search_state.json` | query + location checkpoint; per-job-ID replay candidate | Attempted/unfinished guest job-search paging; **not** coverage completion or application availability |
| `data/linkedin_life_search_state.json` | separate Life Sciences query checkpoint and candidate spool | Cached card titles and source activity; **not** funded/available PhD positions |
| `data/seen.ndjson` | discovery decision / canonical URL hash | Accepted, rejected, or duplicate decision; **not** one published job per decision |
| `data/listings.ndjson` | durable academic listing ID | Historic publication, saved first-seen/deadline/title/source/apply URL |
| `docs/data/listings.json` | current user-visible academic listing | Public browsing eligibility *at export time*; not confirmation that an employer is still accepting applications |
| `docs/data/health.json` | pipeline run and source health | Source attempt/skip/failure, run application outcome |
| `data/life_sources_health.json` | last observed specialist-source check | Life Sciences discovery and result qualification; a replay timestamp is not a new provider fetch |

Analysis reconciles source, application, and public records by original LinkedIn `/jobs/view/{id}`, durable `url_hash`, source label, public listing ID, and source-health event. Near-duplicate groups are **review candidates only**, not identity merges.

## 2. Quantified inventory and integrity

| Measurement | Observed | Interpretation / impact |
|---|---:|---|
| All durable academic listing records | 338 | Across all sources |
| Historically published academic listings | 332 | Historical status can include expired/closed |
| Current public academic export | 181 | Not equal to 332 historic publications |
| LinkedIn-origin historic published listings | **49** | All 49 have distinct LinkedIn job IDs |
| LinkedIn-origin current public listings | **31 / 181** | 17.1% of the public snapshot |
| LinkedIn historic listings with no structured deadline | **32 / 49** | 65.3%; must never imply open status |
| LinkedIn current public listings with no structured deadline | **23 / 31** | 74.2%; rolling deadlines possible, status unverified |
| LinkedIn current public rows with LinkedIn as the application URL | **27 / 31** | 87.1%; no verified employer-specific apply deep link in that field |
| LinkedIn historic rows with direct non-LinkedIn applications | **8 / 49** | Four are candidate direct links; four are generic landing pages |
| LinkedIn discovery decisions | **167** | 41 accepted, 119 rejected, 7 marked duplicate |
| Accepted LinkedIn decisions missing a listing reference | **4 / 41** | 9.8% of LinkedIn accepted decisions; traceability gap, not proof of four missing live vacancies |
| Accepted LinkedIn decisions with a valid referenced journal hash | **37 / 41** | All 37 references resolve; no dangling non-null references in this subset |

**Decision ledger warning:** Discovery-decision counts, source-listing counts, and the public export are *different grains*. Do not subtract 41 accepted from 49 published to infer undispatched records. Four accepted decisions dated October 3–4 lack `listing_url_hash`; their canonical hashes should be reconciled only with verifiable provenance.

## 3. Production search completeness and freshness — HIGH

- Economics/predoc source configured search portfolio reports **675 keyword × location pairs**. Its persisted ledger contains **14 pending queries**, **zero fully completed queries**, 13 offsets at page 10 and one at page 0 (the access-limited query).
- The economics ledger recorded `access_blocked_until=2026-11-03T05:50:37.969631Z` from the previous provider restriction. This timestamp is a *previously recorded boundary*, **not** permission to force traffic once it passes. Do not bypass access controls, robots requirements, rate limits or auth walls.
- The Life Sciences ledger has **20 pending searches**, **zero fully completed queries**, 18 at offset 10 and two at 20. There are **87 distinct buffered job cards**. Its own `access_blocked_until` is null, but the scraper explicitly honors a shared cross-audience provider block.
- In the latest pipeline run [#41498257599](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41498257599), `board:linkedin.status=skipped`, `requests=0`, `plan_size=0` and `provider_cooldown_active=true`; this is correct truthful classification, **not** source success.
- The specialist `life_linkedin` source was **skipped** in the latest selected Life Sciences check. It recorded **zero new matching doctoral candidates** despite retaining 87 historical cards; `last_success_at` predates the run.
- Historical examples: [pipeline #41251862847](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41251862847) reported 220 raw LinkedIn cards, 24 relevant, five new, without errors. [Pipeline #41278362736](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41278362736) reported 119 raw, 16 relevant, ten new before an actual fetch/access failure. Subsequent cooldown skips contribute no new completed query coverage.

**Impact:** A green GitHub Actions workflow and nonzero historic LinkedIn counts cannot demonstrate a fresh, complete, timely feed. Query scheduling and source accessibility remain separate from publication/notification health.

## 4. Identity and duplicate-risk triage — HIGH

### UiT climate-governance cluster: five probable mirrored adverts

Five **currently public** academic records share a normalized employer and the same title, *Postdoctoral Research Fellow in Climate and Environmental Governance*, with five distinct LinkedIn job IDs:

| Collegeum ID | LinkedIn job ID |
|---:|---:|
| 222 | 4477002506 |
| 233 | 4477783880 |
| 235 | 4478230740 |
| 291 | 4481871120 |
| 327 | 4483945899 |

This is **one suspect entity cluster, not five confirmed independent requisitions**. The original jobs must retain their immutable URLs, hashes, marks and Telegram delivery receipts. An **official Jobbnorge vacancy-feed entry** now identifies the governance-specific role as **Jobbnorge requisition 309437**, titled `Postdoktor i klima- og miljøstyring`, closing **15 November 2026**: [official recruitment URL](https://www.jobbnorge.no/ledige-stillinger/stilling/309437/postdoktor-i-klima-og-miljoestyring). A [Norwegian public employment board](https://arbeidsplassen.nav.no/stillinger/stilling/b96205c3-348a-4cf2-9726-0f93fde289cc) independently describes the same UiT RiverPulse governance responsibilities. This is strong **one-official-position** evidence for the five similarly titled, near-identical LinkedIn posts; it is *not* yet an explicit origin-ID→Jobbnorge-ID mapping for each of the five LinkedIn job IDs. Obtain or document that last crosswalk before preserving one canonical public listing and suppressing mirrored browse rows; do not delete history or delivery receipts. A title-only dedupe could collapse genuinely separate appointments, whereas doing nothing may inflate browsing and notifications by up to four mirrored records.

### King's College London group: same displayed title, distinct requisitions

LinkedIn-origin Collegeum IDs **247** and **248** share the displayed label `Research Associate (Evaluation Manager)` but previously established official recruiting evidence identifies **requisitions 160868 and 160625**, with different contract terms and closing dates. Official [King's job 160868](https://www.kcl.ac.uk/jobs/160868-research-associate-evaluation) shows a November 9, 2026 closing date and indefinite contract; the [second requisition 160625](https://www.jobs.ac.uk/job/DTG863/research-associate-evaluation-manager) was a two-year fixed-term advert that closed October 28. **Do not merge them**. Audit the recorded null deadlines and title granularity with official source evidence. Historical ID 248 should not be treated as an open rolling post without verification.

The two clusters are different: the first needs original requisition verification; the second needs field/availability correction without deduplication.

## 5. Application-link specificity — HIGH

All 31 current LinkedIn-origin public records use HTTPS, but HTTPS **alone** does not establish an actionable application. Of 49 historic LinkedIn-origin publications, 41 retain LinkedIn as the apply link. Among the eight **historical** non-LinkedIn application URLs, four point to broad, potentially non-actionable pages. **Only ID 333 of these four remains in the current public export**; IDs 52, 315 and 316 are absent from the latest public export:

| Collegeum ID | Stored application destination | Risk |
|---:|---|---|
| 52 | `https://www.jobs.lse.ac.uk/` | LSE vacancy-search homepage, not posting-specific |
| 315 | `https://www.lse.ac.uk/LSEJobs` | LSE jobs index, not posting-specific |
| 316 | `https://www.fnuniv.ca/` | Institution homepage, not posting-specific |
| 333 | `https://rb.wd5.myworkdayjobs.com/FRS` | Workday career landing/index, not a requisition deep link |

For ID 333, independent employer search finds a plausible [Federal Reserve Bank of Dallas Research Analyst posting, requisition R-0000032835](https://rb.wd5.myworkdayjobs.com/FRS/job/Dallas-TX/Research-Analyst_R-0000032835-1). Confirm it is the *same LinkedIn requisition and still actionable* before altering the saved journal or public projection.

The other four non-LinkedIn URLs are more specific, but merely having a detailed path does not prove current availability. Prioritize official employer deep links when verifiable; retain LinkedIn source identity and avoid substituting a generic or unrelated application page.

## 6. Life Sciences replay buffer — MEDIUM/HIGH

Of **87 distinct cached LinkedIn cards**, a conservative title-only triage found:
- **24** with an explicit doctoral/PhD-style title prefix.
- **25** with signals of a different job level/type (e.g. principal scientist, director, postdoctoral researcher, senior scientist, managerial role).
- **38** neither group under these simple title heuristics; require vacancy description and employer verification before categorizing.

These are **triage buckets, not validated eligibility labels**. A title such as `Doctorant - Candidatures spontanées` may be a generic unsolicited application rather than a funded opening; even an explicitly titled PhD posting may have expired. Senior and postdoctoral cards are not equivalent to entry doctoral funding opportunities. No buffered item should be promoted into a funded/active Life Sciences subscription merely because it matched a search keyword. `last_replayed_at` is not proof of fresh posting or official employer availability.

## 7. Field suitability and false-positive review — MEDIUM

Two **historical** LinkedIn publications are already **absent from the current public export**: **ID 326** (`Prospect Research Officer`, Western University) and **ID 234** (`Research Assistant`, College of Immigration and Citizenship Consultants). Employer [Western Advancement's prospect-management team](https://advancement.uwo.ca/our_teams/prospect-research.html) and the original [ID 326 job description](https://ca.linkedin.com/jobs/view/prospect-research-officer-at-western-university-4484472525) show fundraising/prospect intelligence, not academic economic research; this confirms the field mismatch but **does not establish current dashboard contamination**. Other [ID 234 job-description evidence](https://remotive.com/remote/jobs/research/research-assistant-6019982) concerns research support for an immigration-consultant regulator rather than economics predoctoral training, although a role-based relevance review remains appropriate. Preserve both historical records and receipts and verify existing routing; do not erase by title alone.

Additional visible records with no deadline, especially UiT IDs 222/233/235/291/327 and King's IDs 247/248, should be labeled **deadline not recorded**, not silently interpreted as open.

## 8. Required remediation and measurable acceptance

1. **Provider access (critical):** honor existing LinkedIn cooldown and any subsequent 403/429/robots denial. Observe a *permitted* future source-bearing run; require nonzero actual search requests, checkpoint-safe pagination, and actual per-query completion (without raising traffic ceilings). Report successful *completed queries* separately from cards scanned, candidates replayed, records accepted, and newly published jobs. Do not report zero requests as an empty successful search.
2. **Identity (high):** verify the five UiT links against now-identified official Jobbnorge requisition **309437** (governance position, deadline **2026-11-15**) and document the per-LinkedIn-job-ID crosswalk before canonicalizing visible rows. Only a confirmed matching official ID justifies a reviewed alias/duplicate resolution; preserve journal identities and delivery receipts.
3. **Links (high):** manually verify and replace the four generic application URLs with position-specific official links if and only if employer IDs match. If they cannot be verified, label links `unverified` and avoid claiming the records are directly actionable.
4. **Freshness and deadlines (high):** record verified deadline/closed state for official King's requisitions. Display the 23/31 missing deadline rate for LinkedIn-origin public records as *unknown*, not rolling/open.
5. **Life Sciences quality (high):** replay-buffer counts must remain separate from qualified funded/active PhD inventory. Add a low-cost title/degree triage **for review only**, with conservative heuristics and tests; never silently discard plausible foreign-language doctoral cards.
6. **Decision lineage (medium):** reconcile the four unlinked accepted LinkedIn decisions through exact hashes and original decision history; do not backfill guessed matches.
7. **Sustained monitoring (high):** as independent diagnostics, check current source-health `skipped/failed/partial/successful`, fully completed queries, pending offsets, candidate spools, record-level source URLs, application specificity, and publication visibility. The monitoring baseline above is a historical snapshot, not an automatic failure threshold for volatile vacancy counts.

### Acceptance checklist

- [ ] LinkedIn access is compliant; there is no account/proxy/anti-bot workaround.
- [ ] At least one future source-bearing run confirms completed search-query coverage without losing checkpoints.
- [ ] Public LinkedIn listings are separated from archived decisions and cached, not-yet-qualified cards.
- [ ] UiT official requisition identity is verified; no accidental historical deletion or replay.
- [ ] Four generic application pages resolved or explicitly labeled unverified.
- [ ] King's official deadlines/contracts recorded without collapsing distinct vacancies.
- [ ] Accepted decision references reconciled only with immutable historical evidence.
- [ ] The Telegram /sync projection repair passes CI and a real HTTP 200 sync; this is a separate end-to-end defect.

## Limitations and confidence

**High confidence:** committed counts, exact IDs, hashes, links, source health, query offsets, journal integrity and processing timestamps from the listed artifacts. **Medium confidence:** probable duplicate group and whether a generic deep link is actionable, pending official employer confirmation. **Low confidence:** current acceptance/funding state of historical LinkedIn posts, not verified via employer postings at this snapshot.

No live LinkedIn collection, access-control bypass, provider identity rewrite, outbound Telegram send or production data migration was performed for this audit. This assessment should be revisited only with new lawful provider and employer evidence.
