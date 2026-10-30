# HKU official research-source activation — 30 October 2026

## Evidence and scope

HKU Careers provides actual public, employer-controlled application advertisements. One currently open economics-adjacent position is [Research Assistant I, requisition 537693](https://jobs.hku.hk/en/job/537693/research-assistant-i), advertised 21 October 2026 and closing 30 November 2026 (or when filled). Employer: **University of Hong Kong, Department of Real Estate and Construction**; location Hong Kong; full-time, temporary one-year appointment from January 2027. Research project concerns Indian city regulation, survey data, differences-in-differences and geospatial analysis. Degree: Bachelor's **plus at least two years of experience**, or Master's; **not** a blanket fresh-bachelor predoc. Application is via HKU's own job-specific link.

The official [HKU Careers search results](https://jobs.hku.hk/en/search/?search-keyword=research+assistant) include the same generic Research Assistant I title in unrelated medical departments (e.g. requisition 537670). The main index contains administrative staff from the Faculty of Business and Economics (e.g. requisition 537762). Thus filtering by job title or faculty name alone is unsafe.

## Implementation

Activate existing disabled `hku_econ_social_jobs` rather than creating a new source. Reuse the existing `link_scan` adapter, with an optional **vacancy-card-only** departmental content gate and narrow research-assistant title gate. The main HKU index is the existing source URL. Suppress unrelated medical and administrative adverts before they become posting candidates, and keep `field_implied=false` for the downstream field/degree/expiry checks. Preserve original candidate manifests as historical evidence; no publication or subscriber state changes.

## Acceptance

- Fixture regressions: accepted 537693; rejected medical 537670; rejected business faculty administration 537762; one job identity on duplicated HTML; invalid department regex fails closed.
- Full CI must pass across both supported Python versions, packaging and Telegram worker.
- **Runner acceptance remains required before merge:** a credential-free, read-only live collection must confirm HKU Careers' real HTML exposes an anchor and a containing row with the Department of Real Estate and Construction, and report no fetch or parser faults. The public web description is evidence of a live vacancy but is not proof of GitHub-runner parser success.
- Fresh production health must confirm enabled source counted as successful, not a false healthy-empty. Preserve canonical URLs and current publication deduplication.

## Additional candidates reviewed

Already activated: WIFO Austria, CEPS Brussels, NUS Singapore, Yale EGC, Wharton, Texas A&M, Brandeis, Urban Institute, shared regional Federal Reserve Workday.

Still candidate-only: IAB Germany, IFAU Sweden, LISER Luxembourg, ESRI Ireland, Bank of Finland, HKUST Singapore (SMU), ANU Australia, University of Sydney, Melbourne, Queensland, UNU-WIDER, SEO Amsterdam, UK CEPR, Brookings, Princeton RPDE, UCL Management, and IFS. The latter blocked sources are not safe to activate. Avoid new Yale Inclusion Economics feed overlapping Yale EGC.

Separate production problem: 2026-10-30 run 41009131022 reported one career-source error, Jobinja robots policy denied; academic board source errors were zero. Do not attribute the career error to academic sources or bypass robots policy.
