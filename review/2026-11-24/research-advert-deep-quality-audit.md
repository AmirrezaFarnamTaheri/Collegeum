# Third-pass data-quality and source-gap audit: 251 distinct research adverts

**Reviewed 24 November 2026 · Historical evidence, not a live-open-vacancy certification**

This is a broader, source-aware examination of the fixed 251-advert cohort. It cross-references the original advert evidence ledger, the public Economics listings snapshot, the live board registry and both official-source expansion manifests. It adds a conservative external spot-check of named first-party employer pages, without claiming those page checks were completed by Collegeum's production collector.

**Pinned repository evidence:** main commit `7faf8ab263f251f2e5b5fd5351af061034018755`; [251-advert audit](research-adverts-251.json) blob `e20fa237035c6b0e548018242bc69df7dd02711e`; [public listings](../../docs/data/listings.json) blob `7651cfa557b21197cb11ec78a4c5f1440229b156` (generated `2026-11-24T14:54:00Z`); [source registry](../../config/sources.toml) blob `57b54ef6706885d39f192dc2561f4200024dd82e`. New reports are dated analyses; ongoing refreshes may change the public snapshot.

## The central finding: the checked target and the product's visible inventory are different

| Measure | Count | Interpretation |
| --- | ---: | --- |
| Historical review cohort | **251** | Fixed, selected requisition identities with dated assessment outcomes, not all public vacancies |
| Primary matching substantive bodies | **134** (53.4%) | A body was reviewed at the time; may be closed or ineligible |
| No substantive body | **117** (46.6%) | Access, fetch, removed, shell and closed-notice-only outcomes |
| Latest Economics public listings | **211** | Current file snapshot; no inference that each is presently open |
| Public rows mapped into the fixed review | **79** (37.4%) | 78 matched by durable journal ID; 1 additional J-PAL/Zurich mirror by reviewed alias URL |
| Public rows **outside** this review | **132** (62.6%) | No fixed-251 review match; not thereby classified as wrong or unverified by every other pipeline |
| Historical reviewed journals no longer in latest public file | **92 of 170** | Could be legitimately filtered, expired, superseded or unpublished; do not resurrect automatically |
| Current public journal records lacking a full body in this review | **46 of 78** | Verification exposure requiring visibility and provenance reconciliation |

**Why this matters:** A completion metric calculated against a chosen 251-record cohort is not a measure of complete coverage of 211 visible public records, much less of all discoverable research roles. The next comprehensive audit must follow *every public listing ID* as well as discovered employer requisitions, without assuming a fixed target of 251. The [132-row outside-cohort list](public-listings-outside-251.csv) is the immediate missing join inventory.

The additional 16 separately checked journal identities in the original review file were deliberately excluded from its target. They were checked, but they demonstrate that 251 is a chosen denominator, not the whole candidate pool. The previously identified J-PAL/Zurich mirror and likely Utrecht mirror remain exclusions rather than additional unique positions.

## Coverage and eligibility integrity at the source grain

| Cohort | Advert identities | Substantive bodies | Current rules applied |
| --- | ---: | ---: | --- |
| First expansion: ESMT Berlin, Indian School of Business, WU Vienna | 21 | 21 | 17 accepted, 2 rejected, 2 deferred |
| Second expansion: Vienna, Amsterdam, Maastricht and Utrecht universities | 60 | 56 | 10 accepted, 46 rejected, 4 deferred |
| Older journal identity review | 170 | 57 | 169 not assessed, one deferred |
| **Combined** | **251** | **134** | **27 collector-eligible, 48 subject-rejected, 7 deferred, 169 not assessed** |

Of the **81** newly researched institutional adverts, only **27** passed the existing collector's role, field and other gates. **48** were rejected and **6** deferred. This is why a broad university directory cannot be counted as 100% relevant without subject and role analysis. These are *candidates before downstream ingestion, extraction, deduplication and publication*.

The historical 170 are especially exposed: 169 have `eligibility: not_assessed` in this audit. Among those, 56 have full bodies, including 37 classified as readable and 19 classified as closed. The other 113 lack full bodies. A historical publication is **not** a current-open or current-eligible verdict. The existing [176-record follow-up queue](research-advert-evidence-gaps.csv) covers unknown/deferred eligibility; the new [251-row granular matrix](research-advert-deep-gaps-251.csv) extends it to every cohort member, including subject-rejected and already-assessed jobs.

### Response and access state

| Recorded outcome | Count | Risk | Bounded remediation |
| --- | ---: | --- | --- |
| Readable advert | 114 | Not necessarily open or current | Recheck lifecycle and applicant restrictions at employer URL |
| Explicitly closed | 24 | Could remain in historical publication | Verify active visibility; retain closure and identity |
| Access unavailable | 69 | Primary body cannot be corroborated from this reader | Observe provider policies; use permitted alternatives or ask for access |
| Fetch failed | 11 | Retriable timeout or response-size issue may exist | Controlled retry / bounded first-party parser; keep failures explicit |
| Removed endpoint | 14 | Original requisition URL returned HTTP 404/410 | Archive, or bind an official successor with a *new* identity |
| Unverified HTTP 200 page | 19 | Soft missing page, redirect to index or JS shell | Require primary requisition, title and substantive body |

The largest unavailable clusters are `predoc_org` **26**, `uchicago_bfi` **13**, `wharton_predoc` **7**, and `jpal_global` **7**. Together these account for **53/69** access-unavailable records. Provider restrictions are neither a technical defect to bypass nor proof that a vacancy has closed.

Among the 11 fetch failures, five Yale Economic Growth Center pages returned `response_too_large` under the historical bounded reader, and four new-university detail pages timed out. Those two failure types need separate repair strategies. The 19 unverified 200 responses similarly need source-specific scrutiny rather than an optimistic "HTTP 200 = valid advert" rule.

## Published-field coverage (the **78 journal-ID matched** records only)

These are measured from `docs/data/listings.json`, not guessed from vacancy text. Missing is `null` / absent / blank; `visa=unknown` is also counted as unresolved. The historical public file has richer fields than the archival 251 audit.

| Field | Unavailable in 78 | Coverage gap |
| --- | ---: | ---: |
| Application deadline | 41 | 52.6% |
| Salary minimum **and** maximum | 54 | 69.2% |
| City | 22 | 28.2% |
| Contract duration | 41 | 52.6% |
| Start date | 64 | 82.1% |
| Visa status (unknown or missing) | 73 | 93.6% |
| Named principal investigator | 32 | 41.0% |

These are **stored-data completeness gaps**, not proof that an employer has published this information or that a deadline must exist. A rolling advert should have an explicit `rolling` lifecycle value, not an invented date. An employer not specifying visa sponsorship must retain `unknown`. Do not interpret `is_remote = false` as independently verified on-site requirements without evidence.

The first official-source expansion recorded **11 eligible candidates without a finite deadline**; its deadlines were present for WU's six roles but not most ESMT/ISB roles. This could be legitimate rolling or not stated. The second expansion captured 56 full-year dates among 60 adverts, of which one had already elapsed at review; the four remaining had failed captures. Neither set was yet a published listing count.

The original review does **not** directly store a normalized employer-approved application link, open/closed/rolling lifecycle, canonical deadline type, salary, country/city, work mode, visa restrictions, degree prerequisites, start date, contract hours, citizenship eligibility or required documents per advert. Those properties may be present elsewhere in collector manifests or public listings. A consistent source-backed, provenance-per-field join is the missing data contract.

## Identifiers, duplicates and archived capture reproducibility

- **105** review identities are URL-derived fingerprints (`url:...`), rather than a visible employer requisition ID. This does not make them duplicates, but URL reformatting, redirects and mirrors need stable identity repair. Compare requisition IDs, final URLs, employer JobPosting identifiers and original journal IDs; retain aliases.
- **15 groups comprising 50 records** share the same normalized institution and title. Those are **not declared duplicates**: e.g. WU Vienna and University of Vienna can have multiple legitimately separate research vacancies under generic titles. Their employer requisition numbers must be inspected before merging identities. Query-bearing application URLs (ReachMee, ADP, ESMT and others) must not be deduplicated by stripping all query parameters.
- Vienna's 15 confirmed German-language mirrors are already aliases, not new positions. The J-PAL/University of Zurich mirror and the likely Utrecht/AcademicTransfer overlap are recorded conservatively.
- **160** 200-status observations carry recorded byte lengths and SHA-256 hashes. That is *capture metadata*; it is **not** an independently repeatable full-body check merely because a hash string exists. The ordinary metadata-only audit does not reload raw HTML. A stronger reproducibility procedure should validate original raw captures in controlled storage, or store limited redacted, licence-compliant structured evidence with primary identity, timestamp and content hash.
- Historical collector `source=linkedin` appears on five records, but their review URLs resolve to employer/secondary first-party content; do not assume their LinkedIn discovery IDs can be reconstructed from those URLs without an explicit identity mapping.

## Policy drift requiring an explicit owner decision

The top comments in `config/sources.toml` and a note on `poverty_action` say **J-PAL is excluded via `config/preferences.toml`**. In the current codebase, however, `excluded_employers = []`, `jpal_global` is enabled, and a J-PAL item (public ID 31) exists in the published snapshot. That is a verifiable **configuration/documentation mismatch**, not grounds to silently remove positions or overwrite user preferences. Confirm the intended employer policy, update documentation to match the decision, and enforce it consistently for collection, older listings and publication.

## Five official Yale pages: externally readable, but not yet collector-verified

The previously recorded Yale EGC fetch failures are recoverable leads. An independent read of the actual employer pages (separate from the 251 official-reader captures) established the following **candidate** information on 24 November 2026:

| Official vacancy | Employer page indicates | Next validation |
| --- | --- | --- |
| [Economic History postdoc](https://egc.yale.edu/opportunities/postdoctoral-associate-economic-history-program-1) | Application deadline **31 January 2027** | Bounded primary-body extraction and requisition matching |
| [Macro-Development postdoc](https://egc.yale.edu/opportunities/postdoctoral-associate-macro-development) | Application deadline **31 January 2027** | Same; keep year and intake context |
| [Kuznets Markets and Development postdoc](https://egc.yale.edu/opportunities/postdoctoral-associate-kuznets-markets-and-development) | Application deadline **31 January 2027** | Same |
| [Development Economics Research Fellow](https://egc.yale.edu/opportunities/development-economics-research-fellow-2) | **Rolling** applications | Preserve rolling status; no made-up cutoff |
| [Development and Experimental Economics Research Fellow](https://egc.yale.edu/opportunities/development-and-experimental-economics-research-fellow-1) | **Rolling** applications | Same; follow official employer application route |

These records **remain `fetch_failed` in the historical ledger**. A web reader being able to display a page does not validate the production collector's safety, HTML size, identity or downstream publication gates. The next engineering iteration should start with a failing source-specific replay test, then implement bounded extraction and confirm all five job identities.

## Broader official-source candidates that the fixed 251 misses

The board registry has **151 boards; 82 are enabled and 69 disabled**. The 251-review sample includes **51** registered sources, of which 49 are currently enabled and two disabled. Hence **33 of 82 enabled boards have no record in this chosen cohort**. That is a *sampling gap*, not evidence those 33 boards are malfunctioning.

The following are independently inspected **source-adapter leads**, not new enabled sources, not added to the 251, and not yet counted as eligible ingestion:

| Institution/source | Official evidence | Distinct missing piece / safe gate |
| --- | --- | --- |
| **University of Padua, Economics and Management** | [Economics postdoc advert](https://www.economia.unipd.it/en/en/en/postdoctoral-researcher-economics): deadline **30 Nov 2026**; [central research positions](https://www.unipd.it/en/opportunita-ricerca-posizioni-aperte) | First-party department advert plus EconJobMarket application: bind identity and mirror, then apply economics/postdoc + lifecycle gates. No Padua board entry |
| **Erasmus University Rotterdam** | [Academic vacancies](https://www.eur.nl/en/working-at-eur/working-areas/academic-staff); [quantitative empirical legal studies postdoc](https://www.eur.nl/en/working-at-eur/vacancies/postdoctoral-researcher-quantitative-empirical-legal-studies): deadline **31 Jan 2027**, Economics among qualifying PhDs | Accessible job-specific official pages with published date, deadline, duties, salary and degree. Law-hosted work needs field-specific review; avoid general staff or professor false positives. No Erasmus board entry |
| **Ghent University** | [Faculty-specific scientific jobs](https://www.ugent.be/en/work/scientific); [Business Economics doctoral fellow](https://www.ugent.be/en/work/scientific/doctoral-fellow-77/) | Clear faculty/department, application cutoff and skills. Example above **closed on 22 March 2026**; index contains mostly off-field roles. Add only after matching current roles, not historic ones. No Ghent board entry |
| **KU Leuven** | [Employer job portal](https://www.kuleuven.be/personeel/jobsite/jobs/60784116?lang=en) | Employer requisition links exist, but economics subject, advertised date and application status require live detail proof. Distinct from the separately added KU Leuven PhD *programme* lead |
| **Tilburg University** | [Academic vacancies](https://www.tilburguniversity.edu/about/working/vacancies) | Official site links toward AcademicTransfer. Require employer requisition identity to avoid mirrors; distinguish programme admissions from individual jobs |
| **Hertie School** | [Research and administration jobs](https://www.hertie-school.org/en/jobs) | Research-assistant and postdoc categories exist; generic visiting-scholar dates are **not job deadlines**. Prove a specific currently eligible role before enabling |
| **University of Antwerp** | [English academic vacancies](https://www.uantwerpen.be/en/jobs/vacancies/academic-staff/) | Official index is structured but currently surfaces many off-field roles. Require economics/public-policy duties and job-specific requisition link before accepting |
| **Bocconi IGIER** | [IGIER research vacancies](https://igier.unibocconi.eu/learn-and-work/vacancies) | **Already enabled** as `bocconi_igier` but absent from this 251 review. Its displayed labour-economics postdoc has a **24 Nov 2025** deadline; test lifecycle expiry and whether new opportunities are found, rather than adding a duplicate source |

These verified official sources reveal missing coverage or untested routes, **not** a precise count of jobs Collegeum should publish. Other staged boards—including IAB, LISER, ESRI, HKU, HKUST, SMU and additional Workday hosts—already exist disabled for explicit parser, access or eligibility reasons. Preserve those gates; no robots/authwall bypass, blind bulk enabling or unchecked direct writes to the public listings.

## Actionable remediation order, with every record assigned one primary priority

The downloadable [251-record matrix](research-advert-deep-gaps-251.csv) is sorted by priority and retains all existing immutable advert IDs, source URLs, evidence statuses, public-listing links, field gaps and next actions. Priority is a **triage indicator**, not a completed verification verdict.

| Priority | Records | Meaning |
| --- | ---: | --- |
| **P0** | **2** | Closed adverts still represented by a public JSON row: verify actual applicant visibility, then archive or retain according to current evidence |
| **P1** | **107** | Public row lacks a reviewed body; or current capture failed/shell; or readable historic body lacks eligibility assessment; or candidate deferred |
| **P2** | **59** | Access-policy constraints and accepted candidates requiring standard periodic source review |
| **P3** | **83** | Other known closed/removed records, off-field exclusions or lower-priority archival checks |
| **Total** | **251** | Exactly one primary priority per row; flags may overlap |

Recommended execution sequence:

1. **Publication trust:** audit the **132 public records outside this fixed sample** and the **46 matched public records without full body evidence**. Do not remove published items solely because this one historical audit did not fetch them. Reconcile actual current feed visibility, original provenance, publication rules and existing historic decisions.
2. **Provider-specific repair:** reproduce Yale's five oversized responses; independently repair the four timed-out university captures; handle 19 soft-200, JS shells or redirected index pages with exact requisition matching and bounded retrieval. Make hard source refusals terminal until permitted.
3. **Field-backed semantics:** add `deadline_type = fixed | rolling | applicant_specific | unconfirmed` and lifecycle status separately, plus field-level institutional evidence for location, role level, salary units, visa, contract, start and applicant restrictions. Missing is not necessarily a violation.
4. **Eligibility and duplicates:** triage 37 readable unassessed historical records first, then the rest of the 169 unknowns if primary evidence becomes available. Use employer IDs before collapsing any same-title groups; preserve Vienna translations and existing proven mirror handling.
5. **Source diversity:** pilot Padua and Erasmus job-specific readers, audit Ghent index's economics relevance, and test the existing Bocconi feed before adding a duplicate. Re-evaluate staged sources only after documented permit/parse contracts.
6. **Quality gates:** maintain distinct visible counters for (a) assessed identity, (b) full employer evidence, (c) active and eligible published listing, and (d) present-but-unverified. Audit the whole public snapshot, not an arbitrary fixed sample. Compare these counts against prior dated snapshots without claiming universe-wide completeness.

## Evidence limits and reproducibility

All tabulated counts come from pinned repository data and deterministic joins. The [metrics JSON](research-advert-deep-gaps-metrics.json) contains input blob SHAs and computed totals. [Source-level](research-advert-source-matrix.csv) and [row-level](research-advert-deep-gaps-251.csv) CSVs are inspectable without changing production scraping or front-end copy.

The publication join uses exact **journal ID** first, then a reviewed **exact URL/alias** match. It is deliberately not fuzzy matching by institution and title, which could inflate coverage or merge separate requisitions. A page's current status can change after its dated capture; neither public-listing presence nor a 200 response alone proves applications are open. Official links above are independent desk research and do not replace the first-party bounded collector replay.

**Separate inventory:** The Economics PhD *programme admissions* catalogue now has 253 seeds (56 verified deadline observations in the prior snapshot). This report covers the 251 distinct *research vacancy adverts*; those two denominators must not be mixed.
