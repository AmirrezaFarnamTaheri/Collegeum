# predoc-not-org

[![CI](https://github.com/AmirrezaFarnamTaheri/predoc-not-org/actions/workflows/ci.yml/badge.svg)](https://github.com/AmirrezaFarnamTaheri/predoc-not-org/actions/workflows/ci.yml)
[![GitHub Pages](https://github.com/AmirrezaFarnamTaheri/predoc-not-org/actions/workflows/pages.yml/badge.svg)](https://amirrezafarnamtaheri.github.io/predoc-not-org/)
[![Dashboard](https://img.shields.io/badge/Live_Dashboard-GitHub_Pages-blue)](https://amirrezafarnamtaheri.github.io/predoc-not-org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A zero-budget pipeline that discovers, deduplicates, and broadcasts
full-time **pre-doctoral** research assistantship openings — economics,
business, public policy, and quantitative social science — in the **UK,
Europe and Canada** — to Telegram, once a day, for free.

🌐 **Live Web Dashboard:** [https://amirrezafarnamtaheri.github.io/predoc-not-org](https://amirrezafarnamtaheri.github.io/predoc-not-org)

It reads the job boards and university career sites where these roles are
posted (PREDOC.org, EconJobMarket, the European Job Market, jobs.ac.uk,
EURAXESS, university Workday/Varbi portals, department pages, LinkedIn) plus
optional RSS feeds and career-page metadata. It filters out the large
false-positive classes specific to this domain (PhD studentships, postdocs,
faculty postings, industry and bank jobs, US positions, medicine/psychology,
"I just finished my predoc" posts), reads each new advert's page (deadline,
supervisor, visa rules, filled or not), deduplicates cross-posted listings,
and posts each new one to Telegram — with ✅ ❌ 📝 buttons and a `/positions`
command — plus an interactive dashboard and RSS feed on GitHub Pages.

No API key is needed: without `GEMINI_API_KEY` a rule-based extractor is
used. With a key, Gemini does the extraction and the same preference rules
still apply.

**New here? Read `SETUP_GUIDE.md`** (step by step, GitHub website only).
**What changed from the first version:** `CHANGES.md`.

See `REVIEW.md` for the defect register this rebuild fixed, `ARCHITECTURE.md`
for the design and trade-off rationale, `COMPLIANCE.md` before enabling any
optional source, and `OPERATIONS.md` for the runbook once it's live.

## Quickstart

```bash
git clone <this-repo>
cd predoc-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[portals]"

cp .env.example .env
# edit .env: TELEGRAM_BOT_TOKEN, TELEGRAM_PUBLIC_CHANNEL_ID (GEMINI_API_KEY optional)

predoc-pipeline init             # creates the local database
predoc-pipeline smoke            # offline sanity check, no network needed
predoc-pipeline sources verify   # IMPORTANT — see "About the source list" below
predoc-pipeline run --dry-run    # ingest and gate, send nothing
predoc-pipeline run --only cemfi,predoc_org   # just some job boards
predoc-pipeline run              # the real thing
predoc-pipeline telegram-sync    # answer /positions and save ✅ ❌ 📝 taps
predoc-pipeline dashboard        # regenerate docs/data/*.json without a full run
```

For a scheduled, hosted setup add `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_PUBLIC_CHANNEL_ID` (your own chat id, for a personal bot) as
repository secrets. `.github/workflows/pipeline.yml` runs daily at 04:00 UTC
and `.github/workflows/telegram.yml` answers commands every 30 minutes. The
dashboard (`pages.yml`) is optional: it needs a public repository on the Free
plan and the repository variable `ENABLE_PAGES=true`.

### What you get, and how to change it

`config/preferences.toml` decides what is sent: regions, wanted and unwanted
fields, allowed employer types, banned employers (J-PAL), PhD-position and
expiry rules. `config/sources.toml` lists the sources; the `[[board]]`
entries are on by default, the `[[feed]]`/`[[portal]]` entries are templates.

### About the feed and portal templates

**The `[[feed]]` and `[[portal]]` entries ship with `verified = false` and
`enabled = false`.** During this project's research, no confirmable,
currently-live public feed URL could be found for INOMICS, EconJobMarket,
EURAXESS, or jobs.ac.uk specifically — job board feed infrastructure changes
often enough that a URL found via search is not the same thing as a URL that
returns data today. `predoc-pipeline sources verify` fetches every enabled
source once and reports what actually comes back; treat it as the mandatory
first step, not an optional check. See the notes on each entry in
`config/sources.toml` for what to look for, and `predoc-pipeline sources
discover <url>` to find a site's real feed URL from its homepage.

## Project layout

```
src/predoc_pipeline/
  core/            Stdlib-only: URLs, text, MinHash+LSH, fuzzy matching,
                   time parsing, SQLite storage, rate limiting, the
                   deterministic gate. Unit-testable with zero dependencies
                   installed — see tests/core/.
  ingest/          Polite HTTP (conditional GET, robots.txt, pacing), the
                   source registry, feed autodiscovery, and the collectors
                   (feeds, portals, optional jobspy/twitter).
  extract/         The classification prompt and two Gemini REST backends
                   with automatic fallback, plus an optional instructor
                   backend.
  boards/          Job-board scrapers (ported from predoc-bot), preference
                   rules, detail-page heuristics and filled-position checks.
  publish/         Telegram Bot API client, message rendering, the
                   /positions bot and the ✅ ❌ 📝 feedback store.
  policy.py        Applies config/preferences.toml to every listing.
  models.py        Domain model (PredocListing) and the model-facing wire
                   schema (ExtractionResult) plus the coercion between them.
  pipeline.py      Orchestrates one full run.
  state.py         The committed NDJSON journal, dashboard JSON export,
                   and RSS feed generation.
  cli.py           `predoc-pipeline` command-line entry points.

tests/core/        Unit tests, stdlib only — run with plain `python3 -m
                   unittest`, no pip install required.
tests/integration/ Tests needing httpx/pydantic/respx — skip cleanly if
                   those aren't installed.
tests/fixtures/    Labeled examples for `predoc-pipeline eval`.

config/sources.toml   The source registry (see above).
config/preferences.toml  What counts as a position you want.
data/                 Committed state: listings.ndjson, seen.ndjson,
                       feedback.json (your marks), telegram_state.json.
docs/                 The static dashboard (docs/index.html) and its data
                       exports, deployed via GitHub Pages.
.github/workflows/    pipeline.yml (the daily run), telegram.yml (commands and
                       buttons), ci.yml (tests on every push), pages.yml
                       (optional dashboard deploy), dependabot.yml.
tools/build_single_file.py
                   Regenerates compile_project.py, a dependency-free
                   single-file materializer of the whole project — useful
                   for dropping this into an environment that can't clone a
                   repo. Never hand-edit compile_project.py; regenerate it.
```

## Testing

```bash
make test-core          # stdlib only — runs anywhere with just python3
make test                # full suite, needs `pip install -e ".[dev]"`
make eval                # gate precision/recall against tests/fixtures/golden.jsonl
make smoke               # offline self-check, no network or credentials
```

`tests/core/` is deliberately runnable with zero installed dependencies —
that's what `tests/core/test_no_third_party.py` enforces. If you're auditing
this project or just don't want to `pip install` anything yet, start there:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/core -t . -v
```

## Design principles this project holds itself to

1. **The model's daily request quota, not compute, is the scarce resource.**
   Every layer before extraction exists to protect it: the seen-items gate,
   the deterministic rule-based classifier, per-source item caps.
2. **Nothing is asserted without being checked.** Source URLs default to
   `verified = false` until someone runs `sources verify`. Rate limits are
   configuration, not hard-coded constants, because the provider itself says
   they aren't guaranteed.
3. **A crash should never cause a duplicate broadcast or a silent data
   loss.** Rows are inserted before broadcasting, not after; the committed
   state is an append-then-sorted-rewrite journal, not a binary database
   file that can't be diffed or safely merged.
4. **Silent failure is the default failure mode for an unattended scraper,
   so it's treated as a first-class case, not an afterthought.** Per-source
   yield is tracked and surfaced on the dashboard; consecutive empty runs
   and newly-dead sources trigger a maintainer alert.
## License

MIT — see `LICENSE`.
