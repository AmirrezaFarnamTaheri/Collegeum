# Economics PhD admissions — official-source monitor

Collegeum incorporates **programme discovery leads**, not the upstream
application-deadline assertions, from
[Economics PhD App Deadlines](https://github.com/paultran47/econ-grad-app-deadlines)
by Paul L. Tran (MIT licence, upstream commit
`49604886769441a11c1e79ab7d1fab68ba5b3d36`).
Its copyright and permission notice is at
[`docs/licenses/econ-grad-app-deadlines-MIT.txt`](licenses/econ-grad-app-deadlines-MIT.txt).

## One source of truth: each official university programme page

- `config/phd_admissions_seeds.json` keeps 251 programme names, country codes,
  official programme links and **unverified** structure hints. No upstream
  deadline data is imported or used by a publisher.
- `tools/update_phd_admissions.py` checks each primary university programme
  link using a bounded HTTPS read that respects robots.txt. It does **not**
  follow arbitrary external links, search for a more convenient source,
  bypass access controls, or scrape the upstream directory again.
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
  a yearless month/day, or the upstream table.
- The static Collegeum dashboard has a separate **PhD admissions** directory
  with search, country filtering, status filtering, and institution links.
  General non-US admissions with a **fresh, explicit, officially verified**
  future deadline are separately announced in the existing Telegram channel.
  There is no conversion into funded research-employment vacancies, X posts
  or personalised research-job notifications. Funding is explicitly unverified.

## Automatic refresh

The independent `phd-admissions-refresh` workflow runs at **03:17, 09:17,
15:17 and 21:17 UTC** (subject to GitHub Actions scheduler delays). Each run
checks at most 25 oldest-due official programme URLs. Never-checked programmes
take priority so missed GitHub schedules cannot strand calendar shards. At a
reliable four-runs-per-day cadence all 251 receive an initial attempted check
within 11 successful runs (under three days). A recorded check is eligible
for renewal after 11 days; the monitor makes no network requests if none are
due. Trusted source-code or seed changes also bootstrap a check on `main`
without waiting for the next cron. On trusted checker updates, the bounded
batch can recheck previously readable programme pages whose deadlines were
inconclusive, so improved extraction takes effect without manual overrides.
This mode does not retry robots-blocked, access-restricted or failed sources
early.
A previously verified deadline is
**withdrawn** if source evidence ages beyond 14 days, or the date passes.
After every check it commits only the derived
`docs/data/phd_admissions.json`. The existing Pages deployment publishes the
result and its MIT notice. No vacancy ingestion, subscriber delivery, or
provider-restricted retries are involved. Failed/blocked checks remain visible
as unverified; no assumption of a live programme is made.

For offline verification:

```bash
python3 -S tools/update_phd_admissions.py --check
PYTHONPATH=src python3 -m unittest tests.core.test_economics_phd_admissions -v
```

For a bounded live execution **in the authorised Actions environment**:

```bash
python3 -S tools/update_phd_admissions.py --batch-size 25
```

The programme catalogue never joins the employment job-board or
`health.json`. Telegram announcements run only through the existing production
publisher with its own `data/phd_admissions_telegram.json` receipt journal.
They require a current official-source deadline, a fresh check, a matching
institutional HTTPS source and corroborated non-US country-domain evidence.
Country codes copied from the upstream directory are not sufficient on
their own. Unknown-country, US, blocked, stale, yearless and ambiguous
admissions do not generate posts. The bot sends at most two programme
announcements per normal run by default. Repeated or uncertain sends are
held, not blindly retried, and prior confirmed posts are never deleted by
an admissions-source refresh. A crash after Telegram accepts a send but
before its git checkpoint can still require manual channel reconciliation;
the system does not promise unconditional exactly-once delivery.
A university's official programme website remains the
decision authority for eligibility, funding and deadlines. Even an
automatically corroborated date should be rechecked before submitting.
