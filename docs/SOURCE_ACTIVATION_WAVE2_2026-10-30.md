# Non-US recruitment activation wave 2 — 30 October 2026

## Scope and operational goal
Promote exactly two previously disabled official public recruitment sources in
continental Europe: WIFO (Austria) and CEPS (Belgium). The economics registry
moves from **76 to 78 enabled** if this change is merged. This is a
configuration count, not a guarantee of 78 healthy or eligible job feeds.
Existing 46 other unapproved members of the 51-source candidate expansion
remain disabled; the original candidate CSV manifests are historical records,
not current live flags.

## Official employer evidence

| Source | Employer / country | Accepted current vacancy | Format |
|---|---|---|---|
| `wifo_austria_jobs` | Austrian Institute of Economic Research / Austria | PhD Candidate, Prae-Doc (m/f/d, 30 hours/week) | Specific WIFO job announcement |
| `ceps_brussels_research` | Centre for European Policy Studies / Belgium | Research Assistant – Green transition and sustainable societies (ERCC Unit) | CEPS October 2026 PDF |
| `ceps_brussels_research` | CEPS / Belgium | Research Assistant – Enlargement Programme (Foreign Policy Unit) | CEPS October 2026 PDF |

Exact official source vacancy URLs appear in
`config/approved_research_sources_wave2_20261030.csv`.
The link-formatted CEPS adverts are PDFs; they are actual job descriptions, not
unrelated PDF announcements. Their contents and application instructions
require the existing downstream degree, deadline, location and publication
gates. They are **not** presumed to be uniformly full-time economics predocs.

## Verification evidence

- Read-only source anchor discovery on [GH runner 40956134883](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40956134883):
  both official employer landing pages responded HTTP 200, with distinct
  job-specific links; WIFO also had an economist staff vacancy, and CEPS
  unrelated management adverts. Those are deliberately excluded.
- Real scraper acceptance on [runner 40957033829](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40957033829):
  WIFO 1 unique accepted candidate and CEPS 2, with zero fetch, parse,
  or pagination-limit failures on either source.
- RED test [runner 40956514299](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/40956514299):
  tests failed before activation. After configuration was enabled,
  one assertion assumed a trailing slash; the app intentionally normalizes
  vacancy URLs without that slash. Its expected URL was corrected
  without changing production canonicalization.
- Full final-head CI verification must be completed before merge.

## Safeguards

Both source records retain `field_implied=false` and use *both* a narrow
`link_pattern` and a `title_allow_pattern`. This prevents an unrelated
WIFO economist listing or CEPS managers' PDF from being admitted merely
because they share the employer's careers page. WIFO is restricted to explicit
doctoral announcements, CEPS to the two approved research-assistant themes.
No bots, secrets, Telegram receipts, subscriber state, saved job history, or
production ingestion journal are modified by this PR.

After merge the next real production ingestion must still verify that the
sources are healthy or legitimately empty and that the degree/field filters
exclude any unrelated candidates. Ingestion on Oct 29 with 76 sources was
internally **partial**: 66 successful, 7 empty, 2 failed (CREST 503 and
Copenhagen), 1 skipped; it published 15 positions. Those outstanding source
failures are not repaired by this expansion.
