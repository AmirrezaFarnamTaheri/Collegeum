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

### X / Twitter ingestion methods

The pipeline supports three distinct mechanisms for X/Twitter discovery:

1. **Official X API v2 (`X_BEARER_TOKEN`)**:
   - Uses official developer credentials and calls the v2 recent search endpoint (`/2/tweets/search/recent`).
   - Fully compliant with the X Developer Agreement and Developer Policy.
   - Constrained by monthly request quotas on Free/Basic tiers (e.g., 100 queries/month on Free, 10,000 queries/month on Basic).
   - Recommended and default method when credentials are provided.

2. **Xquik Platform API (`XQUIK_API_KEY`)**:
   - Queries a third-party managed proxy endpoint without requiring X developer accounts or credentials.
   - Recommended as an alternative when official API quotas are exceeded.

3. **`ENABLE_TWITTER` via `twscrape` (legacy authenticated scraper)**:
   - Performs automated session-based scraping with account credentials.
   - X's terms of service prohibit automated scraping of web interfaces. Accounts used this way risk rate limiting and suspension.
   - Off by default; requires `ENABLE_TWITTER=true` and `TWSCRAPE_ACCOUNTS`.

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
| Academic Job Boards | **On** | No | No | Low — parses public job announcements |
| RSS/Atom feeds | **On** | Yes | Yes | None — public syndication protocol |
| Schema.org portals | **On** | Yes | Yes | Low-medium — relies on public structured data |
| Official X API v2 | **On** (with token) | N/A (REST API) | N/A | None — compliant with X Developer Policy |
| Xquik Platform API | **On** (with key) | N/A (REST API) | N/A | Low — managed proxy service |
| `jobspy` (job boards) | **Off** | N/A (library-internal) | No | High — ToS violation risk, IP/account blocking |
| `twscrape` (social) | **Off** | N/A | No | High — ToS violation, account suspension |

*Note on Academic Job Boards*: Direct job-board and ATS scrapers do not dynamically query `robots.txt` files, but requests are strictly paced per host with politeness delays and concurrency limits to prevent server impact.
