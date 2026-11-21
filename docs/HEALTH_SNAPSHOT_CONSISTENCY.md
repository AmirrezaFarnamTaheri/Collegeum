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

Each of the five component observations also records a SHA-256 checksum
of the exact bounded JSON bytes read alongside its source timestamp.
A data refresh which changes catalogue content but accidentally reuses its
old `generated_at` can no longer evade the post-push consistency audit.
Missing components explicitly have a null checksum and a missing freshness
state; a source with an invalid JSON payload fails the audit rather than
being silently treated as healthy.

Official funded-call and PhD-admission delivery reports also depend on
durable Telegram receipt journals. The reconciler records only opaque
SHA-256 fingerprints of the two bounded receipt JSON files, never their
contents, message text or user data. The post-push audit compares those
fingerprints as well as the component hashes. A changed, deleted, malformed
or replaced receipt journal can therefore no longer leave an otherwise
up-to-date official-call report undetected. Both journals are read-only to
this audit, and absent ledgers remain explicitly represented by null
fingerprints until independently initialized.

The public dashboard reevaluates each component's effective age against the
current viewer clock (8 hours for official calls, PhD admissions and listings;
24 hours for Life Sciences and career) and requires a valid recorded digest.
If any component is missing, stale, future-dated or otherwise unverifiable,
the status displays an incomplete pipeline rather than an unwarranted green
`Pipeline active` label. Previously published health without component
metadata still uses its preexisting application-level fallback until the
next checkpoint publishes the new provenance format.

The check does **not** claim a stale provider has recovered: older snapshots
remain visibly stale, and genuine `partial` ingestion remains degraded even
when GitHub Actions itself finishes successfully.

Use `PYTHONPATH=src python3 -m tools.reconcile_public_health
--expected-run-id "$GITHUB_RUN_ID" --check` as an offline operator audit.
Do not manually edit health or journals to make a failing check green. Rebase
and restore trustworthy institutional data and GitHub verification instead.
