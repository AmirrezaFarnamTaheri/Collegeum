# Durable LinkedIn Search Rotation Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist query-level progress across four-hour Collegeum workflow cycles, consume all observations collected before a bounded soft deadline, rotate all three research audiences fairly, and avoid repeating a fully completed query within 48 hours.

**Architecture:** A per-source JSON ledger records a stable search identity (source/keyword/location), last complete coverage point, in-progress pagination cursor, and a bounded candidate replay buffer. The LinkedIn scraper obtains a fair due-query schedule from this ledger and runs within a monotonic time/request budget. The existing single checkpointing GitHub Actions job commits candidate journals and query ledgers together, while all notifications continue through the unchanged single-writer pipeline.

**Tech Stack:** Python 3.11/3.12, asyncio, Pydantic source config, pytest, GitHub Actions, existing LinkedIn Jobs adapter and journal.

## Global Constraints

- The scheduler is not an always-on service and does not increase workflow frequency; existing workflow remains every four hours.
- Revisit a fully completed search no sooner than 48 hours after its coverage point. A partially completed search resumes pagination without re-running a completed page unless pagination staleness requires restarting from page 0.
- Never update the last-complete timestamp on HTTP errors, pagination truncation, quota stop, parser failures or interrupted time-box.
- Lookback must be at least the elapsed days since the last successful coverage point plus a one-day overlap, rounded UP to a provider-supported date window; record when this exceeds the supported maximum. The first attempt uses a 30-day lookback.
- Enforce bounded request count, bounded wall time, bounded page depth and bounded candidate replay. Stop immediately on access-denial responses; never attempt account/proxy/access-control workarounds.
- Preserve original LinkedIn URL identity; no direct writes to historical listings or Telegram delivery receipts. Store per-source search ledgers alongside journal state in the SAME final git checkpoint.
- Separate economics/predoc and Life Sciences search state. Incremental replay must not falsely claim an employer-confirmed open, eligible or funded position.
- New/overdue queries cannot be starved by very long pending pagination; one actor writes each per-source ledger.
- Tests use offline fake endpoints; never call LinkedIn during CI.

---

### Task 1: Pure, persistent query-level scheduler

**Files:**
- Create: `src/predoc_pipeline/boards/scrapers/linkedin_scheduler.py`
- Test: `tests/boards/test_linkedin_scheduler_20261101.py`

**Interfaces:**
- Consumes: configured keyword/location pool, exact UTC time and optional previous ledger.
- Produces: `load_state(path)`, `save_state(path, state)`, `select_due_queries(...)`, `query_window_seconds(...)`, `record_page(...)` and `record_failure(...)`.

- [ ] **Step 1: Add failing fixture tests** for 48-hour cooldown, first-seen fairness, interrupted cursor, stale pagination reset, date-window rounding/overlap, out-of-order clocks, corrupt ledger, empty pages, page-depth limits, failure backoff, deduped replay, preservation of old listing identities.
- [ ] **Step 2: Verify RED** with `PYTHONPATH=src pytest tests/boards/test_linkedin_scheduler_20261101.py -q` (missing module/contract).
- [ ] **Step 3: Implement scheduler** with bounded validated JSON state, stable per-source keys, atomic write via temporary file and rename, and a finite, deterministic due priority. Keep a bounded replay buffer, record deferred/coverage gaps.
- [ ] **Step 4: Verify GREEN** using the same focused command.
- [ ] **Step 5: Run affected integration checks** with `PYTHONPATH=src pytest tests/boards -q`.
- [ ] **Step 6: Commit scheduler and passing tests** to feature branch.

### Task 2: Time-boxed LinkedIn scraper integration

**Files:**
- Modify: `src/predoc_pipeline/boards/scrapers/linkedin_scraper.py`
- Modify: `tests/boards/test_linkedin_econ_phd_coverage_20261101.py`
- Test: `tests/boards/test_linkedin_checkpointed_discovery_20261101.py`

**Interfaces:**
- Consumes: scheduler ledger, scraper config options `checkpoint_path`, `time_budget_seconds`, `cooldown_hours`, `max_lookback_days`.
- Produces: stable posting list and `search_diagnostics`; persists only its own source ledger.

- [ ] **Step 1: Add failing fake-HTTP scenarios** for completed and partial searches, retry without duplicate jobs, saved offsets, short/empty pages, deny/429 stops, clock drift and budget expiry.
- [ ] **Step 2: Verify RED** with focused pytest.
- [ ] **Step 3: Integrate scheduler** behind explicit `checkpoint_path`, retaining legacy branch behavior for existing tests without persistence. Preserve all source limits and stable URL de-duplication.
- [ ] **Step 4: Verify GREEN** with focused pytest, lint, and mypy.
- [ ] **Step 5: Run affected integration tests** using `pytest tests/boards tests/integration/test_life_sciences.py -q`.
- [ ] **Step 6: Commit passing changes**.

### Task 3: Production checkpoint and publication safety

**Files:**
- Modify: `config/sources.toml`, `config/life_sciences.toml`, `.github/workflows/pipeline.yml`
- Modify: `src/predoc_pipeline/ingest/life_sciences.py`
- Test: `tests/integration/test_linkedin_scheduler_persistence_20261101.py`

**Interfaces:**
- Consumes: two distinct per-source checkpoint paths.
- Produces: checkpointed ledgers next to `data/listings.ndjson` and `data/career_jobs.ndjson`, source diagnostics.

- [ ] **Step 1: Add failing tests** for missing ledger, malformed-but-recoverable ledger, replay while eligible, life source candidate cap, source timeout and single-commit list.
- [ ] **Step 2: Verify RED** in CI.
- [ ] **Step 3: Configure two distinct ledgers and short per-run timeboxes**, update Life Sciences timeout for bounded slow discovery, include both ledgers in existing one-writer workflow state checkpoint, and preserve discovery buffering even when downstream work is deferred.
- [ ] **Step 4: Verify GREEN** with offline pytest.
- [ ] **Step 5: Run full Python 3.11/3.12 CI, Telegram worker, release and single-file build** on exact final commit.
- [ ] **Step 6: Commit, review and leave draft pending operator activation requirements**.

## Externally observable decisions

- Initial 48-hour revisit, one-day overlap and 30-day initial lookback are approved from the discussion.
- The configured 96/24 request caps remain hard ceilings, not targets. Proposed soft collection budgets are 240/75 seconds, respectively; the worker ends earlier when no query is eligible.
- Complete scans at a provider-imposed pagination ceiling are recorded as truncated, not confidently complete.
- No automatic production merge or live LinkedIn rate experiment is implied by CI success. Provider visibility and authorization are independent from scheduler correctness.
