# Collegeum source expansion — 5 October 2026

Research identifies **19 additional official pages** worth staging, plus three lower-confidence leads. Each of the 19 has a URL absent from the current board registry. This is a researched shortlist, not a claim that all pages have current vacancies or that the existing generic adapter already handles them. No production sources were activated and the website's headline count was not changed.

## Current coverage first

**Validation update, 6 October 2026:** [LBS economics/marketing validation](source-validation-lbs.md) confirms different application-date semantics: economics has an expired hard deadline; marketing has a priority date followed by review until filled. Interfolio vacancy identifiers were verified as linked targets, while current application availability remains unverified. These pages remain staged monitors, not two confirmed open vacancies.

**Implementation update, 5 October 2026:** the redundant broad-link PREDOC entry has now been removed locally, retaining its dedicated parser. Validated registry counts are 74 boards / 68 enabled / six disabled, plus two feeds and one portal. The paragraph below preserves the original audit baseline; it is not the current configured count. Registry validation now rejects duplicate names across collector kinds. Live healthy coverage and the dashboard headline still require reconciliation.

The registry contains 75 board entries, six disabled, and a duplicated `predoc_org` name. That is 69 enabled entries / 68 distinct enabled names, not 75 independently healthy monitors. Several entries also contain multiple URLs, so board entries, URLs, employers and healthy scrape results are different counts. The latest saved run has 22 failed board keys and 11 zero-result keys. See [audit.md](audit.md), particularly F06, F07 and F19.

Fix uniqueness and verification before adding pages. Recovering even a portion of the failed sources may add more useful coverage than many new low-yield indices. Use employer/job identifiers to deduplicate official pages against PREDOC, jobs.ac.uk, EURAXESS and other aggregators.

## First batch: directly relevant recruitment pages

All adapter suggestions below are implementation inferences from inspected content, not successful pipeline scrape results. “Inline” means the recruitment information itself lives on the monitored page and cannot be treated as a list of arbitrary outbound links. Positive-field defaults must still yield to contradictory job evidence.

| ID | Official monitored page | Scope / location | Observed recruitment evidence | Integration and caveat |
|---|---|---|---|---|
| 01 | [Kellogg research fellowship applications](https://www.kellogg.northwestern.edu/academics-research/research-support/research-fellows/apply/) | Empirical/behavioral predoc fellows; US | Explicit application table, fellow tracks and Fall 2026 recruitment information | Parse table rows and vacancy application links; separate economics/finance/quantitative marketing from psychology-only roles. Allow seasonal empty tables. |
| 02 | [Stanford GSB dedicated-track projects](https://www.gsb.stanford.edu/programs/research-fellows/academic-experience/dedicated-track/projects) | Predoc research projects; US | Official indexed content describes a September 3, 2026 application opening and individual projects | Custom section parser; one project can share a general application portal with others, so URL-only dedupe must not collapse all projects. Direct refetch was intermittent; verify transport before activation. |
| 03 | [LBS economics predoc recruitment](https://www.london.edu/faculty-and-research/economics/pre-doctoral-research-assistant) | Economics predoc; UK | Advert content names academic year 2026/27 and a predoctoral RA role | Inline advert/program parser with dated cohort identity; do not fabricate a deadline if absent. |
| 04 | [LBS marketing predoc recruitment](https://www.london.edu/faculty-and-research/marketing/pre-doctoral-research-assistant-in-marketing) | Marketing research predoc; UK | Predoc programme and 2026/27 start information | Inline parser; retain quantitative/social-science marketing projects and apply configured field policy. |
| 05 | [LBS finance researcher recruitment](https://www.london.edu/faculty-and-research/finance/pre-doctoral-researcher-recruitment) | Finance/economics/accounting predoc; UK | Dedicated recruitment and eligibility information | Inline/cohort monitoring; form/contact-based applications need an explicit application method rather than a guessed ATS URL. |
| 06 | [CREST opportunities](https://crest.science/opportunities-2/) | Economics, finance, quantitative sociology and statistics; France | Separate pre-doc/PhD/postdoc/RA sections | Restrict parsing to job-opening sections, excluding job-market placement biographies. Follow official advert/PDF links; field policy required for non-economics statistics. |
| 07 | [Nuffield jobs and vacancies](https://www.nuffield.ox.ac.uk/the-college/jobs-and-vacancies/) | Social-science research appointments; UK | Current index contains a research-engineer vacancy | Narrow link scan of vacancy items plus details/PDF. College administrative jobs must fail role filtering. Complements the disabled broad Oxford entry. |
| 08 | [ESSEC jobs](https://job.essec.edu/jobs) | Business-school research employment; France and other campuses | Official jobs index | Inspect Teamtailor-style job links and pagination; filter research roles. Assign country from each vacancy, not from the school's French headquarters. |
| 09 | [Barcelona School of Economics job openings](https://bse.eu/research/job-openings) | Economics research; Spain | Dedicated research-openings index with EURAXESS publication path | Official-detail link scan; complements the existing EURAXESS BSE search. Deduplicate by advert/job identity. Initial page read succeeded; a later read timed out, so retain diagnostics. |

These nine pages are the highest-priority integration batch. They cover recurring research recruitment rather than general university navigation. The Stanford and BSE entries need a repeatable transport check before activation; all nine still need extraction fixtures.

## Second batch: broader roles, cycles and targeted programme monitoring

| ID | Official monitored page | Scope / location | Why useful | Integration and boundary |
|---|---|---|---|---|
| 10 | [IZA job portal](https://jobs.iza.org/) | Labor economics; Germany | Official current-openings portal; research associates and student helpers are described | Link scan + role/degree classification. The portal also targets experienced PhDs; do not relabel every research associate as predoc. Historical predoc PDFs establish recurring interest, not a current opening. |
| 11 | [NHH vacant PhD positions](https://www.nhh.no/en/study-programmes/phd-programme-at-nhh/vacant-phd-positions/) | Economics/business PhD; Norway | Persistent programme vacancy page; states the next main deadline is January 15, 2027 | Monitor for actual department application links; allow seasonal emptiness. A programme-wide deadline alone should not create a specific vacancy record. Fits the repository's configured PhD support. |
| 12 | [NHH all vacancies](https://www.nhh.no/om-nhh/ledige-stillinger/) | Academic/research jobs; Norway | Complements the dedicated PhD page with research employment | Follow official vacancy/Jobbnorge links; classify senior faculty and administrative roles separately. Overlaps future repaired Jobbnorge coverage. |
| 13 | [Sciences Po research vacancies](https://www.sciencespo.fr/recherche/en/faculty/vacancies/) | Social-science research/academic jobs; France | Central official vacancy surface across departments | Narrow section parser + linked adverts. Verify economics/political-science quantitative relevance per role; no blanket field implication for the whole institution. |
| 14 | [Bank of Canada all job opportunities](https://careers.bankofcanada.ca/go/All-Job-Opportunities/2400817/) | Central-bank research employment; Canada | Official searchable jobs table | SuccessFactors-style table/pagination or dedicated adapter. Restrict to research assistant/analyst/economist roles consistent with degree policy; exclude IT/admin assistant titles. |
| 15 | [Bank of Canada students and recent graduates](https://www.bankofcanada.ca/careers/students/) | Early-career recruitment; Canada | Official page describes research-assistant eligibility and recurring campaigns | Programme/campaign monitor that follows an actual open campaign. Complement ID 14; never count one vacancy twice. |
| 16 | [Stanford GSB research fellows admissions](https://www.gsb.stanford.edu/programs/research-fellows/admission) | Predoc recruitment cycle; US | Official admissions/application-cycle page linked to dedicated-track projects | Monitor changes to opening dates and application route; combine IDs 02/16 into one source with two page roles. Official search discovery succeeded; direct fetch was intermittent. |
| 17 | [Wharton roles and opportunities](https://research.wharton.upenn.edu/roles-opportunities/) | Full-time predoc programme; US | Dedicated predoc section explains research appointments and links resources | Programme hub/change monitor; follow recruitment resources to real adverts. Exclude undergraduate/current-student assistantships and explanatory programme text from vacancy output. |
| 18 | [Wharton Mack Institute research opportunities](https://mackinstitute.wharton.upenn.edu/research/research-opportunities/) | Innovation-management predoc programme; US | Describes two-year predoc appointments and links the Penn careers portal | Programme monitor + targeted Penn job discovery; no claim that a position is currently open. Exclude semester student assistantships and fellow biographies. Shares employer/ATS coverage with ID 17. |
| 19 | [Western economics job opportunities](https://economics.uwo.ca/about-us/job-opportunities.html) | Economics academic recruitment; Canada | Official department vacancy index | Lower priority: predominantly academic/faculty recruitment; follow only supported PhD/postdoc/research employment roles, not the whole faculty market. |

The shortlist is **19 pages**, not 19 independent employers or 19 currently open jobs. It can be represented by fewer registry sources, for example one Stanford source with project/admission URLs, one NHH source with PhD/employment URLs, and one Bank of Canada source with job/campaign URLs. Nine first-batch pages plus ten second-batch pages would take the monitored-URL inventory up by 19 after validation; they should not be blindly added to the current “75” headline.

## Hold or validate before adding

| Lead | Evidence and decision |
|---|---|
| [UCL CReAM jobs](https://w.cream-migration.org/jobs.htm) | Official job-page search discovery, but direct opening failed in this research session. Validate its current canonical address and vacancy content before staging it as healthy. |
| [Princeton economics join our team](https://economics.princeton.edu/join-our-team/) | Page opens and includes predoc/research specialist listings, but several descriptions explicitly refer to 2022/2023. Valuable discovery lead; insufficient evidence that all displayed posts are current. Require live ATS confirmation. |
| [Sciences Po economics research opportunities](https://www.sciencespo.fr/department-economics/research/research-opportunities/) | Page opens, but inspected RA and CEPR opportunities are explicitly from 2022. Hold automatic vacancy ingestion; prefer ID 13 and verify current department adverts. |

Bruegel was also researched, but this pass did not verify a durable official vacancy index. Do not substitute old PDFs, a single historic social post or third-party copies for a monitored current recruitment page. Columbia's pre-doc staff roster was excluded because a people list is not a vacancy board. Existing UBC Workday and LSE entries were not counted as new sources.

## Repair existing sources alongside expansion

- LSE is already configured but disabled. Its `Vacancies/W/` assumption should be checked against the official [CEP urban research assistant path](https://jobs.lse.ac.uk/Vacancies/I/6762/0/461348/15539/research-assistant-cep-urban), which uses `Vacancies/I/`. This is evidence of a URL-pattern mismatch, not proof that that individual advert is still open.
- Consolidate the two PREDOC adapters and the PSE/CEMFI alternative-page entries after checking which surfaces actually add unique adverts. Unique source IDs must keep per-adapter diagnostics intact.
- Review failed Opportunity Insights, NBER, SIEPR, Tobin, IPA and the central-bank sources before relying on aggregate counts. Do not fix all of them by setting `may_be_empty=true`.

## Acceptance conditions for activation

**Nuffield follow-up, 6 October 2026:** [current index/detail/application-route validation](source-validation-nuffield.md) confirms the official vacancy surface and records the application destination's unreadable content. Discovery, role-policy verification and fixtures remain required; this does not add a healthy monitor to coverage.

Detailed follow-up: [CREST validation and conflicting PDF/platform deadlines](source-validation-crest.md). A successful PDF read uncovered an actual recruitment-platform deadline extension; source activation still requires individual-advert and policy validation.

**CREST recheck, 5 October 2026:** [the official opportunities page](https://crest.science/opportunities-2/) still mixes vacancy sections with job-market placement biographies. Its vacancy area currently links a scientific-machine-learning postdoc, an experimental-economics lab manager and a computational judicial-analysis postdoc. This supports section-scoped discovery, not unrestricted outbound-link ingestion. Vacancy detail dates, field eligibility and actual open status still need verification before activation; page availability alone is insufficient.

For each candidate, retain a dated response fixture and a recorded parser result, including an intentionally empty season where relevant. Demonstrate: a real eligible vacancy is extracted; unrelated navigation/admin/roster content is excluded; location comes from the vacancy; missing facts stay unknown; application links identify the actual route; closed/historical adverts are rejected without confusing first-review dates with deadlines; duplicates across aggregators do not suppress distinct projects; and errors remain visible in health.

Prefer batches of 3–5 sources. Measure eligible unique adverts gained, false positives, failed detail fetches and extraction cost. Only then activate the next batch and regenerate the public coverage count from the registry/runtime. RSS, structured ATS data and official HTML/PDF adverts are preferred where those mechanisms actually exist; no RSS endpoint was invented for pages that do not advertise one.
