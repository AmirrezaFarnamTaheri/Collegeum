# Research advert continuation — 284 checked identities

Review date: 25 November 2026 (prior dated capture and 24 November UTC repository snapshot). Baseline `e549c1cb0d8546d17f2bdca13870dbebcd0c49ee`. This is an auditable desk-research and proposed data-reconciliation patch, not a claim of 284 active jobs or collector verification.

## Scope and results

- 251 original identities + 16 previously documented additional identities (all 267 distinct) + 17 additional assessments = **284** distinct research advert identities. 15 new assessments come from the existing publication journal; two are previously absent official employer leads. Prior failed/access-restricted observations remain explicit and count only as review attempts. The 253-admissions programme catalogue is excluded.
- **154** identities have matching substantive body evidence across the historical and independent evidence layers, versus 134 in the original cohort. 130 lack such evidence. The original collector eligibility results are preserved; an independently readable advert is not a newly accepted collector record.
- 216 baseline public records and 500 journal records were checked for exact joins and field/lifecycle metadata; 106 public rows have exact journal-ID or URL evidence linkage to this expanded review (including a provisional EPFL representative), 110 remain outside it. 138 public rows lack journal verification timestamps; 126 lack finite deadlines. All 216 public IDs join to the journal. These are metadata gaps, not a guarantee of closed/fake vacancies.
- 68 LinkedIn-source public rows lack journal verification timestamps. Use job-specific employer pages where permitted; a blocked page is not proof of invalidity. Do not fabricate source checks or timestamps.

## Proposed lifecycle correction (two rows)

| Journal ID | Primary evidence | Decision |
|---|---|---|
| 294 | [Carlo Alberto detail](https://www.carloalberto.org/about/jobs-fellowships/post-doctoral-position-mind-the-nexus-project/) specifies a 20 September 2026 cutoff and November start. [Employer index](https://www.carloalberto.org/about/jobs-fellowships/) still labels it open. Earlier matching body capture on 24 November records the elapsed deadline. | Suppress expired application in active projection using recorded closure observation; preserve index conflict, journal identity and delivery history. Reopen only with a revised authoritative cutoff. |
| 318 | [EconJobMarket requisition 12920](https://econjobmarket.org/positions/12920) states 23 November 2026 application cutoff, no further applications, review underway. Earlier matching capture confirms closure. | Record closure observation and remove active projection; preserve journal status published as historical and delivery receipts. |

The proposed change sets `closed_at` to the original dated matching source capture (observation timestamp, not the precise time the employer closed applications), adds reason/date notes, removes only IDs 294/318 from the active JSON, updates health closed count and the listings content hash. Date-only/ambiguous cutoff times are retained as source notes, not invented UTC deadlines. RSS's 100 items did not include either vacancy; no RSS or delivery mutations. No generated timestamp or prior run outcome is rewritten. Reconciliation applies to the pinned snapshot; a concurrent collector refresh requires a new comparison, not blindly replaying the entire old journal.

## Evidence and source corrections

The 17 extra assessments and five Yale recoveries are in [independent evidence](research-advert-independent-evidence.json). Ten of the journal additions and both newly discovered employer adverts have substantive matching primary descriptions; five journal additions are index-only, secondary-only or inaccessible. The five Yale official pages are readable via desk research, but their original bounded-reader failures remain unchanged until collector replay succeeds. Three have January 31, 2027 cutoffs and two explicitly rolling.

EPFL employer requisition 2590 is a single distinct source role. Journal IDs 423, 424, 462 are a suspected mirror cluster. Only one provisional representative is included in this review; precise binding to individual LinkedIn records is not proven. No production alias suppression is imposed. Warwick ID 450 is not counted because the matching title might be an existing Warwick requisition; the aggregator failed to load. No identity counted by title alone. The previous excluded IDs 31, 223 and 455 retain their original exclusion rationale.

Source policy: corrected misleading comments in config/sources.toml to match the existing effective configuration (J-PAL enabled; excluded_employers empty; IPA access-disabled). The actual eligibility preferences, enabled flags, and access controls are unchanged; employer policy changes remain an owner decision.

Padua and Erasmus are verified first-party source candidates, not enabled adapters. Each has a job-specific source and cutoff, distinct from the PhD programme catalogue. Ghent, KU Leuven, Tilburg, Hertie, Antwerp and already-enabled Bocconi remain source-specific pilot leads; no bulk activation without permitted, job-specific parser and relevance tests.

## Remaining items, explicitly not represented as resolved

- Whole-publication source verification: the [216-row matrix](public-listings-review-216.csv) provides each baseline ID, evidence and per-field gaps, including LinkedIn queue. A metadata join is not an external source check. 110 rows still lack matching review cohort evidence.
- Original missing-body, inaccessible, soft-200, and unassessed historical records: [284-row expanded matrix](research-adverts-284.csv) retains original outcomes and new independent evidence separately. Retry only through permitted sources. Reproduce Yale oversized captures and university timeouts with bounded parser fixtures before changing the collector.
- All 500 journal rows receive a lifecycle/routing disposition in [journal crosswalk](journal-reconciliation-500.csv); unshown published records with no lifecycle marker require publication-routing investigation, not automatic restoration.
- Deadline semantics, visa, salary, location, contract, degree and start fields: preserve unknown vs explicitly rolling vs fixed cutoff. Evidence notes from new sources contain verified field values for follow-up replay. Do not infer visa or salary; no artificial last_verified_at updates. No production schema change in this patch.
- Identity continuity: exact URL/durable journal joins and independent employer requisitions only. Existing proven aliases remain; uncertain same-title clusters are not merged. Test URL canonicalization and alias continuity using source-specific requisition fixtures.
- Source-adapter and audit automation: provider permission, identity, bounded fetch, full body, lifecycle, field gate, duplicate checks and publication replay are required before enablement. Complete full repo test suite and review CI for the proposed patch; the local execution environment could not clone the GitHub repository due to DNS restrictions.

## Verification

In-memory checks on pinned source bytes verified SHA-256 against the original health receipt; unique 284 identities; original 251+16 disjoint; exactly two modified journal rows, all other journal fields and delivery receipts unchanged; exactly 214 remaining active records, every unrelated record byte/semantic-preserved; no affected RSS item; health closed count 55 and matching new public content hash. The source registry's effective non-comment/non-note configuration is unchanged. GitHub CI is separate from these structural checks and must be inspected before merge.

Prior audit: [PR #242](https://github.com/AmirrezaFarnamTaheri/Collegeum/pull/242), head `5bcbb02fc7d3d57868147029ce2de058a183f818`. The review is intentionally independent of that open PR and does not assert it was merged.
