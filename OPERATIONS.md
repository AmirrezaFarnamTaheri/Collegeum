# Operations runbook

For maintainers diagnosing a quiet channel or a source failing to produce
vacancies. Operational errors are written to logs and health artifacts by
default; **ordinary Telegram users never receive error alerts or logs**.

## First look: three places, in order

1. **`docs/data/health.json`** (rendered by the dashboard's footer health
   dot). Shows the last 30 runs with outcomes and per-source counts.
2. **The GitHub Actions run log** plus the `dlq-<run_id>` artifact uploaded
   on each run (`run.log` and `dlq-failures.json`). These are the detailed
   diagnostics, not bot messages.
3. **Optional dedicated Telegram administrator:** to explicitly opt in,
   set `TELEGRAM_OPERATIONAL_ALERTS_ENABLED=true` **and**
   `TELEGRAM_ADMIN_CHAT_ID` to a positive private chat ID **different**
   from `TELEGRAM_PUBLIC_CHANNEL_ID`. This is disabled by default; neither
   the public vacancy destination nor subscribers are ever fallback
   operational-alert recipients.

A known upstream EJME problem currently yields unresolvable `[nid]`
application links: that discovery pass is recorded as skipped and retried
later, rather than publishing invalid listings. The separately configured
EconJobMarket scraper continues to collect its own valid vacancies.
ifo source discovery follows `https://www.ifo.de/karriere-am-ifo` and
`/stellenangebot/` job links instead of the retired `/karriere` path.

## Common failure signatures

### "outcome=quota-stopped" in the run log, published count near zero

The daily model request budget was exhausted before the queue was cleared.
This is expected occasionally (a backlog after adding new sources, a busy
posting day) and self-heals: unprocessed items were never marked `seen`, so
they're retried tomorrow with a fresh quota.

If it happens **every day**: your `LLM_REQUESTS_PER_DAY` setting is higher
than what your account actually gets, or you've enabled enough sources that
daily new-item volume exceeds the free tier. Check the AI Studio console for
your account's actual current limit (see `ARCHITECTURE.md` §3.2 — the
provider does not publish a fixed table anymore) and either lower
`LLM_REQUESTS_PER_DAY` to match, tighten the deterministic gate, or disable a
high-volume, low-yield source.

### A source shows up in the "fetching but yielding nothing" alert

Run `predoc-pipeline sources verify` locally. Likely causes, roughly in
order of frequency:

- **The site redesigned and the feed URL moved or the JobPosting markup
  changed.** For a feed, try `predoc-pipeline sources discover <site-url>`
  against the site's homepage or careers-section root — it looks for
  `<link rel="alternate">` feed declarations. For a portal, view-source the
  detail page and check whether the `<script type="application/ld+json">`
  block with `"@type": "JobPosting"` is still there; if it moved from the
  index page to detail pages (or vice versa), adjust `follow_links` /
  `link_pattern` in `config/sources.toml`.
- **The source now requires a session/cookie/login it didn't before.**
  `PoliteClient` does not authenticate; if a source added a login wall,
  either find an unauthenticated equivalent or disable it.
- **robots.txt changed to disallow the path.** Check
  `<source-root>/robots.txt` directly. If it now disallows the pipeline's
  user agent, respect that — do not work around it.

### "extraction failed" errors accumulating in the DLQ

Check `dlq-failures.json` for the actual error string. Two provider-side
patterns to recognize:

- **`HTTP 400` mentioning schema/field names**: the provider likely changed
  something about the supported JSON-Schema subset. Compare
  `models.py::EXTRACTION_JSON_SCHEMA` against the current
  `ai.google.dev/gemini-api/docs/structured-output` page.
- **`HTTP 404` on both backends**: the model name in `GEMINI_MODEL` may have
  been retired. Check the current model list in the AI Studio console and
  update the setting.

A single stuck item (same error, same URL, every day) that isn't a systemic
issue: check the DLQ payload for that specific item — it's often a page that
returns almost no text (a blocked page, a JS-only render) and simply isn't
extractable. Safe to ignore; it will never accumulate cost since it's
retried, not cached as a permanent failure, but also never a `seen_items`
entry gets written for `stage=extract` failures by design (see
`pipeline.py::_process` — extraction failures are not marked seen, so they
retry indefinitely; if one is truly unextractable forever, that's a
low-priority nuisance, not a data-loss bug).

### The dashboard shows 404 or stale data

`docs/data/listings.json` and `health.json` are written by the pipeline run
and committed by the workflow, then deployed by
`.github/workflows/pages.yml` on any push touching `docs/**`. If the
dashboard looks stale:

1. Check whether the `pipeline.yml` run actually committed anything
   (`git log -- docs/data/listings.json`) — no new listings means no new
   commit, which is correct behavior, not a bug.
2. Check whether the `pages.yml` workflow ran and succeeded after the last
   `pipeline.yml` commit.
3. As a manual fix, run `predoc-pipeline dashboard` locally against your own
   copy of `data/predocs.db` (or after `restore_if_needed` rebuilds it from
   the journal) to regenerate the JSON files without a full pipeline run.

### The ingestion snapshot is over eight hours old

The `ingestion-freshness-recovery.yml` workflow checks the latest public
`docs/data/health.json` after a successful `main` CI push or a successful
scheduled `telegram-sync`. It is **not** an additional GitHub cron: scheduled
events can be delayed or dropped by GitHub. The fallback uses only GitHub's
built-in `GITHUB_TOKEN` (Actions write permission) to request a **new**
`workflow_dispatch` on `main`; it cannot directly publish or change journals.

Recovery is deliberately conservative:

- It requests a new ingestion only if the published health timestamp is **older
  than eight hours**, the Actions API is readable, and **all** known ingestion
  runs predate that health timestamp and are completed.
- If an ingestion is already queued/running, it leaves it alone.
- If a newer run completed but failed to update the public snapshot, it **does
  not retry**: investigate logs, state checkpointing, and dashboard persistence.
  Likewise, malformed timestamps or unavailable run history never authorize a
  duplicate publish.
- Any requested run uses the normal `predoc-pipeline` workflow (not an old
  rerun) and existing `predoc-bot` concurrency and idempotent publication
  journals. A successful watchdog **does not** prove an ingestion succeeded.

For a manual read-only watchdog check, select **Actions → ingestion-freshness-
recovery → Run workflow**, retaining `check_only=true`. For targeted collection
acceptance without Telegram sends, select **Actions → predoc-pipeline → Run
workflow** on `main` with `dry_run=true`; enable a normal production run only
after verifying the checks. Inspect the ensuing new run ID and the fresh health
timestamp, not just the watchdog status.

This is a **best-effort in-repository fallback**, not an independent scheduler.
If both main CI and Telegram sync stop running, GitHub supplies no further
`workflow_run` event. For a strict ingestion freshness SLA, use a separate
external observer/scheduler with a narrowly scoped GitHub Actions dispatch
credential and the same no-newer-run safety gate. See issue #52.

### Duplicate listings appearing in the channel

This should be structurally very hard to hit (see `REVIEW.md` C3 and C5),
but if it happens:

1. Check whether the two "duplicate" messages have **different**
   `apply_url`s. If so, Tier 1 (exact URL match) correctly didn't catch it —
   check whether Tier 2/3 should have. Pull both listings'
   `institution`/`title`/`summary` from the database and manually compute
   `Deduplicator.signature(...).jaccard(...)` to see how close they actually
   were to the threshold; this is real signal for whether
   `DEDUPE_JACCARD_THRESHOLD` needs adjusting.
2. Check `run_log` for whether a run crashed between insert and broadcast
   for the first copy, and the *second* "duplicate" is actually
   `_republish_pending` correctly recovering a genuinely-pending item (in
   which case this is not a duplicate at all — check the Telegram channel's
   actual message history against `telegram_message_id` in the database).

### X/Twitter ingestion or broadcast failures

Run `predoc-pipeline test-x` or `predoc-pipeline search-x` locally to diagnose:

- **`HTTP 401 Unauthorized`**: Invalid or expired OAuth credentials. Verify `X_CONSUMER_KEY`, `X_CONSUMER_SECRET`, `X_ACCESS_TOKEN`, and `X_ACCESS_TOKEN_SECRET` in `.env` or repository secrets.
- **`HTTP 403 Forbidden` ("duplicate content")**: X rejects identical status text posted within a short interval. The pipeline logs this and continues without dropping listings.
- **`HTTP 429 Too Many Requests`**: X API v2 rate limit exceeded (e.g., search or posting limits on Free/Basic tiers). Ingestion will retry on the next scheduled run. When `X_BEARER_TOKEN` reaches monthly search caps, clear it from the active settings and process environment before setting `XQUIK_API_KEY`, as the official API takes precedence whenever `X_BEARER_TOKEN` is configured.

### Querying and verifying listings locally

To inspect whether a position was discovered, accepted, or expired without opening SQLite:

```bash
predoc-pipeline search "institution or keyword"          # active listings only
predoc-pipeline search "institution or keyword" --all    # include pending, closed, and expired
```

## Routine maintenance

- **`predoc-pipeline stats`** — inspect current database listing counts and outcomes of the last 10 runs.
- **`predoc-pipeline test-telegram`** — send a verification message to ensure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_PUBLIC_CHANNEL_ID` are valid.
- **`predoc-pipeline test-x`** — post a test tweet to verify X broadcaster OAuth credentials.
- **`predoc-pipeline search-x [query]`** — test live X search queries using either official API v2 or Xquik.
- **`predoc-pipeline vacuum`** — prune expired DLQ and seen-item entries and compact the SQLite database file.
- **`predoc-pipeline sources verify`** — check reachability and response size for every enabled source in `config/sources.toml`.
- **Review `docs/data/health.json` weekly** — monitor per-source yield to identify dead feeds or silent scrapers.
- **Re-run `predoc-pipeline eval`** — verify deterministic gating precision and recall against `tests/fixtures/golden.jsonl` when modifying patterns in `core/gating.py`.

## Escalation / when to actually worry

Everything above is designed to fail safely: extraction failures retry, DLQ
entries are visible, and a single dead source doesn't affect the others. The
critical escalation event is **credential compromise**:
- If `TELEGRAM_BOT_TOKEN` leaks: revoke and regenerate immediately via
  [@BotFather](https://t.me/BotFather), then update the repository secret.
- If X credentials leak: revoke the keys and access tokens in the X Developer
  Portal and update repository secrets.
- Note that `export_feed()`'s RSS feed and the GitHub Pages dashboard operate
  independently of broadcast tokens and continue updating even during broadcast outages.
