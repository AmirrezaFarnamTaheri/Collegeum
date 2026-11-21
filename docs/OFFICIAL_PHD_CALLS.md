# Official PhD scholarships, studentships and fellowships

This monitor closes an important Collegeum source-coverage gap: **ordinary LinkedIn
feed posts are not LinkedIn Jobs listings**. Collegeum now monitors reviewed
official institutional call pages and announcement indexes independently, without
claiming to scrape LinkedIn feeds or circumventing any 403/429 access restriction.

## Current official coverage

The approved registry at `config/official_phd_calls_sources.json` currently
checks both IEB/University of Barcelona's **News** and **Call for Applications**
indexes, plus the two currently open Economics and Energy/Climate 2027
PhD call pages directly (so pagination cannot hide them), and five Henley
departmental PhD opportunities pages (Finance and Accounting, International
Business and Strategy, Informatics and Operations, Entrepreneurship, and
Leadership/Organisations), plus the University of Reading's distinct 2027 **Home-fee PhD bursaries** and
**International PhD Studentship Competition** for all eligible research
areas, explicitly including Henley Business School. Additional institutions can be added to this reviewed
registry without changing the parser or publisher.

The monitor follows **at most six new** prioritized same-host HTML PhD call links per
index run and rechecks **at most two** still-open previous calls after they
scroll off an index, never arbitrary third-party search links or PDFs. It uses one bounded
read for each approved Henley page. The resolver rejects external links, insecure
schemes, credentials, unexpected redirects, oversized responses and restricted
paths. Every fetched URL must be permitted by its own host's robots.txt.
Unavailable or disallowed robots.txt is a failed check, never an implicit grant.

Same-host scholarship PDF/DOC/DOCX links discovered in official indexes
are counted as **unverified document-coverage gaps**; discovery alone never
fetches a file or creates publication evidence. An accessible index with zero **newly discovered** HTML call links
is reported as an **empty index** coverage limitation, even if older
already-known calls are successfully rechecked. Source diagnostics show
`discovered_links`, `rechecked_links` and total `candidate_count`;
none of these imply that the institution has no opportunities. These limitations degrade public source
health until a separately reviewed and robots-permitted document workflow
is implemented.

## Admission versus funding deadline

Institution-specific pages can contain several unrelated dates. The parser
accepts an explicit **scholarship/fellowship/studentship** closing date in its
own application context, not a general PhD deadline, intake date, examination,
recommendation, prior closed academic-year cycle or recruitment result.
An explicitly closed *current* scholarship window is blocked even when
an old deadline remains visible on the institutional page. Prior-year
closure notices do not suppress a separately verified open funding cycle.

Examples from the November 2026 verified primary-source investigation:

- IEB full-time Economics PhD Scholarship 2027: two application steps due
  **11 December 2026**, separate from generic University of Barcelona PhD intake.
- IEB Energy and Climate Economics PhD Fellowship: a distinct application with
  its own two required steps, also due **11 December 2026**.
- Henley Finance and Accounting: **21 February 2027** is the funding application
  cutoff, **10 January 2027** is a recommended PhD admission-application date,
  and **30 June 2027** is a different PhD programme deadline. They are never
  treated as interchangeable dates.
- University of Reading's separate International PhD Studentship Competition
  (including Henley applicants) closes **15 January 2027**. Its official page
  calls this the application deadline, and the parser requires the funding
  page's own Deadline section and handles day ordinals (15th). This is **not**
  the Henley departmental studentship closing 21 February 2027.
- CEMFI's independently monitored **programme** admission remains outside
  this scholarship ledger. Its current official verification is policy-blocked
  and is not promoted by social-post dates.

Every posted call must be freshly checked (14 days maximum), link to the same
official HTTPS evidence page, have an explicit current-cycle deadline, and
provide independently corroborated non-US location evidence. A national
university domain supplies such evidence for Henley; IEB's generic .edu host
requires its current **08034 Barcelona / +34** institutional postal and telephone
address. Absence or contradiction suppresses publication.

## Operations and receipt safety

The existing isolated `phd-admissions-refresh` workflow also runs
`tools/update_official_calls.py`, following the same four UTC cron slots and
trusted main-branch Telegram-sync fallback. Its only side effect is an
institutional-source-only public catalogue
`docs/data/official_phd_calls.json`; it never reads Telegram credentials.

On refresh completion, the existing ingestion freshness watchdog can request
one ordinary main publishing workflow when a verified, eligible call is newer
than the latest pipeline run and has no receipt. The watcher applies the
publisher's institute-name and recommended-admission-date validation, refusing
dispatch for cases the publisher would reject. It also refuses active/newer
ingestion, blocked evidence, unknown states and untrusted provenance.

The ordinary production pipeline alone can attempt at most two official-call
Telegram sends per run (override `TELEGRAM_OFFICIAL_CALLS_MAX_PER_RUN`;
live workflow defaults to two). **Failed requests consume the same budget**
as successful messages, and a Telegram 429 rate-limit response immediately
stops that batch; every attempted call remains checkpointed and reserved.
`TELEGRAM_OFFICIAL_CALLS_ENABLED` is off by default for local runs and
explicitly enabled in the reviewed production workflow. Every independent
call/cycle has a separate key (official URL + intake year) and separate
`data/official_phd_calls_telegram.json` receipt. The ledger is checkpointed
before attempting a send; confirmed, uncertain and permanent-failure states
are never blindly resent.

`docs/data/health.json` contains a separate `official_calls` section for
current source statuses, empty indexes, unsupported document links, held
publication groups, eligible calls, unsent eligible count, confirmed
receipts, uncertain receipts and last confirmed delivery timestamp. A healthy
source refresh is **not** evidence that Telegram delivered anything.


Invalid or incomplete catalogue schemas cannot report a healthy official-call
engine: the public health status falls back to `unavailable` when the catalogue
kind, version, call list or source list fails validation.

## Review-only institutional PDF evidence

The approved source registry also includes IEB's official call-document index
\`https://ieb.ub.edu/convocatorias/\`. Download buttons sometimes say only
"Descargar PDF" while the immediately preceding heading identifies the actual
PhD scholarship. The index parser recognizes generic action labels such as "Web personal"
only when an adjacent H2–H4 heading establishes a PhD funding call and the
same-host HTML destination path also identifies a relevant programme/call.
The **HTML detail page is independently fetched and validated** before
the observation can be verified; index words alone do not suffice.
The document-link parser similarly uses adjacent headings for PDF/DOC/DOCX,
but never treats a document link as a verified scholarship. Binary .doc
remains unsupported. DOCX can be manually reviewed, not published.

A separate, explicitly opt-in \`tools/official_call_pdf_review.py\` reviewer
only accepts exact, manually approved institutional PDF URLs in
\`approved_documents\`. To review the approved IEB PDF, use the repository's
locked environment:

\`\`\`bash
uv run --locked python -m tools.official_call_pdf_review \
  --source-id ieb-document-index \
  --url https://ieb.ub.edu/wp-content/uploads/2026/11/IEB-PhD-Scholarship-2027-28.pdf \
  --fetch
\`\`\`

Each fetch performs a new robots permission check, only accepts exact-host
HTTPS PDF paths, rejects unsafe redirects and non-PDF content types, and
limits downloads to 1 MiB. Parsing occurs in a separate local process with
CPU/memory/wall-clock limits, a maximum of eight pages and 24,000 extracted
text characters. Scanned/unreadable pages, encrypted or scripted PDFs, and
contradictory/missing cycle, eligibility or deadline evidence fail closed.
No JavaScript, macros, OCR, or external commands embedded in a PDF are run.

The evidence result deliberately uses \`status=document_review_only\`, not
\`verified\`. It is printed for operator review and **never automatically
inserted into** \`docs/data/official_phd_calls.json\`, the publishing journal,
or any Telegram message. The reviewed IEB PDF maps to its already-delivered
canonical HTML call and must not create another URL-based delivery identity.
This is a bounded verification tool, not a claim of full institutional PDF
coverage; tracking issue #183 retains the controlled promotion requirement.

## Review-only institutional DOCX evidence

Institutional Word `.docx` calls now have a **separate opt-in** reviewer:
`uv run --locked python -m tools.official_call_docx_review --source-id SOURCE --url EXACT_APPROVED_DOCX_URL --file LOCAL.docx`
or, only after confirming official-source permission and robots policy, replace
`--file LOCAL.docx` with `--fetch`. The exact HTTPS URL and canonical
institutional HTML identity must first be included in the source registry's
`approved_documents`; no DOCX URLs are pre-approved in the registry.
Older binary `.doc` files remain unsupported and are never executed.

The DOCX review fetches at most 1 MiB, requires the standard OOXML DOCX MIME,
and performs a fresh robots check before each network access. Unexpected
redirects, credentials, off-host targets, alternative ports, query strings,
wrong MIME, or changes in document URL are held. The OOXML ZIP is parsed in
an isolated worker with 5 seconds CPU, 512 MiB address space and 8 seconds
wall time. It permits at most 100 entries, 3 MiB aggregate expanded data,
1 MiB per entry, 150 paragraphs and 24,000 characters of extracted body
text. XML DTDs/entities, external relationships, macros, OLE objects,
embedded content, active controls, revisions, fields, inaccessible/absent
body text, and unsafe ZIP members are rejected. No OCR, Word/LibreOffice
execution, document rendering or macro execution is used.

The extracted body must independently corroborate the institution and
call title, explicit PhD scholarship, eligibility, current intake, funding
deadline, and geographical evidence. Missing or contradictory evidence
produces `document_unverified`. Even accepted evidence is only
`document_review_only`, with the content hash and an existing canonical
HTML identity; it cannot become a published observation, create a Telegram
receipt, or trigger the watchdog. The unattended discovery monitor continues
counting found documents as coverage gaps; this extension does not authorize
unattended downloads or claim full DOCX/DOC/PDF recall.

## Independent document review journal and source health

Both review CLIs accept an optional `--record` flag. Only an explicit
operator invocation of `--file` or an approved `--fetch` (subject to fresh
robots permission) plus `--record` appends to
`docs/data/official_document_reviews.json`. The journal is **not** written
by scheduled discovery, CI or Telegram publication. It contains only
approved exact URLs, canonical HTML aliases, source IDs, method (local file
versus live fetch), results, reasons, UTC timestamps and document SHA-256
fingerprints. Successful audits additionally preserve the exact approved
institution/title, intake year, funding deadline type and ISO date, and a
bounded official-source deadline excerpt. The excerpt must contain the
matching dated cutoff and cannot contain an email address; full document
text and email contact addresses are not stored.

The journal is bounded, schema-validated and atomically saved. Duplicate
unchanged results do not grow it, while a revised document with a different
content fingerprint becomes a separate review event. A corrupted journal
fails closed instead of being silently overwritten. No journal entry can
have the publication status `verified`; successful parsing is *always*
`document_review_only`. Revisions and changed URLs require fresh
operator evidence. Coordinate concurrent operator sessions before committing.

The published health collector can read a **committed** journal (if one
exists) and report review-only success, held/failed reviews, robots blocks,
live-fetch failures and distinct content revisions. Missing journal means
`not_recorded`; invalid journal is `unavailable` and degrades health.
HTML source coverage is independently counted as `discovered_html_links`,
`new_html_links`, `historical_rechecks`, source/detail robots blocks and
`document_links_by_format` (PDF, DOC, DOCX). A previous-catalogue snapshot
without these new per-format fields cannot claim format-complete coverage.

The three IEB indexes had zero eligible HTML links in the 21 November 2026
snapshot because the earlier HTML parser checked only anchor labels.
The institutional listing uses a descriptive heading with a generic
"Web personal" action link; the contextual HTML candidate fix addresses
this specific recall gap without bypassing detail-page checks or treating
already delivered IEB awards as new Telegram identities. The index also
exposes multiple historical/closed document calls: a count of 12 document
candidates is **not** twelve open scholarships. PDF/DOCX candidates are
not downloaded automatically, and .doc remains a held format.

Both reviewed-document fetchers now reject *all* HTTP redirects before
following them, even a same-host redirect that appears harmless. This
prevents fetching changed or unapproved document URLs under a stale exact
registry approval.

## Read-only institutional document triage

Every successful official HTML-index refresh retains bounded, same-host
PDF/DOC/DOCX candidate URLs in the public official-call catalogue. To
reconcile these unverified leads without fetching files or touching Telegram,
run from the repository root:

```bash
python3 -S -m tools.official_document_triage > document-review-queue.json
```

The stdlib-only command checks the approved registry, current index
observations, historical confirmed funding-call ledger, and the separate
document review audit. It deduplicates identical URLs across multiple
indexes, refuses untrusted hosts or conflicting approvals, and fails closed
at 300 distinct documents. The output is a **human-review queue** and cannot
trigger any scholarship publication or bot send.

The following `next_action` values make status explicit:

- `approval_required`: discovered URL without exact per-document approval
- `review_required`: approved URL without independently reviewed evidence
- `review_complete_no_delivery`: actual reviewed PDF/DOCX evidence exists,
  but there is no matching confirmed or previously attempted channel receipt;
  release still needs separate operator approval
- `already_delivered_same_cycle`: approved canonical HTML call, intake year
  and funding deadline **all** match an existing confirmed Telegram receipt
- `prior_attempt_requires_reconciliation`: a prior pending, uncertain, held,
  or legacy-year attempt shares the canonical source and funding cutoff;
  never infer an unsent scholarship from an absent confirmation
- `permission_blocked`, `review_failed`, or `conflicting_approvals`: held
  because evidence is inaccessible, inadequate, or conflicting
- `unsupported_legacy_doc`: legacy binary Word files have no approved safe
  parser and must remain unverified and unexecuted

An older receipt for the same institutional URL but a **different**
funding cycle never suppresses a genuine new opportunity. A successful
document review cannot acquire status `verified` through this command;
any new document-backed posting requires separately authorized
evidence promotion under existing no-replay safeguards.

## Durable post-send outcomes

For independently verified institutional admissions and funding calls, the
trusted production \`main\` pipeline now requires **two independent remote
write stages**: a create-only pre-send intent and a create-only post-result
outcome under \`data/telegram_delivery_outcomes/{admissions,calls}/\`.
A confirmed outcome stores the Telegram message ID; an uncertain, held or
permanently rejected outcome is explicit and never reinterpreted as sent.

The local journal checkpoints first; the authenticated GitHub Contents API
then creates the corresponding outcome record immediately after Telegram
returns, without waiting for the end-of-run state commit. Existing keys
cannot be overwritten, and 409/422/5xx/transport errors fail closed. If
GitHub fails to persist an outcome **after** Telegram accepted a send, the
local confirmed record is preserved and the existing immutable intent still
prevents replay; the operator must reconcile the missing remote outcome.
No system can guarantee a Telegram message ID after a runner crash that
occurs before receiving/persisting the Bot API response.

## Compact multi-position channel format

Approved departmental pages sharing a single institutional funding window can now
opt into an explicit `posting_group` in the official source registry. All
members must independently pass the same institutional verification, and must
match institution, country, funding type, funding cutoff, recommended admission
submission date, and intake. Never infer groups from the institution name or
the same cutoff alone. Each group contains at most six source pages.

The channel receives a single post with an institutional heading, one shared
deadline and admission recommendation, a concise list of positions, and one
official link per position. A source page which lists a closed 2026/27 intake and an open 2027/28 intake
uses the **open** year. Original 2026-key receipts remain immutable: a new
2027-key observation is blocked from reissuing only if its same official URL,
institution and funding deadline match the old receipt, including when the
university edits its page title. A genuinely new
annual funding deadline is not suppressed. The watchdog applies the same
compatibility and group completeness checks as the publisher.

Each opportunity retains its original `call_key`
and its own receipt, even when the Telegram `message_id` is shared. All
participating keys are checkpointed and durably reserved before the single
Telegram send. Failed or uncertain sends hold all members without blind retry.
The health report continues to count confirmed *calls*, and also exposes
`confirmed_messages` for the number of message IDs acknowledged by Telegram.
This is historical delivery accounting, **not** a live channel audit: a
user-deleted or manually posted message does not retroactively change a
confirmed send receipt.

The five Henley Business School departmental 2027 studentships are explicitly
approved to group prospectively. The source registry declares
`posting_group_expected: 5` for each department; if any source is blocked,
incomplete, changes its deadline or has already been attempted, the engine
holds the entire group and reports `group_waiting` rather than sending a
partial announcement. Legacy groups without a declared size continue to use
existing bounded grouping rules. Already confirmed messages 136–140 are
historical receipts, **not** automatically deleted or reissued by this change.
The user reported deleting Telegram messages 136–140 on 20 November 2026
(issue #171). Their original receipts remain intact; this reported cleanup is
not independently confirmed by a Bot API receipt. The user will publish
the replacement manually. There is **no automated one-time reissue
authorization or workflow** in this change. Never clear historical
receipts to force a resend.

## Additional official bursary coverage

The University of Reading's 2027 Home-fee PhD bursaries are monitored from
their verified direct university URL. This is a distinct funding call for new
**Home-fee** applicants, across disciplines. Its official 30 April 2027 date
is a **bursary** application cutoff, not a general PhD-admission deadline,
and applicants must already have received an offer by that date. The bursary
covers Home-rate PhD tuition for up to four years. The channel explicitly
labels the Home-only eligibility and tuition support only when verified
against the official article; a maintenance stipend is not promised.
As with other funding calls, refresh must verify the source under robots and
deadline checks before publishing. Never advertise this bursary as open to
international-fee applicants.

## Adding future sources safely

Add reviewed official HTTPS institutional index/direct URLs with institution
and country to `config/official_phd_calls_sources.json`, keeping the source
count below 20. Changes trigger offline registry validation and a bounded
`main` source check. A successful HTML response is not automatic eligibility;
unsupported documents and uncertain deadlines remain unverified. Do not add
social-post URLs, scraped job-board mirrors or default country guesses.
