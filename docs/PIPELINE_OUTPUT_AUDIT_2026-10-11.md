# Historical pipeline-output audit and repair — 11 October 2026

## Sources inspected

- [Workflow #38139499012](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/38139499012): job successful; application **partial**; 81 sources, 25 failed, 31 source errors, 2 publications.
- [Workflow #38128994107](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/38128994107): job successful; application **partial**; 26 failed sources, 32 source errors, 114 new publications.
- Earlier 9–10 October jobs #37999493839 and #38051274329: full application outcomes **ok**.
- Downloaded five historical DLQ ZIP artifacts. The four completed runs' `dlq-failures.json` held `[]`, although later source failures were visible in health telemetry. The cancelled run #38114147888 had only `run.log`.
- Parsed latest `main` `data/listings.ndjson` (175 unique listings), `data/seen.ndjson` (498 unique seen items), `docs/data/listings.json` (134 matching-count records), RSS (100 entries), and health history (27 runs). These have no observed parse errors or duplicate journal identities.

## Historical records conservatively quarantined

Ten previously published records have objectively unusable application links. This does **not** establish that the underlying vacancies closed.

| Durable listing ID | Defect | Telegram message retained |
| --- | --- | --- |
| 55 | authentication-redirect | No |
| 115 | unresolved-url-template | No |
| 117 | unresolved-url-template | No |
| 119 | generic-job-board-homepage | No |
| 120 | unresolved-url-template | No |
| 121 | unresolved-url-template | Yes |
| 122 | unresolved-url-template | Yes |
| 145 | unresolved-url-template | Yes |
| 148 | unresolved-url-template | No |
| 162 | unresolved-url-template | No |

## Changes on PR branch only

- Source journal: 175 records retained; 10 entries now carry an explicit output-audit quarantine timestamp and reason, with original IDs, hashes, `published_at`, and Telegram receipts unchanged.
- Public listings snapshot: 134 → 127; 7 faulty records removed without inventing replacements.
- RSS feed: 100 → 93; 7 unusable links excluded. RSS is capped at 100; the next real export can fill available slots with other valid jobs.
- Health: originally `status=degraded`, `last_run.outcome=partial`; both preserved. Derived closed count 5 → 15, with explicit output-audit provenance.
- History in existing public Git commits and any previously transmitted messages is not erased. Nothing is posted/reposted to Telegram during this repair.
- Future protection: ingest URL/auth detection, pre-LLM link-scan template exclusion, public export filtering, and sanitized source failure entries in DLQ artifacts. Offline `tools/audit_pipeline_outputs.py --repair` also creates backups before mutating.

## Remaining manual acceptance

Live re-verification of individual vacancies, provider-specific scraper fixes, external account/Telegram availability, and running the new pipeline code on `main` after PR review. Public job-specific `http://` links are not automatically rejected solely for lacking TLS.

Reviewed at 2026-10-11T18:00:00Z.
