# Collegeum

[![CI](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/workflows/ci.yml/badge.svg)](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/workflows/ci.yml)
[![GitHub Pages](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/workflows/pages.yml/badge.svg)](https://amirrezafarnamtaheri.github.io/Collegeum/)
[![Dashboard](https://img.shields.io/badge/Live_Dashboard-GitHub_Pages-blue)](https://amirrezafarnamtaheri.github.io/Collegeum/)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0.en.html)

An automated pipeline that discovers, filters, and broadcasts pre-doctoral
research assistantships, fellowships, and academic research openings in
economics, finance, public policy, and quantitative social science. It covers
the UK, Europe, Canada, the US, and international research institutions,
delivering new positions to Telegram and X/Twitter daily at zero infrastructure
cost.

**Live dashboard:** https://amirrezafarnamtaheri.github.io/Collegeum

## What it does

The pipeline runs on GitHub Actions every four hours and performs a full cycle:

1. **Discovers** vacancies from academic job boards (PREDOC.org, EconJobMarket,
   European Job Market, jobs.ac.uk, EURAXESS, SOMMA, academics.de), university
   applicant tracking systems (Workday, Varbi), department career pages,
   RSS/Atom feeds, and X/Twitter accounts.
2. **Filters** unrelated vacancies through a deterministic rule-based gate that
   checks institution, field, region, position type, and employer classification.
3. **Extracts** structured metadata — deadlines, supervisors, visa sponsorship,
   application links, filled status — using either a zero-dependency heuristic
   parser or an optional LLM provider (Gemini, Groq, OpenAI, Anthropic, Mistral,
   NVIDIA, OpenRouter, or any OpenAI-compatible endpoint).
4. **Deduplicates** cross-posted listings across three tiers: exact URL hash,
   MinHash/LSH similarity, and fuzzy composite keys.
5. **Broadcasts** new positions to a Telegram channel, an X/Twitter account, and
   an interactive GitHub Pages dashboard with RSS syndication.

No paid API keys are required. Without any model-provider key, the built-in
heuristic extractor parses vacancy pages. When a key is configured, the LLM
provides structured extraction subject to the same policy rules.

## Quickstart

```bash
git clone https://github.com/AmirrezaFarnamTaheri/Collegeum.git
cd Collegeum
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[portals]"

cp .env.example .env
# Edit .env: set TELEGRAM_BOT_TOKEN and TELEGRAM_PUBLIC_CHANNEL_ID
#           (GEMINI_API_KEY or another LLM key is optional)

predoc-pipeline init             # initialize local database and directories
predoc-pipeline smoke            # offline sanity check (no network or credentials)
predoc-pipeline sources verify   # test discovery and parsing for enabled sources
predoc-pipeline run --dry-run    # ingest and gate without models or broadcasting
predoc-pipeline run --only cemfi,predoc_org   # run specific sources only
predoc-pipeline run              # full cycle: ingest, gate, extract, dedupe, broadcast
predoc-pipeline telegram-sync    # answer bot commands and persist button taps
predoc-pipeline dashboard        # export dashboard JSON and RSS feed without a full run
predoc-pipeline search "macro"   # query cached active listings by keyword
predoc-pipeline stats            # show database counts and recent run outcomes
predoc-pipeline vacuum           # prune dead-letter and seen rows, compact the database
```

## Deployment

For a scheduled, hosted setup on GitHub Actions:

1. **Configure secrets.** In **Settings > Secrets and variables > Actions**, add
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_PUBLIC_CHANNEL_ID`. The bot must be an
   administrator of the destination channel. See `SETUP_GUIDE.md` for full
   instructions including private commands, encrypted feedback, and optional
   integrations.

2. **Enable the dashboard (optional).** Set the repository variable
   `ENABLE_PAGES=true` and make the repository public. The dashboard deploys
   via GitHub Pages on every push and after each pipeline run.

3. **The pipeline runs automatically.** The `pipeline.yml` workflow fires at
   00:07, 04:07, 08:07, 12:07, 16:07, and 20:07 UTC. The `telegram.yml` workflow
   checks for private bot commands at :15 and :45 every hour when
   `ENABLE_TELEGRAM_SYNC=true`.

See `SETUP_GUIDE.md` for detailed deployment, `OPERATIONS.md` for production
runbooks, and `COMPLIANCE.md` before enabling external scrapers.

## Telegram bot

The Telegram bot provides two surfaces:

- **Public channel announcements.** New vacancies are posted as formatted cards
  or digest messages to a public channel. No private data is exposed.

- **Private owner console.** In a private chat with the bot, owners can browse
  positions, save/hide/track applications, search by keyword, and ask natural
  language questions about stored vacancies (powered by OpenRouter with a
  database-grounded tool-call protocol). The bot supports English and Persian
  menus.

An optional Cloudflare Worker (`cloudflare/telegram/`) provides a durable
webhook handler with serialized update processing, crash recovery via alarms,
quota-gated public AI, and checkpointed delivery that never silently
acknowledges an unconfirmed Telegram send.

## Configuration

- **`config/sources.toml`** — Source registry. `[[board]]` entries are active by
  default; `[[feed]]` and `[[portal]]` entries are templates that default to
  `enabled = false` and `verified = false`.

- **`config/preferences.toml`** — Filtering criteria: included regions, academic
  fields, employer classification patterns, position types, and deadline expiry
  rules.

- **`.env.example`** — All environment variables with defaults and inline
  documentation. Copy to `.env` for local runs; use repository secrets for CI.

## Project layout

```
src/predoc_pipeline/
  core/            URL handling, text processing, MinHash+LSH, fuzzy matching,
                   time parsing, SQLite storage, rate limiting, deterministic gating
  ingest/          HTTP client (conditional GET, robots.txt, pacing), source
                   registry, feed autodiscovery, collectors for boards, feeds,
                   ATS portals, and X API v2 / Xquik
  extract/         Classification prompts, LLM REST backends with fallback,
                   and a zero-dependency heuristic extractor
  boards/          Job-board scrapers, preference rules, detail-page heuristics,
                   and filled-position verification
  publish/         Telegram Bot API client, X/Twitter broadcast client, message
                   formatting, and encrypted feedback store
  pipeline.py      Orchestrates the ingestion, gating, extraction, and broadcast cycle
  policy.py        Applies config/preferences.toml to every listing
  models.py        Domain models and extraction schema
  state.py         NDJSON journal, dashboard JSON export, and RSS generation
  cli.py           Command-line interface

cloudflare/telegram/   Optional Cloudflare Worker for durable Telegram webhook handling
config/                Source registry and filter preferences
data/                  Committed state: listings, seen items, feedback
docs/                  Static web dashboard and JSON/RSS data feeds
tests/                 Unit tests (core) and integration tests
tools/                 Maintenance scripts (e.g. false-closure repair)
```

## Testing

```bash
make test-core          # stdlib only, no dependencies required
make test               # full suite
make eval               # gate precision/recall against tests/fixtures/golden.jsonl
make smoke              # offline self-check without network or credentials
```

Core tests run with standard Python 3 and no installed packages:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/core -t . -v
```

## Design principles

1. **The model quota, not compute, is the scarce resource.** Every layer before
   extraction exists to protect it: the seen-items gate, the deterministic
   classifier, and per-source item caps.

2. **Nothing is asserted without being checked.** Source URLs default to
   `verified = false` until someone runs `sources verify`. Rate limits are
   configurable, not hard-coded.

3. **A crash should never cause a duplicate broadcast or silent data loss.**
   Rows are inserted with pending status before broadcasting; committed state
   uses an append-then-sorted-rewrite NDJSON journal.

4. **Silent failure is the default failure mode for an unattended scraper.**
   Per-source yield is tracked in run health metrics; consecutive empty runs
   and failing sources trigger maintainer alerts.

## License

GNU Affero General Public License v3.0 (AGPL-3.0-or-later). See `LICENSE`.
