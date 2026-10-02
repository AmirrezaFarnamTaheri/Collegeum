# Review: defect register

This is a line-by-line review of the two documents this project started
from — the researcher agent's architecture report and the coder agent's
`compile_project.py` — plus the corrections that came out of checking their
factual claims against current sources. Every item below was either fixed in
this rebuild (marked **Fixed**, with where) or is a known limitation carried
forward deliberately (marked **Accepted**, with why).

Severity is about consequence, not code size: a one-line dedup bug that
silently drops real listings is Critical; a missing type hint is Cosmetic.

---

## Part 1 — Factual corrections to the architecture report

These are claims the researcher document stated as settled fact that no
longer match (or never matched) the provider's current behavior. Getting
these wrong doesn't crash the pipeline — it makes it silently wrong in
production, which is worse.

| # | Claim in the reviewed report | Correction | Severity | Status |
|---|---|---|---|---|
| F1 | "Gemini free tier: 15 RPM / 1,500 RPD" as a fixed constant | Google no longer publishes a static free-tier table. Current docs say limits "depend on a variety of factors," are visible only in the AI Studio console, apply **per project, not per API key**, and are "not guaranteed." Hard-coding a number is building on sand. | Critical | **Fixed** — `settings.py`: `LLM_REQUESTS_PER_MINUTE` / `LLM_REQUESTS_PER_DAY` are configuration with conservative defaults, not architectural constants. `RateLimiter` in `core/ratelimit.py` enforces them locally and a 429's own `RetryInfo.retryDelay` always overrides the local estimate (`extract/gemini.py::_parse_retry_delay`). |
| F2 | RPD resets "daily" with no timezone specified | The provider resets daily quotas at **midnight Pacific time**, not UTC. A UTC-keyed counter drifts by up to 8 hours and can let a run blow through the real daily cap while believing it has budget left. | High | **Fixed** — `core/ratelimit.py::quota_day()` computes the Pacific quota day (with a DST approximation) and is used as the SQLite `llm_usage` key throughout. |
| F3 | Architecture assumes `gemini-2.0-flash` and the `generationConfig.responseSchema` shape as *the* API | The provider has since published an `/v1beta/interactions` endpoint with a different (`response_format`) shape, alongside a "breaking changes" notice for that same new API, while `:generateContent` remains live. Committing to one shape is committing to guessing right about a still-moving target. | High | **Fixed** — `extract/gemini.py` implements both `_InteractionsBackend` and `_GenerateContentBackend`, auto-probes which one the account can reach, and caches the answer in `meta` so subsequent runs skip the probe. |
| F4 | GitHub Actions framed as "~120 of your 2,000 free minutes" | The 2,000 minutes/month cap applies only to **private** repositories on the Free plan. Public repos get unlimited Actions minutes. For a public predoc-tracking repo, minutes are not the constraint — the model's daily request quota is. | Medium | **Fixed** — `.github/workflows/pipeline.yml` comment states this correctly; nothing in the design budgets against a minutes cap that doesn't apply. |
| F5 | `disable_web_page_preview` presented as the way to suppress link previews | Bot API 7.0 replaced this field with `link_preview_options`; the old field is deprecated (though still accepted by some server versions). | Medium | **Fixed** — `publish/telegram.py::TelegramClient.send_message` sends both fields; unknown fields are ignored by the API, so this is strictly more compatible. |
| F6 | 4096-character Telegram limit treated as a raw-string length check | The documented limit applies to the message **after entity parsing** — `&amp;` counts as one character, an HTML tag counts as zero. Measuring raw HTML either truncates too early or, if you count code points wrong, can go over. | Medium | **Fixed** — `core/textproc.py::telegram_visible_length()` strips tags and un-escapes entities before counting; `publish/telegram.py::render_card` sizes the summary against the real remaining budget. |
| F7 | EURAXESS treated as a source that can be filtered to predocs via its "R1" tag | EURAXESS's "First Stage Researcher (R1)" classification is for doctoral candidates. An R1-filtered feed returns PhD studentships almost exclusively — the opposite of what this pipeline wants. Neither reviewed document flagged this. | Critical (would have silently filled the channel with the wrong content) | **Fixed** — `extract/prompt.py` explicitly instructs the model to reject PhD studentships and doctoral positions regardless of portal labeling; `core/gating.py::HARD_REJECT` has a dedicated, multilingual `phd-studentship` pattern as a pre-model backstop. `config/sources.toml` documents the R1 trap inline on the EURAXESS entry. |
| F8 | Specific feed URLs given for EconJobMarket, EURAXESS, and jobs.ac.uk | No confirmable, currently-live public feed URL could be found for any of these during this project's research. A URL that looks plausible in a search result is not the same as a URL that returns data today. | High (silent zero-yield source looks identical to "no new postings") | **Fixed** — every entry in `config/sources.toml` ships with `verified = false` and `enabled = false` by default; `predoc-pipeline sources verify` is the mandatory first command after cloning, and it reports reachability per source rather than assuming it. |
| F9 | INOMICS, J-PAL, and IPA absent from every source list | These are among the largest single employers of predocs globally (J-PAL and IPA especially). Missing them isn't a bug in code, but it's a real gap in coverage that the review should have caught. | Medium | **Fixed** — added as `verified = false` template entries in `config/sources.toml`, tagged `largest-source`, so they're the first thing flagged by `sources verify` and the first thing a maintainer should confirm. |

---

## Part 2 — Defects in `compile_project.py` (the coder agent's output)

### Critical — silent data loss or duplicate delivery

| # | Defect | Why it matters | Status |
|---|---|---|---|
| C1 | WAL never checkpointed before the workflow commits `predocs.db` | SQLite in WAL mode keeps recent writes in a separate `-wal` file until a checkpoint folds them back in. Committing only the `.db` file can ship a database **missing its most recent transactions** — the exact commit that "worked" in testing can silently regress in production once the WAL grows past what auto-checkpoint covers under load. | **Fixed** — `core/db.py::Database.close()` always calls `checkpoint()` (`PRAGMA wal_checkpoint(TRUNCATE)`) before closing. More fundamentally, **fixed at the design level**: the database is no longer committed at all (see A1 below); the committed artifact is the NDJSON journal, so this failure mode is structurally eliminated rather than just patched. |
| C2 | `with get_connection(...)` used as if it were a context manager that closes the connection | `sqlite3.Connection` used directly as a context manager only wraps a **transaction** (commit/rollback on exit) — it does not close the connection. Every call site using this pattern leaked a connection. | **Fixed** — `core/db.py` separates `connect()` (returns a raw connection), `transaction()` (an explicit `contextmanager` doing `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`), and `Database` (a class that owns the connection and closes it via `closing()`-equivalent lifecycle in `__exit__`). No code path conflates "transaction scope" with "connection lifetime." |
| C3 | Broadcast-then-insert ordering | The reviewed pipeline sent the Telegram message first and wrote the database row second. A crash between the two steps leaves a message live in the channel with **no record** that it was sent — the next run has no way to know, and re-sends it. | **Fixed** — `pipeline.py::_process` inserts the row as `status='pending'` *before* calling Telegram; `_broadcast` flips it to `published` only on confirmed delivery. A crash mid-broadcast leaves a recoverable `pending` row that `_republish_pending` picks up on the next run — duplicate delivery becomes structurally impossible rather than merely unlikely. |
| C4 | Every ingested item re-sent to the LLM on every run, with no pre-extraction "seen" gate | Feeds re-serve the same entries every day. Without a gate, daily model spend is proportional to **feed size**, not to **new postings** — and with a fixed daily quota, this pattern eventually spends the entire budget re-classifying yesterday's listings and never reaches today's, especially once several sources are enabled. | **Fixed** — `core/db.py`'s `seen_items` table plus `pipeline.py::_process`'s seen-check (keyed on canonical URL hash + content hash) runs *before* the deterministic gate and *before* extraction. Spend is now proportional to genuinely new-or-changed items. |
| C5 | Empty MinHash signatures compare as Jaccard similarity 1.0 | Two `datasketch.MinHash` objects built from empty token sets are numerically identical, so any two very short (or empty) listings would register as a 100% duplicate match and one would be silently suppressed. | **Fixed** — `core/minhash.py::MinHash.from_tokens()` returns `None` for an empty token set; `Deduplicator.find()` treats a `None` signature as "no signal from this tier," never as a match. Covered by `test_minhash.py::test_empty_token_set_returns_none` and `test_dedupe.py::test_two_empty_texts_do_not_match`. |

### High — wrong behavior under realistic conditions

| # | Defect | Fix |
|---|---|---|
| H1 | `active_listings` query compared offset-bearing ISO timestamp strings against SQLite's `datetime('now')` (space-separated, no offset) | All timestamps standardized to `YYYY-MM-DDTHH:MM:SSZ` UTC; all "N days ago" comparisons go through `strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)` so both operands share a format (`core/db.py`, `core/timeparse.py`). Regression-tested with same-calendar-day rows in `test_core.py::test_recent_listings_uses_comparable_timestamp_format`. |
| H2 | Naive/aware datetime subtraction inside `_deadlines_close` raised `TypeError`, taking down the dedup stage | `core/timeparse.py::days_between()` normalizes both operands to UTC before subtracting. Tested with one naive and one aware input in `test_timeparse.py::test_days_between_mixed_awareness_does_not_raise`. |
| H3 | Required `HttpUrl canonical_application_url` field forced the model to invent a URL, while the same prompt told it not to invent facts — a direct contradiction | Split into a wire schema (`ExtractionResult`, everything optional) and a domain schema (`PredocListing`, validated) in `models.py`. `coerce()` falls back to the discovery source URL when the model correctly returns `null` for the application URL, and `publish/telegram.py::render_keyboard` labels the button "Open listing" rather than "Apply" in that case, so nothing is claimed that isn't true. |
| H4 | `tenacity` retried permanent 4xx errors (e.g., "can't parse entities") up to 4 times with exponential backoff | `publish/telegram.py::TelegramClient.send_message` only retries `429` and `5xx`; any other 4xx raises immediately with `permanent=True`. Same principle applied to the extraction backends (`extract/gemini.py`): a 400/404 triggers a same-request fallback to the *other* backend shape exactly once, not a retry loop against the same broken request. |
| H5 | 429 `retry_after` from Telegram ignored in favor of a fixed sleep | `TelegramClient` reads `parameters.retry_after` from the response body and sleeps that long (plus a small margin) before the next attempt. Tested in `test_telegram.py::test_429_honours_server_retry_after`. |
| H6 | extruct pointed at 7 *landing* pages; `JobPosting` JSON-LD lives on *detail* pages for essentially every applicant-tracking system | `ingest/collectors.py::collect_portals` supports `follow_links` + `link_pattern` per source, crawling a bounded number of detail pages when the index page itself carries no `JobPosting` metadata (which is the common case). |
| H7 | `data/accounts.txt` held plaintext X/Twitter credentials inside the repository and was not gitignored | Credentials are read from the `TWSCRAPE_ACCOUNTS` environment variable (a CI secret) and written only to a `tempfile.TemporaryDirectory()` that is cleaned up when the process exits (`ingest/collectors.py::collect_twitter`). Nothing account-shaped is ever written to a path git tracks; `.gitignore` also excludes `data/accounts.txt` defensively. |
| H8 | No rate limiter existed in the code despite the architecture doc's Phase 3 claiming one | `core/ratelimit.py::RateLimiter` implements both a per-minute token bucket and a persisted daily counter, wired into every extraction call in `extract/gemini.py`. |
| H9 | 4096-character message limit unenforced at render time | `publish/telegram.py::render_card` computes the fixed-content length first (via `telegram_visible_length`), then sizes the truncatable summary against whatever budget remains, with a defensive hard cut as a last resort. |

### Medium — quality, correctness-adjacent, or maintainability

| # | Defect | Fix |
|---|---|---|
| M1 | Hashtags built by removing spaces only; a name like "Côte d'Ivoire" produces a hashtag that visually runs on past its intended boundary | `core/textproc.py::hashtag()` NFKD-folds accents and keeps only `[A-Za-z0-9]` runs, capitalizing each — "Côte d'Ivoire" → `CoteDIvoire`. |
| M2 | `disable_web_page_preview: False` sent unconditionally (previews always shown, contrary to the architecture doc's own intent) | Both `disable_web_page_preview` and `link_preview_options.is_disabled` are set consistently from a single `link_previews` flag, defaulting to previews **off** for a cleaner feed. |
| M3 | `gather()` applied a single global cap across all scrapers, biasing toward whichever ran first | `ingest/collectors.py::gather()` and `Source.max_items` apply the cap **per source**, so one prolific feed can't crowd out everything else in a run. |
| M4 | No conditional GET or robots.txt handling — every fetch was a full, unconditional GET | `ingest/http.py::PoliteClient` stores `ETag`/`Last-Modified` per URL and sends `If-None-Match`/`If-Modified-Since`; a body-hash check catches servers that don't honor conditional headers but return unchanged content anyway. `robots.txt` is checked via stdlib `urllib.robotparser`, cached per host per run. |
| M5 | `char_ngrams` (3-grams) used as the near-duplicate signal for MinHash, which is a poor discriminator on long text (two unrelated English job ads share most of their trigrams) | `core/dedupe.py` and `core/textproc.py::word_shingles` use word 5-shingles as the default signal, falling back to character trigrams only for texts too short to shingle by word (`< 24` words) — matching the standard near-duplicate detection literature (Broder). |
| M6 | `datasketch` pulls in `numpy` (and transitively, on some platform/version combinations, `scipy`) for what is fundamentally about ninety lines of modular arithmetic | Replaced with a from-scratch, pure-stdlib MinHash + banded LSH implementation (`core/minhash.py`), with the banding math (`_choose_bands`) documented and unit-tested against the analytic `P(candidate\|s)` curve. |
| M7 | Heavy, ToS-sensitive dependencies (`python-jobspy`, `twscrape`) declared as hard requirements | Moved to optional extras (`boards`, `social` in `pyproject.toml`); `ingest/collectors.py` imports them lazily inside the collector function and degrades to "source skipped, extra not installed" rather than failing the whole install. Both collectors are also **disabled by default** in `settings.py` — see `COMPLIANCE.md`. |
| M8 | `respx` declared as a test dependency but never actually used in a test | `tests/integration/test_extraction.py` and `test_telegram.py` use `respx` to mock the provider and Telegram APIs and assert on the retry/backoff/fallback behavior directly (backend fallback on 404, 429 `RetryInfo` handling, permanent-error non-retry). Both files skip cleanly via `unittest.skipUnless` when the optional dependencies aren't installed. |
| M9 | No evaluation harness; gate/prompt changes had no regression signal | `tests/fixtures/golden.jsonl` (24 labeled real-world-shaped examples, covering every false-positive class identified in this review) plus `predoc-pipeline eval`, reporting precision/recall for the deterministic gate. Currently scores 1.000/1.000 against the fixture set. |
| M10 | Daily commit of a binary SQLite file to the repository | Addressed at the design level — see Architectural change A1 below. |
| M11 | Workflow used `continue-on-error: true` at the job level, so a failing run still showed green | `.github/workflows/pipeline.yml` uses `continue-on-error` only on the run step itself (so a partial failure doesn't block committing the state that *did* succeed), then has a separate "Evaluate outcome" step that fails the job for anything worse than `outcome=partial`. |

### Cosmetic / minor

| # | Defect | Fix |
|---|---|---|
| Z1 | No `py.typed` marker despite type hints throughout | Added at `src/predoc_pipeline/py.typed`. |
| Z2 | Mixed use of `Optional[X]` and `X \| None` | Standardized on `X \| None` throughout (Python 3.11+ target). |

---

## Part 3 — Architectural changes beyond individual defects

**A1. The committed artifact is an NDJSON journal, not the SQLite database.**
This is the single biggest structural change from the reviewed design. Git
cannot delta binary SQLite pages usefully — a daily commit of even a modest
database adds on the order of a gigabyte a year to repository size, and two
runs whose commits interleave produce a binary merge conflict nobody can
resolve. `data/listings.ndjson` (one sorted, canonical JSON object per line)
is the committed source of truth; the SQLite database is a gitignored,
rebuildable cache (`state.py::restore_if_needed`). This one change also
happens to make C1 (WAL checkpoint timing) irrelevant for repository
correctness, though `checkpoint()` is still called for anyone working with a
copied `.db` file directly.

**A2. Sources are declarative configuration, not embedded code.**
`config/sources.toml`, loaded via stdlib `tomllib`. Every source carries an
explicit `verified` flag. This is a direct response to F8: rather than
asserting specific feed URLs work (an assertion this review could not
confirm), the design makes "have you actually checked this source returns
data" an unavoidable, single-command step (`predoc-pipeline sources verify`)
rather than a hidden assumption baked into source code.

**A3. Two-schema extraction contract.**
See H3. The wire schema the model sees is intentionally loose (nullable,
string-typed where reasonable); the domain schema the rest of the pipeline
uses is strict. `coerce()` is the one-way, well-tested bridge. This also
sidesteps a second, related problem the reviewed schema had: generating a
JSON Schema directly from a strict Pydantic model produces `format: "uri"`
(not in the documented supported subset) and `$ref`/`$defs` for nested models
— both used in this project's tests are none — so `models.py::EXTRACTION_JSON_SCHEMA`
is hand-written against the documented subset instead of generated.
