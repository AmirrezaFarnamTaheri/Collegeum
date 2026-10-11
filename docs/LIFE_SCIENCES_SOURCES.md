# Life Sciences PhD — European source catalogue

This independent, opt-in Telegram discovery track must not change economics
preferences, public academic filters or unrelated career alerts.

## Coverage (11 October 2026)

| Group | Enabled | Candidate (disabled) | Examples |
| --- | ---: | ---: | --- |
| Core | 10 | 10 | EURAXESS, AcademicTransfer, Max Planck, Karolinska, Uppsala, Copenhagen, VIB, EPFL, CRG and Vienna |
| Nordic universities | 9 | 10 | Lund, Umeå, Gothenburg, Aalto, Stockholm, KTH, Linköping, SLU and University of Helsinki |
| DACH | 3 | 17 | University of Basel, Biozentrum Basel and University of Bern |
| Benelux | 3 | 14 | Utrecht University, Radboud and Ghent |
| France and Iberia | 4 | 14 | Inria, IBEC, IRB Barcelona and CNRS doctoral calls |
| Central/South Europe | 0 | 18 | Existing Italian, Irish, Polish and Czech leads |
| Aggregator topic shards | 8 | 0 | 5 EURAXESS and 3 AcademicTransfer independently rotated subject groups |
| Eastern Europe and Balkans | 0 | 43 | Baltic/Balkan institutions, Poland, Hungary, Czechia, Slovakia, Romania and Greece |
| Specialist research institutes | 0 | 50 | European molecular biology, neuroscience, genomics and medical research centres |
| Doctoral programmes | 0 | 12 | Cohort-based programmes requiring explicit opening and deadline checks |
| **Total** | **37** | **188** | **225 unique catalogue entries** |

**Enabled does not mean end-to-end collection has been verified.** Enabled
feeds have a supported listing format and sample vacancy link shape, but
remote markup, robots.txt, access restrictions and vacancy availability may
change. The 188 candidate sources have `enabled=false`, `link_pattern='^$'`
and are **never automatically fetched or delivered**. Their institution
homepages are deliberately not presented as functioning job scrapers.

Core entries remain in `config/life_sciences.toml`. Nine regional/topic
catalogues are stored in `config/life_sciences_sources/`: `nordics.toml`,
`dach.toml`, `benelux.toml`, `france_iberia.toml`, `central_south.toml`,
`aggregator_topics.toml`, `eastern_balkans.toml`,
`specialist_institutes.toml`, and `doctoral_programmes.toml`.
The source loader enforces stable, unique identities and a bounded catalogue.

### Priority institutions

- Karolinska, Uppsala, Lund, Umeå, Gothenburg and Aalto offer doctoral
  research in genetics, neuroscience and other biological disciplines.
- University of Basel and Biozentrum Basel offer biomedical research,
  including molecular and cellular biology.
- Utrecht, Radboud, Ghent and AcademicTransfer provide Dutch and Belgian
  PhD vacancies. Ghent lists positions under general "Doctoral fellow"
  titles, requiring departmental/card or detail-page research evidence.
- CRG, IBEC and IRB Barcelona are particularly relevant to epigenetics,
  chromatin, regulatory genomics and molecular biology. IRB's 2026
  extraordinary PhD fellowship call advertises a 28 October 2026 deadline.
  The dated individual advert, not a generic programme page, is authoritative.
- EPFL, Vienna, Copenhagen, CNRS and Inria expand Switzerland, Austria,
  Denmark and France coverage. Helsinki and Bern provide additional
  Finnish and Swiss university PhD vacancies via supported detail-link shapes.

Only listings for explicitly identified continental-European workplaces
qualify. Country defaults are hints, not proof of a job's actual location.
Unknown location, UK/US/Canada positions, expired deadlines and explicitly
self-funded opportunities must not produce Life Sciences alerts.
Funding, salary and tuition remain unverified until a specific posting is
individually examined.

## Runtime budget and fairness

The independent opt-in source feed checks at most **12 enabled sources**
per four-hour pipeline run, rotating oldest last-attempt first using
`data/life_sources_rotation.json`. With 37 enabled feeds, full coverage
requires **four successful runs** (roughly 16 hours, subject to cron delays).
The original 19 EURAXESS and 15 AcademicTransfer topical searches are intact,
but each is now assigned to a smaller source shard of 2–4 queries rather than
being fetched as a large all-at-once batch. Limits remain 60 candidate cards
per source and 200 per run.
Doctoral-looking cards are prioritized before capping and sources are
interleaved. Sparse doctoral cards can receive at most 6 detail-page fetches
per provider, 24 in total, each with an 18-second timeout.

The bot uses the same private, checkpointed delivery mechanism as existing
categories. It does not publish Life Sciences posts into the economics
public listing feed and does not require Iran/remote career-market selection.

## Public source-format probing

An optional manual GitHub Actions workflow
(.github/workflows/verify-life-sciences-sources.yml) checks enabled source
landing pages. Choose core or one of nine regional/topic groups and a 4/8/16
request budget. To inspect all 37 enabled feeds, dispatch the manual
workflow three times with region=all, limit=16, and offsets **0, 16, 32**.
Reports expose checked count and next_offset so no provider is skipped.
Disabled candidate homepages are never fetched by this probe.

The standalone probe (tools/probe_life_sciences_sources.py) uses the
robots-aware PoliteClient, fetches at most one public landing page per
source, and records status and vacancy-link count in a downloadable JSON
artifact. A 200 response with zero detected job links is flagged as
inconclusive or changed markup; it is NOT automatically healthy.
Subscriber IDs, tokens and encrypted delivery records are never accessed.

IMPORTANT: The separate legacy asynchronous production board HTTP client
does not currently automatically enforce robots.txt, although it applies
host delays. Site terms and access restrictions must be checked before
activating any further sources. Do not bypass access controls; the probe
cannot certify continued source compatibility.

## Procedure to activate a candidate

1. Find the official listing of CURRENT doctoral vacancies, not just a
   graduate-school homepage, and check individual job/admission links.
2. Verify a real listing URL, detail-link structure and a workplace location.
   Check whether the page requires JavaScript, an account or authentication.
3. Check site terms, robots.txt and reasonable host request limits.
4. Replace the disabled ^$ link pattern with a narrow tested expression,
   confirm institute location assumptions and set a polite host interval.
5. Add a regression fixture with a real URL and evidence of an eligible
   doctoral research position; test localization if relevant.
6. Run the manual source probe, enable only if access and extraction succeed,
   and preserve last-known-good results and failure diagnostics.

Higher source counts should improve coverage, not manufacture claims that
funding, availability, location or automated retrieval were verified.
