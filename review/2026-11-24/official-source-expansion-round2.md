# Official university posting sources: second expansion, 24 November 2026

Four additional official university sources are enabled after permitted page captures, vacancy-identity checks and offline replay through the collector. The registry grows from **147 to 151 sources**, with **78 to 82 enabled**. The existing 69 disabled sources retain their previous settings.

The selected review cohort contains **60 research-role advert URLs**. **56 returned readable, identity-matched advert bodies** and **four timed out**. The complete collector replay produces **10 eligible candidates, 46 rejections and four deferred candidates**. These are collection and review outcomes; no production database ingestion, model extraction, publication or messaging occurred during this research pass.

The complete per-advert record is in [official-source-expansion-round2.json](official-source-expansion-round2.json). It contains actual source and capture URLs, timestamps, HTTP outcomes, content hashes, employer IDs where available, translation aliases, short evidence excerpts, deadlines, lifecycle flags and collection decisions.

## Sources and observed outcomes

| Official source | Research adverts selected | Readable bodies | Eligible | Rejected | Deferred |
| --- | ---: | ---: | ---: | ---: | ---: |
| [University of Vienna: predoc](https://jobs.univie.ac.at/go/Praedoc/8877001/) and [postdoc](https://jobs.univie.ac.at/go/Postdoc/8879501/) | 28 | 26 | 6 | 20 | 2 |
| [University of Amsterdam](https://werkenbij.uva.nl/en/vacancies) | 18 | 17 | 1 | 16 | 1 |
| [Maastricht University](https://vacancies.maastrichtuniversity.nl/go/All-jobs/8842002/) | 9 | 8 | 2 | 6 | 1 |
| [Utrecht University](https://www.uu.nl/en/organisation/working-at-utrecht-university/jobs) | 5 | 5 | 1 | 4 | 0 |
| **Total** | **60** | **56** | **10** | **46** | **4** |

The four timeout records remain unavailable. They do not count as readable bodies or confirmed detail evidence. Every readable body was reviewed, including research adverts that the production collector rejects before requesting details because the role or subject is outside its configured scope.

The 56 readable adverts include 55 with future full-year closing dates and one with an elapsed deadline. Subject and role rejection reasons remain recorded separately from the deadline lifecycle. An accessible page or a future deadline alone does not establish eligibility.

## What each adapter verifies

### University of Vienna

The public SuccessFactors tables expose separate predoc and postdoc categories. Discovery follows only observed pagination on those category paths, within the fixed request and card limits. The table's `Datum` column is a posting date and is never reused as an application deadline.

The source selects English research adverts. The captured indexes contain 44 language-specific research cards; the 28 English entries form the selected cohort. Fifteen German translations were linked to their English adverts through the same explicit employer **Job ID**. Those translations are recorded as aliases rather than additional reviewed positions. A further German capture timed out and is not assigned an invented alias.

Each accepted detail requires a matching canonical URL, the listing title in the official title metadata, the corresponding displayed title, an explicit employer Job ID and a complete application deadline. Two observed scientific-project title-order variants are recognized explicitly. Duties, qualifications and the reviewed research-context sections provide subject evidence; general university introductions and employee benefits do not.

The observed American date order is pinned to the English deadline field. A literal `mm/dd/yy` format hint is allowed only after an actual four-digit-year date. Yearless values, malformed dates, applicant-specific alternatives and conflicting repeated fields defer the candidate.

### University of Amsterdam

Discovery reads the official English vacancy cards and follows only same-origin numeric offsets. Job URLs end in stable numeric requisition IDs. General staff and faculty cards are excluded by the research-role gate.

The detail checks compare the canonical ID, repeated displayed requisition numbers, all main advert titles, the structured JobPosting title and the full-year closing date. Repeated responsive-layout sections must agree. Closing dates from recommended vacancies elsewhere on the page cannot change the current advert's deadline.

The reviewed variants of the duties and qualifications headings supply subject evidence. Employee benefits, faculty biographies and recommended jobs remain outside that field decision. The current eligible advert is the postdoctoral knowledge-security and geopolitical-context position, requisition **15624**.

### Maastricht University

The official SuccessFactors table explicitly labels its closing-date column. Discovery validates that column independently from other page dates and retains the stable requisition URL. The corresponding advert must have the same canonical identity and title.

Every explicit application or publication-end cutoff in the reviewed advert blocks must agree with the listing date. A second full date, yearless date, unknown cutoff or applicant-specific alternative cannot disappear behind the first valid date. Deadline labels outside the reviewed block layout also fail closed. The observed sentence explaining that a role may fill before its advertised deadline is handled as an early-filling notice, not as an additional cutoff declaration.

Subject checks use the verified role title and its duties or qualifications. Broad faculty labels are kept as metadata until the advert is verified. This matters for the health-economics postdoc: its medical-faculty affiliation must not cause the collector to reject the job before reading its explicit economics duties. The adapter preserves the shared relevance rules and does not let that faculty label establish relevance on its own.

The two eligible captures are the behavioral and sustainable finance postdoc (**1377839757**) and the health-economics/health-technology-assessment postdoc (**1375965757**).

### Utrecht University

The detail requires agreement among the canonical slug, visible title, JobPosting title, HireServe application identity and full-year closing date. The verified role title and the `Your job` and `Your qualities` sections supply subject evidence. A broad department/faculty label or the `About us` section cannot qualify an otherwise unknown role. Section boundaries include nested heading levels, so a biography does not become job evidence merely because its heading uses a different tag.

The transnational-retirement postdoc, HireServe **1362168-EN-970**, passes the current rules. The sociology research assistant and meta-science postdoc remain rejected for insufficient subject evidence under the existing long-text policy. Their faculty biographies are not added back to increase the eligible count.

## Fetch and eligibility boundaries

The new `official_university` scraper requires verified detail evidence before a candidate can be emitted. It uses the existing collector contract introduced for the earlier official-source expansion. Missing bodies, identity mismatches and incomplete date evidence defer the candidate; normal closed-page and expiry handling remains in force.

The adapter pins the four public origins and the permitted index paths. It accepts only bounded, observed pagination, with at most eight index pages and 250 cards. Detail requests are serialized per source. A 403, 429 or access interstitial during discovery or detail fetching stops subsequent detail requests for that provider during the run. Earlier discovered candidates remain available for a later permitted run.

All four entries use `field_implied = false`. A faculty or employer name never grants automatic subject relevance. Source-country defaults are explicitly marked `reviewed_source_profile`; they are not presented as independently confirmed job-location labels.

## Evidence and validation

The new advert captures were obtained on 24 November 2026 between **15:43 and 15:50 Tehran time** (12:13–12:20 UTC in the evidence records). The existing bounded official-source HTTPS reader checked robots permission before content requests, constrained redirects to the reviewed official host, and preserved the original response metadata. Identical captures and provider restrictions were cached. No failed URL was retried early.

This round's adapter validation uses those actual captured pages offline. It does not claim a successful live run through the pipeline's separate HTTP transport. Earlier same-session probes of that transport failed the public-DNS preflight before any request was sent; the destination guard remains unchanged.

Validation completed:

- **73 focused tests passed**, covering source discovery, bounded pagination, mandatory detail verification, identity and date disagreement, unrelated recommended vacancies, broad faculty/benefit text, country provenance and provider-denial propagation.
- **All 56 readable full captures passed the adapter's detail contract.** The full collector replay retained the existing role, subject, degree, age and expiry policies and produced the totals above.
- **Ruff and mypy passed** for the new module and the relevant edited tests.
- An independent reviewer replayed the reported Maastricht cutoff, Utrecht faculty-evidence and later-index access-refusal regressions successfully.

Fixtures preserve observed markup, factual identities and dates while using abbreviated, author-written representative prose. Capture provenance and regression cases live under `tests/fixtures/boards/official_university_20261124/` and `tests/boards/test_official_university_sources_20261124.py`. This fixture location is covered by the existing standalone distribution include rule.

## Candidates not enabled

**KU Leuven:** the official robots endpoint returned HTTP 503 during this pass. No vacancy body was requested, no source entry was enabled and no early retry was made.

**Tilburg University:** the captured official employer page links an interactive SuccessFactors application. The actual vacancy contract was not separately captured and validated in this round, so it was not added as an enabled source.

Previously restricted sources retain their existing policies. The additional four sources have actual permitted index and advert evidence rather than generic careers-page placeholders.
