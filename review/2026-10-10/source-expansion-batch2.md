# Further official source expansion — 10 October 2026

Three additional official monitors are integrated and enabled locally. Their
endpoints were absent from the registry; names remain unique across boards,
feeds and portals. The existing HTTP, link-scan, enrichment and relevance policy
remain in use. No listing database, personal state or remote deployment changed.

| Source | Live discovery | Detail validation | Coverage boundary |
|---|---|---|---|
| [University of Warwick](https://workwithus.warwick.ac.uk/search/?q=economics) | 48 distinct job tiles; repeated desktop/mobile links collapse | Economics Research Assistant advert returns 9,090 text characters | The economics query currently returns broad university vacancies. No economics default; unrelated roles and research fields still face filtering. All 48 appear in one response; future pagination needs revalidation. |
| [Bank of Canada](https://careers.bankofcanada.ca/go/All-Job-Opportunities/2400817/) | 16 distinct table rows; location and deadline preserved | PhD Researcher advert returns 12,285 characters | Whole-bank index includes IT/admin and senior roles. PhD job-market titles and requirements are retained. Deadline text preserves time/timezone, while the existing normalized field is date-only. Current index reports one page. |
| [Sciences Po](https://www.sciencespo.fr/recherche/en/faculty/vacancies/) | 3 official department adverts within the ongoing-recruitment tab | All three details return substantive text: 4,822, 8,988 and 1,602 characters | Partial coverage: two Drive-only PhD/postdoc adverts are omitted until their detail extraction is validated. Past recruitment and biographies are excluded; original French titles are retained. |

## Production collection evidence

A read-only run of only these three sources discovered **67 adverts**. Title and
context checks rejected 59 before detail enrichment. Eight candidates reached
enrichment; two received `wrong-field-detail` rejection hints, leaving **six
unrejected extraction candidates**. Zero details were deferred, and discovery
reported no fetch/parse errors. These candidates have not undergone final
structured extraction, degree/eligibility checks or publication. They are not six
confirmed predoc vacancies.

The Bank of Canada candidate is explicitly a PhD job-market position. Warwick
includes research-fellow positions. The expansion follows the existing configured
role scope; it does not relabel these posts as predocs to inflate yield.

## Candidate discovery and suitability

Eight official endpoints were inspected: three London Business School department
pages, Warwick, IZA, SAFE, Sciences Po and the Bank of Canada. The three integrated
sources have current server-rendered cards plus usable production detail text.

- LBS economics and marketing contain one inline advert with an Interfolio
  application ID. A dedicated adapter must isolate advert text, preserve cohort
  identity and handle removal/renewal. Economics has an expired March 2026 hard
  deadline; marketing has a priority date followed by review until filled.
  Neither is activated as a current vacancy based on a programme page alone.
- LBS finance uses a form-based application flow; a comparable detail/identity
  contract has not been validated.
- IZA currently reports no announcements. SAFE's scientific and administrative
  vacancy sections are empty. Neither is activated with guessed future markup.
- NHH remains disabled for the detail-extraction limitation recorded in the
  [first batch](source-expansion.md).

## Evidence and verification

- [Discovery JSON](batch2/discovery.json): production scraper statistics and
  normalized titles, URLs and deadlines for all 67 adverts.
- [Detail JSON](batch2/details.json): representative production detail text
  lengths, final URLs and short excerpts.
- [Collection JSON](batch2/collection.json): production filtering/enrichment
  statistics and candidate rejection hints. Detail text is capped by the
  collector's existing 6,000-character budget.
- [Validation script](batch2/validate.py): rerun from the repository root with
  the project Python environment; performs read-only collection without durable
  storage, model calls or broadcasting.
- `tests/boards/test_source_expansion_batch2.py`: seven source-contract cases
  covering registry configuration, actual card counts, distinct identity,
  metadata, scope exclusions, relevance policy and HTTP failure classification.
  Fixtures preserve captured vacancy markup; the past-tab negative control is
  synthetic. No test depends on a continuing live vacancy.

Validation completed: **932 tests and 15 subtests passed**. Ruff passed for the
new test module and retained validation script; `git diff --check` passed.
The test run reports the existing `twitter_text`/`pkg_resources` deprecation
warning. These local checks do not establish deployment or final eligibility.

Current registry totals: **81 boards, 74 enabled and 7 disabled**. The two feed
templates and one portal template remain disabled. This batch adds three enabled
monitors, with Sciences Po explicitly partial. Counts do not establish health of
the other configured sources or future compatibility after site layout changes.
