# Independent ingestion recovery observer

This is a **separate Cloudflare Worker** with a UTC Cron Trigger at minute 37
every two hours, not another GitHub Actions schedule or a Telegram bot endpoint.
It reads committed public production health and trusted GitHub workflow history.
It never directly publishes vacancies or contacts subscribers.

## Verified deployment state (2026-11-03 UTC)

**Deployed but NOT activated.** Trusted-main
[disabled bootstrap #41630610227](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41630610227)
successfully created `collegeum-ingestion-observer` in the configured Cloudflare
account with Cron `37 */2 * * *` and explicit `RECOVERY_ENABLED=false`.
A separate read-only
[Cloudflare inventory attempt 2](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41629216487)
verified script identity, Cron and scheduled handler, but reported the
`GITHUB_TOKEN` Worker secret **missing**. That inspection deliberately failed
its activation gate. Do not claim recovery can dispatch or has been exercised.

The one-time bootstrap workflow is now **manual-only** and refuses to overwrite
an existing observer. Do not attempt another initial deployment on this account.
An accepted recovery requires the credential, verified enabled binding, actual
Cloudflare Cron invocations, and a checkpoint + Telegram receipt audit.

## Runtime safety

- Read only `main:docs/data/health.json` through GitHub's authenticated
  contents API. The freshness threshold is strictly **more than eight hours**.
- If stale, read recent `main` production pipeline history. Any queued,
  running, active or newer main pipeline blocks an additional dispatch.
- Only a trusted stale snapshot and exclusively older completed runs can
  authorize one `pipeline.yml` workflow dispatch to `main` with
  `dry_run=false`.
- Missing credentials, future timestamps, malformed health, incomplete or
  unexpected API responses, and ambiguous dispatch responses **fail closed**.
- There is **no public recovery HTTP endpoint** (`fetch()` returns 404 and
  `workers_dev=false`). No Telegram tokens, subscriber data, journal writes
  or vacancy publishing belong in this Worker.

## Finish activation — deliberate operator steps

1. An authorized repository owner creates an **expiring fine-grained GitHub
   credential** with access to **only**
   `AmirrezaFarnamTaheri/Collegeum`: **Contents read** and **Actions write**.
   No other repository permissions. Record its expiration/rotation privately.
   Never paste the credential into this repository, issue, chat or a log.
2. Verify the intended Cloudflare account and existing disabled Worker. Use
   the trusted-main, read-only `inspect-independent-ingestion-observer`
   workflow. It checks Worker identity, Cron, secret-binding **name/type** and,
   when settings access permits, the exact `RECOVERY_ENABLED` plain-text
   binding. It reports only fixed states (`enabled`, `disabled`,
   `unverified`), never secret contents. A missing binding is a failed gate.
3. From a trusted interactive checkout, with the verified Cloudflare account
   configured and the existing locked Wrangler client installed, bind the
   credential **as a Cloudflare secret**, not a plain-text variable:

       cd cloudflare/telegram
       npm ci
       npx wrangler whoami
       npx wrangler secret put GITHUB_TOKEN --config ../ingestion-watchdog/wrangler.jsonc

   Supply the credential only to Wrangler's secure prompt. In CI or a
   noninteractive shell, a blank standard input **may be accepted as an empty
   secret**; never run `secret put` without a verified nonempty input source.
   Do not pass a token as a shell argument or place it in a tracked file.
4. Re-run the independent inventory. Require `presence=deployed`,
   `cron=configured`, `scheduled_handler=present`,
   `github_credential_binding=present` and
   **`recovery_enabled=disabled`**. Verify the token can read committed
   health, and that an authorized operator has checked its repository scope
   and expiration; an API 200 response alone does not prove least privilege.
5. Only after all gates pass, explicitly enable recovery on the **intended
   account** from a trusted checkout:

       npx wrangler deploy --config ../ingestion-watchdog/wrangler.jsonc --var RECOVERY_ENABLED:true

   The command must retain the existing `GITHUB_TOKEN` secret binding.
   Re-run the independent inventory and require
   `recovery_enabled=enabled` **and** the secret binding still present.
   The checked-in default remains `false`; ordinary redeployment without
   the override safely disables recovery. Do not enable a fork.
6. Confirm a **real Cloudflare scheduled invocation** logs
   `fresh; action: none` when production health is fresh, with no new
   `predoc-pipeline` workflow-dispatch. Later, when health becomes genuinely
   stale and there is no newer/active ingestion, verify the observer requests
   one new trusted `main` run; that run checkpoints fresh production health,
   correctly classifies degraded sources, and does not duplicate Telegram
   deliveries or rewrite receipts. Record run IDs, checkpoint time, and
   sanitized operator evidence in [issue #52](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues/52).

To **disable**, deploy without the override or disable the Cron Trigger.
Rotate or revoke the fine-grained credential separately in both GitHub and
Cloudflare. If any validation is ambiguous, leave recovery disabled.

### New accounts or disaster-recovery bootstrap only

The `bootstrap-disabled-independent-ingestion-observer` workflow can be
manually invoked from trusted `main` on an account proven not to contain the
Worker. Its locked Wrangler dry-run precedes writes; a cross-account,
credential-accessible read-only inventory rejects duplicate identities and
incomplete account/script access; an additional settings check refuses to
overwrite an existing Worker. The only allowed deployment is disabled, with a
postcheck of Worker identity, Cron and `RECOVERY_ENABLED=false`.
**Do not use this workflow to enable recovery or rotate secrets.**

## Limits

- An independent Cloudflare Cron is not a guaranteed no-delay scheduler.
- The GitHub watchdog and Cloudflare observer have a narrow read/dispatch
  race; the application's publishing journal and `predoc-bot` concurrency
  remain essential, and no global exactly-once guarantee is claimed.
- A dispatch is not evidence of fresh health, correct extraction, verified
  open/funded vacancies, or zero duplicate Telegram receipts.
- Keep issue #52 open until independent enabled-Cron recovery and production
  acceptance have been demonstrated.
- Offline tests: `node --test cloudflare/ingestion-watchdog/*.test.mjs`.
  CI also requires a locked Wrangler build dry-run.

Related: [#52](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues/52),
[#32](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues/32),
[#80](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues/80).
