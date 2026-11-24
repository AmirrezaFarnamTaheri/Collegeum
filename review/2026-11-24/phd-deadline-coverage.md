# Economics PhD deadline coverage — 24 November 2026

## Result

The current official-source observation catalogue contains **56 confirmed deadlines out of 251 programmes**. The starting repository (`0a6a22a42314d516c775de17f6dfd6521d22780b`) already contained 41 confirmations; the user-facing snapshot quoted 39. This change adds 15 current confirmations through live robots-aware official-source checks. It does not assert that all 251 programmes have a dated application deadline.

Every programme is accounted for in the [complete source review](phd-deadline-source-review.json): 210 previously unconfirmed programmes received source research, and the 41 original confirmations received stored-evidence checks. Research notes and search discoveries are explicitly separate from automated corroboration. No candidate date is copied into the live catalogue by hand.

The [generated coverage audit](../../docs/data/phd_admissions_coverage.json) records the status, reason, official URLs, evidence, check time and next action for every programme. It is refreshed by the admissions workflow and downloadable from the dashboard.

## Newly corroborated deadlines

Each entry below passed the live collector. The linked page, original evidence excerpt, UTC check time and visited official sources remain in `docs/data/phd_admissions.json`. Calendar dates are the university-published closing dates; local closing times and applicant conditions remain governed by the university.

| Programme | Official deadline | Official evidence |
|---|---|---|
| HKUST | 2026-12-01 | [University source](https://prog-crs.hkust.edu.hk/pgprog/2027-28/mphil-phd-econ) |
| University of Pennsylvania | 2026-12-08 | [University source](https://economics.sas.upenn.edu/graduate/prospective-students/application-guidelines) |
| Carnegie Mellon University | 2026-12-15 | [University source](https://www.cmu.edu/tepper/programs/phd/admissions) |
| Keio University | 2026-12-24 | [University source](https://www.keio.ac.jp/en/admissions/grad/doctoral/gsecon/) |
| Central European University | 2027-01-15 | [University source](https://www.ceu.edu/admissions/doctoral#doctoral-degree-deadlines) |
| DIW Berlin | 2027-01-15 | [University source](https://www.diw.de/de/diw_01.c.799242.de/application.html) |
| NHH Norwegian School of Economics | 2027-01-15 | [University source](https://www.nhh.no/en/study-programmes/phd-programme-at-nhh/vacant-phd-positions/) |
| University of Notre Dame | 2027-01-15 | [University source](https://economics.nd.edu/graduate/admissions-and-funding/) |
| McMaster University | 2027-01-31 | [University source](https://applygrad.mcmaster.ca/portal/start_your_app?cmd=get_results&selectedterm=sept) |
| Stockholm University | 2027-01-31 | [University source](https://www.su.se/english/divisions/department-of-economics/education/courses-and-programmes/applying-to-the-phd-programme-in-economics) |
| University of Montreal | 2027-02-01 | [University source](https://admission.umontreal.ca/programmes/doctorat-en-sciences-economiques/) |
| Kyoto University | 2027-03-11 | [University source](https://www.econ.kyoto-u.ac.jp/kueac/application/doctoral/) |
| University of Cologne | 2027-03-15 | [University source](https://cgs.uni-koeln.de/en/economics/phd-programme/application) |
| Trinity College Dublin | 2027-03-31 | [University source](https://www.tcd.ie/economics/programmes/postgraduate/phd-in-economics-/admission-requirements/) |
| University of Edinburgh | 2027-08-01 | [University source](https://study.ed.ac.uk/programmes/postgraduate-research/278-economics) |

## Remaining automated results

| Result | Programmes | Meaning |
|---|---:|---|
| `fetch_failed` | 31 | A current official-source request did not succeed. |
| `no_explicit_deadline` | 100 | The permitted investigation did not establish one current, unambiguous application cutoff. |
| `robots_disallowed` | 1 | The published robots policy prohibits the request. |
| `robots_unavailable` | 62 | Robots instructions were not obtainable; permission is not assumed. |
| `unsafe_redirect` | 1 | The source redirects outside the allowed institutional route. |
| `verified` | 56 | Current full-year deadline and official provenance are supported. |

These are collector outcomes, not interchangeable claims about a university. The source-review file provides the institution-specific explanation: yearless dates, unpublished cycles, multiple applicant deadlines, rolling admission, supporting-document or funding dates, programme-identity questions, and inaccessible pages.

Washington University in St. Louis had a supported date in an earlier research capture, but the final live check of its repaired official source failed. It remains unconfirmed. York also failed its final live check; its earlier readable page additionally had different domestic and international cutoffs. Tohoku's doctoral timetable also passes the new scoped parser, with its mandatory preliminary stage retained, but the final live check could not obtain robots instructions. Neither a parser test nor an earlier candidate was used to override any current failure.

## Why 251 dated confirmations cannot honestly be promised

- [ETH Zurich](https://ethz.ch/applications/teaching/en/applications/eapply/programmetype.html) explicitly distinguishes doctoral registration, which has no general deadline, from programmes with fixed application windows.
- [University of Otago](https://www.otago.ac.nz/study/enrolment/enrolment-deadlines) says doctoral applications have no specific due dates. A made-up annual cutoff would misrepresent that policy.
- [UC Merced](https://graduatedivision.ucmerced.edu/prospective-students/application-dates) says Economics is not accepting Fall 2027 applications and points applicants to the anticipated Fall 2028 cycle. Other programmes' dates on the same page cannot fill that gap.

These official sources demonstrate a substantive limit in the requested metric. A complete programme inventory can include corroborated rolling admission, a closed intake or an unpublished next cycle; those are not dated deadlines. The present change retains the existing strict deadline definition and records the unresolved work explicitly.

## Implementation and safeguards

- Added narrowly scoped institutional parsers for explicit doctoral sections, admission tables and application ranges. They bind deadlines to Economics doctoral scope and the application role; no calendar cutoff is embedded in code.
- Added complete French date parsing and supported parenthesized weekday/time formats while retaining the printed year. Yearless closing dates and ambiguous numeric month/day ordering remain unconfirmed.
- Required domestic/international and full-time/part-time groups to agree before exposing a single deadline. Additional incomplete dates, duplicated conflicting sections, invalid ranges and unknown applicant qualifiers fail closed.
- Repaired ten official source URLs. Each repair first invalidated the old observation and required a fresh robots-aware check of the new URL. Restricted or failed original sources were not retried ahead of their existing cooldown.
- Fixed the dashboard's date-format check and centralized the confirmation gate used by the count, filter and cards. It verifies calendar validity, a supported future date, timestamp validity, freshness, matching HTTPS provenance, an investigated source and the actual date in the evidence excerpt. Confirmed cards display the excerpt so applicable groups and mandatory preliminary stages remain visible.
- Added an offline audit of all 251 rows, a public JSON export, automatic refresh integration and Pages asset staging. The audit never fetches a source or promotes research notes.

## Validation

Validation on the final change: 455 standard-library core tests pass; the full suite passes 2,807 tests and 708 subtests, with eight unrelated browser-layout tests skipped because Playwright is unavailable. Ruff passes across `src`, `tests` and `tools`; mypy passes for all 90 source files. Catalogue/provenance validation and cross-checks between all 251 review, audit and observation records pass. The regression tests cover positive official layouts and failures involving programme scope, funding dates, applicant groups, multiple sections, missing years, calendar validity, stale observations and forged provenance. Dashboard behaviour runs against the real extracted JavaScript and the committed catalogue.

The standard publication integrity audit has no errors. Its four historical warnings concern older employment-listing records, outside this admissions change.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/core -t . -q
PYTHONPATH=src .venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check src tests tools
PYTHONPATH=src .venv/bin/mypy src
python3 -S tools/update_phd_admissions.py --check
python3 -S tools/audit_phd_admissions.py --json
python3 -S tools/audit_publications.py --strict
```

`audit_phd_admissions.py --require-all-verified` intentionally returns exit status 1 for this catalogue: the audit must not report complete dated coverage while unresolved programmes remain.

## Continuing coverage

The existing schedule checks eligible official sources in bounded batches. Fresh confirmations expire after 14 days or when their deadline passes. Previously readable misses can be reconsidered when the extractor improves; failed or restricted sources retain their normal retry cadence.

Further confirmed dates require newly published official calls, correctly scoped alternative university sources, or explicitly modelled intake/applicant-specific dates. Rolling admission and closed intakes should be represented as their own corroborated facts if the product later expands beyond a single dated-deadline metric.
