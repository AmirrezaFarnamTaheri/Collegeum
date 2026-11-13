# Non-US Economics PhD Telegram and Favorites Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add eligible non-US Economics PhD positions to the Telegram channel, safely backfill historical positions once, and let every Telegram reader save private favorites through the existing bot.

**Architecture:** Retain original website/X route, adding independent Telegram eligibility, send state, and a historical candidate scan. Render URL deep links carrying stable 16-hex listing keys, with per-user private favorites in the Worker Durable Object and encrypted polling fallback.

**Tech Stack:** Python 3.12, SQLite, NDJSON journal, pytest, JavaScript Cloudflare Worker Durable Objects, Node test runner, GitHub Actions.

## Global Constraints

- No production sends, webhook changes, or deployment in this PR.
- Existing website/X and predoc routing, original `published_at`, `x_post_id`, owner marks, and private alert receipts must be preserved.
- US/unknown-country PhDs, generic admissions, completed-PhD research jobs and unrelated subjects never enter the new channel cohort.
- Unknown availability must not be presented as independently verified open.
- Confirmed Telegram acknowledgements are durable; uncertain sends are held, not blindly retried.
- No public personal favorites data or IDs; private users must authenticate by Telegram chat/sender ID.

---

### Task 1: Multi-destination eligibility and publication state

**Files:**
- Modify: `src/predoc_pipeline/routing.py`, `src/predoc_pipeline/core/db.py`, `src/predoc_pipeline/state.py`
- Test: `tests/integration/test_non_us_econ_phd_channel.py`

**Interfaces:**
- Consumes: `Router.position_kind(...)`, `Router.channel_for(...)`, existing `Database` rows/journal
- Produces: `Router.telegram_phd_eligible(...)`, `Router.destinations(...)`, independent `telegram_delivery_state` and confirmation on rows

- [ ] **Step 1: Add failing tests.** German Economics doctoral vacancy yields web+Telegram, while US, unknown, non-Economics, postdoc/qualified staff are excluded; legacy predocs unchanged; confirmed/uncertain receipts survive journal round trip.
- [ ] **Step 2: Verify red.** GitHub CI Python tests show missing new routing/state interfaces.
- [ ] **Step 3: Implement minimum.** Add narrow Economics work-location check; additive destinations; migrate state on old rows; preserve monotonically imported confirmed/uncertain receipt evidence; do not change preexisting status/publication timestamps.
- [ ] **Step 4: Verify green.** Focused pytest passes.
- [ ] **Step 5: Integration.** Routing/regression and state reconciliation suites pass.
- [ ] **Step 6: Commit passing files.** `feat: support additive Telegram PhD routing and independent receipts`.

### Task 2: Historical backfill and deep-link publication

**Files:**
- Modify: `src/predoc_pipeline/pipeline.py`, `src/predoc_pipeline/publish/telegram.py`, `src/predoc_pipeline/settings.py`, `.env.example`
- Test: `tests/integration/test_telegram_phd_backfill.py`

**Interfaces:**
- Consumes: `Router.destinations`, `Database.active_listings()`, independent delivery receipts
- Produces: bounded historical Telegram backfill; `render_keyboard(...)` and `render_digest_batches(...)` with per-item Save links

- [ ] **Step 1: Add failing tests.** Historical already-web-published Economics PhD gets queued; existing acknowledgements skip; second run no repeat; missing credentials/retries do not unpublish website; keyboard deep links resolve correct numbered items.
- [ ] **Step 2: Verify red.** CI highlights absent backfill/button behavior.
- [ ] **Step 3: Implement minimum.** Build journal-derived eligible backfill queue with verification, bounded batches, historical label, initial per-destination acknowledgements and uncertain holds. Add deep links only with valid configured bot username.
- [ ] **Step 4: Verify green.** Focused pytest passes.
- [ ] **Step 5: Integration.** Publication, Telegram, X and pipeline suites pass.
- [ ] **Step 6: Commit.** `feat: backfill historical Economics PhDs and add channel save links`.

### Task 3: Per-user favorites in webhook and polling

**Files:**
- Modify: `cloudflare/telegram/worker.mjs`, `cloudflare/telegram/subscribers.mjs`, `src/predoc_pipeline/publish/bot.py`, `src/predoc_pipeline/publish/feedback.py`, `src/predoc_pipeline/publish/cloud.py`
- Test: `cloudflare/telegram/worker.test.mjs`, `tests/integration/test_telegram_favorites.py`

**Interfaces:**
- Consumes: `/start f_<16hex>` and `fav:<action>:<key>` callbacks; authenticated snapshot records, private encrypted store
- Produces: `/favorites`, `/bookmarks`, per-user idempotent Save/Remove, private paginated favorites, deletion, sync preservation

- [ ] **Step 1: Add failing tests.** Two users save same key separately; one removes without impacting the other; no alert enrollment; pre-snapshot save hydrates after sync; replay safe; invalid/forged identities ignored; /delete clears only user's records.
- [ ] **Step 2: Verify red.** Worker and Python suites reject missing features.
- [ ] **Step 3: Implement minimum.** Add private user-namespace storage and callbacks with bounded 200-item quota and verified data lookup. Polling fallback uses encrypted private FeedbackStore, not owner marks. Keep polling/webhook consumers mutually exclusive; preserve stale-state safety.
- [ ] **Step 4: Verify green.** Worker and Python focused tests pass.
- [ ] **Step 5: Integration.** Worker npm tests, Python Telegram/private-state regression tests pass.
- [ ] **Step 6: Commit.** `feat: add user-scoped Telegram favorites`.

### Task 4: Documentation and verification

**Files:**
- Create: `docs/specs/2026-11-13-non-us-econ-phd-telegram-favorites-design.md`
- Modify: `docs/TELEGRAM_OPERATIONS.md`, `cloudflare/telegram/README.md`

**Interfaces:**
- Consumes: production configuration, rollback and test entry points
- Produces: documented rollout, preview, new bot username config, reconciled uncertain sends, user deletion

- [ ] **Step 1: Add docs verification assertions for config and publishing guard.**
- [ ] **Step 2: Verify expected docs/config failures.**
- [ ] **Step 3: Document staging order and preview, no automatic live activation or reset.**
- [ ] **Step 4: Verify guard tests.**
- [ ] **Step 5: Check repository Python, Worker test suites and GitHub PR CI; disclose any unavailable checks.**
- [ ] **Step 6: Commit.** `docs: document safe Telegram PhD and favorites rollout`.

## Unresolved product decisions

None: existing approved spec defines eligibility, retention, identity, and rollout safety. Configuration values such as the public bot username must be provided by the operator before enabling live deep links.
