# Durable Telegram send-intent reservations

## Why this exists

Telegram Bot API sends have no caller-supplied idempotency key. Collegeum
used to checkpoint admission and independent doctoral-funding receipts on a
runner, then commit the journals only at the end of the ingestion job. If a
runner died after Telegram accepted a message but before the Git push, another
runner could start with an outdated ledger and send again.

This now covers three *separate* public publishers: reviewed official general
PhD admissions, individually verified institutional scholarship/fellowship/
studentship calls, and separately published job vacancies (including the
historical non-US Economics PhD channel backfill). Private subscriber state
and ordinary job-board routing remain independent.

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

Vacancy posts reserve the hashes of **all known apply/source URLs** in a
connected alias group before issuing the single channel post; the same
vacancies namespace covers both ordinary channel cards and previously
web-published PhD backfill cards. This prevents a recovered, differently
chosen URL alias from authorizing a second send. Reservations contain hashes,
not the original public URLs or Telegram payload. A partial reservation
followed by a failed later alias reservation is held for review, never sent.
One authorized fresh generation is allowed after an operator verifies that a
held vacancy was not delivered, via the existing
`resolve_telegram_delivery` / `resolve_phd_channel_delivery` procedures.
An ordinary fresh runner, Telegram timeout, invalid acknowledgement, or known
rate limit does **not** constitute such authorization.

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

When a GitHub reservation exists but Telegram explicitly refuses a send
(such as HTTP 429), the receipt becomes **retry_held**, not an automatic retry.
The official-call health summary reports pending, retry_held, uncertain, and
permanent_failure states separately; all are unconfirmed publication backlog.
This makes an access or rate-limit failure visible without risking a second
accepted send.

Issue #176 tracks the original crash window and recovery policy. Regression
tests cover duplicate HTTP 422, unknown API outcome, lost runner-local ledger,
admissions lifecycle, explicit reissues, and fail-closed missing configuration.

## Boundaries

This protects future sends by the general admissions publisher,
independent official funding-call publisher, ordinary vacancy channel
broadcaster and historical non-US Economics PhD backfill publisher.
Previously confirmed Telegram messages retain their historical IDs; this
change does not authorize a resend. Published website/X receipts, Save buttons,
source scanning and private subscriber messages are unaffected.

GitHub Contents API requests are one per unique URL alias. If too many
aliases or repository write throttling prevent all reservations, sending
fails closed and requires reconciliation. The upstream Telegram Bot API
still does not provide actual exactly-once delivery acknowledgements after
runner failure; unresolved intents remain operator-held rather than
risking duplicate posts.
