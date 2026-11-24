# LinkedIn content and access review — 24 November 2026

The LinkedIn adapter now requires consistent job identity and a recognisable
advert description before supplying detail evidence. Malformed search cards
preserve the existing query cursor, and an access challenge stops queued detail
requests and records the shared provider cooldown. The optional generic JobSpy
collector no longer initiates LinkedIn requests.

This work uses local snapshots, synthetic response fixtures and current official
API documentation. It does not include a new LinkedIn job search, account login,
credential change, production dispatch, journal migration or notification send.

## Findings and resulting behaviour

| Finding | Change |
|---|---|
| A card could take its identity from an unrelated URL or disagreeing URN and link. | Validate the provider hostname and complete job path. When both the URN and link identify a job, they must agree. Regional LinkedIn links and actual relative job paths remain supported. |
| Dropping one invalid card could make a full search page appear short and complete. | Keep readable candidates in the replay buffer, retain the previous pagination offset and completion timestamp, and use the existing transient retry interval. |
| A missing description caused the entire response page to become advert evidence. | Require a primary advert description, exclude sidebars and related-job cards, and reject conflicting canonical or Open Graph job identities. Unknown response layouts remain unverified. |
| A retained job description could omit the separate closed-application banner. | Preserve an explicit primary-job closure marker alongside the advert description. Related-job closure markers do not affect the primary job. |
| An HTTP 200 sign-in/security challenge could be accepted as content, including when residual cards were present. | Recognise challenge structure, withhold its content, and apply the existing provider-wide cooldown. An HTTP 200 challenge remains recorded as HTTP 200 rather than a fabricated HTTP error status. |
| Concurrent detail requests could pass the cooldown check before the first request reported denial. | Serialize detail requests within the provider instance so waiting requests observe the earlier denial. Other providers remain independent. |
| `backend = "jobspy"` bypassed the board's checkpoint, cooldown and request policy. | Reject that unsupported backend explicitly before importing or calling the external library. Unknown backend names also fail with zero requests. |
| Enabling generic JobSpy started two separate LinkedIn searches and requested descriptions outside the governed adapter. | Retain the two existing Indeed searches and their original per-query result ceiling. Report LinkedIn as unsupported in this collector and direct configuration to the existing checkpointed boards. |

Stable job IDs and all matched search-query labels remain available for deduplication
and provenance. Equal job titles at one employer still do not establish identical
requisitions. No historical source IDs, application destinations, journal hashes
or delivery records are rewritten by these changes.

## Supported integration boundary

Both configured LinkedIn boards use the existing checkpointed `guest` backend.
Their configured search ceilings, portfolios, environment flags and credentials
are unchanged. Parser acceptance and cooldown expiry do not establish provider
permission or employer verification.

The 96-request economics and 24-request Life Sciences allowances are **search
budgets**. Detail enrichment has separate existing collector limits; this change
does not reinterpret those discovery allowances as a combined search/detail
budget. Configuration comments now describe that boundary explicitly.

The current official [Job Posting API overview](https://learn.microsoft.com/en-us/linkedin/talent/job-postings/api/overview)
describes a restricted partner integration for publishing jobs on customers'
behalf. It is not a documented open job-search replacement for this engine.
The [API operation documentation](https://learn.microsoft.com/en-us/linkedin/talent/job-postings/api/sync-job-postings)
likewise concerns creating, updating, renewing and closing postings. No read API
or access entitlement is invented from those publishing capabilities.
LinkedIn's [automation guidance](https://www.linkedin.com/help/linkedin/answer/a1341387/prohibited-software-and-extensions)
and [User Agreement](https://www.linkedin.com/legal/user-agreement) remain separate
provider constraints. Connected account access does not authorise broader
collection, and this change adds no login, cookie, proxy or identity-rotation path.

Ordinary LinkedIn feed posts remain outside the Jobs adapter. University and
employer sources continue to supply independent evidence for application
deadlines, admission scope and funding. A search card alone does not certify any
of those facts.

## Stored telemetry inspected

The committed public snapshot was generated at `2026-11-24T09:20:33Z`.
These are stored observations, not the result of a new live check.

| Observation | Economics | Life Sciences |
|---|---:|---:|
| Query identities in checkpoint | 313 | 93 |
| Queries with `complete` status | 39 | 15 |
| Queries with `pending` status | 264 | 77 |
| Saved replay candidates | 4 | 119 |

The economics source health at that snapshot is `skipped`, with provider
cooldown as the reason and its last recorded successful run on 16 November.
The academic public snapshot contains 211 rows, including 69 LinkedIn-origin
rows with 69 distinct LinkedIn job IDs; 53 of those rows have no deadline.
These counts do not establish current employer availability or completed search
coverage. Saved cards and registered queries are not fresh completed searches.

## Offline validation

The new content/access suite and generic JobSpy isolation test pass 44 cases.
The existing LinkedIn scheduler, shared cooldown, checkpoint discovery,
access-control, coverage, card-parser and integration regressions pass 116 cases:
**160 passing tests in the combined LinkedIn suite**. Targeted Ruff checks pass
for the LinkedIn implementation, the shared collector and new tests. Mypy reports
no issues in the three LinkedIn source modules.

Regressions cover conflicting card IDs, misleading hosts, nested card markup,
different jobs with the same title, retained query provenance, unrelated detail
text, mismatched canonical identities, primary versus related closure markers,
partial-card retry without cursor advancement, HTTP 200 challenges, 403/429/999
denials, concurrent queued details, cross-audience cooldown and unsupported
backends. Related-job exclusions also cover BEM class names such as
`similar-jobs__section`, without rejecting unrelated names such as
`base-cardinality`. No test performs live LinkedIn access.

```sh
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/boards/test_linkedin_*.py tests/integration/test_linkedin_*.py -q
```
