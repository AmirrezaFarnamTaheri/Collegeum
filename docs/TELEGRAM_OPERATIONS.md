# Telegram subscriptions and operations

The bot uses the existing Collegeum Bot API token and scheduled GitHub Actions.
It has two deliberately separate surfaces:

- **Subscriber chat:** Each person privately selects role topics and independently
  opts into Iran-based and/or globally remote career feeds with `/start` or
  `/settings`. Nothing is subscribed by default. The native Telegram interface
  provides a compact home overview, separate academic/career/market screens,
  select-all or clear-all controls, English/Persian language selection,
  personal pause/resume, `/delivery` settings (individual alerts or a daily
  digest, limits of 3/6/10 opportunities per day, optional 22:00-08:00 quiet
  hours, and explicitly selected time zone), `/sources` health status and
  paginated `/latest` previews. `/stop` and `/delete` require confirmation before
  removing active subscription and delivery state (historical Git repository
  versions remain subject to their own retention policy).
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
| Remote | [Jobicy public API](https://github.com/Jobicy/remote-jobs-api) | Only jobs explicitly marked Anywhere/Worldwide/Global in `jobGeo`, excluding Iran-restricted posts; title matched to role; max two cursor pages plus one batch status check per four-hour cycle |
| Iran-based | [Jobinja](https://jobinja.ir) | Conservative HTML job-link parser for Iranian employer listings; rotate one of four Persian queries per cycle; at most 30 cards. Does not call an unofficial paid API. |
| Iran-based | [IranTalent](https://www.irantalent.com/en/jobs) | Public unfiltered listing page at `/en/jobs`; validate canonical detail paths and explicit Iranian location before accepting a matched role. At most one request per cycle. No undocumented private API. |

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

Requests from a single non-owner subscriber are bounded to 20 interactive
commands per scheduled sync to protect other subscribers from command floods.
Critical stop, delete, and pause requests always bypass this limit.

## Message lifecycle and recovery

```text
Scheduled 4h collection (rotating source cohorts)
  -> existing academic gate/extraction/deduplication -> academic listings journal
  -> opt-in career feeds (up to two Jobicy pages, one status check, one Jobinja fetch)
  -> deduplicated career jobs journal + data/career_health.json

Telegram inbox job (~30 minutes during configured dayparts)
  -> getUpdates(offset, limit=30)
  -> verify private chat ID == user ID
  -> save encrypted subscription + callback ID before advancing offset
  -> match new academic/career listings to each user's opt-in timestamp
  -> write untracked private batch and encrypted "sending" intents
  -> GIT CHECKPOINT: commit encrypted feedback + Telegram offset on main
  -> ONLY ON CHECKPOINT SUCCESS: sendMessage for reserved batch
  -> persist "sent" acknowledgement / "uncertain" / "rejected" disposition
  -> GIT CHECKPOINT: commit encrypted acknowledgements on main
  -> fail run if stage or checkpoint failed; preserve recovery information
```

This is an **at-most-once automatic retry policy** for uncertain delivery, not
magic exactly-once Telegram delivery. An acknowledgement can be lost after the
remote API accepts the message. Never replay an in-flight/uncertain item
without checking the destination. Use:

```sh
predoc-pipeline subscriber-reconcile CHAT_ID 'career:KEY' --confirmed-sent --message-id 123
predoc-pipeline subscriber-reconcile CHAT_ID 'career:KEY' --confirmed-not-delivered
# See counts without exposing identifiers:
predoc-pipeline subscriber-pending
# On a trusted private operator terminal only, show full recovery keys:
predoc-pipeline subscriber-pending --show-ids
```

The second form only applies after independently verifying no message arrived.
For a local operator checkout, the encrypted `data/feedback.enc` must then be
committed and pushed to the scheduled workflow's `main` branch before the
next run; editing a local file alone does not update the hosted worker. Never
commit the decrypted state, outbox batch, bot tokens, or private terminal output.
When a permanent Bot API 400 rejects invalid message markup, the delivery is
quarantined as `rejected` and shown in the admin queue rather than retried
every half hour. HTTP 429 is deferred, without holding the runner through
unbounded `retry_after` waits. `sending` and `uncertain` records require
remote verification before resetting them. `/stop` removes the subscriber's
active choices and receipts from the current encrypted file, but previous Git
commit snapshots remain in repository history; this is not a historical erasure
guarantee. A newly subscribed role/scope never backfills notifications first
published before opt-in. `/latest` is an explicit user-requested preview of
current matching opportunities, including positions published before opt-in.

Individual delivery is bounded to 4 attempted messages per user per sync and
24 Telegram messages across users per sync. Per-user daily limits of 3, 6 or
10 opportunities (default 6) count sent and ambiguous receipts. Daily
digest mode groups up to four jobs in one checkpointed message after 09:00
local time, with durable per-job receipts. Optional quiet hours suppress
new planning between 22:00 and 08:00 in the chosen time zone. A rotating
last-recipient cursor avoids always serving the first users first.
Personal pause does not block source collection or public publication.

## Cadence, cache and failure semantics

- The previous 6-hour pipeline cron is now **every 4 hours**. Automated
  scheduled executions poll alternating deterministic halves of enabled
  academic boards, syndicated feeds and portals: every enabled source remains
  eligible once per 8 hours. Public source-attempt timestamps are stored in
  `data/source_rotation.json` to catch up missed cron slots and avoid
  immediate duplicate polling when a scheduled run is delayed.
  Manual pipeline runs and `--only` overrides still scan selected/all sources.
- Per-run `max_details_per_run` and `recheck_max_per_run` were halved.
  The pipeline and Telegram jobs share a single serialized workflow
  concurrency group to avoid racing on committed state.
- Jobicy requests follow its public API fair-use guidance. This project uses
  at most two cursor pages and one status check for up to 100 IDs per four-hour
  cycle, plus one Jobinja keyword request and one unfiltered IranTalent
  listing request. Only a verified `closed` result
  suppresses a remote job; an `unknown` result or network failure does not
  establish closure. Conditional requests use the ordinary polite HTTP cache when a
  reusable response body exists. The SQLite cache is ephemeral on hosted
  runners; persistent deduplication relies on NDJSON journals and encrypted
  delivery receipts. Successful private receipts are kept for 45 days;
  uncertain/rejected/sending records remain until reviewed. Source polling
  counts, retrieval timestamps and errors are saved in
  `data/career_health.json` for the private admin panel.
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


## Bot interface and API choice

Collegeum uses official Telegram Bot API features: short command menus,
scoped administrator commands, an optional Persian command list, inline
keyboards, callback acknowledgements, message edits for navigation,
pagination, source-status screens, and URL buttons on delivered cards.
See [Telegram's bot interface guidance](https://core.telegram.org/bots/features)
and [Bot API reference](https://core.telegram.org/bots/api). The bot is not a
Mini App and needs no additional HTML UI backend.

Jobs from Iranian platforms use public listing pages when allowed. There is
no verified official public job-search API for Jobinja, Jobvision, IranTalent,
or e-estekhdam in this release. Jobvision's candidate-profile API is **not**
used to collect vacancies. A separate provider comparison, access constraints,
and the necessary verification gate for a future partner API are documented in
[IRAN_JOB_PROVIDERS.md](IRAN_JOB_PROVIDERS.md).

The subscriber `/sources` panel distinguishes healthy, empty, error,
degraded, idle and stale (>12 hours) statuses and displays only
allowlisted provider names/counts; it does not return arbitrary source errors,
subscriber data, credentials, or full HTTP response bodies. The admin can
inspect counts and limited, escaped source error summaries.

The source/job card UI can preview existing opportunities without marking
them as delivered. Push notifications remain **new-after-opt-in** only.


## Optional private repository for subscriber state

Public Git stores only Fernet ciphertext, but past snapshots remain retrievable.
For a stronger privacy boundary, configure a **different private GitHub
repository** containing `data/feedback.enc` and `data/telegram_state.json`.
Set the public Collegeum repository's Actions variable
`PRIVATE_STATE_REPO=OWNER/PRIVATE_REPO` and the Actions secret
`PRIVATE_STATE_TOKEN` to a narrowly scoped token with Contents write access
to that private repository. Scheduled workflows check its GitHub `private`
flag before accessing subscriber data; a public target is rejected.

**Migrate before enabling the variable.** In a trusted checkout, copy the
current encrypted state files into the private repository and commit/push them.
A configured private backend refuses to start when a required private file is
missing but an old public checkout still contains it. Never create a new
empty private state over active subscribers. Confirm the private checkout
succeeds and every checkpoint goes to the private repository before stopping
public state commits. Once verified, remove the tracked current encrypted
state and public offset files from the public repository's current tree;
previous public Git versions remain accessible. Token rotation, legacy Git
history removal, private-repository history retention, and actual subscriber
erasure still require explicit operator procedures. No code can retroactively
revoke copies of old Git commits.

If `PRIVATE_STATE_REPO` is unset, the legacy encrypted-in-public-repository
mode remains active for backwards compatibility. Production deployments with
unrestricted subscriber enrollment should use private storage.


### Fernet key rotation

On a trusted operator checkout (never in public CI logs), pause all scheduled
state-writing jobs, load the current authoritative encrypted file, set the old
`FEEDBACK_ENCRYPTION_KEY` and new `FEEDBACK_NEW_ENCRYPTION_KEY` in the local
environment, and run `predoc-pipeline subscriber-rotate-key`. The command
validates the new Fernet key, atomically re-encrypts the active file, verifies
it can be decrypted, and prints neither key. Commit the rotated ciphertext
to the configured state repository, update the Actions
`FEEDBACK_ENCRYPTION_KEY` secret, then resume the jobs. Old Git commit
snapshots remain decryptable using the old key; rotation does not erase those
historical copies.

## Standalone one-file distribution

The generated `compile_project.py` is **not committed** to source control.
Ordinary source pushes produce a verified, downloadable GitHub Actions artifact
in `build-single-file` (retained for 14 days). Publishing a GitHub Release
attaches the verified `compile_project.py` as a release asset. To generate and
verify it locally, run `make verify-single-file`. The source archive and
Python wheel contain the source and tooling rather than the giant generated
materializer, which is obtainable separately.
