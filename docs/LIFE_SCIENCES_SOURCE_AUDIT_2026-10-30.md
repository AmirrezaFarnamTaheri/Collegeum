# Life Sciences source-health validation — 30 October 2026

## Scope and evidence boundary

This document distinguishes the **registered / enabled** source count from
actual accessible, parseable vacancy listings. It reports read-only public
GitHub-runner observations; it does not validate all returned positions,
funding arrangements, PhD eligibility or closing dates.

The Life Sciences registry has 225 entries (36 enabled, 189 disabled after
the Copenhagen policy quarantine). The economics registry has 76 enabled
boards at the last observed production ingestion.

## Reproduced source-health defect and fix

The former `tools/probe_life_sciences_sources.py` always inspected
`urls[0]` even when a source had 2–4 distinct search queries, and its
single-source result was interpreted as the health of the entire source.

Regression run [40955464547](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40955464547)
reproduced four failures. After the correction, run
[40955886645](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40955886645)
passed the Python 3.11 and 3.12 full test/coverage, lint, type-check and
release-archive checks.

The revised probe:
- visits **all** configured query URLs (at most four per source);
- checks each URL through the same robots-aware `PoliteClient`;
- reports each endpoint's HTTP code, matching-link count and failure status;
- preserves a source-wide `ok` only if at least one search has real matching
  links and no endpoint had a fetch, robots, parser or unsupported-type error;
- reports `partial` for mixed access failures, `no_recognized_vacancy_links`
  when all queried pages lack recognized links, and `too_many_urls` rather
  than silently probing an incomplete set;
- deduplicates HTML vacancy URLs across query partitions. RSS counts remain
  entry counts, not cross-feed identity checks.

Live source acceptance run
[40956232626](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40956232626):

| Source / query | HTTP observation | Recognized links |
|---|---|---:|
| AcademicTransfer epigenomics: chromatin | 200 | 0 |
| AcademicTransfer epigenomics: epigenomics | 200 | 0 |
| AcademicTransfer epigenomics: psychiatric genetics | 200 | 1 |
| AcademicTransfer epigenomics: regulatory genomics | 200 | 0 |
| **AcademicTransfer source unique total** | 4 queries inspected | **1** |
| EURAXESS gene-regulation: four queries | 200 each | 10 per query |
| **EURAXESS source unique total** | 4 queries inspected | **10** |

The EURAXESS search URLs returned the same ten job links across four
query partitions. Those links are not forty vacancies. Their topic relevance
requires separate full-text checks; identical responses could indicate broad
queries or ineffective upstream search filters.

## Five problematic providers independently inspected

One-off read-only diagnostics on GitHub Actions:
[40955464775](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40955464775).

| Source | HTTP and first-page anchors | Diagnosis |
|---|---|---|
| Linköping University | 200, 89 anchors, 0 matching job links | Public HTML is a job-application shell; the official rendered page has listings, but source HTML does not |
| Swedish University of Agricultural Sciences (SLU) | 200, 39 anchors, 0 matching job links | Public HTML exposes generic navigation, not the vacancy records in a parser-readable form |
| University of Bern | 200, 51 anchors, 0 matching job links | Careers landing page embeds the Prospective recruitment application in an iframe |
| AcademicTransfer epigenomics | 200, 30 first-query anchors, 0 matches | Misdiagnosed as empty when only the first search was checked; another query did return a vacancy |
| IBEC Barcelona | 200, 204 anchors, 11 links matching its configured URL pattern | Previous transport failure was not reproduced; 11 links are candidates, not verified eligible PhDs |

**Do not** mark Linköping, SLU or Bern healthy solely because their pages
return HTTP 200. Proper allowed API/HTML vacancy adapters and job-identity
regressions are still required, or the sources should remain quarantined.
Do not bypass robots restrictions or count navigation and scripts as jobs.

## Economics production ingestion status

Fresh completed run [40953929832](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40953929832)
ingested 314 items, published 15, and classified 76 enabled boards:
66 successful, 7 empty, 2 failed and 1 skipped.
Its internal outcome was **partial** (despite a green GitHub Actions check).
The failed economics sources were CREST (HTTP 503) and Copenhagen.
Separately, the career-source Jobinja fetch was blocked by robots, and
non-JSON model responses required heuristic fallback. A green workflow
is not evidence of fully healthy ingestion.

## Acceptance remaining

1. Repair or disable the Linköping, SLU and Bern life-science
   adapters based on an accessible, officially permissible vacancy feed.
2. Validate the individual Life Sciences job details (required degree,
   geography, deadline, funding) rather than treating parser links as eligible.
3. Resolve CREST and Copenhagen economics failures without faking empty runs.
4. Verify downstream country and publication exports after the next completed
   ingestion on the final merged head.

The read-only diagnostic/acceptance workflows were deliberately temporary;
only the reusable probe code and regression tests are intended for production.
