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
  There is **no** Telegram backfill, vacancy creation, deduplication or
  conversion of programme admissions into funded research-employment offers.

## Automatic refresh

The independent `phd-admissions-refresh` workflow runs daily at 03:17 UTC
(subject to GitHub Actions scheduler delay), checking the 25 oldest due official
URLs per day. Never-checked programmes take priority so missed GitHub schedules
cannot silently strand skipped calendar shards. At a reliable daily cadence all
251 receive an initial attempted check within 11 runs; a recorded
check is eligible for renewal after 11 days. Trusted source-code or seed
changes also bootstrap a check on `main` without waiting for the next cron.
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

Never switch these dates into the job-board, health.json, or Telegram
publishing pipelines. A university's official programme website remains the
decision authority for eligibility, funding and deadlines. Even an
automatically corroborated date should be rechecked before submitting.
