# Compliance and responsible-use notes

This is not legal advice. It's a factual account of what each part of this
pipeline does, so whoever runs it can make an informed decision about what
to enable. Read this before flipping any flag in the "opt-in sources"
section of `.env` or `settings.py`.

## What's on by default, and why it's the safer default

**RSS/Atom feeds** (`ENABLE_FEEDS`, default **on**) and **Schema.org
`JobPosting` metadata on career pages** (`ENABLE_PORTALS`, default **on**)
are both channels that publishers deliberately expose for machine
consumption. A syndication feed exists specifically so that readers,
aggregators, and yes, scripts, can consume it without visiting the page. The
`JobPosting` microdata/JSON-LD standard exists specifically so that search
engines (and anything else) can parse job listings structurally instead of
scraping visible text. Reading either is not meaningfully different from what
a search engine's crawler already does, and both defaults ship with:

- **robots.txt compliance** (`ingest/http.py::PoliteClient`), checked via
  stdlib `urllib.robotparser` and cached per host for the run. If a site's
  robots.txt disallows the pipeline's user agent from a path, that path is
  not fetched — full stop, no override flag.
- **A descriptive, honest User-Agent** including a contact address
  (`settings.py::http_user_agent`). An operator who wants this traffic to
  stop should be able to find and contact you before reaching for a
  firewall rule. Do not ship this with a generic or spoofed user agent.
- **Per-host pacing** (`per_host_delay_seconds`, default 1 second) and
  **conditional GET** (`ETag`/`If-None-Match`, `Last-Modified`/
  `If-Modified-Since`) so that unchanged sources cost the target server a
  304 response with no body, not a full re-fetch, every single day.

None of this eliminates the possibility that a specific site's terms of
service restrict automated access even to its own published feed — read a
source's terms before adding it to `config/sources.toml`, especially for
anything beyond a standard RSS feed or a straightforward careers page.

## What's opt-in, and what you're opting into

### `ENABLE_JOBSPY` (commercial job boards — LinkedIn, Indeed, etc.)

`python-jobspy` scrapes job board search results and detail pages. This is
meaningfully different from reading a feed: these platforms' terms of
service generally restrict automated scraping, LinkedIn in particular has a
well-documented history of pursuing legal action against scrapers (with
outcomes that have varied by jurisdiction and specific facts), and scraping
at any real volume risks the scraping IP or associated account being
blocked. `python-jobspy` itself is a legitimate open-source project — the
compliance question is about what you do with it, not about the library.

If you enable this, do so with the understanding that:
- You are responsible for reviewing the current terms of service of any
  platform you scrape via this flag, at the time you enable it — those terms
  change, and this document does not track them.
- Rate limiting (`per_host_delay_seconds`, `max_items_per_source`) reduces
  but does not eliminate detection risk.
- This is the reason the flag defaults to `false` and is not enabled in the
  example workflow.

### `ENABLE_TWITTER` (authenticated social search)

`twscrape` requires real X/Twitter account credentials and performs
authenticated scraping, which X's terms of service prohibit for automated,
non-API access. Practically: accounts used this way get flagged and
suspended with some regularity, this treats a real person's account as
infrastructure (don't use an account you actually care about), and X's
official API v2 is the ToS-compliant alternative — at a price point that, at
last check, starts well above this project's zero-dollar constraint for
search-capable tiers, and should be re-priced against current rates before
being ruled out.

If you enable this:
- Use a dedicated account created for this purpose, not a personal one.
- Credentials are read from the `TWSCRAPE_ACCOUNTS` environment variable
  (a GitHub Actions secret in CI) and are never written to a path git
  tracks — see `ingest/collectors.py::collect_twitter`, which writes the
  session database only to a `tempfile.TemporaryDirectory()` that is deleted
  when the process exits.
- Understand that account suspension is a "when," not an "if," at any
  sustained volume.

## Data handling

- **No personal data beyond what's in a public job advertisement is
  collected.** Names captured are supervisor/PI names as stated in adverts
  that are themselves public postings — the same information anyone reading
  the ad would see.
- **The public dashboard and RSS feed only ever show `status='published'`,
  non-expired listings** (`state.py::_public_record`, `active_listings()`).
  Rejected items, duplicates, and DLQ entries are operational data, visible
  only in the private SQLite database and the workflow's own logs/artifacts
  — never published.
- **Source URLs are retained** (as `source_url` and `alternate_sources`) so
  that a listing can always be traced back to where it was found, and so a
  correction or takedown request has something concrete to act on.

## Takedown / correction requests

Every published listing carries its original source URL in the dashboard's
detail view. If an institution wants a listing removed or corrected, the
fastest path is deleting or updating the corresponding row's `status` via
the CLI (or waiting for `expire_past_deadline` if the listing has simply
closed) and letting the next run's journal write reflect the change. There
is currently no automated takedown-request intake; for a channel with real
traffic, adding one (even a simple form that opens a GitHub issue) is a
reasonable next step.

## Summary table

| Source | Default | Robots.txt honored | Conditional GET | Primary risk |
|---|---|---|---|---|
| RSS/Atom feeds | On | Yes | Yes | Low — this is what feeds are for |
| Schema.org portals | On | Yes | Yes | Low-medium — depends on the specific site's terms |
| `jobspy` (job boards) | **Off** | N/A (library-internal) | No | High — ToS violation risk, IP/account blocking |
| `twscrape` (social) | **Off** | N/A | No | High — ToS violation, account suspension |
