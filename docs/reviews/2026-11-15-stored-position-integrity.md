# Collegeum stored-position integrity audit — 15 November 2026

## Source snapshot and grain

- Controlling source: `data/listings.ndjson` on `main` at commit `840832698064e708637b917f01d905d173481bad`, 437 accepted URL-identity records (historical journal).
- Separate ledger: `data/career_jobs.ndjson` at the same revision, 98 career-key records (97 `life_sciences_phd`, 1 `data_analyst`).
- **535 stored entries are not 535 verified open vacancies or deduplicated human jobs.** The career and academic ledgers use different grains and may overlap.
- Profile as of 2026-11-15 ~08:10 UTC. Repeat with `python -m tools.audit_stored_positions`. The script is read-only and reports durable IDs but never prints signed URLs or tokens.

## All-record checks (before remediation)

| Quality dimension | Journal (437) | Career (98) | Interpretation |
|---|---:|---:|---|
| Duplicate primary identities | 0 IDs / 0 URL hashes | 0 keys | No broken primary-key grain |
| Missing country | 4 | 9 | Needs source evidence, not inferred employer headquarters |
| Minimum degree unknown/unstated | 146 | not in career schema | Not proof of a qualification error |
| Deadline absent | 185 | 46 | Absence is uncertainty, not indefinite availability |
| Deadline passed by audit time | 124 | 15 by date | Historical archive, not necessarily a live vacancy |
| Past deadline but missing expiry marker | 3 (#198, #249, #338) | not applicable | Check post-date expiry lifecycle, not a permission to republish |
| Confirmed new PhD Telegram receipts | 16, message IDs 117–119 | separate subscription system | Never replay or reset |
| Legacy Predoc Telegram message IDs | 98 not marked `confirmed` in newer PhD-only state | not applicable | **Not failures.** Old Predoc receipt model predates new PhD state field |
| Numeric ATS location | not observed | 1 (`location="7"`) | Display bug rather than a usable city |
| Generic career-base URLs shared by multiple records | parameterized ATS links | multiple | Query/requisition IDs must NOT be erased to deduplicate |

All journal records have an application URL and an institution string. Thirty-six lacked `last_checked_at` at the snapshot. These fields are not proofs of application availability.

## Verified remediation in this change

1. **Funded doctoral studentships and quantitative human sciences.** HKU / Max Planck Population Studies listing #195 was incorrectly excluded by both a narrow Economics-only topic condition and an admissions-regex false positive. The employer calls it a **jointly funded, position-specific four-year studentship**, requiring a two-part application and placement in Hong Kong and Rostock. The official closing deadline is **1 December 2026**. It is a supported doctoral vacancy, not merely generic graduate-school admissions. Routing now considers explicit computational human/social sciences, digital demography, quantitative social sciences, population studies and closely related research focus. Funding is required only to override a generic-admissions phrase; actual role, country, topic and completed-PhD checks still apply. Source: https://www.mpg.de/27030733/hku-mpidr-phd-stundentship

2. **Predoc location accuracy.** Journal #53 was recorded as `United States` / not remote, despite J-PAL's official Good Business Lab job advert explicitly saying **remote in Colombia**. Corrected country and remote marker; attribution now identifies Good Business Lab as the employer and J-PAL as the listing source, preserving URL identity and publication history. Source: https://www.povertyactionlab.org/careers/research-associate-good-business-lab-job-105625 . Journal #40 says Chinese University of Hong Kong in the employer field; set the previously blank country to Hong Kong without altering its already-recorded Predoc Telegram message #20. Other blanks (#41, #152, #200) are left unresolved rather than guessed.

3. **Doctoral minimum-degree evidence.** Passau Development Economics listing #407 was misrecorded as needing a completed PhD, excluding a genuine doctoral vacancy. Its official requirements allow an **MA/MSc in Economics or Development Studies** or near-completion, with applications by **22 November 2026**. Correct the minimum degree, source note and project summary; add official links without rewriting the durable identity or delivery state. The end-of-day timestamp is an explicitly marked placeholder, not a verified cutoff hour. Source: https://www.uni-passau.de/fileadmin/dokumente/beschaeftigte/Stellenangebote/2026_11_WM_Prof_Grimm_engl__002__Ri_MG.pdf . The dashboard fields are aligned with the journal to avoid a public-state-divergence error.

4. **Life Sciences category purity.** Existing career titles for Symbolic AI, Swedish `nationalekonomi` (Economics), and unrelated Computing Science were eligible for a Life Sciences category due broad page context / English-only exclusions. The original career rows stay auditable; explicit off-field titles are excluded by the shared current/historical Life Sciences guards, with exceptions for actual biological and genomic research in the *title*. The Helmholtz Munich numeric ATS location `7` is replaced with the verified country, and future numeric location tokens are not displayed as cities.

5. **Previously mitigated non-vacancy pages.** Federal Reserve internship FAQ #201 and Stanford-only undergraduate opportunity #295 are historical source records; the publication-quality guards already suppress these as actionable vacancies. Do not delete the historical records or treat those pages as open employment requisitions.

## Deliberate non-changes and unresolved checks

- Do **not** conflate old Predoc message IDs with the distinct PhD `telegram_delivery_state`. A backfill that relied on that field alone could duplicate old Predoc posts.
- No blanket renaming of `country` from institution headquarters or location guessed from descriptive boilerplate. Further missing-location records require official role-location verification.
- Do not erase meaningful ATS query strings when deduplicating career URLs: two postings can share the same path but differ by actual requisition ID.
- Some Life Sciences records are Economics or general computational science, with their own subscriber audience. **Quarantining them from an incorrect Life Sciences category does not automatically create an approved academic journal listing.** A separately tested cross-ledger adoption workflow would be required to bring verified unmirrored economics opportunities into the public channel.
- Each of the 124 past-deadline journal records remains historical until source-specific closure and public projection are checked. Do not mark a vacancy closed solely because it is off-topic, and do not claim missing deadlines imply open status.
- The 16 confirmed Economics doctoral deliveries in messages 117–119 retain their message IDs. No extra Telegram post is claimed by merging this PR. Any next controlled send must pass offline eligibility, source-link checks, batching and durable duplicate protection.

## Controls and acceptance

- New regression cases cover the HKU–Max Planck source record, funded versus generic admissions, genuine adjacent doctoral topics, unrelated/qualified-staff exclusions, verified Predoc locations, off-topic Life Sciences classifications, numeric ATS locations, and journal/career primary-key integrity.
- Original red CI run: https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/43693752314 (15 expected new failures on the old code).
- Pass only after Python 3.11 and 3.12 full suites, Telegram Worker checks, exact-head build, and journal-to-dashboard integrity pass.
- Retain the **existing Predoc Telegram channel** and existing six-per-cycle historical limit. Merge and CI do not themselves establish that Telegram published a new digest.
