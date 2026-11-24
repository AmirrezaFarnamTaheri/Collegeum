# Official research-source expansion — 24 November 2026

Three new official employer indexes are enabled, covering institutions in Germany,
India and Austria. The registry grows from **144 to 147 boards**, and from **75 to
78 enabled boards**. The existing 69 disabled boards remain disabled.

The read-only replay found **21 distinct listed research requisitions**. Of these,
**17 passed the collector's role, subject, region and expiry checks**, two were
rejected by the existing subject policy, and two were deferred because their
official adverts have explicit elapsed start dates without a current closing date.
These are discovery and collector results, not a claim of 17 newly published or
previously unseen opportunities. Aggregator overlap and the downstream extraction,
deduplication and publication gates still apply.

| Source | Official index | Listed research requisitions | Eligible collector candidates | Other outcomes |
| --- | --- | ---: | ---: | --- |
| ESMT Berlin | [Jobs @ ESMT Berlin](https://jobs.esmt.berlin/de) | 2 | 2 | None |
| Indian School of Business | [Academic Openings](https://www.isb.edu/work-at-isb/academic-openings) | 13 | 9 | 2 subject rejections, 2 deferred stale adverts |
| WU Vienna | [Current vacancies](https://jobs.wu.ac.at/) | 6 | 6 | None |

The machine-readable evidence is in
[`official-source-expansion.json`](official-source-expansion.json).
It records every listed research job, original and final URLs, capture time,
response size, content hash, location provenance, collector outcome and reason.

## Evidence and practical limits

The initial live pipeline HTTP probe sent **zero requests**: the workspace could
not resolve public DNS for its outbound-destination guard. The guard remains
intact. Research then used the existing bounded official-source HTTPS reader,
which works through the environment's network proxy. Each new provider's robots
policy was checked before content; only independently located official URLs were
read, with same-host redirect validation and bounded responses. All three selected
indexes and all 21 linked research adverts were captured successfully.

The actual captured pages were replayed through the new adapter and `_collect`
without network requests, a database, model extraction, alerts or publication.
This verifies the observed source contracts and collector behavior. It is not
presented as a successful live run through the pipeline's separate HTTP transport.
The first normal scheduled run will establish operational source health in its
usual execution environment.

Reduced HTML fixtures preserve the observed card structures, titles, URLs and
requisition IDs. Detail fixtures retain the observed structure and essential facts
with abbreviated prose. Full captures were used for the separate 21-advert replay;
the fixtures are not substituted for that evidence.

## Exact source contracts

`official_research` is a narrowly scoped adapter with three named profiles. Every
profile requires its exact configured index, expected heading, actual vacancy
cards and a provider-specific job URL. Unknown or empty layouts fail visibly;
none of these providers has a reviewed healthy-empty contract. New pagination or
a listing above the bounded card limit is reported as partial coverage.

Details must return the same requisition and matching title. ESMT and WU also
require a matching, unique canonical URL. Conflicting cards for the same identity
are not resolved by choosing the first result. Distinct WU requisitions 2966 and
2967 retain separate identities despite their identical job titles.

The collector's new detail requirement is opt-in to this adapter. Missing,
redirected or mismatched details are deferred, including strong predoc titles.
An HTTP 404 or 410 keeps the existing closed-link behavior. Provider-wide access
denials stop subsequent detail requests from that source. Deferred evidence states
have controlled public messages and do not appear as corroborated new candidates.

### ESMT Berlin

The observed HRworks cards identify a predoc and a postdoc at the European
Expectations Center: [predoc 63a5b3](https://jobs.esmt.berlin/de?id=63a5b3) and
[postdoc f47b7c](https://jobs.esmt.berlin/de?id=f47b7c). Both have job-specific
Economics/Finance evidence. Administrative, controller, events and other staff
cards are excluded by the source role guard.

Subject checks read only the duties and qualification sections. Generic business
school introductions and employee financial benefits cannot establish the research
field. The complete scoped advert remains available to downstream extraction.

### Indian School of Business

The academic index yields 13 research-assistant/associate links. Teaching-focused
academic-associate entries and the separate non-academic recruitment system are
outside this source's contract. The [Bhavna Rai Economics/Public Policy
advert](https://www.isb.edu/work-at-isb/academic-openings/research-associate-with-professor-bhavna-rai)
provides an example of an explicitly scoped research role.

Eleven titles name a supervising professor. A source-scoped title check removes
only the `with/under Professor` introducer from the faculty-exclusion calculation;
the displayed employer title is preserved. Actual professor roles and other
excluded faculty terms still fail the normal gate.

Subject evidence comes from approved role, responsibility and qualification
sections. School biography, generic faculty biography, institutional commitment
and benefits sections cannot qualify an otherwise subject-unknown advert. With
that distinction enforced, the Sumeet Kumar role lacks sufficient subject evidence
under the current policy, and the Vandith Pamuru role is rejected as outside the
selected subject scope. The adapter does not add institutional language back to
retain a larger count.

Two index-listed adverts require fresher evidence: [SRITNE](https://www.isb.edu/work-at-isb/academic-openings/research-assistant-sritne)
states an expected joining date of 10 November 2025, and [Deepa Mani](https://www.isb.edu/work-at-isb/academic-openings/research-associate-position-under-the-professor-deepa-mani)
states a start of 24 August 2026. They are deferred, not declared closed. A future
explicit application deadline can resolve the elapsed-start concern.

The `.edu` suffix must not turn an Indian employer into a US job. An advert's own
`Location` paragraph takes precedence, including the explicitly identified
Hyderabad/Mohali campuses. Without a usable advert location, the reviewed India
source default is retained and recorded as `country_basis=reviewed_isb_profile`.
That default is not represented as a confirmed job location. A recognized explicit
foreign location can override it.

### WU Vienna

The index supplies six research/predoc requisitions, with actual institute or
department metadata. It uses several legitimate ID-label formats; each must agree
with the numeric identity in its vacancy URL. The canonical employer name is
`WU Vienna`, so the expanded university name does not itself supply an economics
subject match.

The actual `Research and Teaching Assistant/Associate` and `prae doc` title forms
are recognized. Faculty, administrative and IT job titles remain excluded. Subject
evidence is limited to the explicit institute/department, duties and qualifications.
The university welcome paragraph is excluded by its structural position, even if
its wording or HTML element changes; salary/contact material does not qualify the
research field.

English application dates use the standard explicit-deadline parser. German
`bewerben Sie sich bitte bis spätestens DD.MM.YYYY (Kennzahl: ID)` dates are read
only with a full year and matching requisition ID; incomplete or conflicting
labels defer the advert. The captured German positions close on 25 November and
2 December 2026. None of their employment start/end dates is substituted for an
application closing date.

## Candidates deliberately not enabled

| Candidate | Observed blocker |
| --- | --- |
| [London Business School Economics predoc](https://www.london.edu/faculty-and-research/economics/pre-doctoral-research-assistant) | Official closing date was 27 March 2026. The 2026/2027 employment start does not reopen applications. |
| [Erasmus University Rotterdam vacancies](https://www.eur.nl/en/working-at-eur/search?display=results&view=search_page) | Robots policy was readable; the bounded listing fetch timed out. No early retry or activation from indexed text. |
| [University of Oslo Faculty of Social Sciences](https://www.sv.uio.no/english/about/vacancies/) | Official index readable with Economics vacancies, but the linked Jobbnorge robots endpoint returned HTTP 406. No job detail was requested and the source was not enabled. |
| [Hertie School](https://www.hertie-school.org/en/jobs) | Official careers page readable; its published d.vinci script redirected to the provider's widget-error script. No usable vacancy payload was established. |

Previously quarantined providers are not re-enabled by this work.

## Validation

Focused tests exercise listing identity, real role variants, faculty/admin
exclusions, same-title distinct jobs, missing and conflicting detail identities,
provider-denial stopping, subject leakage from navigation and school biographies,
India/foreign-location provenance, elapsed starts, and full-year German deadlines.
They also preserve the legacy best-effort detail behavior for existing sources.
Ruff and mypy are clean for the affected adapter, collector and filter modules.
The complete project suite and standalone-distribution gates run separately as
the final integration checks.
