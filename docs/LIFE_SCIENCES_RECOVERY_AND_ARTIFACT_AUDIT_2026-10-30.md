# Life Sciences PhD — source recovery and output-quality audit
**30 October 2026 · Independent private Telegram category · evidence-based snapshot**

## What is counted and what is not

The registry contains **225 unique source definitions: 36 enabled, 189
candidate-only** on production main. Sources are checked in an oldest-attempt
first rotation, with a maximum of 12 sources per scheduled run; 36 enabled
sources require three successful rounds to attempt all sources. A source
attempt is not proof of its health. Candidate-only programmes and institutes
are not contacted.

The committed `data/career_jobs.ndjson` contains **62**
`life_sciences_phd` records. The pre-existing explicit-title quarantine
suppresses one Max Planck economics/climate item from exports without
modifying its journal or historic delivery receipts. Consequently, a normal
title-filtered export should contain **61** eligible-for-review rows before
any additional collection, not 62 independently verified currently open
jobs. All 62 saved job records have unverified availability and funding.
**51 of 62** lack an explicit country field in the *journal* (the CSV exporter
can recover some from their original location strings).

The corpus has **6 focus** and **56 related** priority labels. These are
classifier scores, not verified PhD funding, employer acceptance or live
application status.

## Recovery evidence and defects

| Provider | Status and evidence | Outcome |
| --- | --- | --- |
| Linköping University | Official ReachMee tenant `I011/853`, runner 40962362857 found 9 uniquely identified doctoral candidates | Recovered in merged PR #68; 9 candidates, not 9 qualified life-science PhDs |
| Swedish University of Agricultural Sciences (SLU) | ReachMee tenant `I017/1114`, same runner found 6 doctoral candidates | Recovered in PR #68; subject/degree checks still apply |
| University of Bern | Existing institute landing is an iframe/JS shell; zero raw job anchors in runner 40955464775 | **Unresolved.** Individual official biomedical ads exist, but a supported listing feed is not verified |
| AcademicTransfer epigenomics | Four distinct topic URLs required; earlier first-URL-only probe falsely reported empty. Runner 40956232626 found one job via third query | Probe repaired; no new source activation needed |
| IBEC Barcelona | One-off transport error was not reproduced; 11 official job-link candidates on HTML in runner 40955464775 | Keep enabled but never equate all links with eligible open PhDs |
| University of Copenhagen | Explicit robots denial (HTTP 999) on runner | Disabled, do not bypass policy |
| DKFZ | Official d.vinci detail URLs exist; the original `/en/jobs/iframe` source was candidate-only. A new `/en/jobs` test returned HTTP 200 but zero parsed doctoral links on runner 41049902554 | **Not yet verified**. Do not count the proposal in PR #70 as production-ready without a compatible public listing adapter and closing-date extraction |

For DKFZ, the 2026-0194 bioinformatics PhD advert had an October 29,
2026 deadline. A historical posting persisting in an index is **not** a
current opportunity. A source-scoped `require_deadline` contract ensures
that missing expiry evidence cannot become an eligible alert.

## Artifact defects and repairs proposed by PR #70

1. **No per-source production truth:** before the PR, a rotation journal
   recorded attempts, not success, failed detail fetches, parsed doctoral
   count, field-eligible count or a proved empty state. A separate
   `data/life_sources_health.json` now tracks observed statuses with timestamps,
   retains the last checked state for sources not polled during the current
   rotation, and distinguishes discovered/verified-empty/unverified-empty/
   partial/failed/skipped. It contains no subscriber information.
2. **Unclear export evidence:** the CSV was already escaping formulas and
   recovering explicit countries from location. Its new sidecar quality
   metrics distinguish known/derived/missing countries, availability,
   stale observations, unverified funding, and duplicate application URLs.
   Missing availability is displayed as `unknown`, not blank or `active`.
3. **Stale doctoral recruitment calls:** annual programme and seasonal calls
   require a known, unexpired deadline; missing closing dates cannot imply
   an open application period. Older stored rows remain preserved pending
   independent revalidation.
4. **PhD-required false positives:** adverts specifying that the applicant
   must already hold a completed PhD are rejected, despite a misleading
   title containing 'PhD', while the ordinary master's-to-doctorate
   pathway remains eligible.
5. **High-volume collector constraints:** maintain maximum 12 selected
   sources per run, per-source and global detail-fetch budgets, and
   interleaved result ordering. The new health monitor is an additive
   reporting channel, not a substitute for submission-eligibility checks.

## Expansion priorities

**First repair functioning feed adapters**, rather than counting generic
homepages. Prioritize the University of Bern's official Prospective
recruitment interface, dynamic university ATS feeds, and current sources
with 200 responses but zero job anchors.

**Next validate high-value institutes** already registered disabled, including
DKFZ, EMBL, ETH BSSE, Vienna BioCenter, Max Delbrück Center, neuroscience
institutes and molecular-genomics centres. A current individual vacancy,
unambiguous department/workplace, accurate source host, degree requirement,
deadline and authorized read-only runner response are mandatory before
activation.

**Finally validate cohort programmes** (EMBL, FMI, ISTA, IMPRS, Life Science
Zurich and relevant doctoral schools). These require call-specific opening/
closing periods; a programme description is not itself an active vacancy.

## Unfinished acceptance gates

- Green Python 3.11/3.12 CI, lint, types, integration checks and release audit.
- Live source adapter acceptance for DKFZ or keep it disabled.
- Fresh production `life_sources_health.json` after an actual 12-source
  opt-in ingestion and three rotations.
- Export sidecar independent review of dated job records before claiming
  open, fully funded, geographically eligible positions.
- No change to subscriber opt-ins, Telegram receipts, economics outputs,
  or historical journal identities.

The production source and publication numbers are unchanged until merge
and runner/ingestion confirmation.
