# Durable Telegram send-intent reservations

## Why this exists

Telegram Bot API sends have no caller-supplied idempotency key. Collegeum
used to checkpoint admission and independent doctoral-funding receipts on a
runner, then commit the journals only at the end of the ingestion job. If a
runner died after Telegram accepted a message but before the Git push, another
runner could start with an outdated ledger and send again.

This applies to public official general PhD admissions and separately tracked
PhD scholarship, fellowship, and studentship calls. It does not mix either with
vacancies or private subscribers.

## New send protocol for reviewed main ingestion

1. Recheck the opportunity's official institutional evidence, deadline,
   non-US location corroboration, and existing receipt.
2. Write the local pending delivery checkpoint.
3. Before calling Telegram, create an immutable *new* file in the repository's
   main branch using GitHub's Contents API with no overwrite SHA. Paths are
   under data/telegram_delivery_intents/ and contain a namespace, hashed
   opportunity key, hashed operation, and timestamp. No token, message text,
   subscriber data, or source URL appears in the file.
4. **Only an HTTP 201 Created is sufficient to send.** A pre-existing intent
   (HTTP 409/422), refused write, rate limit, network timeout, unexpected
   response, or missing GitHub credential stops the Telegram send. The
   publisher never blindly retries an uncertain write.
5. The ordinary local delivery journal records the eventual Telegram
   acknowledgment as confirmed (with message_id), uncertain, or
   permanent_failure. That journal remains checkpointed to Git at the end.
   The immutable reservation is not automatically removed.

An admission's first send uses the operation INITIAL. A later legitimate
admissions cycle uses a new deadline-specific operation only after the
existing 180-day lifecycle checks. An explicit replacement after verified
deletion uses a distinct operation containing the prior ID and authorization
timestamp. Independent funding calls use the official URL and intake-year
identity. Old intents never authorize replays.

## Operational security

The production pipeline workflow sets the durable-reservations flag to true
on trusted main and supplies the scoped GitHub Actions token with contents
write permissions. Local runs default to false. A missing reservation on the
trusted main ingestion workflow is a fatal no-send condition, even if an
environment flag was accidentally omitted. New intent commits create only
new paths, leaving in-flight journal files untouched. The normal final
git pull --rebase can incorporate those Git commits before persisting
other state.

A reserved but unconfirmed call is **not proof of a delivered post**. Review
the channel and GitHub run audit. If a Telegram message was confirmed,
reconcile its receipt. Otherwise require the explicit operator workflow for
a replacement; never delete a reservation merely to force a send.

Issue #176 tracks the original crash window and recovery policy. Regression
tests cover duplicate HTTP 422, unknown API outcome, lost runner-local ledger,
admissions lifecycle, explicit reissues, and fail-closed missing configuration.

## Boundaries

This protects future sends by the general admissions and independent official
funding-call publishers only. Previously confirmed Telegram messages retain
their historical IDs; this change does not authorize a resend. It does not
change LinkedIn access policy, robots requirements, vacancy-ingestion receipts
or other Telegram delivery systems.
