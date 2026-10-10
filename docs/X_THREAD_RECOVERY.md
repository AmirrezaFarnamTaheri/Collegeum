# Recovering X publications

The scheduled pipeline publishes single posts. Both `post_listing()` and the
thread APIs checkpoint publication progress locally. Single posts use the same
submission-intent and acknowledgement protection as a one-segment thread.
Existing active website listings with no X ID are retried on later runs, up to
`X_RETRY_LIMIT` (default 20; zero disables recovery). Hidden, expired, closed,
policy-excluded and Telegram-routed listings are excluded. New deliveries are
not retried twice in the same run. Website publication history is preserved.

Use a persistent `X_THREAD_JOURNAL_PATH` (default `data/x_threads.sqlite3`). Its
`data/x_threads.ndjson` sibling is the durable, versioned text journal.
Each confirmed post ID and each submission intent is flushed and atomically
replaced before the next segment is attempted. The SQLite file is a derived
cache: a fresh runner can restore from the text journal alone. Preserve the
text journal before discarding a workspace. Existing cache acknowledgements
are preserved when restoring an older text snapshot; conflicting ID sequences
fail, and a pending intent in either equally advanced copy blocks replay.
The pipeline workflow stages the
default text journal when it exists; successful remote state delivery still
depends on that workflow's commit/push succeeding.

Set `X_PUBLICATION_SCOPE` to a stable identifier for the destination account
before enabling X publishing. Without it, the scope is a hash of the OAuth consumer
key and access token. Credential rotation therefore creates a different scope;
configure a stable account identifier to retain recovery continuity. Separate
accounts must use separate scopes. The journal stores hashes, counters and
public post IDs, not credentials or post text.

Retry the same thread with the same logical key and unchanged text. Confirmed
IDs are returned without re-posting those segments, and the next segment replies
to the last confirmed ID. Completed threads return their saved IDs without
network calls. Listing APIs use the canonical apply-URL hash, with separate keys
for single posts and threads. Keep the publication mode stable to retain recovery.
If a job or thread has changed, reconcile the original
thread before assigning a deliberately new logical key through `post_thread`.

An `XError` exposes `created_ids`, `next_index`, `thread_key`, `uncertain`,
`status` and `reset_ts`. A confirmed rejection such as HTTP 429 leaves the
segment retryable. A timeout, HTTP 5xx, malformed success response, interrupted
process or failed acknowledgement write leaves an unresolved submission intent.
Automatic retries stop there because X may already have created the post.

After verifying the remote outcome for that exact account and segment, record
one of these local resolutions, using the key from the error:

```python
# The exact segment exists on X; use its verified ID.
client.thread_journal.resolve(error.thread_key, post_id="1234567890123456789")

# Alternatively, verification establishes that no post was created.
client.thread_journal.resolve(error.thread_key, confirmed_not_created=True)

# Then retry the original thread unchanged.
ids = client.post_thread(original_posts, thread_key=original_logical_key)
```

These resolution methods do not contact X and cannot verify a caller's assertion.
Do not confirm absence while another publisher is still submitting that segment.
Concurrent publishers using the same journal serialize segment claims; a second
publisher sees the active intent and stops without duplicating its request.

Malformed, unsupported or empty existing text journals fail without replacement
or publication. Restore a verified backup rather than deleting a journal to
bypass that error. Do not delete an unresolved intent or reset a scope to retry
an uncertain request. Exactly-once remote publication cannot be promised across
the interval between remote acceptance and durable local acknowledgement;
explicit reconciliation covers that interval.

Owned OAuth sessions are reused and closed by `XClient.close()` or its context
manager. Externally supplied sessions remain owned by their caller.
