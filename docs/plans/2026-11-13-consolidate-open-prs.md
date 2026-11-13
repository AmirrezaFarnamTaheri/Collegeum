# Consolidate Collegeum Open PRs Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate PRs #147, #152, and #153 into one reviewable integration PR with passing CI and no changes to production state.

**Architecture:** Use existing PR #153 as the isolated integration branch; transplant the small #152 cadence audit and #147 pinned GitHub Action upgrade without changing their semantics. Repair the currently failing #153 Python/Worker code, add regression coverage, and run a fresh CI evaluation. Retain external operational acceptance gates as separate from code-test success.

**Tech Stack:** GitHub Actions, Python 3.11/3.12, mypy/ruff/pytest, JavaScript/Cloudflare Worker, Node test runner, GitHub repository API.

## Global Constraints

- **No deployment or publication**: do not trigger production ingestion, send Telegram messages, modify webhook credentials, or rotate subscriber state.
- Keep current journal/publication data authoritative; never edit committed listing or encrypted private-state files to force tests green.
- Preserve existing eligibility and privacy constraints for the non-US Economics PhD and favorites features.
- Keep action dependencies pinned to full immutable upstream SHAs; do not replace pinning with version tags.
- Keep earlier PRs open until an integrated branch contains their code and fresh checks demonstrate equivalent behavior.
- Treat GitHub Actions run status as remote verification only; local shell network checkout is unavailable in this environment.
- Do not change historical test assertions unless supported by actual current journal/dashboard data.

---

### Task 1: Fix Telegram favorites Worker failures

**Files:** Modify `cloudflare/telegram/worker.mjs`. Test `cloudflare/telegram/worker.test.mjs`.

**Interfaces:** Consumes authenticated `/start f_<16hex>`, `fav:remove:<16hex>`, `/favorites`, and uploaded `listing:<64hex>` snapshot. Produces user-scoped saved favorites with open-advert navigation.

- [ ] **Red:** Reference CI #43419046578 fails Worker tests 109 (favorites removal) and 110 (post-sync hydration).
- [ ] **Fix:** Dispatch `fav:` callback according to colon-delimited protocol rather than pipe-delimited academic callbacks; convert snapshot storage Map values to an array before length checks; embed official advert link in the favorite list; correct the user ID regex in sync export.
- [ ] **Green:** Fresh `npm test` / `npm run check` in GitHub CI must pass, including tests 109 and 110; do not alter tests to make them pass.
- [ ] **Review:** A nonowner authenticated private sender must not mutate another user's favorites, and idempotent repeats must preserve one bookmark.
- [ ] **Commit:** Push the Worker fix to the integration branch.

### Task 2: Fix Python typing errors

**Files:** Modify `src/predoc_pipeline/publish/feedback.py`, `src/predoc_pipeline/publish/bot.py`. Test `tests/integration/test_telegram_favorites.py`.

**Interfaces:** `FeedbackStore.add_favorite(user:int,prefix:str)`, `remove_favorite(...)`, `_handle_message(...)`.

- [ ] **Red:** Reference CI #43419046578 reports five mypy errors in these two files.
- [ ] **Fix:** Preserve validated `str` prefix types when unpacking optional identity returns; explicitly narrow `chat: int | None` in the private-only control branch.
- [ ] **Green:** Fresh `mypy src` and `pytest tests/integration/test_telegram_favorites.py` pass.
- [ ] **Review:** Existing owner-only tracking and per-user favorites remain separate.
- [ ] **Commit:** Push typing fixes to the integration branch.

### Task 3: Include PR #152 ingestion-schedule audit

**Files:** Modify `tools/ingestion_watchdog.py`, `tests/integration/test_linkedin_verified_reconciliations_20261103.py`. Create `tests/core/test_watchdog_pending_slot_20261110.py`.

**Interfaces:** `audit_cadence(...)` produces `late_pending` and `late_pending_ticks` while preserving mature `missing_ticks` and schedule provenance.

- [ ] **Red:** Compare current `main` with PR #152's patch and confirm the new test cases are missing.
- [ ] **Fix:** Transfer exactly the reviewed changes from PR #152, using current-main historical fixture (both expired KCL records absent from public export).
- [ ] **Green:** `python -m unittest tests.core.test_watchdog_pending_slot_20261110` and relevant integration tests pass on CI.
- [ ] **Review:** No cron cadence, retry policy, or production workflow trigger is changed.
- [ ] **Commit:** Push the audited change to the integration branch.

### Task 4: Include PR #147 pinned setup-uv action

**Files:** Modify all eighteen YAML workflows listed in PR #147.

**Interfaces:** Replace setup-uv SHA `07a047e608db84b3d8c06cd9a7c7dcc9c355c18e` (v10.3.2) with `68559e99cc807c1eb7e9238fd43a15bba460eec2` (v10.3.3), preserving per-file YAML syntax, comments and job logic.

- [ ] **Red:** Confirm old SHA remains in the integration branch before change.
- [ ] **Fix:** Apply the exact SHA-only edit to the eighteen affected workflows.
- [ ] **Green:** GitHub workflow YAML contracts and CI pass with new action revision.
- [ ] **Review:** Historical output assertions for St. Gallen ID 139 remain unchanged and current main journal gives `min_degree=masters`; old PR #147 failures derive from stale branch data.
- [ ] **Commit:** Push action upgrade as a separate change.

### Task 5: Fresh CI and PR consolidation

**Files:** Update PR #153 description; annotate/close PRs #147 and #152 only once integration CI passes. No production files change in this task.

**Interfaces:** GitHub Checks, GitHub PR comparison and status.

- [ ] **Verify:** `ci` workflow Python 3.11/3.12, type check, Worker test/bundle checks and publication safety assertions pass on the integration SHA.
- [ ] **Review:** Compare #152/#147 changed file semantics against integration branch; no unexpected changes to data, schedule or state.
- [ ] **Consolidate:** Update PR #153 title/body to cover all three, link its CI URL, and clearly document remaining operational gates.
- [ ] **Close redundant PRs:** Only after verified inclusion and passing CI, close #147 and #152 with a link to #153; do not merge to main or deploy.
- [ ] **Report:** Name successful tests and outstanding external health/source issues explicitly.

## Unresolved externally observable decisions

No new user choices: user requested consolidation and resolution of all open PRs. Production activation and merging to main are intentionally excluded until CI and operational gates pass.
