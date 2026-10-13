# Telegram database chat protocol

After integration with current main, subscriber commands (`/start`, `/settings`,
`/latest`, `/stop`, `/delete`, and administrator controls) keep their existing
polling behavior. AI commands are added alongside those controls. Webhook mode
is refused while subscriber records exist, because this optional Worker does
not implement their subscription and unsubscribe protocol. Keep polling enabled
for the current subscriber bot until a complete webhook migration is validated.

The Telegram bot is the only user interface for AI database questions. It has
two audiences: configured owners can browse and track vacancies without product
rate limits; other users can ask about public vacancy facts in a private chat.
Public users cannot read owner bookmarks, applications, hidden marks or query
context. Personal feedback buttons remain owner-only.

## Commands and screens

Owners use `/menu`, `/positions`, `/saved` (alias `/valid`), `/applied`, `/hidden`,
`/search economics London`, `/new`, `/closing`, `/ask` and `/forget`.
Lists show one page with Previous, Next and Home buttons. Details open in the
same message. Existing save/hide/applied buttons retain their toggle behavior.
Search requires all supplied words to match the stored record. Recent means
seven days; closing soon means a known deadline within seven days.

Public users use `/ask` or ordinary natural-language questions, with `/start`
and `/help` explaining access. `/forget` clears only their own follow-up query
context and does not reset rate limits.

## Authority and scope

`config/telegram-assistant.json` is the versioned protocol shared by the Python
polling bot and the Cloudflare worker. OpenRouter interprets intent; it does
not generate the answer delivered to the user.

1. Authenticate the Telegram sender and establish owner/public permissions.
2. Reject questions longer than 1,000 characters. Public requests reserve a
   rate-limit slot before any provider request; failures consume their slot.
3. Send only the question, UTC date, protocol and previous validated query to
   OpenRouter. Do not send credentials, raw database pages or private marks.
4. Require exactly one `query_database` function call. Ignore model prose.
5. Validate the result against a closed schema. Reject unknown fields, SQL,
   unknown functions, impossible dates, invalid enums, excessive limits and
   unauthorized personal filters.
6. Execute deterministic filtering/counting/grouping over stored records.
7. Render facts from those records, with IDs/source adverts for listing answers,
   snapshot information and explicit “Unstated” values for absent fields.

Allowed topics are stored research vacancy facts, employers, locations,
deadlines, compensation, qualifications, technical requirements and stated
visa terms. Owners may also query their own saved/applied/hidden records.
General knowledge, creative writing, coding, political questions, weather,
secret retrieval, web research, predictions and personal eligibility decisions
are outside scope. Unsupported requests return a fixed scoped refusal.

This grammar prevents an AI from supplying fabricated answer text or executing
arbitrary SQL. It does not prove perfect semantic interpretation: a model may
choose an incorrect valid filter. The user can inspect source records and
rephrase. Results describe the stored inventory, not exhaustive live market
coverage. Missing deadlines cannot match a known-deadline filter. Inferred or
unknown visa status cannot satisfy a filter for explicit sponsorship.

## Limits and privacy

- Owners: no application request-frequency or shared-public cap. Provider limits,
  bounded query/output sizes and provider timeouts still apply.
- Public users: three requests per rolling minute per Telegram user ID.
- Public users collectively: 100 requests per rolling hour by default, controlled
  by `TELEGRAM_AI_PUBLIC_HOURLY_CAP` (Python) / `PUBLIC_HOURLY_CAP` (Worker).
  The Worker deployment defaults public AI to disabled until the operator sets
  `TELEGRAM_AI_PUBLIC_ENABLED=true`; `TELEGRAM_AI_ENABLED=false` disables all
  AI questions in Worker mode.
- Up to five configured keys can be considered when OpenRouter returns 429.
- Each parser request has a 600-token output limit. At most five listing records
  are rendered, with bounded fields and complete HTML tags.
- Follow-up memory stores validated filters, not raw questions or model prose.
  Polling auxiliary state stays in the encrypted feedback envelope when the
  configured encryption key is present; local plaintext remains gitignored.
- Public refusals and provider errors never include API keys or response bodies.
- Prepared polling replies are cached privately by chat/message identity. Retries
  reuse the result instead of spending another provider call/quota reservation.
  Polling also checkpoints public quota reservations by update ID before the
  provider call, preventing double charging after process termination.
  Confirmed and possibly accepted replies are not sent again automatically.
- Worker AI requests reserve quota atomically before entering the durable
  asynchronous AI queue. Telegram's webhook receives success only after this
  admission and a recoverable inbox checkpoint, not after OpenRouter completes.
  Menus/callbacks do not wait on that queue. Provider fallback has a shared
  25-second budget; Telegram's own delivery time is separate.
- Explicit Telegram throttling keeps a prepared Worker reply for later retry.
  Retrying that reply does not repeat AI work or apply tracking toggles twice.
  Durable Object alarms retry unfinished updates independently of Telegram
  webhook retries. Ambiguous outbound sends may be delivered twice after the
  90-second recovery lease; Telegram's send-message API provides no atomic
  confirmation with Durable Object storage.
- Large detail answers disclose how many matched records are actually shown;
  users can ask for specific IDs to retrieve omitted details.

## Two delivery modes

Polling remains the default. It runs on the existing GitHub Actions schedule,
using the existing `OPENROUTER_API_KEY` and optional `OPENROUTER_MODEL` secrets/
variables. Reply speed is still determined by that schedule.

The optional [Cloudflare worker](../cloudflare/telegram/README.md) receives
Telegram webhooks for faster replies. Its private Durable Object owns marks
while webhook mode is enabled. Authenticated `/sync` transfers listing snapshots
and feedback between the pipeline and the worker. Local marks seed it once;
subsequent worker feedback, including undo tombstones, is authoritative.
The sync token does not grant Telegram or Cloudflare account administration.

Tests cover protocol validation, ignored AI prose, SQL refusal, private-mark
isolation, missing-fact rendering, output length, rate caps, feedback undo,
pagination and replay handling. They use fixtures and mocked providers. Live
Telegram/OpenRouter acceptance requires configured runtime credentials; local
test success alone does not establish it.
