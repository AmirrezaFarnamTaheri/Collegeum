# Official source expansion — 10 October 2026

Three sources are integrated and enabled locally; one further source is staged
and disabled. All four endpoints were absent from the existing registry. Names
remain unique across board/feed/portal entries. Existing adapters and filtering
policy are retained; no new API, credentials or browser runtime is required for
the enabled additions.

| Source | Discovery through production adapter | Detail evidence | Decision |
|---|---|---|---|
| [Nuffield College](https://www.nuffield.ox.ac.uk/the-college/jobs-and-vacancies/) | 1 vacancy card, title and 18 October 2026 deadline preserved; menu duplicate excluded | Official HTML advert returns substantive text (6,957 characters) | Enabled. Current research-engineer role fails the configured role gate; monitor future supported research posts. |
| [CREST](https://crest.science/opportunities-2/) | 3 official PDF adverts inside the recruitment tab; placement biographies, research papers and contact links excluded | Representative postdoc PDF extracts 4,275 text characters | Enabled. No economics default across the centre; field/category policy still applies. |
| [ESSEC Business School](https://job.essec.edu/jobs) | 14 server-rendered Teamtailor cards with distinct vacancy IDs | Representative administrative advert extracts 2,729 text characters | Enabled. Current titles fail role filtering. No headquarters country or blanket field default; infer each workplace from its advert. |
| [NHH](https://www.nhh.no/om-nhh/ledige-stillinger/) | 2 official Jobbnorge vacancy links; repeated title/read-more links collapse | Representative Jobbnorge detail returns only 9 characters: `Laster...` | Disabled. Validate structured detail or official PDF access before enabling. |

The production collection for the enabled additions discovered 18 adverts,
rejected 17 for `no-role-term`, and emitted one candidate for downstream
extraction. **No confirmed eligible listing or publication gain is claimed.**
Sparse monitors can still add future coverage; current research-engineer, lab
manager, administrative and senior faculty roles must not be relabelled as
predocs merely to increase yield.

## Selection and boundaries

- Nuffield uses vacancy cards rather than the broad university index or its
  navigation menu. Deadline/title fields use separate selectors.
- CREST scans only official uploaded PDF links in its job-opening tab, rather
  than arbitrary outbound links on the placement page. This deliberately does
  not discover all hypothetical future external ATS links; inspect the source
  contract if the recruitment format changes.
- ESSEC uses job cards only. No pagination links were present in the current
  14-card HTML response; this is not proof of future pagination coverage.
- NHH's index could be monitored, but the current detail contract is inadequate
  for vacancy extraction. It remains staged rather than counted as healthy
  enabled coverage.
- All sources permit seasonal emptiness. HTTP errors still produce failed
  discovery; tests verify they do not become successful empty results. A future
  HTML-layout change still requires operational investigation.
- Kellogg's official research-fellowship table currently says there are no
  openings. It is not activated using guessed future application-row markup.
- BSE was readable through web research but failed the local production HTTP
  attempt; no source was activated on web-search reachability alone.
- LBS and Stanford programme/cohort pages still need dedicated inline/project
  identity handling; the older researched backlog remains separate from the
  enabled registry.

## Reproducible evidence

- [source-discovery.json](source-discovery.json): discovery-only adapter results
  for all four sources, including manually probed disabled NHH.
- [source-details.json](source-details.json): representative detail extraction
  result, final URL, text length and short sample for each source.
- [source-collection.json](source-collection.json): production collection/gating
  metrics for the three enabled additions.
- `tests/boards/test_source_expansion.py`: real registry settings against reduced
  captured HTML, identity checks, title/deadline preservation, negative placement
  controls, existing role/field policy and explicit HTTP-failure tests.
- `tests/fixtures/boards/source_expansion/`: captured vacancy markup dated
  10 October 2026 with image assets removed; fixtures do not perform network
  requests or depend on a continuing vacancy.

Registry totals: 78 boards / 71 enabled / 7 disabled. The two feed and one portal
templates remain disabled. The increase is three enabled monitors, not four
currently healthy sources or four currently open relevant vacancies. No public
headline count, stored listings, personal state or remote deployment was changed.
