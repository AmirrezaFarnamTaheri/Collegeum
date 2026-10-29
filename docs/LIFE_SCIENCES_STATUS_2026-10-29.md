# Life Sciences PhD source and stored-output audit — 29 October 2026

## Evidence boundary

Examined committed `config/life_sciences.toml`, nine
`config/life_sciences_sources/*.toml` catalogues,
`data/career_jobs.ndjson`, `data/life_sources_rotation.json`,
`docs/data/health.json`, `docs/data/listings.json`, and the life
CSV exporter. **All counts below are a snapshot of committed data**, not
a fresh verification of live vacancy websites. No private subscriber
state or messages were inspected or changed.

## Source registry

| Catalogue | Enabled | Disabled |
|---|---:|---:|
| Core | 10 | 10 |
| Nordics | 9 | 10 |
| DACH | 3 | 17 |
| Benelux | 3 | 14 |
| France/Iberia | 4 | 14 |
| Central/South Europe | 0 | 18 |
| Aggregator topic shards | 8 | 0 |
| Eastern Europe/Balkans | 0 | 43 |
| Specialist institutes | 0 | 50 |
| Doctoral programmes | 0 | 12 |
| **Total** | **37** | **188** |

37 enabled entries need four complete successful discovery rotation slots
when each run admits at most 12 sources. Last-attempt timestamps are
recorded in `data/life_sources_rotation.json`, but **attempted is
not synonymous with healthy, parsed or productive**. An independent
life-sciences health matrix per provider is still required.

The manual `verify-life-sciences-sources` workflow checks bounded
landing pages; dispatch region=all, limit=16 at offsets 0, 16 and 32,
then reconcile results. The current probe checks only the first
configured URL per source. A successful first URL does not establish
all topical shards of an aggregator are accessible.

## Journal/output profile

- 63 stored career rows: **61 life_sciences_phd**, 2 other career jobs.
- All 61 PhD rows have distinct stored job keys and URLs.
- 6 marked `research_priority=focus`, 55 `related`.
- 61 of 61 have `funding_status=unverified` — do not imply full funding.
- All 61 legacy records lack the explicit `country` key. Most provide a
  country in `location`; the historical CSV exporter did not recover it.
  This PR persists the identified country for new rows and recovers a
  recognized country from legacy `location` for CSV, without guessing
  from institution or portal.
- 20 of 61 have `last_seen_at` more than seven days before
  **2026-10-29 20:00 UTC**. These are *stale observations*, not
  proof that a posting is expired or closed. `availability` is usually
  absent; recheck on the employer site before asserting availability.
- Stored positions are intentionally excluded from
  `docs/data/listings.json` (the public economics dashboard). The
  public dashboard held 179 other listings in this snapshot.

## Identified semantic risks

**High confidence / rule defect.** `life_max_planck` produced
“PhD Researcher (m/f/d): Economic Impacts from Complex Climate Risks”.
A title explicitly about economics was not excluded by the old
`economics` title pattern. General institutional boilerplate about
genomics or neurobiology could make it appear biological.
Regression: an economic PhD title with only unrelated background biology
is rejected; an actual molecular-biology PhD with a secondary economic
aspect is preserved.

**Manual review needed.** Inria's “High-dimensional data analysis ... survival
modelling in presence of competing risks” may be statistics applied to
medicine or pure mathematical research. Without a verified biological
research objective, do not mark it a confirmed life-sciences match.
Max Planck's “Community ecology, stone tool use and social behavior in
gracile capuchin monkeys” is also outside the stated molecular/genomic
research priorities unless its specific scientific scope justifies inclusion.

**Export/schema defect.** A valid country is determined during
`classify_post` but was discarded before journal persistence.
The historical CSV therefore had a blank country for stored entries.
This PR adds a backward-compatible export fallback and unit regression
without changing Telegram state or retroactively modifying journal keys.

## Overall pipeline is separate

`docs/data/health.json` at 2026-10-29T15:20:52Z says `degraded`.
The most recent recorded run (40898829634) has:
59 successful, 7 empty, 2 failed, 1 skipped of 69 attempted sources;
`board:copenhagen` timed out, `board:crest_jobs` got HTTP 503, and
`board:european_job_market` was skipped.
These are **economics/source pipeline metrics**, not a 37-source
life-sciences health report. The field `last_successful_run_at`
was still 2026-10-20T19:59:23Z, so an Actions success cannot be
reported as an end-to-end source-health success.

## Acceptance before promoting further Life Sciences sources

- Run three bounded GitHub-runner verification batches (0,16,32), and
  preserve artifacts with checked count, robots policy, status, and URLs.
- Verify each provider's actual doctoral advert link pattern, workplace,
  recent deadline, degree requirement and biological research goal.
- Reconcile journal records that were false-positive or stale using
  dedicated audited cleanup; do not silently rewrite published receipts
  or trigger notifications.
- Add explicit per-source `last_success_at`, empty-vs-failure,
  candidates, accepted, detail errors and stale-state diagnostics.
- Introduce a separate fresh-export quality gate covering country
  completeness, stable URL identity, category, explicit funding uncertainty,
  and records excluded by the biological-field policy.

No source was enabled or automatically republished as a result of this audit.
