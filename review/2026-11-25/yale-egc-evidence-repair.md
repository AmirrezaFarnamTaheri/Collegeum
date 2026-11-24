# Yale EGC advert context and deadline repair

Review date: 25 November 2026. Baseline commit: `dbe5dfd2a0ac47a7cd22b075e479089598e5f3e0`. Source-health snapshot: 2026-11-24T19:54:35Z. This is a follow-up to the 298-record review, not an expansion of that cohort.

## Diagnosis

The five historical `response_too_large` outcomes were independent audit-reader observations, not proven production failures. The five most recent recorded production runs show Yale EGC discovery successful, six raw items, five relevant, zero reported fetch/parse/limit errors. All five job IDs have `last_verified_at` in the production journal. The shared 8 MiB HTTP bound is unchanged; no provider restriction is bypassed. Health and verification timestamps do not certify correct extraction.

Inspection exposed an actual stored-content error: ID 296's summary describes a communications associate, department incorrectly names that neighboring vacancy, and the role has min_degree=phd and kind=research. ID 298 also inherits the neighboring communications department. The current employer index contains a communications vacancy alongside five research roles. Generic `find_card` can select a shared multi-advert wrapper (reproduced using a synthetic fixture); this is a demonstrated contamination mechanism, not a captured replay proving the precise historical cause. Enable anchor-only discovery for Yale EGC so index text from neighboring roles cannot supply department, deadline or summary hints. Other boards' default behavior and downstream field/role rules are unchanged. Full detail extraction still uses existing checks.

## Primary employer evidence and proposed changes

| Journal ID | Official Yale advert | Correction |
| --- | --- | --- |
| 296 | [Development and Experimental Economics Research Fellow](https://egc.yale.edu/opportunities/development-and-experimental-economics-research-fellow-1) | Replace contaminated summary/department; predoctoral role, bachelor's or master's, supervisors Maria Kogelnik and Rohini Pande, rolling applications. |
| 298 | [Development Economics Research Fellow](https://egc.yale.edu/opportunities/development-economics-research-fellow-2) | Clear unrelated department; corroborate Rohini Pande, degree and skills; explicitly rolling. |
| 456 | [Macro-Development](https://egc.yale.edu/opportunities/postdoctoral-associate-macro-development) | 2027–28 appointment; date-only January 31, 2027. |
| 458 | [Kuznets Markets and Development](https://egc.yale.edu/opportunities/postdoctoral-associate-kuznets-markets-and-development) | 2027–28 appointment; date-only January 31, 2027. |
| 460 | [Economic History](https://egc.yale.edu/opportunities/postdoctoral-associate-economic-history-program-1) | Date-only January 31, 2027. |

[Official index](https://egc.yale.edu/opportunities/jobs-research-fellowships) identifies the two predoctoral roles separately. Stata and/or R is a disjunctive requirement: the summary records it explicitly, not a structured list incorrectly implying that both are mandatory; Python is preferred. Salary, workplace location, duration and visa fields remain unchanged where the advert does not establish them. No new collector receipts, verification timestamps or identity changes. The three date-only deadlines use the repository's existing documented UTC end-of-date compatibility convention (see tests/integration/test_deadline_precision.py), rather than the erroneous start-of-day values; the deadline notes explicitly disavow employer-confirmed time/zone. A schema-level date/time precision redesign is still open.

## Consistency

The 500 journal rows and 214 public rows are retained. 3 affected RSS descriptions are updated, maintaining all 100 items and the same order and links. Public content SHA-256 and the matching health receipt are refreshed without changing run outcome or collection timestamp. Before/after values and pinned blobs are in [Yale evidence JSON](yale-egc-evidence-repair.json).

Local isolated tests copied the relevant existing card selector into a small fixture harness: one regression test failed on the old helper, both passed after adding the anchor-only option. The actual repository scraper regression test is included; full CI has not yet run on this branch. Local full clone remains unavailable (DNS). Do not treat this source-specific change as proof all remaining missing bodies, eligibility, source failures or duplicate hypotheses are resolved.
