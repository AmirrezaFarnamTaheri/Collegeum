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

## Tests

`pytest`: 245 tests (81 original + 164 new: the predoc-bot scraper, filter
and heuristic suites, end-to-end runs against mocked job boards and a mocked
Telegram — including a fresh-machine second run that must send nothing — the
bot conversation, the preference rules, the scoped gate).
`predoc-pipeline eval`: precision 1.000, recall 1.000 on 30 labelled examples.
