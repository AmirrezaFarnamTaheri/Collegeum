# Official PhD scholarships, studentships and fellowships

This monitor closes an important Collegeum source-coverage gap: **ordinary LinkedIn
feed posts are not LinkedIn Jobs listings**. Collegeum now monitors reviewed
official institutional call pages and announcement indexes independently, without
claiming to scrape LinkedIn feeds or circumventing any 403/429 access restriction.

## Current official coverage

The approved registry at `config/official_phd_calls_sources.json` currently
checks IEB/University of Barcelona's **News** index (with bounded discovery
of independent doctoral calls) and five relevant Henley Business School
departmental PhD opportunities pages (Finance and Accounting, International
Business and Strategy, Informatics and Operations, Entrepreneurship, and
Leadership/Organisations). Additional institutions can be added to this reviewed
registry without changing the parser or publisher.

The monitor follows **at most six** relevant IEB same-host HTML call links per
index run, never arbitrary third-party search links or PDFs. It uses one bounded
read for each approved Henley page. The resolver rejects external links, insecure
schemes, credentials, unexpected redirects, oversized responses and restricted
paths. Every fetched URL must be permitted by its own host's robots.txt.
Unavailable or disallowed robots.txt is a failed check, never an implicit grant.

## Admission versus funding deadline

Institution-specific pages can contain several unrelated dates. The parser
accepts an explicit **scholarship/fellowship/studentship** closing date in its
own application context, not a general PhD deadline, intake date, examination,
recommendation, prior closed academic-year cycle or recruitment result.

Examples from the November 2026 verified primary-source investigation:

- IEB full-time Economics PhD Scholarship 2027: two application steps due
  **11 December 2026**, separate from generic University of Barcelona PhD intake.
- IEB Energy and Climate Economics PhD Fellowship: a distinct application with
  its own two required steps, also due **11 December 2026**.
- Henley Finance and Accounting: **21 February 2027** is the funding application
  cutoff, **10 January 2027** is a recommended PhD admission-application date,
  and **30 June 2027** is a different PhD programme deadline. They are never
  treated as interchangeable dates.
- CEMFI's independently monitored **programme** admission remains outside
  this scholarship ledger. Its current official verification is policy-blocked
  and is not promoted by social-post dates.

Every posted call must be freshly checked (14 days maximum), link to the same
official HTTPS evidence page, have an explicit current-cycle deadline, and
provide independently corroborated non-US location evidence. A national
university domain supplies such evidence for Henley; IEB's generic .edu host
requires its current **08034 Barcelona / +34** institutional postal and telephone
address. Absence or contradiction suppresses publication.

## Operations and receipt safety

The existing isolated `phd-admissions-refresh` workflow also runs
`tools/update_official_calls.py`, following the same four UTC cron slots and
trusted main-branch Telegram-sync fallback. Its only side effect is an
institutional-source-only public catalogue
`docs/data/official_phd_calls.json`; it never reads Telegram credentials.

On refresh completion, the existing ingestion freshness watchdog can request
one ordinary main publishing workflow when a verified, eligible call is newer
than the latest pipeline run and has no receipt. The watcher refuses dispatch
for active/newer ingestion, blocked evidence, unknown states and untrusted
source provenance.

The ordinary production pipeline alone can send at most two independently
rendered official call messages per run (override
`TELEGRAM_OFFICIAL_CALLS_MAX_PER_RUN`; live workflow defaults to two).
`TELEGRAM_OFFICIAL_CALLS_ENABLED` is off by default for local runs and
explicitly enabled in the reviewed production workflow. Every independent
call/cycle has a separate key (official URL + intake year) and separate
`data/official_phd_calls_telegram.json` receipt. The ledger is checkpointed
before attempting a send; confirmed, uncertain and permanent-failure states
are never blindly resent.

`docs/data/health.json` contains a separate `official_calls` section for
current source statuses, eligible calls, unsent eligible count, confirmed
receipts, uncertain receipts and last confirmed delivery timestamp. A healthy
source refresh is **not** evidence that Telegram delivered anything.

## Adding future sources safely

Add reviewed official HTTPS institutional index/direct URLs with institution
and country to `config/official_phd_calls_sources.json`, keeping the source
count below 20. Changes trigger offline registry validation and a bounded
`main` source check. A successful HTML response is not automatic eligibility;
unsupported documents and uncertain deadlines remain unverified. Do not add
social-post URLs, scraped job-board mirrors or default country guesses.
