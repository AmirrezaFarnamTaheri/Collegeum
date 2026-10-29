# Recovering Linköping and SLU doctoral vacancy discovery

Date: 2026-10-30. Scope: exactly two **already enabled** European life-sciences
sources. No change to the number of enabled sources (36 enabled; 189 disabled).

## Observed root causes

The original Linköping `liu.se/en/work-at-liu/vacancies` page and SLU
`slu.se/en/about-slu/work-at-slu/jobs-and-vacancies` landing page responded
HTTP 200 but contained **no** vacancy-specific anchors matching their declared
institution-page patterns. Therefore the two enabled adapters were effectively
reporting empty despite available official doctoral listings. Previous
[bounded source-shape check](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40955464775)
reported 0 recognized links on both.

These institutions publish job tables through ReachMee, a public recruitment
platform linked from the official institutions' sites. This is not an attempt
to bypass a login, a blocked robots policy or private account data.

## Independent public access verification

Read-only robots-aware probe
[40961785241](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40961785241):

| Source | Official ReachMee tenant | HTTP | Listing anchors found |
|---|---|---:|---:|
| Linköping University | `I011/853` (English site 7) | 200 | 22 job-specific records |
| Swedish University of Agricultural Sciences (SLU) | `I017/1114` (English site 7) | 200 | 16 job-specific records |
| University of Bern (separate investigation only) | Prospective `1001892` | 200 | **0** in raw HTML; JS shell |

After replacing the first two listing URLs and using narrow tenant-scoped
`job_id` patterns, actual `LinkScanScraper.run()` acceptance on the live
public HTML returned
[run 40962362857](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40962362857):

| Source | PhD-title filtered records | Distinct URL IDs |
|---|---:|---:|
| Linköping | 9 | 9 |
| SLU | 6 | 6 |

The 15 URLs are **doctoral postings, not 15 automatically eligible life-sciences
positions**. Linköping includes materials science, engineering and
business-development PhDs, and SLU includes forestry and landscape governance
positions. Full-text relevance and eligibility checks remain mandatory before
any feed publication or Telegram dispatch. Original postdocs and senior
recruitment must not leak into the PhD category.

## Implementation safety

- Only `life_nordic_linkoping` and `life_nordic_slu` are retargeted.
- Tenant IDs `I011/853` and `I017/1114` are part of the job identity
  matching rule; links from other universities cannot cross-match.
- `title_allow_pattern` only admits PhD/Doctoral/Doktorand-style job titles,
  ahead of downstream full-text field and geography checks.
- The sources remain `enabled=true`; their min-interval, country,
  institution and source names are unchanged.
- The parser canonicalizes URL query parameter order; tests compare
  `canonical_url()`, not raw query string ordering.
- No journal, user, subscription, Telegram, or publication output was edited.
- ReachMee validator parameters are currently part of public URLs. If they
  change, the configured source may return zero links; verify via the
  read-only source-health probe and update only from fresh official evidence.
- The Bern Prospective endpoint is a JS bootstrap with no public vacancy
  anchors visible in raw HTML. It remains **unresolved**, not silently
  marked recovered.

## Regression and acceptance

- [RED CI 40961970284](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40961970284)
  reproduced failures against old institutional listing URLs and patterns.
- Added tenant-specific URL/identity fixtures, cross-source exclusion,
  and same-tenant postdoc rejection tests. Existing regional fixture URLs
  updated to actual employer-linked current ReachMee vacancy identities.
- [Live acceptance 40962362857](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40962362857)
  confirmed 9+6 unique doctoral candidates with 200 status on permitted pages.
- Final-head Python3.11/3.12 CI and next scheduled life-sciences ingestion
  remain independent gates; new journal additions cannot be presumed from
  link counts.

Temporary source-verification workflows are removed from the final tree.
