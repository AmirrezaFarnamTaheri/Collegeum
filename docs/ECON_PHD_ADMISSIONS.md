# Economics PhD admissions — official-source monitor

Collegeum incorporates **programme discovery leads**, not the upstream
application-deadline assertions, from
[Economics PhD App Deadlines](https://github.com/paultran47/econ-grad-app-deadlines)
by Paul L. Tran (MIT licence, upstream commit
`49604886769441a11c1e79ab7d1fab68ba5b3d36`).
Its copyright and permission notice is at
[`docs/licenses/econ-grad-app-deadlines-MIT.txt`](licenses/econ-grad-app-deadlines-MIT.txt).

## One source of truth: each official university programme page

- `config/phd_admissions_seeds.json` keeps 253 programme names, country codes,
  official programme links and **unverified** structure hints. No upstream
  deadline data is imported or used by a publisher.
- An obsolete or inaccessible discovery link can be replaced only after
  independently locating an explicit, public, official HTTPS page belonging to
  the same university. Such a change invalidates the old observation and
  resets the affected programme to `unverified`; it does **not** import a
  search result or manually designate a deadline as confirmed. The refreshed
  university URL still receives its own robots-aware source check, and failures
  stay non-actionable. The 2026 review substituted university-owned
  Graduate School/Economics deadline pages for three blocked original leads
  (Harvard, Berkeley and UC Davis), without changing programme identities.
- A subsequent official-source review replaced three more outdated discovery
  leads: Brown University's Economics PhD directory, the University of
  Chicago's Economics PhD-specific `Apply` page, and Columbia University's
  GSAS Economics PhD programme listing. As with every source repair, affected
  observations return to `unverified` until the robots-aware checker
  successfully reads the new URL. The extractor recognises their tightly
  scoped doctoral programme identity rather than interpreting deadlines on
  unrelated Master's applications. Columbia's currently published numeric
  `12/3/2026` remains **unconfirmed** under the country-agnostic numeric-date
  policy; the full year alone does not disambiguate the month and day.
- For the 2027–28 admissions cycle, two outdated but readable discovery
  pages have direct, current-cycle official alternatives: Bocconi's public
  **Preparing to Apply** PhD call and Mannheim GESS **How to Apply**. Both
  replacements reset the respective programme observation to `unverified`
  until the independent verifier fetches its new official HTTPS source.
  Bocconi's common 18 January 2027 cutoff explicitly exempts unrelated
  computing and statistics PhDs with a later date, not Economics and Finance.
  Mannheim's 31 March 2027 *final* application cutoff is distinct from
  its 15 January early-review priority. Neither date is imported into the
  catalogue by a manual source correction; the verifier must independently
  corroborate the explicit current-cycle deadline and record its provenance.
- `tools/update_phd_admissions.py` investigates the university's primary
  programme URL and **at most two relevant linked admissions/funding pages**
  on the same HTTPS institutional host. For generic domains (`.eu`, `.org`,
  `.com`, etc.), one additional linked official contact page may corroborate
  the institution's country through its mailing address (four pages maximum).
  Every page requires robots.txt permission. It does
  **not** follow arbitrary external links, logins, PDFs or aggregators,
  bypass access controls, or scrape the upstream directory again. Blocked,
  off-host, contradictory, unsupported and unreachable evidence fails closed.
  An accessible page with no explicit current-cycle deadline remains unverified.
- Each safely extracted detail (duration, teaching language, entry criteria,
  admissions opening date, tuition, qualifying funding statement, stipend,
  additional fees, tests, references) carries its own official URL, excerpt
  and UTC check time in `official_details`; `investigated_urls` records
  visited primary sources. Contradictory details are suppressed. No amount,
  universal eligibility rule, full funding promise or fee waiver is inferred
  from a discovery lead. The dashboard and Telegram cards only show fresh,
  attributable details; the institution's wording and conditions govern.
- `docs/data/phd_admissions.json` is the **only public programme observation
  catalogue**, separate from `docs/data/listings.json` and the application
  journal. On initial adoption, all 251 programme deadlines are **unverified**.
  Future dates can appear only when explicitly extracted with a four-digit year
  near both a relevant Economics PhD heading and an application-deadline phrase
  on the institution's own page. Multiple distinct dates are ambiguous; do not
  silently select a domestic or international deadline.
- A successful site fetch that does not corroborate an explicit date gets
  `no_explicit_deadline`, not a guessed recurring deadline. Stale observations,
  non-HTTPS seeds, provider errors and robots-disallowed checks are similarly
  non-actionable. No date is inferred from an undated deadline, term start,
  a yearless month/day, or the upstream table. A Master's-degree admissions
  deadline cannot by itself be labelled a direct PhD deadline. For an
  officially linked first-year PhD track (such as BSE's UPF PhD track),
  Collegeum records a separate `admission_route` fact citing the official
  university programme and accepts the Master's-stage date only when the
  university's own application page also names the PhD track. Cards label
  this clearly as Master's-stage doctoral entry, not a standalone
  funded research job or an unconditional direct PhD appointment.
- The static Collegeum dashboard has a separate **PhD admissions** directory
  with search, country filtering, status filtering, and institution links.
  General non-US admissions with a **fresh, explicit, officially verified**
  future deadline are separately announced in the existing Telegram channel.
  There is no conversion into funded research-employment vacancies, X posts
  or personalised research-job notifications. Funding is not assumed: any
  conditional funding or fee details must be supported by field-level official
  evidence and are presented with their original limitations.

## Automatic refresh

The independent `phd-admissions-refresh` workflow runs at **03:17, 09:17,
15:17 and 21:17 UTC** (subject to GitHub Actions scheduler delays). A
**successful scheduled `telegram-sync` completion on the repository's own
`main` branch** also triggers this same, isolated refresh as a fallback
when GitHub drops or delays a cron slot; failed, fork, PR and manual
Telegram-sync events cannot trigger this privileged write workflow.
Telegram sync supplies only the trusted completion signal: the admissions
checker receives no Telegram credentials, sends no Telegram messages and
never dispatches production ingestion. Its existing concurrency lock
serializes overlapping checks. Each run checks at most 25 oldest-due
official programme URLs. Never-checked programmes
take priority so missed GitHub schedules cannot strand calendar shards. At a
reliable four-runs-per-day cadence all catalogued programmes receive an initial attempted check
within 11 successful runs (under three days). A recorded check is eligible
for renewal after 11 days; the monitor makes no network requests if none are
due. Trusted source-code or seed changes also bootstrap a check on `main`
without waiting for the next cron. On trusted checker updates, the bounded
batch can recheck previously readable programme pages whose deadlines were
inconclusive, so improved extraction takes effect without manual overrides.
This mode does not retry robots-blocked, access-restricted or failed sources
early. A trusted code upgrade also rechecks previously verified records missing
the new official detail fields, without promoting third-party assertions.
A previously verified deadline is
**withdrawn** if source evidence ages beyond 14 days, or the date passes.
After every check it commits the derived
`docs/data/phd_admissions.json` and the complete stored-evidence coverage audit,
`docs/data/phd_admissions_coverage.json`, alongside the independent official-call
observations maintained by the same workflow. The existing Pages deployment publishes the
result and its MIT notice. No vacancy ingestion, subscriber delivery, or
provider-restricted retries are involved. Failed/blocked checks remain visible
as unverified; no assumption of a live programme is made.

### Full review of previously readable inconclusive sources

For an authorised, one-time sweep, the `phd-admissions-refresh` workflow has a
`workflow_dispatch` input `full_recheck=true`. On a trusted `main` push,
the commit-message marker `[full-admissions-recheck]` opts into the same
one-off check. This does not change the normal 25-programme rotation.
The CLI equivalent is:

```bash
python3 -S tools/update_phd_admissions.py --recheck-all-readable --batch-size 40
```

It snapshots every previously readable `no_explicit_deadline` or
`ambiguous_deadline` programme, plus any newly adopted `unverified` official
links, divides those safely eligible rows into validated batches of no more
than 40 and checks each source **once**. The run has a longer CI timeout for
the larger source budget. It will not retry robots-disallowed,
robots-unavailable, challenge-restricted or failed providers ahead of their
normal refresh cycle. It also does not recheck already verified entries.
The complete pass does not override the strict source-evidence requirements. A true current-cycle date must
still appear in the institution's own HTML with the matching PhD admissions
context. A university may publish only a yearless or rolling deadline; these
cannot be marked confirmed. An attempted recheck is **not** a promise that
all catalogued programmes have a public official deadline.

The 2026 source remediation also replaces the previously failing UC Davis
Economics departmental FAQ with its official university Graduate Studies
Economics programme page (`https://grad.ucdavis.edu/programs/gecn`).
The outdated observation is reset to `unverified`; the new source still
requires an independent robots-aware fetch. Its separately published
**General** and **Space Available** application dates are not automatically
interpreted as one unconditional final doctoral cutoff.

UIC's official Economics PhD admission schedule uses a Fall-year table under
an explicit `Ph.D. in Economics` heading, with domestic and international
application dates in separate rows. The checker accepts these only if both
full-year dates are present, tied to the same intake, and exactly equal.
Conflicting PhD dates fail as ambiguous, and a later Master's section cannot
contaminate the doctoral evidence. Brown's PhD programme directory sometimes
places its dated cutoff inside nested content after a standalone
`Dates/Deadlines` → `Application Deadline` heading: only that named
Economics doctoral section can supply a candidate, with no date inferred from
course requirements or programme navigation.

Some university-owned doctoral admissions pages publish a single
**schoolwide application cutoff** applicable to multiple explicitly named
doctoral programmes. The Purdue Business PhD admissions page is supported only
when its own HTML names Economics among its doctoral routes, states that
Economics PhD applicants need a GRE score, and ties the dated Fall intake to
the shared `Application Deadlines` section with the official
`all supplemental materials must be received by this date` condition.
Likewise, Wharton's Applied Economics PhD is supported only when its
own Doctoral Application Requirements page names Applied Economics and says
the doctoral requirements apply to **all** applicants, with a dated
submission deadline. A generic graduate, MBA, supporting-test or
financial-support cutoff cannot qualify, and multiple distinct full-year
application dates remain ambiguous. Dates are still confirmed only after
a fresh robots-aware institutional fetch.

The checker also recognises a university's **PhD-only Economics**
admissions FAQ when its exact application-deadline answer and the department's
statement that only Economics doctoral students are admitted both appear on
the official page. An unrelated Master's cutoff, a date in another question,
or contradictory application dates cannot pass the check. University
graduate-major requirements pages can be used when they explicitly identify
Economics, exclusive doctoral admission and a full-year application cutoff.
The checker recognises explicit dates in official same-column admissions
tables and grouped PhD deadline lists without borrowing another programme's
date. These cross-element excerpts are labelled as structured table/list
evidence, with their institutional source URL and check time retained.

## Coverage of the expanded programme directory

The monitor attempts every programme, but a current dated confirmation depends
on what each university publishes and permits the checker to read. Rolling
admission, an unpublished next intake, a yearless recurring date, multiple
applicant-group cutoffs and an inaccessible source are distinct unresolved
cases. None becomes a dated confirmation merely because the catalogue contains
the current catalogue rows or a refresh completed successfully.

`tools/audit_phd_admissions.py` produces one record per programme, including its
current verification status, source URLs, date evidence, last check, next
scheduled check and required next action. It checks the stored observation's
calendar date, exact full date in the excerpt, 14-day freshness, catalogue
metadata, matching official HTTPS host and recorded investigation provenance.
It does not fetch university pages or promote an observation. The automatic
refresh exports this report to `docs/data/phd_admissions_coverage.json`; the
report remains available with the repository documentation and as a public data
asset. The dashboard's count, status filter and cards use the same
current-evidence gate, including removal of stale dates. Each programme shows a
concise date and official link, with applicable applicant restrictions and earlier
required application stages visible beside the date. Expandable admission details
retain supporting source evidence and other verified facts. An open page rechecks
date and evidence expiry on the existing clock and foreground events.

The 24 November 2026 review increased independently corroborated dates from
41 in the starting repository to 56, while auditing the complete 251-programme
inventory. The review records are at
[`review/2026-11-24/phd-deadline-coverage.md`](../review/2026-11-24/phd-deadline-coverage.md)
and
[`review/2026-11-24/phd-deadline-source-review.json`](../review/2026-11-24/phd-deadline-source-review.json).
These are dated research records, not an alternative source of live deadline
values. The public observation catalogue remains authoritative for display.

Reviewed institutional layouts are implemented in small, standard-library
modules under `tools/phd_admissions_*.py`, called by the main collector:

- Explicit Economics doctoral application sections, including shared doctoral
  deadlines only where the same page establishes Economics applicability.
- Doctoral application columns and registration ranges, keeping supporting
  documents, funding, preliminary screening, interviews and enrolment separate.
- Domestic/international and full-time/part-time groups, accepted as a single
  deadline only when all required complete dates agree.
- French full-year date ranges and English dates containing parenthesized
  weekdays or times. The original printed date is retained; a year is never
  supplied from an intake heading or inferred for a yearless closing endpoint.

The adapters have no network access or stored deadline overrides. All source
changes first invalidate the previous observation; the existing robots-aware
collector must fetch and corroborate each new official URL. Missing competing
dates, ambiguous group scopes and malformed fields fail closed. The source
review includes successful checks that produced no date and failed checks that
remained unverified; a tested parser alone does not confirm a programme.

For offline verification:

```bash
python3 -S tools/update_phd_admissions.py --check
python3 -S tools/audit_phd_admissions.py --json
PYTHONPATH=src python3 -m unittest tests.core.test_economics_phd_admissions -v
```

For a reproducible coverage check, pass an explicit timezone-aware `--now`.
`--require-all-verified` exits with status 1 unless all catalogued observations actually
have supported current deadlines. Normal refreshes publish the honest coverage
report without requiring an unattainable all-dates condition.

For a bounded live execution **in the authorised Actions environment**:

```bash
python3 -S tools/update_phd_admissions.py --batch-size 25
```

The programme catalogue never joins the employment job-board or
`health.json`. Telegram announcements run only through the existing production
publisher with its own `data/phd_admissions_telegram.json` receipt journal.
They require a current official-source deadline, a fresh check, a matching
institutional HTTPS source and independent non-US country evidence:
either the university's national domain or a current, source-cited institutional
mailing address on its own HTTPS host. Generic domains such as `.eu` cannot
prove country by themselves. Country codes copied from the upstream directory
are not sufficient on their own. Unknown-country, US, blocked, stale, yearless and ambiguous
admissions do not generate posts. The bot sends at most two programme
announcements per normal run by default. Repeated or uncertain sends are
held, not blindly retried, and prior confirmed posts are never deleted by
an admissions-source refresh. A crash after Telegram accepts a send but
before its git checkpoint can still require manual channel reconciliation;
the system does not promise unconditional exactly-once delivery.
A university's official programme website remains the
decision authority for eligibility, funding and deadlines. Even an
automatically corroborated date should be rechecked before submitting.


### Catalogue expansion and corrected programme identity (24 November 2026)

The current seed inventory grows from 251 to **252** with **KU Leuven**, because the Department of Economics publishes a direct [2027–28 doctoral call](https://feb.kuleuven.be/research/economics/PHD/phdcall). Its official page states a 31 January 2027 deadline, but Collegeum's entry remains **`unverified`** until the scheduled robots-aware checker itself corroborates the institutional page. No date was inferred or manually promoted.

The pre-existing **Tilburg University** lead incorrectly used the Research Master's application page. It now points to the University's [PhD in Economics admission requirements](https://www.tilburguniversity.edu/research/economics-and-management/graduate-school/phd-economics/admission), with its previous inconclusive assessment cleared for a new independent check. Research Master's applicant-category dates must not be applied to the PhD vacancy-based route. These programme-count changes do not affect the separate **251 distinct-advert** review; its original fixed cohort remains valid as a dated audit.

The catalogue subsequently added the **University of Padua**, with its official [Economics and Management PhD call](https://www.economia.unipd.it/en/courses/home-courses/phd-programme/phd-calls-and-admissions) as the lead. The university says the 2027/28 call opens in April 2027; because an in-scope closing date is not yet corroborated, this 253rd programme starts `unverified`. It must not inherit the expired 2026 round's deadline.
