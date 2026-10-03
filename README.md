# predoc-not-org

[![CI](https://github.com/AmirrezaFarnamTaheri/predoc-not-org/actions/workflows/ci.yml/badge.svg)](https://github.com/AmirrezaFarnamTaheri/predoc-not-org/actions/workflows/ci.yml)
[![GitHub Pages](https://github.com/AmirrezaFarnamTaheri/predoc-not-org/actions/workflows/pages.yml/badge.svg)](https://amirrezafarnamtaheri.github.io/predoc-not-org/)
[![Dashboard](https://img.shields.io/badge/Live_Dashboard-GitHub_Pages-blue)](https://amirrezafarnamtaheri.github.io/predoc-not-org/)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0.en.html)

An automated pipeline that discovers, deduplicates, and broadcasts
**pre-doctoral** research assistantships, fellowships, and academic research
openings in economics, finance, public policy, and quantitative social
science across the UK, Europe, Canada, the US, and international research
institutions to Telegram and X/Twitter daily, at zero dollar cost.

🌐 **Live Web Dashboard:** [https://amirrezafarnamtaheri.github.io/predoc-not-org](https://amirrezafarnamtaheri.github.io/predoc-not-org)

The pipeline monitors academic job boards (PREDOC.org, EconJobMarket, European
Job Market, jobs.ac.uk, EURAXESS, SOMMA, academics.de), university applicant
tracking systems (Workday, Varbi), department career pages, RSS/Atom feeds,
and X/Twitter accounts (via official X API v2 and Xquik). It filters out
unrelated vacancies through a deterministic gate, extracts structured metadata
(deadlines, supervisors, visa sponsorship, application links, and filled
status), deduplicates cross-posted listings across three tiers (URL hash,
MinHash/LSH, fuzzy composite keys), and broadcasts new positions to Telegram
channels and X/Twitter feeds. It also updates an interactive GitHub Pages
dashboard and RSS syndication feed.

No paid API keys are required: without `GEMINI_API_KEY`, a built-in heuristic
extractor parses vacancy pages. When configured, Gemini provides structured LLM
extraction subject to the same policy rules.

**Getting Started:** Read `SETUP_GUIDE.md` for deployment instructions.
**Recent Updates:** See `CHANGES.md` for release history and architecture changes.
**Technical Details:** Consult `ARCHITECTURE.md` for design trade-offs,
`COMPLIANCE.md` before enabling external scrapers, `REVIEW.md` for the defect
register, and `OPERATIONS.md` for production runbooks.

## Quickstart

```bash
git clone <this-repo>
cd predoc-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[portals]"

cp .env.example .env
# edit .env: TELEGRAM_BOT_TOKEN, TELEGRAM_PUBLIC_CHANNEL_ID (GEMINI_API_KEY optional)

predoc-pipeline init             # initialize local database and directories
predoc-pipeline smoke            # offline sanity check (tests gating & models)
predoc-pipeline sources verify   # verify reachability of enabled sources
predoc-pipeline run --dry-run    # ingest and gate without calling models or broadcasting
predoc-pipeline run --only cemfi,predoc_org   # run specific job boards
predoc-pipeline run              # execute full cycle: ingest, gate, extract, dedupe, broadcast
predoc-pipeline telegram-sync    # answer bot commands and persist button taps
predoc-pipeline dashboard        # export docs/data/*.json and RSS feed without a full run
predoc-pipeline search "macro"   # query cached active listings by keyword or institution
predoc-pipeline search-x "from:econ_RA"  # query X/Twitter postings (API v2 / Xquik)
predoc-pipeline test-telegram    # send a test message to your configured Telegram channel
predoc-pipeline test-x           # post a test update to your configured X/Twitter account
predoc-pipeline stats            # display database counts and recent run outcomes
predoc-pipeline vacuum           # prune dead-letter/seen rows and compact the database
```

For a scheduled, hosted setup add `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_PUBLIC_CHANNEL_ID` (your own chat id, for a personal bot) as
repository secrets. `.github/workflows/pipeline.yml` runs daily at 04:00 UTC
and `.github/workflows/telegram.yml` answers commands every 30 minutes. The
dashboard (`pages.yml`) is optional: it needs a public repository on the Free
plan and the repository variable `ENABLE_PAGES=true`.

### What you get, and how to change it

`config/preferences.toml` defines filtering criteria: included regions (UK,
Europe, Canada, US, Other), academic and research fields, employer classification
patterns, position types (predoc, PhD, postdoc), and deadline expiry rules.
`config/sources.toml` lists the sources: `[[board]]` entries are active by
default, while `[[feed]]` and `[[portal]]` entries serve as configured templates.

### Feed and portal templates

`[[feed]]` and `[[portal]]` entries default to `verified = false` and
`enabled = false`. Public syndication endpoints change frequently across
academic portals. Run `predoc-pipeline sources verify` to validate connectivity
and data return for configured sources. Consult `config/sources.toml` for
site-specific parameters, and run `predoc-pipeline sources discover <url>` to
detect live RSS or Atom feeds directly from publisher homepages.

## Project layout

```
src/predoc_pipeline/
  core/            Stdlib-only: URLs, text, MinHash+LSH, fuzzy matching,
                   time parsing, SQLite storage (Schema v5), rate limiting,
                   and deterministic gating. Fully unit-testable with zero
                   third-party packages.
  ingest/          HTTP client (conditional GET, robots.txt, pacing),
                   source registry, feed autodiscovery, and collectors
                   (job boards, RSS/Atom feeds, ATS portals, X API v2, Xquik).
  extract/         Classification prompts, Gemini REST backends with
                   automatic fallback, and a zero-dependency heuristic extractor.
  boards/          Job-board scrapers, preference rules, detail-page heuristics,
                   and filled-position verification.
  publish/         Telegram Bot API client, X/Twitter broadcast client, message
                   formatting, `/positions` command handler, and feedback store.
  policy.py        Applies config/preferences.toml to every listing.
  models.py        Domain models (PredocListing) and extraction schema.
  pipeline.py      Orchestrates the ingestion, gating, extraction, and broadcasting cycle.
  state.py         Committed NDJSON journal, dashboard JSON export, and RSS generation.
  cli.py           `predoc-pipeline` command-line interface.

tests/core/        Unit tests, standard library only (no pip dependencies required).
tests/integration/ Tests covering HTTP, persistence, extraction, and publishers.
tests/fixtures/    Labeled examples for precision and recall evaluation.

config/sources.toml      Source registry configuration.
config/preferences.toml  Field, region, and employer filters.
data/                    Committed state: listings.ndjson, seen.ndjson, feedback.json.
docs/                    Static web dashboard (docs/index.html) and JSON/RSS data feeds.
.github/workflows/       pipeline.yml, telegram.yml, ci.yml, pages.yml.
```

## Testing

```bash
make test-core          # stdlib only: runs with standard python3 without dependencies
make test               # full suite: 282 tests passing
make eval               # gate precision/recall against tests/fixtures/golden.jsonl
make smoke              # offline self-check without network or credentials
```

`tests/core/` is runnable with zero third-party packages installed:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/core -t . -v
```

## Design principles this project holds itself to

1. **The model's daily request quota, not compute, is the scarce resource.**
   Every layer before extraction exists to protect it: the seen-items gate,
   the deterministic rule-based classifier, and per-source item caps.
2. **Nothing is asserted without being checked.** Source URLs default to
   `verified = false` until someone runs `sources verify`. Rate limits are
   configurable rather than hard-coded constants.
3. **A crash should never cause a duplicate broadcast or silent data loss.**
   Rows are inserted with pending status before broadcasting; committed state
   uses an append-then-sorted-rewrite NDJSON journal.
4. **Silent failure is the default failure mode for an unattended scraper.**
   Per-source yield is tracked in run health metrics; consecutive empty runs
   and failing sources trigger maintainer alerts.

## License

GNU Affero General Public License v3.0 (AGPL-3.0-or-later). See `LICENSE`.
