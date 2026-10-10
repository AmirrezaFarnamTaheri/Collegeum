# Missing institutional pages: investigation and integration

Seven missing official institutional pages are integrated and enabled locally
on 10 October 2026. This is a targeted coverage investigation, not an exhaustive
worldwide institution inventory. Names and endpoints were compared with the
existing registry before addition. Existing sources and filtering policy remain
in place. No durable listings, personal state, broadcasts or deployment changed.

| Institution and official monitored page | Production discovery | Representative detail | Scope |
|---|---:|---:|---|
| [University of Gothenburg](https://www.gu.se/en/work-at-the-university-of-gothenburg/vacancies) | 62 rows | 13,147 characters | University-wide vacancy table with official ReachMee details; deadline column preserved. English/Swedish variants may share a reference number and require downstream deduplication. |
| [Umeå School of Business, Economics and Statistics](https://www.umu.se/en/usbe/about-us/open-positions/) | 3 adverts | 4,890 characters | English department page with PhD card and postdoctoral scholarship paragraphs. Scholarship status is retained; no assumption of salaried employment. Swedish-only and unrelated university vacancies are outside this monitor. |
| [Linköping University](https://liu.se/en/work-at-liu/vacancies) | 19 rows | 9,524 characters | Official server-rendered table contains plain-text job URLs. New `text_table` adapter reads URL, department, location and closing date without browser rendering. |
| [Duke University](https://careers.duke.edu/search/?q=economics) | 24 rows | 10,148 characters | Official SuccessFactors economics-keyword search. Date column is posting date, not closing date. Current results fit one page; future pagination needs revalidation. |
| [Trinity College Cambridge](https://www.trin.cam.ac.uk/hr/vacancies/) | 2 cards | 3,810 characters | Official HR vacancy cards, excluding navigation, news and repeated More Info links. Current non-research roles fail policy. Separate junior research fellowship competition is not covered. |
| [Bruegel](https://www.bruegel.org/careers) | 1 open call | 1,042 characters | Official Open Calls list, excluding navigation and spontaneous applications. Current visiting fellowship is not relabelled as a paid predoc job and fails configured role policy. |
| [Aarhus University](https://international.au.dk/about/profile/vacant-positions) | 60 records | 10,923 characters | Official embedded Emply JSON, decoded without executing JavaScript. Application deadline, posting date and contract start/end are distinct. Separate graduate-school PhD competitions remain outside this monitor. |

The registry now contains **88 boards: 81 enabled, 7 disabled**. Two feed
templates and one portal template remain disabled. Configured totals do not
establish health of the older sources or universal institutional coverage.

## Collection results and suitability

A production collection restricted to these seven sources discovered **171
adverts or calls**. Initial title/context policy rejected 144. Of 27 candidates
that reached detail enrichment, 12 received `wrong-field-detail` and four
`no-field-in-detail` rejection hints. **Eleven candidates remain unrejected at
the collection stage**, with no details deferred and no discovery errors.

These are not eleven unique confirmed eligible vacancies: they still need final
structured extraction, degree/funding/eligibility checks and deduplication.
Gothenburg has language variants and similar titles; Duke has two policy
associate adverts. Aarhus includes an eligible-looking management research
assistant, but also a fermentation postdoc that survived collection and still
needs final field review. No blanket economics default was added to any broad
institutional index. Existing role, field, expiry and degree policy applies.

## Remaining investigated gaps

| Candidate | Observed local limitation | Decision |
|---|---|---|
| [RAND](https://www.rand.org/jobs.html) | Official page points to `rand.wd5.myworkdayjobs.com/External_Career_Site`; all four production Workday search terms failed with `FetchError`, yielding zero validated records | Not activated; needs a working production discovery contract. |
| [University of Pennsylvania](https://www.hr.upenn.edu/PennHR/careers-at-penn/how-to-apply) | Production HTTP returned 403 | Not activated from search-engine evidence alone. |
| [Urban Institute](https://www.urban.org/careers) | Production HTTP returned 403 | Not activated. |
| [King's College Cambridge](https://www.kings.cam.ac.uk/about/working-at-kings) | Local request raised an exception; initial capture recorded an empty exception string | Not activated; exact failure cause remains unverified. |
| [CEPR](https://cepr.org/about/jobs) | Direct local probe returned 403 | Not activated. |
| [Center for Global Development](https://www.cgdev.org/page/job-opportunities) | Direct local probe returned 403 | Not activated. |

Earlier LBS inline/cohort pages, NHH Jobbnorge details and Sciences Po Drive-only
adverts remain the gaps recorded in the preceding expansion reports. A successful
search-engine fetch is insufficient to activate a failing local adapter.

## Reproducible evidence

- [Candidate discovery](institutions/candidates.json) and
  [additional institute probes](institutions/institute-probes.json) record the
  inspected URLs, responses and observed links.
- [Production discovery](institutions/discovery.json),
  [detail extraction](institutions/details.json) and
  [collection results](institutions/collection.json) record the seven additions.
- [Validation script](institution-validation.py) runs only the seven additions
  from the repository root, without storage, model calls or publication. It
  refreshes evidence and captured fixtures; review fixture changes before use.
- `tests/boards/test_institution_sources.py` covers actual registry settings,
  counts, unique URL identities, title/date semantics and HTTP failures.
- `tests/boards/test_text_table.py` and `test_emply_embedded.py` cover empty versus
  missing/malformed payloads, invalid URL boundaries, valid neighboring records,
  distinct deadlines/posting dates and JSON decoding without code execution.
- Targeted adapter coverage is **98% combined** (Emply 100%, text table 96%).
  Twenty-eight targeted tests passed; Ruff passed for all new code, tests and
  validation scripts. Focused mypy checks passed for both new adapters.
- Full-suite verification: **960 tests and 15 subtests passed**, with the existing
  `twitter_text`/`pkg_resources` deprecation warning. `git diff --check` passed.
  These checks do not establish deployment or final candidate eligibility.

Captured fixtures contain only relevant list/table markup or the official Emply
JSON script. Raw navigation-heavy pages were removed after evidence capture.
