# Official-source eligibility engine invariants

The independent PhD funding-call publisher and the general PhD admissions
publisher share a **no-network, standard-library-only eligibility layer**
with their recovery watchdog. The watchdog decides whether an ordinary
pipeline refresh is worth requesting; it never overrides a source check,
does not publish directly and must not have more permissive rules.

## Shared funding-call contract

`predoc_pipeline.core.official_call_evidence.eligible_official_calls`
is the canonical gate used by:

- `predoc_pipeline.publish.official_calls.eligible_calls`
- `tools.ingestion_watchdog.evaluate_official_calls_trigger`

A verified row must contain a current-cycle funding deadline, a **matching
fully parsed date in the official evidence excerpt** (not merely the year),
up-to-date observations, an exact HTTPS evidence URL, an institutionally
corroborated non-US geography, and independently reviewed source provenance.

The generated source catalogue must retain `generated_at` and validated
`source_id`, `institution`, `index_url` and source status. Removing those
summaries from generated data must not bypass approval. Failed/blocked source
states do not authorize a stale `verified` row.

The same stable URL/intake key is retained for Telegram journals. When a
duplicate key disagrees on funding kind, deadline, recommended admission
submission date, departmental grouping, eligibility or funding scope,
location proof, or subject scope, **all conflicting observations are held**
rather than using the last row. Malformed JSON types are skipped safely.

## Shared admissions contract

`predoc_pipeline.core.official_admissions_evidence.eligible_official_admissions_rows`
is the canonical gate used by:

- `predoc_pipeline.publish.admissions.eligible_official_admissions`
- `tools.ingestion_watchdog.evaluate_admissions_trigger`

Admissions are not salaried vacancies or independent scholarship postings.
The verified *admissions* cutoff must match the official excerpt; an
institutional admission calendar can legitimately contain both a dated
opening and a separate deadline, but an alternative deadline is ambiguous.

For non-national domains (`.eu`, `.org`, `.com`, `.edu`) the site's
institution-country fact must have the **right country name**, matching
time, same-host official evidence and investigated URL. A generic fact
claiming Germany for a Spanish programme is not independent proof.
University-approved query-bearing application URLs remain valid.

The historic admissions delivery identity is
`country_code | institution.casefold()`; different university programme
records that collide on this existing one-post key cannot be independently
sent without operator review. This avoids quietly dropping a second
programme or interpreting a collision as a newly unsent announcement.

## Immutable publication and source-policy boundaries

Only the existing publisher may attempt Telegram delivery after the
persisted create-only reservation. Post-send confirmation/uncertainty
records and prior message IDs remain append-preserving. An ambiguous,
pending, conflicting, stale or robots-blocked item must never be
automatically retried or rewritten.

PDF/DOCX review is operator gated and **cannot** return a Telegram-ready
`verified` funding observation. Legacy binary DOC remains held; blocked
institutional sources require permission, not a mirror, redirect or
challenge workaround. The manually withdrawn Henley messages 136–140
remain the user's responsibility and are not automatically reissued.

## Verification

Tests in
`tests/integration/test_shared_official_call_policy_20261121.py` and
`tests/integration/test_shared_official_admissions_policy_20261121.py`
compare publisher and watchdog responses to valid, mismatched, conflicting
and malformed evidence. The full CI must independently pass Python 3.11,
Python 3.12, Ruff, mypy and Telegram Worker before deployment.
