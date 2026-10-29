# Economics source-access quarantine — 30 October 2026

## Reason for change

The live production pipeline [run 40953929832](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40953929832)
completed with internal outcome `partial`, despite the GitHub workflow showing
success. Of 76 enabled sources, 66 succeeded, 7 were empty, 2 failed and 1
was skipped. **CREST and Copenhagen** were the two failed board adapters.

The CR​EST request returned HTTP 503 twice on the GitHub runner. The Copenhagen
economics source also failed discovery (its existing 60-second source timeout
had not produced a usable result).

## Official access checks

A bounded, credential-free, robots-aware diagnostic workflow inspected
exactly four official URLs, with no vacancy publication or Telegram access:

[Runner 40958027338](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40958027338)

| Endpoint | Result on runner | Meaning |
|---|---|---|
| `https://crest.science/opportunities-2/` | `999` | Access not permitted/confirmed by the polite client's robots policy |
| `https://www.ensae.fr/en/school/current-job-opportunities` | HTTP 200, 176 anchors | Official alternative *landing page* is reachable, but no verified CREST vacancy-specific replacement URLs in extracted links |
| `https://employment.ku.dk/all-vacancies/` | `999` | Robots policy check did not permit retrieval |
| `https://jobportal.ku.dk/` | `999` | Alternate Danish portal also not permissible via current polite client |

**A policy check returning `999` must not be bypassed or classified as a
healthy empty source.** It could reflect an explicit disallow or policy
unavailability. A separately reachable information page is not proof that
its job listings can be scraped or uniquely identified.

## Action

Temporarily set `enabled=false` on exactly two economics boards:
`crest_jobs` and `copenhagen`. Preserve their TOML definitions, expected
vacancy link patterns, historical job IDs, and prior Telegram/output state.
Keep the five approved first-wave boards and two wave-2 European boards
active. This corrects the configured economics registry from **78 enabled
to 76 enabled** (144 total; 68 disabled), without inventing successful
ingestion. It does not mean the 76 remaining sources are all healthy.

A pre-change regression tests this guard (expected RED on old configuration),
and a final-head run must prove registry and historical parser tests still
pass. Disabled-source membership is declared explicitly in
`tests/boards/test_official_sources.py`.

## Re-enable only when

1. The official operator's robots policy explicitly permits automated
   collection on a stable job-listing endpoint, or an approved official
   public feed/API is available.
2. A bounded read-only GitHub-runner probe returns actual job-specific
   unique IDs/URLs and confirms no fetch/parse/robots failures.
3. Semantic checks exclude faculty, unrelated disciplines, already closed
   jobs and required-PhD positions when classified as predoctoral.
4. A separate approved registry change activates the source, followed by
   production ingestion health verification.

No secrets, subscriber state, files containing existing publications or
historical delivery receipts were touched by the quarantine.
