# LinkedIn replay and evidence review — 24 November 2026

This follow-up reviews the LinkedIn implementation at commit `7c410a7` using
offline response fixtures and the committed query checkpoints. It extends the
[earlier content and access review](2026-11-24-linkedin-content-and-access-review.md).
No live LinkedIn requests, account access, production dispatches, credential
changes, source-portfolio changes or budget increases were performed.

## Reproduced failures and fixes

| Reproduction | Resulting behaviour |
|---|---|
| A recommendation nested inside the primary description supplied another job's deadline, PhD requirement and closure text. | Exclude unrelated containers inside a description as well as descriptions inside unrelated containers. Preserve ordinary nested primary content. |
| An authwall inside an explicitly hidden ancestor triggered a provider-wide cooldown despite a visible primary advert. | Remove explicitly hidden and template content before interpreting challenge structure or advert evidence. Visible access challenges still stop collection. Hidden search cards make the response incomplete instead of silently shortening a page into completion. |
| A description longer than 20,000 characters was returned as received after truncating later requirements. | Keep the existing text limit, but return no partial description as verified evidence. A separate, identity-consistent primary closure banner remains usable as closure evidence. |
| A persisted query hash could identify one keyword/location while its record named another; a buffered job's map key could disagree with its card ID. | Validate query hashes against source and canonical query identity, and bind each buffered card to its map key. Validate required title, query provenance and observation/attempt timestamps. Invalid checkpoints fail without being overwritten. |
| Repeated result pages advanced the cursor and consumed the remaining page allowance without adding jobs. | Persist a bounded fingerprint of each accepted page's job IDs per pending query. Reordered repeats retain updated card evidence, keep the cursor and prior completion time unchanged, and defer that query using the existing four-hour transient retry. |
| The shared HTTP client raised an HTTP 200 `access_interstitial` error before the LinkedIn parser saw the body; the queue continued trying other queries. | Recognise that specific access-gate error in search and detail paths. Apply the existing 48-hour provider cooldown while preserving the actual HTTP status. Other HTTP 200 failures remain transient failures. |
| A peer audience recorded denial after search planning, but already queued searches continued. | Recheck the shared cooldown before each queued search request. Retain the earlier accepted page and report the unfinished discovery as partial. |

## Measured request reduction

The same fake provider returned the same ten valid job cards for every requested
offset. Both implementations used one query, a twelve-request ceiling and the
same twelve-page limit. The baseline modules were loaded directly from commit
`7c410a7`; the comparison made no network calls.

| Offline outcome | Baseline | Follow-up |
|---|---:|---:|
| Search requests | 12 | 2 |
| Distinct jobs preserved | 10 | 10 |
| Queries falsely reported complete | 0 | 0 |
| Configured request ceiling | 12 | 12 |

The follow-up avoids ten redundant requests in this repeated-response case.
This is a controlled regression result, not a claim about live provider
performance. Tests also verify that a genuinely new page with overlapping jobs
continues, cross-query duplicate jobs retain both query labels, and pagination
resumes at the unchanged offset after the existing retry interval.

## Checkpoint and access compatibility

Both committed economics and Life Sciences checkpoints pass the stricter
validation without modification. Existing pending cursors that have no page
fingerprints remain readable. Their first subsequently accepted page establishes
new response history; no evidence is invented about previously fetched pages.
Fingerprints exist only within the current pending query and remain bounded by
the existing page limit. Partial or malformed pages do not establish accepted
page history.

Search allowances, separate enrichment limits, portfolios, environment flags and
provider permissions are unchanged. The shared HTTP client's existing eight-MiB
response bound remains unchanged. Parser acceptance, checkpoint validity and
cooldown expiry do not establish employer verification or provider permission.

## Validation

The new regression file adds **34 passing tests**. The complete existing and new
LinkedIn board/integration suite passes **194 tests**. Targeted Ruff checks pass;
Mypy reports no issues in the three LinkedIn source modules.

```sh
.venv/bin/python -m pytest -q \
  tests/boards/test_linkedin_*.py \
  tests/integration/test_linkedin_*.py \
  --basetemp=/tmp/collegeum-linkedin-tests
```

The suite exercises source parsing, checkpoint restoration, retry/cursor state,
shared-HTTP-client access errors, queued detail requests, and downstream deadline,
eligibility and closure enrichment. All clients are fake or use an in-memory
HTTP transport; no test contacts LinkedIn.
