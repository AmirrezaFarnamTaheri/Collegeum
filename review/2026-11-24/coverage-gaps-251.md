# Missing evidence and source expansion: 251-advert review (24 November 2026)

This is a **dated quality audit**, not a live open-vacancy count or a replacement for the [251-advert evidence ledger](research-adverts-251.json). The audit cohort was fixed by a selection rule (81 newly researched source adverts and 170 recent journal adverts); **251/251 checks does not mean 251 current, relevant or fully verified adverts**.

## Evidence gaps at advert grain

| Measure | Number | Meaning |
| --- | ---: | --- |
| Completed distinct advert checks | 251 | A dated outcome was recorded, including failures |
| Identity-matched substantive bodies | 134 (53.4%) | Primary advert content captured; not necessarily open or eligible |
| Without substantive bodies | 117 (46.6%) | Includes 4 closed notices with identity but no body |
| Collector-eligible in this review | 27 (10.8%) | Passed source replay; downstream publication is separate |
| Subject rejected | 48 (19.1%) | Do not promote into eligible listings |
| Eligibility not assessed here | 169 (67.3%) | Historical journal inventory, not automatically a current eligible candidate |
| Explicitly deferred | 7 (2.8%) | Additional current official evidence needed |

Among the 169 `not_assessed` records, **56 retain full bodies** (37 readable, 19 already closed), while **113 have no full body**. Together with 7 deferred records, that produces a **176-record evidence/eligibility follow-up queue**. The [sortable CSV queue](research-advert-evidence-gaps.csv) contains each record's immutable identity, source, outcome, URL, priority and explicit next action. It does not recast unknown outcomes as verified.

### Response outcomes

| Recorded outcome | Count |
| --- | ---: |
| `readable_advert` | 114 |
| `access_unavailable` | 69 |
| `closed_advert` | 24 |
| `unverified_page` | 19 |
| `removed_advert` | 14 |
| `fetch_failed` | 11 |
| **Total** | **251** |

### Largest missing-body source clusters

| Source | Missing bodies |
| --- | ---: |
| `predoc_org` | 32 |
| `uchicago_bfi` | 13 |
| `jpal_global` | 7 |
| `wharton_predoc` | 7 |
| `yale_egc_jobs` | 5 |
| `gothenburg_jobs` | 5 |
| `aarhus_jobs` | 4 |
| `warwick_jobs` | 4 |
| `nus_policy_research` | 3 |
| `copenhagen` | 3 |
| `vienna_university_research` | 2 |
| `bis` | 2 |

The missing-body clusters do **not** license retries through blocked hosts. Among the access-unavailable entries, the largest clusters are `predoc_org` (26), `uchicago_bfi` (13), `wharton_predoc` (7) and `jpal_global` (7). The project explicitly excludes J-PAL as an employer; do not switch it on to improve a metric. Five Yale EGC pages failed the bounded reader as oversized; four new university listings timed out. Preserve request budgets and security constraints when developing alternative permitted official-source reads.

## Work order

1. **P1 — review 37 readable historical records with unknown eligibility.** Apply the current discipline, role, level and access criteria to the *primary* advert. Evaluate whether each is now closed; historical publication alone is not current proof.
2. **P1 — repair 11 fetch errors and 19 unverified HTTP 200 pages.** Investigate oversized Yale pages, four new-source timeouts, JavaScript-only career portals and soft 404s. Use bounded, permitted first-party detail retrieval and requisition matching.
3. **P1 — resolve 3 deferred records with bodies.** Obtain current employer evidence for start dates or ambiguous application cutoffs; do not use guessed years.
4. **P2 — resolve 69 access restrictions only by allowed routes.** Prefer official feeds, accessible job-specific pages or provider cooperation. No robots, authentication or cooldown bypasses.
5. **P2/P3 — handle 14 removed endpoints and 24 closed records as lifecycle data.** Find an official successor requisition if one exists, else archive without claiming recruitment remains open.

The CSV includes P3 closure records because the eligibility status in this particular review is still `not_assessed`; they should *not* be counted as current opportunities.

## The other 251: Economics PhD programme catalogue

This is a **separate dataset**, with exactly 251 institutional programme seeds; it must not be combined with the advert count. Source: [current catalogue](../../docs/data/phd_admissions.json).

| Programme evidence status | Count |
| --- | ---: |
| `no_explicit_deadline` | 100 |
| `robots_unavailable` | 62 |
| `verified` | 56 |
| `fetch_failed` | 31 |
| `unsafe_redirect` | 1 |
| `robots_disallowed` | 1 |
| **Total** | **251** |

Only **56/251** programme records have current official-source deadline confirmations. Among 195 unconfirmed records, 100 did not yield an explicit, single in-scope dated cutoff, 62 could not obtain robots instructions, 31 failed fetching, one encountered an unsafe redirect and one was robots-disallowed. A lack of a universal deadline can be legitimate (rolling, closed or applicant-specific); do not invent one.

**Optional information depth is also thin:** 236/251 programme records have no populated `official_details` keys (tuition, funding, entry route, language, etc.). Those are enrichment opportunities, not evidence that the main programme seed is invalid. Keep details behind disclosure UI, rather than adding more policy text to the frontend.

## Institution and official-source expansion leads (not activated)

- **KU Leuven Economics PhD** is **absent** from the 251 programme seeds. Its official [2027–28 call](https://feb.kuleuven.be/research/economics/PHD/phdcall) and [application page](https://feb.kuleuven.be/drc/Economics/research/econ-phd-application) state **31 January 2027** as the application deadline. Treat as an additional programme candidate with separate provenance; inclusion requires review of catalogue identity/scope and the automated source corroboration process.
- **KU Leuven** also has a distinct [official vacancy site](https://www.kuleuven.be/personeel/jobsite/jobs/60784116?lang=en) with requisition-scoped postings. This is an adapter **research lead**, not an enabled source or a validated Economics vacancy.
- **Erasmus University Rotterdam** publishes [academic vacancies](https://www.eur.nl/en/working-at-eur/working-areas/academic-staff) and a [paginated official search](https://www.eur.nl/en/working-at-eur/search). Its current university-wide feed requires scoped economics-research selection and matching vacancy detail before enablement.
- **Hertie School** publishes [official jobs](https://www.hertie-school.org/en/jobs) and separate [doctoral research positions](https://www.hertie-school.org/en/phd/apply-for-a-phd/open-phd-positions). Governance/doctoral funding routes vary by position and should not be mistaken for one Economics PhD deadline.

These leads do **not** add to the existing 251-advert count or 56 programme confirmations. The present source registry has 151 boards, 82 enabled; disabled boards include deliberate technical, eligibility and provider-access restrictions. Do not bulk-enable them merely to raise coverage.

### Programme-scope checks before enlarging the 251 seeds

- **Tinbergen Institute** is not a separate direct-entry PhD awarder: its [research master admissions](https://tinbergen.nl/admissions) lead towards PhDs at partner schools, and its [PhD vacancy page](https://tinbergen.nl/phd-vacancies) says it does not offer PhD positions directly. Model the research-master admission route or the specific university vacancy, **not** a fictional generic Economics PhD closing date.
- **Maastricht University** is absent as a distinct seed, but its [MSI PhD programme](https://www.maastrichtuniversity.nl/research/msi/research/phd-programme) allows employed, scholarship and externally funded routes; review programme identity, funding and application eligibility before considering a new seed.
- **Utrecht University** is absent from the programme seed list although the [School of Economics](https://research-portal.uu.nl/en/organisations/utrecht-university-school-of-economics/) has PhD candidates. Existing Utrecht job-specific adverts are already in the posting source registry. Do not infer a universal doctoral application deadline from staff profiles or vacancies.

## Quality rules to preserve

- Maintain three separate metrics: **checked**, **identity-matched body**, and **currently eligible/open**.
- Track role identity and first-party URL, HTTP result, timestamp, source evidence, subject decision, lifecycle status and applicant-specific cutoff independently.
- Do not automatically inherit a deadline, salary, location or programme eligibility from search snippets, related cards, faculty biography or other requisitions.
- Retry by source-specific budgets. Distinguish deliberate denial and permanent removal from transient errors.
- Publish audit reports in `review/` only; keep the frontend focused on applicants and concise listing details.

All counts above were computed from the audited JSON on branch `improve/phd-official-coverage`, evaluated against the catalogue snapshot dated 24 November 2026.
