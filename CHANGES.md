# Changes in this version (merged with predoc-bot)

This is the predoc-pipeline project with the working parts of **predoc-bot**
merged in. The architecture is unchanged (gate → extract → dedupe → pending →
broadcast, NDJSON journal as committed state, dashboard + RSS). What changed,
and why:

## Problems found in the original

| # | Problem | Effect | Fixed by |
|---|---|---|---|
| 1 | `.github/` (all workflows) missing from the zip | Nothing ever ran | Restored from `compile_project.py` |
| 2 | Every source in `sources.toml` was a disabled placeholder | 0 positions found | 27 working job boards added as `[[board]]` |
| 3 | Without `GEMINI_API_KEY` the *null* extractor rejected every item | 0 positions published, ever. Gemini is not available in Iran | New rule-based `heuristic` backend, used automatically when there is no key |
| 4 | The gate rejected real adverts that *mention* PhD students, PhD programs, professors, lecturers or a "Chair", and titles like "Pre-doctoral Fellowship" / "Pre-doctoral position" (read as "doctoral fellowship") | 4 of 5 typical CEMFI/UPF/LMU/Bocconi-style adverts were dropped | Rejects now look at the title and the opening lines, not every passing mention, and ignore "pre-" (`core/gating.py`); 6 new golden examples |
| 5 | Links were rewritten into "canonical" form before being shown | `www.` stripped and `:` encoded, which can break the link you click (Varbi `/what:job/...` → 404) | `clean_url()` for links shown to people; `canonicalize_url()` only for hashing |
| 6 | SQLite is gitignored, but `seen_items` and `run_log` lived only there | Every CI run re-judged every item (and, with Gemini, re-spent the quota); "failing N runs in a row" alerts could never fire | `data/seen.ndjson` is committed; run history restored from `docs/data/health.json` |
| 7 | J-PAL and IPA listed as top-priority sources | The owner does not want J-PAL (US-based) | Removed; J-PAL is blocked everywhere via `excluded_employers` |
| 8 | No region, employer-type or field rules | US, industry/bank, psychology/medicine posts would have got through | `config/preferences.toml` + `policy.py`, applied whatever the extractor |
| 9 | No check that a position is still open | Filled positions (dead bit.ly links, "position filled") sent | Link check before sending and every 3 days after |
| 10 | `pages.yml` triggered on `push`, but the bot's own pushes never trigger workflows | Dashboard never updated | `workflow_run` trigger; off unless `ENABLE_PAGES=true` (Pages needs a public repo on the Free plan) |
| 11 | The daily run did `git push` without pulling | Push fails if anything else committed meanwhile | `git pull --rebase --autostash` with retries; shared concurrency group |
| 12 | `dashboard` CLI overwrote `health.json` with an empty history | Lost run history | It no longer touches `health.json` |
| 13 | `ruff check` failed (44 errors) | CI red on every push | Clean |

## New features (from predoc-bot)

* **Job-board scrapers** (`src/predoc_pipeline/boards/`): PREDOC.org,
  INOMICS, The Economic Misfit, EconJobMarket, European Job Market of
  Economists, SOMMA, jobs.ac.uk, EURAXESS, Stockholm University, SSE, Uppsala,
  Lund, Copenhagen, Zurich, Bocconi LEAP, TSE, PSE, Mannheim, Bonn, CEMFI,
  IESE, CREI, UAB, UBC, McGill, Toronto, LinkedIn (academic employers only).
  Each posting's own page is read once: deadline, supervisor, visa rules,
  "PhD required", real location, filled/closed wording, dead links.
* **Preferences** (`config/preferences.toml`): UK/Europe/Canada only; economics,
  business, political science, law; universities, business/economics schools
  and research institutes only; no J-PAL; no PhD-student positions; no expired
  deadlines. Editing the file also clears already-sent positions that no
  longer match.
* **Filled-position checks**: before sending (for anything whose page was not
  read in this run) and every 3 days for sent ones (40 a day). Filled ones
  leave `/positions`, the dashboard and the RSS feed.
* **Two-way Telegram** (`publish/bot.py`, `.github/workflows/telegram.yml`):
  `/positions` (soonest deadline first), `/applied`, `/valid`, `/hidden`,
  `/help`; ✅ ❌ 📝 buttons under every card and in lists (tap again to undo).
  Marks are saved in `data/feedback.json`; ❌ hides a position everywhere.
* **Paged digest**: when many positions are new at once, numbered messages
  of 6 with buttons, instead of one long message.
* Telegram set-up errors (bad token, bot not started, chat not found) keep
  the day's positions queued instead of discarding them.
* Two different adverts with the same title on the same board are no longer
  merged as duplicates.
* Card shows the real application link, "year not stated — check the ad"
  for year-less deadlines, and the visa sentence from the advert.
* New CLI commands: `telegram-sync`, `telegram-chat-id`, `test-telegram`,
  `sources list`. `run --only cemfi,linkedin` runs single boards.
* Schedule: daily at 04:00 UTC (07:30 Tehran).

## Not changed

Feeds/portals collectors, MinHash/fuzzy dedupe, the Gemini backends (still
used when a key is set), the dashboard page, the journal format (new columns
are added automatically to existing databases).

Note: the board scrapers identify as a normal browser and do not consult
robots.txt (the feed/portal collectors still do). They fetch each site a few
times a day at most, with a 1.5 s pause between requests to the same site.

## Recent updates (v1.0.0 enhancements)

### Ingestion & Broadcasting on X/Twitter
* **X Ingestion Backends** (`src/predoc_pipeline/ingest/x.py`, `src/predoc_pipeline/ingest/xquik.py`):
  - Official X API v2 search integration via `X_BEARER_TOKEN` with automatic query construction and pagination.
  - Xquik Platform API integration via `XQUIK_API_KEY` as a cost-effective alternative ingestion backend.
  - Added `predoc-pipeline search-x [query]` CLI command for live terminal queries.
* **X Broadcasting Publisher** (`src/predoc_pipeline/publish/x.py`, `src/predoc_pipeline/publish/x_broadcast.py`):
  - Automated publishing of new predoctoral listings to X/Twitter alongside Telegram broadcasts.
  - Configurable via `X_BROADCAST_ENABLED` and OAuth credentials (`X_CONSUMER_KEY`, `X_CONSUMER_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`).
  - Added `predoc-pipeline test-x` command to verify tweet formatting and API credentials.

### High-Performance Database Architecture (Schema v5)
* **Partial Covering Indexes**:
  - `ix_listings_active` on `(status, first_seen_at DESC) WHERE status = 'active'` accelerates dashboard exports and public queries without scanning historical rows.
  - `ix_listings_pending` on `(status, first_seen_at ASC) WHERE status = 'pending'` accelerates pending broadcast recovery during crash restarts.
* **Expression & Lookup Indexes**:
  - `ix_listings_identity` on `(lower(institution), lower(title))` for O(1) candidate lookup in fuzzy deduplication.
  - `ix_seen_items_decision` on `(decision, item_hash)` for fast cache evaluation.
* **Memory & Storage PRAGMAs**:
  - `mmap_size = 268435456` (256 MB memory-mapped I/O).
  - `cache_size = -65536` (64 MB page cache).
  - `busy_timeout = 10000` (10 seconds timeout for concurrent access).
  - `temp_store = MEMORY` for intermediate sorting.
* **Search CLI**:
  - `predoc-pipeline search <query> [--all] [--limit N]` queries local database records by keyword, institution, or summary.

### Expanded Scope and Scale Caps
* **Geographic & Institutional Coverage**:
  - Preferences expanded to include UK, Europe, Canada, the US, and international research organizations.
  - Covered institutions: universities, central banks (Fed, ECB, BoE, BoC, Bundesbank, etc.), multilateral organizations (World Bank, IMF, OECD, WTO), policy institutes (Brookings, RAND), and economic consultancies (Cornerstone, Analysis Group, NERA, CRA, Brattle).
  - Option to include doctoral (PhD) studentships and postdoctoral positions via `exclude_phd_positions = false`.
* **Throughput Scaling**:
  - Increased run caps: up to 2,500 detail enrichments, 12 concurrent source workers, 25 detail workers, and 10,000 daily LLM request quota.

### Licensing & Open Source Compliance
* Upgraded repository license from MIT to **GNU Affero General Public License v3.0 (AGPL-3.0-or-later)**.

### Code Craftsmanship & Anti-Slop
* **Regex Precompilation**: Precompiled regular expressions across `timeparse.py`, `textproc.py`, `dates.py`, `link_scan.py`, `keyboards.py`, and `discover.py` to eliminate hot-path recompilation overhead.
* **Logging Discipline**: Replaced raw `print()` statements with structured logger calls (`get_logger`).
* **Mobile Layout Hardening**: Added Hallmark mobile guardrails (`overflow-x: clip;`, `overflow-wrap: anywhere;`) in `docs/index.html` to eliminate horizontal scroll anomalies on mobile devices.
* **Exception Hygiene**: Cleaned up swallowed exceptions and sanitized function arguments across heuristics and scrapers.

## Tests

* `pytest`: **295 passing tests** (core standard library utilities, job-board scrapers, preference filters, detail heuristics, Telegram bot conversation flows, X API v2 and Xquik ingestion, X broadcasting, SQLite schema v6 migrations, candidate variables extraction, and end-to-end mocked pipeline runs).
* `predoc-pipeline eval`: precision 1.000, recall 1.000 on 30 labelled golden examples.
* `ruff check`: 0 lint errors across `src` and `tests`.
