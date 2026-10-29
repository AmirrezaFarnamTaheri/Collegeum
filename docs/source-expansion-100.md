# Guarded expansion toward 100 official sources (2026-10-29)

The candidate CSV is `config/source_expansion_20261029.csv`. The registry
contains 30 additional **disabled** `[[board]]` sections (19 Workday, 11 link scans). A separate non-US review cohort in `config/non_us_sources_20261029.csv` adds 21 more disabled official career leads. This makes **51 total new candidates**; none is activated.
Evidence links are *historical candidate leads*, not verified current vacancies.

At inspection, `main` had **71 enabled boards**, 22 disabled boards and
three disabled feed/portal records. Enabling 29 distinct, healthy candidate
boards would yield 100 enabled boards. It would **not** prove 100 healthy boards.

## Probe safely

1. Run the permanent manual Actions workflow `verify-source-expansion-20261029`.
   Choose each cohort (`initial` and `non-us`) and offsets **0, 10, 20**
   (six bounded runs in total), then reconcile all **51 candidates** from JSON
   artifacts. The temporary six-matrix branch acceptance already completed
   successfully on run 40921413336; its artifacts remain available even
   though the branch-only workflow was removed from the production diff.
   Do not count missing or partial reports as passes. The probe checks robots
   policy before requesting source listings or Workday APIs.
   `parser_not_configured` and `blocked_by_robots_or_unknown` are
   blockers, **not** healthy empty periods.
2. Check discovery success, unique vacancy-specific HTTPS URLs, pagination
   completeness, stable vacancy IDs, valid descriptions, field relevance, no
   false empty reports, and any robot/HTTP errors. Results labelled
   `needs_eligibility_review` are **not** activation approvals.
3. Review each actual posting for employer, subject, degree requirements,
   PhD-student versus predoc distinction, FWS/student-only restriction,
   seniority, part-time/temporary restrictions, country and application URL.
4. Review overlapping existing sources (especially regional Federal Reserve
   pages and Yale/Oxford/other university aggregators). Deduplicate by
   canonical posting identity, not merely name or title.
5. Do not activate country-scoped pages merely because the institution is authentic: 16 of the 21 new non-US leads still require verified direct-job link patterns. Only enable an accepted subset in a later, reviewed PR, with a dated
   evidence matrix and regression tests. Run full CI and fresh production
   discovery, then count enabled **and** healthy sources separately.

## Known high-risk leads

- `new_school_social_research`: supplied example is explicitly FWS; it
  cannot establish eligibility for non-student applicants.
- `ohio_state_research`: evidence points to a medical center, not economics.
- `unlv_economics_jobs`: evidence is an assistant/associate professorship.
- `colorado_state_policy`: evidence is an open pool for human development
  and family studies; not a specific eligible economic research opening.
- `rand_research_jobs`: evidence is a corporate PDF, not a live requisition.
- `gwu_policy_staff`, `cepr_uk_internal_jobs`, and several others:
  directories, not verified individual vacancies.
- `federal_reserve_system_jobs`: a single Workday site can contain
  vacancies across Reserve Banks; institution defaults and cross-source
  duplicate handling need verification.

**Safety:** Do not automatically enable candidates merely because a Workday
API returns HTTP 200 or nonzero rows. Full university-wide ATS results
include unrelated fields. The filter may retain PhD student positions because
the current preferences explicitly set `exclude_phd_positions = false`;
do not equate generic pipeline acceptance with *predoc* eligibility.

See `docs/LIFE_SCIENCES_STATUS_2026-10-29.md` for the independent European life-sciences source/output audit (37 enabled sources, 188 disabled candidates, 61 stored PhD entries and known quality risks).
