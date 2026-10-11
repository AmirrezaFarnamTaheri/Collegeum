# Telegram subscriptions and operations

The bot uses the existing Collegeum Bot API token and scheduled GitHub Actions.
It has two deliberately separate surfaces:

- **Subscriber chat:** Each person privately selects role topics and independently
  opts into Iran-based and/or globally remote career feeds with `/start` or
  `/settings`. Nothing is subscribed by default. `/latest` previews the
  newest matching listings, and `/stop` erases personal subscription and
  delivery state.
- **Admin chat:** The exact positive private ID in `TELEGRAM_ADMIN_CHAT_ID` may
  use `/admin`. Telegram native inline menus provide overview, recent runs,
  queue/uncertain sends, cache/source counts, and a **confirmed** pause/resume
  switch for private notifications only. The "Run pipeline in GitHub" link
  opens the authenticated GitHub Actions workflow; the bot does not carry an
  additional GitHub PAT or allow arbitrary shell commands.

Subscriber IDs, interests, feedback marks, callback IDs, and private delivery
receipts are stored in **Fernet-encrypted** `data/feedback.enc`. This requires
`FEEDBACK_ENCRYPTION_KEY` (created using `predoc-pipeline feedback-key`);
without the key, subscriptions are refused and no subscriber data is saved
in plaintext. The public dashboard/export remains entirely unaffected by
private subscription preferences. The bot does not expose other users'
subscriptions, admin logs, or delivery state.

## Sources and classification

Academic listings keep the existing Collegeum pipeline, data journal, and
publication destinations. The private dispatcher matches predoc, PhD and
postdoc categories from stored, published and still-open academic listings.
The existing owner-only feedback buttons continue working.

Career listings are a **separate lightweight feed**, not fed into the academic
gate/model, public dashboard, channel broadcast or X:

| Market | Source | Selection and limits |
|---|---|---|
| Remote | [Jobicy public API](https://jobicy.com/jobs-rss-feed) | Only jobs explicitly marked Anywhere/Worldwide/Global/Iran in `jobGeo`; title matched to role; one request per four-hour cycle |
| Iran-based | [Jobinja](https://jobinja.ir) | Conservative HTML job-link parser for Iranian employer listings; rotate one of four Persian queries per cycle; at most 30 cards. Does not call an unofficial paid API. |

Role categories: data scientist, data analyst/BI, economics/management
consulting, and economic/research analyst. Do not classify a generic analytics
keyword in a description as a job-title match. A country-restricted remote
job must **not** appear under worldwide-remote. "Worldwide" is a job-board
label, not a guarantee of employment eligibility or payment from Iran.
The Jobinja adapter is best-effort: when its HTML/robots/access changes,
the source reports an error and produces zero results rather than invent
postings. Its coverage and live reliability require monitored verification.

The only career-publication record is `data/career_jobs.ndjson`, keyed by a
stable URL hash. It stores canonical URLs, source, role, country/remote scope,
employer, title, and first-observed time; it stores **no user data**. It keeps
up to 3,000 records for 21 days, saved by atomic replacement and fsync.
Unchanged jobs retain first-seen dates, so regular polling does not trigger
repeat alerts. Scheduled pipeline workflow commits this journal.

## Message lifecycle and recovery

```text
Scheduled 4h collection (rotating source cohorts)
  -> existing academic gate/extraction/deduplication -> academic listings journal
  -> small opt-in career feeds (max 2 HTTP fetches) -> career jobs journal

Telegram sync (~30 minutes while scheduled)
  -> getUpdates(offset)
  -> verify one-to-one private chat/user identity
  -> save encrypted subscription + callback ID atomically
  -> advance offset only after state persistence
  -> match published listings to each subscriber's topic/scope timestamps
  -> persist "sending" intent BEFORE sendMessage
  -> sendMessage -> persist "sent" acknowledgement (message ID)
                   or "uncertain" after ambiguous network outcome
  -> commit encrypted file and Telegram cursor to main
```

This is an **at-most-once automatic retry policy** for uncertain delivery, not
magic exactly-once Telegram delivery. An acknowledgement can be lost after the
remote API accepts the message. Never replay an in-flight/uncertain item
without checking the destination. Use:

```sh
predoc-pipeline subscriber-reconcile CHAT_ID 'career:KEY' --confirmed-sent
predoc-pipeline subscriber-reconcile CHAT_ID 'career:KEY' --confirmed-not-delivered
```

The second form only applies after independently verifying no message arrived.
`/stop` removes the subscriber's saved choices and receipt history. A newly
subscribed role/scope never backfills postings first published before opt-in.

Budget is at most 4 attempted notifications per user and 24 across users per
sync; the next run continues unmatched items. A rotating last-recipient
cursor avoids always servicing the first users first. User-specific
notification pause does not block collection or the legacy public channel.

## Cadence, cache and failure semantics

- The previous 6-hour pipeline cron is now **every 4 hours**. Automated
  scheduled executions poll alternating deterministic halves of enabled
  academic boards, syndicated feeds and portals: every enabled source remains
  eligible once per 8 hours.
  Manual pipeline runs and `--only` overrides still scan selected/all sources.
- Per-run `max_details_per_run` and `recheck_max_per_run` were halved.
  The pipeline and Telegram jobs share a single serialized workflow
  concurrency group to avoid racing on committed state.
- Jobicy requests follow its public API fair-use guidance (not more than one
  pass per hour); this project polls at most once per 4 hours. Conditional
  requests use the ordinary polite HTTP cache when a reusable response body
  exists. The SQLite cache is ephemeral on hosted runners; persistent
  deduplication relies on NDJSON journals and encrypted delivery receipts.
- Telegram update cursors and subscriber state are written and committed
  together. If a write fails, the update is replayed and callbacks are
  idempotently recognized. Partial publishing never erases prior receipts.
- Admin views show only aggregate subscriber/outbox counts and run summaries.
  The queue view distinguishes pending academic records, uncertain public
  channel deliveries, uncertain private deliveries and dead-letter events.
  It does **not** silently clear or replay ambiguous messages.
- Per-source errors land in dead-letter records and raise partial-run
  telemetry; inaccessible Jobinja pages are not equivalent to empty job
  markets. Enabling a workflow on `main` without `FEEDBACK_ENCRYPTION_KEY`
  leaves subscriber handling inactive.

The admin panel intentionally does not run a publicly reachable web server:
a static GitHub Pages admin surface could not safely authenticate writes or
protect subscriber data without adding a separate trusted backend.
