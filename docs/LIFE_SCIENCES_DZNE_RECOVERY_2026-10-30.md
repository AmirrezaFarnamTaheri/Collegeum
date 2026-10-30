# DZNE Life Sciences recruitment recovery — 30 October 2026

## Evidence from the official employer feed

The **German Center for Neurodegenerative Diseases (DZNE)** runs a d.vinci recruitment site at [jobs.dzne.de](https://jobs.dzne.de). Its English/German landing pages return HTTP 200 with **no job anchors in the raw HTML**. The official [sitemap](https://jobs.dzne.de/sitemap.xml), however, returned 15 unique individual vacancy URLs in [runner 41063934918](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41063934918), with an employer-owned URL identity.

Of the four URLs containing casual doctoral keywords, **three are postdoctoral roles** and one is a current, entry-level PhD position:

- Employer URL: https://jobs.dzne.de/en/jobs/101677/phd-researcher-fmx-laminar-7t-fmri-of-medial-temporal-lobe-hyperactivity-in-aging-and-alzheimers-disease-1578202610
- Job requisition: **101677**; PhD researcher studying Alzheimer’s disease and laminar 7T fMRI; Multimodal Neuroimaging Group, DZNE Magdeburg
- Official XML `<startDate>`: **2026-10-19T22:00Z**; `<endDate>`: **2026-12-01T22:59:59.999Z**, both explicitly employer-provided
- `<profile>`: a master's degree in neuroscience, psychology, cognitive science, biomedical sciences or related discipline
- Official application path: `https://jobs.dzne.de/en/jobs/101677/apply`
- **Funding has not been verified**, so all downstream records remain `funding_status=unverified`. Current presence in a sitemap does not verify actual later application acceptance.

Read-only [runner 41064734952](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41064734952) verified the current job page is returned as structured **`<jobPublication>` XML**, including `id`, `language`, `position`, `jobPublicationURL`, `applicationFormURL`, `startDate`, `endDate`, `tasks` and `profile`. An accessible *older* 101632 PhD URL is **not in the current sitemap**, and must not be resurrected solely because it returns HTTP 200.

## Changes

This change recovers the **existing** `life_special_de_dzne` candidate. No extra duplicate source is registered.

The source-specific `dzne_sitemap` adapter reads a bounded official XML sitemap; accepts only current individual DZNE `/(en|de)/jobs/{id}/{slug}` vacancy URLs; filters out postdoctoral and unrelated jobs from the candidate set before fetching details; deduplicates by requisition ID; prefers English where present; validates employer URL, XML requisition ID, language and application path; and retains the employer's date, qualification and research evidence without inferring funding.

The regular Life Sciences collector still performs independent doctoral-title, field relevance, degree-required, Europe workplace, age, closure and deadline checks before any publication. **No private state or Telegram send receipts are modified.**

A valid sitemap with no current doctoral candidates may be treated as a verified PhD-empty period. An inaccessible, malformed or off-host-only sitemap, invalid detail, partial detail fetch or exceeded request budget remains an error/partial—not fabricated healthy emptiness. The existing human-facing HTML source probe delegates to the specialized live runner instead of misreading an XML index as zero links.

## Acceptance and counts

- Red/green tests cover individual official ID and application URL, mixed postdoc/staff exclusion, duplicate IDs across languages, expired and mismatched requisitions, malformed/DTD-containing XML, bad or off-host URLs, empty-period detection, and bounded request enforcement.
- Dedicated read-only runner `verify-life-dzne-live` must inspect an actual current official vacancy and classify with the production pipeline; all GitHub Python 3.11/3.12 checks, build, lint, typing and Telegram worker must pass before merging.
- Registry baseline: **225 total definitions, 37 currently enabled on main**. Enabling DZNE proposes **38 enabled**; this is **not** a claim of 38 independently green production source checks, nor 38 open PhD listings.
- Production health and CSV export must be checked on a fresh scheduled ingestion to confirm the source and persisted job-level fields. The historical career journal is preserved.

## Next candidates

Once DZNE is integrated, recover other existing disabled specialist-institute definitions—MPI-CBG, DZNE-related neurology institutes, Leibniz-FLI, Charité, European biomedical doctoral programmes—only on employer-controlled vacancy and application identities. Do not confuse general programme pages, archive pages or postdoctoral positions with current first-doctorate recruitment.
