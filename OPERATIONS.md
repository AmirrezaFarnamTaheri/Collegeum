# Operations runbook

For the person who gets the alert (or notices the channel has gone quiet)
and needs to know what to check, in order.

## First look: three places, in order

1. **The Telegram admin chat** (`TELEGRAM_ADMIN_CHAT_ID`), if you configured
   one. `pipeline.py::_maybe_alert` sends here on three conditions:
   consecutive empty runs past `EMPTY_RUN_ALERT_THRESHOLD` (default 3), three
   or more sources fetching successfully but yielding zero items, or a run
   stopping early on quota exhaustion.
2. **`docs/data/health.json`** (rendered by the dashboard's footer health
   dot). Shows the last 30 runs with their outcome, item counts, and error
   counts — this is the fastest way to see *when* something changed.
3. **The GitHub Actions run log**, plus the `dlq-<run_id>` artifact uploaded
   on every run (`run.log` and `dlq-failures.json`) — the full detail behind
   the summary in (2).

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
- **`HTTP 429 Too Many Requests`**: X API v2 rate limit exceeded (e.g., search or posting limits on Free/Basic tiers). Ingestion will retry on the next scheduled run. When `X_BEARER_TOKEN` reaches monthly search caps, set `XQUIK_API_KEY` to route searches through the Xquik proxy.

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
