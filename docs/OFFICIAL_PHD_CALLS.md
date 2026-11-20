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

Same-host scholarship PDF/DOC links discovered in official indexes are counted
as **unsupported documents**; they are never scraped, fetched, inferred or
published from filenames. An accessible index with zero HTML candidates is
reported as an **empty index** coverage limitation, not proof that the
institution has no opportunities. These limitations degrade public source
health until a separately reviewed and robots-permitted document workflow
is implemented.

## Admission versus funding deadline

Institution-specific pages can contain several unrelated dates. The parser
accepts an explicit **scholarship/fellowship/studentship** closing date in its
own application context, not a general PhD deadline, intake date, examination,
recommendation, prior closed academic-year cycle or recruitment result.

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
than the latest pipeline run and has no receipt. The watcher refuses dispatch
for active/newer ingestion, blocked evidence, unknown states and untrusted
source provenance.

The ordinary production pipeline alone can send at most two independently
rendered official call messages per run (override
`TELEGRAM_OFFICIAL_CALLS_MAX_PER_RUN`; live workflow defaults to two).
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
institution, title and funding deadline match the old receipt. A genuinely new
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
not independently confirmed by a Bot API receipt. A replacement requires a
separately authorized, durable, group-aware one-time reconciliation. Never
remove receipt history to trigger a resend.

## Additional official bursary coverage

The University of Reading's 2027 Home-fee PhD bursaries are monitored from
their verified direct university URL. This is a distinct funding call for new
**Home-fee** applicants, across disciplines. Its official 30 April 2027 date
is a **bursary** application cutoff, not a general PhD-admission deadline,
and applicants must already have received an offer by that date. The bursary
covers Home-rate PhD tuition for up to four years, not a living stipend.
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
