# Source activation wave 1 — 29 October 2026

## Operational contract

The PR proposes to promote **5 distinct, independently evidenced** sources
from the previously disabled registry. Enabled economics-board count moves
**71 -> 76** after merge. This is *not* a claim of 76 healthy feeds; a
production collector run, job-level eligibility checking, and fresh source
health still need confirmation.

The evidence registry `config/approved_research_sources_wave1_20261029.csv`
stores source identity, official job-specific evidence, and exclusion risks.
Original candidate manifests remain historical evidence of the disabled
research phase (`enabled=false` in the CSVs is *not* the live TOML state).

All promoted sources have `field_implied=false` and an explicitly narrow
`title_allow_pattern`. The general economics/degree/expiry/detail checks
still apply. Broad academic/admin career portals must **not** be treated as
automatically eligible predoc sources.

| Source | Country | Current employer-specific eligibility evidence | Restriction |
|---|---|---|---|
| `tamu_public_policy` | US | Predoctoral Research Assistant (Finance, economics/tax policy) | Exact predoc research-assistant title; no postdocs |
| `brandeis_business_econ` | US | Temporary School of Business and Economics RA, req. R0013392 | Econ business RA only; **10 weeks, 20h/wk** |
| `urban_institute_policy` | US | Quantitative Health/Income/Benefits Policy RA, req. R-801655 | Quantitative RA; require full-text field evidence |
| `federal_reserve_system_jobs` | US | Philadelphia and Chicago economics-department RA roles | Research-assistant titles only; overlapping Fed URLs dedup |
| `nus_policy_research` | Singapore | NUS IPS Policy Lab RA, BA in economics/business | Selected policy/social-lab RA titles only |

## Evidence and limitations

Initial 51-candidate robots-aware runner inspection:
https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40921413336 .
Do not confuse `needs_eligibility_review` with applicant eligibility.
Job-specific official evidence is in the CSV; every role still needs
location, degree, freshness, application, and source-identity checks.

**Important exclusions:** `yale_inclusion_economics` stays disabled:
the same current predoctoral economics fellowships are present on the
already-enabled `yale_egc_jobs` board. Enabling a second Yale crawler
would inflate the source count and risk duplicate alerts.
`hku_econ_social_jobs` stays disabled until the general university ATS
can distinguish economics RA requisitions from unrelated laboratory jobs.
NUS non-US coverage is new, but the indexed policy role may have
qualitative and administrative work; do not mislabel it as a strictly
quantitative economics predoc.

The university-wide Workday search endpoints have cross-field search
noise. Source-scoped title filtering occurs immediately after parsing
and **before** deduplication and downstream econometrics verification.
An absent rule preserves legacy behavior, and an invalid regular expression
fails closed. When a source legitimately has no eligible titles, empty
results are not positive evidence of open positions.

## Post-merge verification

1. Require full CI green on Python 3.11/3.12, gating, lint, type checks,
   packaging and Telegram-worker tests.
2. Check the new head's read-only source probe evidence and ensure
   all five have at least one identifiable current vacancy, with no
   robots/pagination/schema violations.
3. After merge, verify main's TOML registry enables exactly these five
   new candidates and the retained other 46 remain disabled.
4. Observe the next **completed** main `predoc-pipeline` ingestion health.
   Confirm the five sources are successful or legitimately empty, and
   that none added faculty, administrative, unrelated medical, or
   postdoctoral false predocs.
5. Investigate any new duplicates from overlapping Federal Reserve
   portals by canonical requisition identity; do not resend prior alerts.

No subscriber state, encrypted feedback, or Telegram sent-intent journal
should be changed in this PR.
