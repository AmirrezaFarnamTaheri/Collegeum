# Helmholtz Munich — official Life Sciences recruitment source recovery

## Production source (30 October 2026)

The pre-existing catalogue entry `life_special_de_helmholtz_munich` had been disabled because the official careers page is a JavaScript shell with no vacancy anchors. The academic source registry still records the same 225 provider identities: **no new duplicate entry** is introduced.

Verified official landing pages:
- [English careers](https://www.helmholtz-munich.de/en/career/jobs) declares B-ite widget `helmholtz-zentrum-muenchen:main-listing-en`.
- [German careers](https://www.helmholtz-munich.de/karriere/stellenangebote) declares `helmholtz-zentrum-muenchen:main-listing-de`.
- The employer's publicly embedded scripts are at `https://cs-assets.b-ite.com/helmholtz-zentrum-muenchen/jobs-api/main-listing-{en,de}.js`.
- The embedded public widget (not a private API or a credential) uses B-ite search `https://jobs.b-ite.com/api/v1/postings/search` and employer-specific `custom.Zuordnung` filters `Homepage_englisch` / `Homepage_deutsch`. The client key is extracted from the publisher's JS each run; it is **not hardcoded or stored**.

## Actual job observations (GitHub runner)

- [Official English search probe](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41060890478): six individual employer-hosted vacancy URLs; zero doctoral roles.
- [Official German search probe](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41061091332): ten individual URLs, including shared English entries; zero doctoral roles.
- [Actual Collegeum scraper live acceptance](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/41062422262): ten distinct URLs after inter-language deduplication; 0 fetch/parse/limit errors, 0 qualifying Life Sciences PhD positions; both published scripts and the read-only API were robots-permitted from the GitHub runner.
- Every returned link is the official form `https://jobs.helmholtz-muenchen.de/jobposting/<publisher-ID>`, with a posting-specific identity and employer-supplied dates.

The older indexed "PhD Candidate — Organelle Biology and Proteomics in Cardiometabolic Disease" advert **was not present in either current live feed** on October 30. Do **not** publish it merely because an indexed URL still resolves, and do not call the ten employee vacancies ten biology PhDs.

## Integration safeguards

This recovery **reuses** the existing audited `BiteJobsScraper`, adding a tightly pinned `site_profile = "helmholtz_munich"` with exact official widget URL(s), search endpoint, origin and vacancy host. ZEW's separate economic-research B-ite source remains unchanged.

Both language cohorts are bounded by a three-page-per-cohort cap, checked pagination metadata, and validated individual job IDs/hosts. Duplicate IDs from German/English feeds collapse within a single collector run. Network failures remain partial/failed rather than healthy-empty. Staff, technician, student assistant, senior scientist and administrator listings do **not** pass Life Sciences doctoral classification. Employer-given expiry dates are retained in the career journal for any future eligible doctoral record; missing funding remains unverified.

The source contributes **one functional enabled recruitment provider**, changing enabled definitions from 36 to 37 of 225, even when there are no currently open doctoral vacancies. This status must still be confirmed by a fresh scheduled main ingestion after merge; CI and read-only probes alone cannot certify the durable production report.

## Remaining admissions/recovery queue

University of Bern, DKFZ, ETH D-BSSE, Helsinki, ISTA and Vienna BioCenter still need official individual vacancy evidence; EMBL's winter PhD call closed October 12, 2026. Source-health rotation and export freshness require further production acceptance. Do not enable old programme pages or circumvent access denials.
