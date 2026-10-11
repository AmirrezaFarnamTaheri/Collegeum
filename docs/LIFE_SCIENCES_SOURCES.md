# Life Sciences PhD — European source catalogue

This independent, opt-in Telegram discovery track must not change economics
preferences, public academic filters or unrelated career alerts.

## Coverage (11 October 2026)

| Group | Enabled | Disabled | Examples |
| --- | ---: | ---: | --- |
| Core | 10 | 10 | EURAXESS, AcademicTransfer, Max Planck, Uppsala, Karolinska, Copenhagen, VIB, EPFL, CRG, Vienna |
| Nordics | 4 | 15 | Lund, Umeå, Gothenburg, Aalto |
| DACH | 2 | 18 | University of Basel, Biozentrum Basel |
| Benelux | 3 | 14 | Utrecht, Radboud, Ghent |
| France and Iberia | 3 | 15 | Inria, IBEC, IRB Barcelona |
| Central/South Europe | 0 | 18 | Polish, Italian, Irish, Czech and Baltic research institutions are pending |
| **Total** | **22** | **90** | **112 registered sources** |

Enabled means an official job-listing page and one individual job URL shape
were inspected. It does NOT prove that automated fetches succeed today or
that a current, relevant, funded position exists. Disabled entries are a
research backlog, intentionally configured with a never-matching ^$ pattern;
they are not functioning scrapers. Never count them as active coverage.

Core entries remain in config/life_sciences.toml. Five regionally organized
catalogues live in config/life_sciences_sources/ (nordics.toml, dach.toml,
benelux.toml, france_iberia.toml, central_south.toml). The source loader
rejects duplicate IDs and oversized catalogues.

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
- EPFL, Vienna, Copenhagen and Inria expand Switzerland, Austria, Denmark
  and France coverage.

Only listings for explicitly identified continental-European workplaces
qualify. Country defaults are hints, not proof of a job's actual location.
Unknown location, UK/US/Canada positions, expired deadlines and explicitly
self-funded opportunities must not produce Life Sciences alerts.
Funding, salary and tuition remain unverified until a specific posting is
individually examined.

## Runtime budget and fairness

The new opt-in source feed polls at most 8 sources per pipeline run, rotating
them by the last attempt recorded in data/life_sources_rotation.json. All 22
can be visited within three successful scheduled runs, barring cron delays or
failures. Limits are 60 candidate cards per source and 200 per run.
Doctoral-looking cards are prioritized before capping and sources are
interleaved. Sparse doctoral cards can receive at most 6 detail-page fetches
per provider, 24 in total, each with an 18-second timeout.

The bot uses the same private, checkpointed delivery mechanism as existing
categories. It does not publish Life Sciences posts into the economics
public listing feed and does not require Iran/remote career-market selection.

## Public source-format probing

An optional manual GitHub Actions workflow
(.github/workflows/verify-life-sciences-sources.yml) checks enabled source
landing pages. Choose all or one regional group and a 4/8/16 request budget.
The all setting checks up to 16 per run: use regional selections to inspect
the remaining providers.

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
