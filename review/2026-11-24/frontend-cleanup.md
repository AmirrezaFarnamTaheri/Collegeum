# Programme directory interface review — 24 November 2026

The admissions and funding sections now present programme choices, dates and
application links without embedding the research log or pipeline policy in the
browsing page. The complete research and verification records remain in the
repository and published data assets.

## Interface changes

- Shortened the introduction, section headings and status text. The programme
  count describes the current filters, for example `251 programmes · 56 verified
  deadlines`; it does not repeat the verification policy.
- Reduced the initial programme list from 30 rows to 12. Search and filters reset
  the page size, and **Show more** adds 12 rows while preserving open details.
- Placed verified closing dates first, ordered by date, followed by unconfirmed
  programmes ordered by institution. Dates use readable labels and semantic
  `<time>` elements.
- Kept each institution, country, date status and official programme link visible.
  Applicant restrictions, compulsory preliminary stages and supported entry-route
  distinctions remain visible beside the date. Those conditions must not disappear
  into a collapsed disclosure.
- Moved supporting source evidence, check dates and other verified facts into native
  **Admission details** disclosures. Unsupported seed structure hints are no longer
  repeated on every row. Stale or unverified facts are withheld.
- Removed the admissions audit download, collector explanations and repeated
  funding-policy blocks from the browsing sections. The footer retains a compact
  directory-credits link to the upstream MIT licence notice.
- Added narrow-screen wrapping and visible keyboard focus for disclosures. Fixed
  the load-more button's CSS so its `hidden` attribute actually hides it, including
  small filtered result sets.

## Freshness while a page remains open

The existing midnight, foreground and one-minute checks now refresh admissions
when a deadline or a supporting fact changes eligibility. They use the same
provenance and freshness gates as the count, filters and rows. A small state
comparison prevents rebuilding unchanged cards every minute, preserving open
disclosures and avoiding unnecessary focus disruption. Loading and failed-fetch
messages are not replaced with an artificial empty-directory result.

## Verification

The actual inline JavaScript is executed with Node and a controlled clock. The
focused interface, date lifecycle and catalogue tests passed **44 tests and 258
subtests**. They cover all stored verified date layouts, invalid dates and source
provenance, count/filter agreement, search and paging controls, ordering, escaping,
visible applicant conditions and entry routes, disclosure preservation, midnight
expiry and the exact 14-day evidence boundary. The expiry regression also checks
that unchanged eligibility does not rewrite the result DOM.

```sh
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/integration/test_phd_admissions_ui.py \
  tests/integration/test_deadline_ui.py \
  tests/core/test_economics_phd_admissions.py \
  tests/core/test_official_calls_dashboard_visibility_20261120.py -q
```

The existing eight Playwright layout tests require a browser environment that is
not available in this workspace. An installed Chromium was also unable to start
because the runtime refused its required socket operation. CSS and markup were
reviewed, but no successful browser rendering or screenshot comparison is claimed.
