# Helmholtz Munich — recovered official Life Sciences source (30 October 2026)

## Identified public transport

The institution's [official recruitment page](https://www.helmholtz-munich.de/karriere/stellenangebote) embeds the B-ite `main-listing-de` JavaScript widget. The live runner [41061091332](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41061091332) confirmed that:

- The provider publishes its recruitment widget at `https://cs-assets.b-ite.com/helmholtz-zentrum-muenchen/jobs-api/main-listing-de.js`.
- The widget's public browser key and category filter `Homepage_deutsch` permit bounded read-only queries of `https://jobs.b-ite.com/api/v1/postings/search`.
- **10 active recruitment entries** were returned in the German index, with 40-character vacancy identities and HTTPS employer application links under `jobs.helmholtz-muenchen.de/jobposting/...`. The parallel English index returned six and appears narrower. The German index is the primary supported source.
- The **10 discovered entries are not 10 PhD jobs**. They include research staff, administrative positions, trainees and students. At the probe cutoff, **zero verified PhD titles** appeared in that listing. Do not count those jobs as doctoral opportunities or infer open/fully funded doctoral roles.
- The public listing provides a per-job listing end time; this is preserved as a posting deadline where available. A date alone never implies that application is still open.

## Implementation

Reused the pre-existing, regression-tested ZEW B-ite posting identity validator, adapted the source-specific request configuration without modifying ZEW's API semantics, and activated the **existing** disabled `life_special_de_helmholtz_munich` definition (no duplicate registry entry).

Supported source behavior:

1. Only a known official widget, official origin, official search API, expected employer-hosted application domain and stable job IDs are accepted.
2. Discover the public client key from the current published widget script instead of persisting a key as a secret.
3. Verify the published listing type, category and language before issuing bounded requests.
4. Keep paging bounded, reject inconsistent offsets or repeated pages, and surface malformed postings as parser faults.
5. A genuinely empty provider response is marked `verified_empty` **only when the index explicitly reports total=0**.
6. Preserve employer-provided posting dates, application deadlines, institute, research area, and location where present.
7. Run **every** discovery through the ordinary Life Sciences doctoral-role, biology-field, location, degree, expiry and funding filters; office/staff/student postings are not published as PhD vacancies.

## Verification gates

- Unit: canonical 40-hex employer vacancy identities; correct provider request; pagination; unrelated staff exclusion; field and deadline provenance; wrong domain/mismatched ID and invalid widget fail closed; legitimate empty vs broken empty; unchanged ZEW tests.
- End-to-end: dedicated, **read-only** GitHub Actions runner [verify-life-helmholtz-bite-integration](../.github/workflows/verify-life-helmholtz-bite-integration.yml) invokes the production Life Sciences `discover` function for this source, verifies official HTTPS vacancy URLs and reports eligible doctoral matches without changing any journal or subscriber state.
- Full repository CI (Python 3.11 and 3.12, type-check, lint, Telegram worker) and single-file build required before merge.
- Once merged, the **production** health journal should show one additional enabled source but **not** any new verified-open PhD positions unless an actual qualifying employer ad appears. The source remains an enabled *recruitment collector* even during a legitimate period of zero suitable PhD openings.

## Next recovery priorities

Other existing disabled specialists include MPI institutes, DZNE, Leibniz Institute on Aging, Charité, Vienna BioCenter, SIB Switzerland, VHIR, ISGlobal, and CIC bioGUNE. Reactivate only after a supported official vacancy index and vacancy-specific employer URLs, applicant degree requirements, current application status and biological research field are verified. Do not count general career/programme pages, closed doctoral admissions calls, or HTTP 200 pages with no parseable vacancy identities as functional.
