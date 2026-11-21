# Production health snapshot reconciliation

The four-hour production ingestion can overlap an independently committed
official programme/call discovery refresh. Previously the pipeline exported
`docs/data/health.json` **before** its Git rebase, so a fresh outer
`generated_at` could embed a **two-hour-old** official-call report even
after the newer catalogue was committed. GitHub CI success and true
application health are separate and must never be conflated.

After the workflow's durable local commit and non-forced `git pull --rebase`,
`python3 -m tools.reconcile_public_health --expected-run-id "$GITHUB_RUN_ID"
--write` reads the **rebased** institutional catalogue and existing receipt
journal, recomputes the public-only official-call summary, and records bounded
provenance for five independent components: official funded calls, Economics
PhD admissions, Life Sciences, career, and website listings. Timestamps are
kept per component; the original ingestion `generated_at` and application
outcome are **never** replaced. Classification is `current`, `stale`,
`missing`, `invalid`, `future`, or `mismatched`, with a separate
`updated_after_pipeline` marker. Stale or invalid official-call snapshots
cannot present eligible/unpublished calls as currently verified.

The reconciled public health is added to the local checkpoint commit with
`git commit --amend --no-edit`, then pushed using the existing non-forced
push. The workflow cannot erase Telegram receipts, approve a document or
perform source requests. A failed health repair produces an explicit warning
but does **not** stop the push of already reserved Telegram send intents.
After the durable checkpoint, `--check` validates this run's identity,
application/source consistency, and component timestamps; a mismatch fails
the **workflow audit**, not the earlier receipt checkpoint.

The check does **not** claim a stale provider has recovered: older snapshots
remain visibly stale, and genuine `partial` ingestion remains degraded even
when GitHub Actions itself finishes successfully.

Use `PYTHONPATH=src python3 -m tools.reconcile_public_health
--expected-run-id "$GITHUB_RUN_ID" --check` as an offline operator audit.
Do not manually edit health or journals to make a failing check green. Rebase
and restore trustworthy institutional data and GitHub verification instead.
