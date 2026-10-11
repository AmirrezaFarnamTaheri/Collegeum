# Collegeum — production-output due diligence

**Baseline:** published main-branch snapshot generated 2026-10-11 12:41:36 UTC, health snapshot 12:41:37 UTC. **Working remediation:** draft PR [#16](https://github.com/AmirrezaFarnamTaheri/Collegeum/pull/16). **Authority:** the committed production dataset, its ingestion code, GitHub Actions logs, and linked original employer/advertiser vacancy pages. No claims of live delivery are based on a green workflow alone.

## Method: distinguish format, semantics, provenance, delivery

An output is correct only if (1) its bytes parse under the consumer's format rules, (2) record identity and linkage are consistent, (3) field meanings match authoritative vacancy evidence, (4) time and lifecycle are valid at publication, (5) filtering/routing is consistent with policy, (6) externally presented application links actually lead to vacancy/application pages, (7) the deployed site shows the intended snapshot, and (8) notifications were accepted/recorded by the remote service. A passing syntax test is **necessary but not sufficient** for these independent conditions.

Each finding below is classified as **confirmed from local artifacts**, **confirmed with an employer source**, **suspected requiring re-verification**, or **not verifiable without credentials/browser/provider access**. Counterfactual checks include searching for exact duplicates, alternate employer pages, differences between source and publication, and whether missing data may genuinely be absent in the advert.

## 1. Full current-output inventory

| Artifact | Main snapshot | Tested properties |
|---|---:|---|
| data/listings.ndjson | 175 records | JSON syntax; IDs; URLs; identity; statuses; timestamps; history |
| data/seen.ndjson | 498 decisions | References; rejection reasons; content hashes; recovery |
| docs/data/listings.json | 134 visible records | Schema; count; field parity with state; ranking; URLs; deadlines |
| docs/feed.xml | 100 most recent visible records | RSS XML, GUIDs, ordered membership, title/link/description/category/date parity |
| docs/data/health.json | 81 current source identities, 27 recorded runs | Outcome/status consistency, source accounting, quota/state chronology |
| docs/index.html | dynamic dashboard and CSV export | Labels, filters, role mapping, deadlines, compensation, safe export |
| docs/rss.xsl | HTML stylesheet of RSS | Correct canonical self-link and static inclusion |
| data/telegram_state.json, feedback.json | minimal committed metadata | Existence, but not proof of actual Telegram delivery |
| compile_project.py | reproducible single-file project artifact | Source manifest parity, static asset completeness, cross-platform line endings |

The following are **positive results** on the baseline: 134 dashboard IDs uniquely exist in the state journal; the dashboard count equals the array length; 100 RSS items match the first 100 dashboard records in order and share exact titles, destinations, GUID sources, descriptions, categories and first-seen publication dates. No repeated application URLs, state IDs or state URL hashes were found. These tests do **not** validate the factual truth of those identical fields.

## 2. Actual data quality and measured completeness

The visible 134 records classify as 83 predoc/RA, 15 doctoral, and 36 postdoctoral. The baseline job kinds are not reliable without examining the employment stage. In particular, [Bank of Canada's PhD Researcher](https://careers.bankofcanada.ca/job/Ottawa-%28Downtown%29-PhD-Researcher-%282026-2027-PhD-Job-Market%29-ON/606660617/) is a **permanent** Senior Economist/Senior Financial Sector Specialist recruitment, not doctoral enrollment. PR #16 now supports a separate **research staff** classification rather than misrepresenting senior employment as a PhD studentship.

| Field | Published entries with a value | Without a value |
|---|---:|---:|
| Explicit deadline | 82 | 52 |
| Numerical salary (baseline) | 26 | 108 |
| Raw salary text | 30 | 104 |
| Identified city | 72 | 62 |
| Principal investigator | 95 | 39 |
| Required tools | 37 | 97 |
| Preferred tools | 0 | 134 |
| Minimum degree other than unstated | 77 | 57 |
| Explicit or other non-unknown visa status | 16 | 118 |

**Interpretation:** absence is not automatically a parser defect. Confirm with the original advert before imputing deadline, salary, sponsorship, PI, skills, or location. Some published salary **values** are worse than missing: TV-L pay grades #118/#156, a 2026 rate-year note #148, and mixed pay grades #133 were incorrectly turned into monetary values. PR #16 retains raw source text where amounts are ambiguous, stops inventing USD/year defaults and handles basic country/locale currencies.

A targeted provider comparison confirms a stronger omission: Bank of Canada [officially states annual CAD 114,952.50–156,778.00](https://careers.bankofcanada.ca/job/Ottawa-%28Downtown%29-PhD-Researcher-%282026-2027-PhD-Job-Market%29-ON/606660617/), but current item #77 has **no salary** in the published snapshot. A fix to the salary parser alone will not restore the value until extraction/refresh reads the source evidence.

Other ground-truth conflicts: #173 identifies "CAS in Medication Safety University of Bern" despite the [Institute for Financial Management's Finance PhD](https://jobs.unibe.ch/offene-stellen/doktorand-in-und-assistent-in/e819ecc1-afc0-4b98-9d48-fec4dbaa8090); #46 assigns the [Penn Behavior Change for Good predoc research-and-communications coordinator](https://bcfg.wharton.upenn.edu/opportunities/) to Chicago Booth; #139 marks PhD as minimum degree although [University of St. Gallen explicitly requires a completed master's for its PhD student position](https://jobs.unisg.ch/offene-stellen/research-and-teaching-associate-in-strategic-management-phd-student-m-f-d/af629a21-df7d-4783-9ddd-54b48564e108). Confidence scores of 0.83–0.98 did not prevent these errors. They are scores from heuristic/model fusion, not demonstrated calibrated probabilities of correctness.

## 3. URL/application correctness

Structural URL validity is not evidence of a job-opening or application destination. Confirmed harmful outputs include #55 (scraped Google sign-in page and long login URL presented as role information), #25 (Greenhouse URL with explicit error=true query), and #119 (generic EconJobMarket homepage in place of a specific advert/application link). PR #16 quarantines obvious access/error-page artifacts, permits safe unwrapping of a Google Forms continue URL, and does not invent a destination when the real application link is unverified. A generic careers homepage may be a useful source page but must never be described as a direct job application.

Remaining gate: live-request validity, login/captcha state, region restrictions, and actual apply button behavior must be checked per provider. Do not treat a 403 from a CI runner as proof that a human-facing vacancy is closed. On HTTP 404/410, use confirmation or multiple observations before closing a vacancy unless independent source evidence is decisive.

## 4. Source reliability and misleading historical outcomes

The production health payload declares 81 sources and reports **44 successful, 12 empty, 25 failed, 3 partial**, adding to 84 because the three partial sources are counted twice. Correct mutually exclusive accounting using actual per-source evidence is:

| Source outcome | Count |
|---|---:|
| Successful | 44 |
| Explicitly permitted empty | 3 |
| Failed or unexpectedly empty | 31 |
| Partial | 3 |
| Skipped | 0 |
| **Total** | **81** |

The additional nine unexpectedly empty-but-HTTP-successful collectors are academictransfer, BIS, ifo, NIESR, NY Fed, RWI Essen, SOMMA, UZH and ZEW. Some may legitimately have no vacancies, but their configuration does not identify them as seasonal/possibly empty. Treat this as **unverified source coverage**, not demonstrated permanent site failure. Partial scrape data from McGill (64 items), UBC (34) and Chicago Workday (89) was accompanied by parsing errors. A partially yielding source is not healthy merely because it returned dozens of items.

The rolling health file retains 27 runs; 22 previous rows had outcome "ok" while source evidence showed failures. PR #16 derives truthful historical summary classifications without rewriting historical raw outcomes and ensures successful-check timestamps are preserved. Source 403/404/418, DNS, and parsers still require provider-specific live remediation.

## 5. Suppression, rejection decisions and loss of recall

Seen-item decisions: 302 rejected, 145 accepted and 51 duplicate. Of the rejected records, at least 13 are labeled "not a vacancy: phd_studentship" and seven "not a vacancy: postdoc". These labels conflict with current inclusion of doctoral and postdoctoral positions. Not every such posting is valid or still open; the issue is that the old rejection **cannot be falsified on an unchanged posting** if eligibility preferences change.

The previous fingerprint candidate-v3 encoded title, body and hints but no eligibility-policy version. A rejected record could therefore stay suppressed indefinitely after source expansion. PR #16 now versions cached decisions with a stable, per-run policy fingerprint; it reopens relevant old PhD/postdoc rejections once, rechecks previously rejected records when filter semantics change, and preserves accepted/duplicate decisions when source evidence is unchanged. Reprocessing remains bounded by existing extraction quotas; live recall must be measured after the next production run.

There are 35 historical accepted decisions without populated listing-reference hashes. Five source hashes directly match an existing listing identity; the remaining cases need trace-level inspection before any joining. All 164 currently populated listing-reference hashes resolve. The patch repairs provenance only when an exact identity match exists; guessing based solely on title/institution risks incorrectly merging separate cohorts.

## 6. Duplicate detection versus distinct listings

No exact duplicate IDs, application URLs or URL hashes were found. However, 19 same-title/same-employer collisions use **distinct** URLs: multiple University of Chicago Booth research professional adverts, MIT Sloan technical associates, Gothenburg postdoctoral fellow adverts and other institutions. These are **review candidates**, not automatic duplicates. Distinct requisition codes, supervisors, departments, cohort years and research briefs often denote different jobs with identical generic titles. Do not deduplicate these using only normalized title and institution; verify the posting identity or content fingerprint and honor explicit different job IDs.

## 7. Deadlines and state transitions

Three historical rows (#1, #21 and #27) were published after their stated cutoff. They have since been expired and omitted from the site. Their original journal events should remain auditable. The old active-listing query checked status and explicit expired/closed flags but not the actual deadline, leaving a grace-period window in which expired jobs could remain visible. Pending retry queries allowed a one-day deadline grace period. PR #16 now enforces exact UTC deadline instants in active search, pending retries and pre-publication extraction.

The browser originally rendered unknown deadlines as "Rolling review" for many undated records. "No deadline supplied" and "employer confirmed rolling" are different facts: the fixed frontend shows "Deadline unstated" until a rolling assertion exists. The persisted exact local timezone or date-only precision of an employer deadline cannot always be reconstructed from a UTC-only stored instant; do not claim a precise local closing hour unless sourced.

## 8. Website, RSS, CSV, Telegram and X

- **Website:** old GitHub navigation/issue links and embedded constant pointed to predoc-not-org. Fixed on PR. Dashboard JSON is reparsed each visit, but deployment/Pages cache and service availability were not confirmed using a logged-in browser.
- **RSS:** the main snapshot's homepage and Atom self-link used predoc-not-org. The stylesheet appended /feed.xml to an already slash-terminated address. Fixed on PR. RSS has a 100-item cap and is not a lossless export of 134 website records; those counts should not be presented as a contradiction.
- **CSV:** the dashboard exports filtered selections with quoting and formula neutralization, covered by Node/Python regression tests. The salary display previously invented currency/year units where unknown; corrected. CSV inherits record-level semantic errors from its input.
- **Telegram:** 34 stored Telegram message identifiers, but many records are intentionally web-only; null is not proof of delivery failure. A completed telegram-sync job can skip without processing when FEEDBACK_ENCRYPTION_KEY is absent. Actual subscription processing, bot commands, encryption and receipts require configured live credentials for proof.
- **X:** no stored X post identifiers in this snapshot. This supports "no recorded X posting receipts," not a categorical assertion that X posts failed; configuration, authorization and publication history are separate.
- **Single-file distribution:** previously omitted several required dashboard assets. The generated bundle now includes static HTML/SVG/PNG/XSL/JSON assets while excluding mutable public snapshot files. Manifest and newline-conversion tests were expanded. The release-refresh workflow commits the bundle on feature branches, so CI on the original pre-refresh commit may fail the freshness check; evaluate the dispatched CI on the refreshed head.

## 9. CI and falsifiable future release gates

The added dependency-free audit checks strict JSON (including no duplicate keys and no NaN), NDJSON shape, source/public identity consistency, count/field types, URL validity, timestamps, chronology, health accounting, RSS well-formedness, ordered membership, and **exact RSS title, description, link, source GUID, categories and publication timestamp parity**. Historical semantic anomalies are warnings, not fake structural errors. CI also exports the complete machine-readable findings as a GitHub artifact; the console displays only a bounded sample.

These gates remain to establish real-world correctness before merge/release:
1. Re-ingest verified employer pages for high-confidence wrong employers, degree requirements, missing salary and ambiguous applications, with the source URL and tested evidence attached.
2. Diff all old and regenerated state/dashboard/RSS items; require expected changes only, preserve immutable identity/delivery history and publication lifecycle.
3. Measure a sample of direct application links in a real browser from supported regions; distinguish auth blocking, transient failure and a confirmed closed posting.
4. Verify that expanded life-sciences sources and filters are **actually merged and enabled**; main still has 88 economics-focused board configurations, two feeds and one portal, with biological/biomedical fields explicitly rejected.
5. Verify X, Telegram and GitHub Pages with their actual connected environments; do not infer delivery from GitHub workflow success.
6. Re-run reproducible-build checks and the Python 3.11/3.12 test matrix on the PR's **latest generated commit**, not a stale pre-refresh commit.

## 10. Decision, boundary and status

**Confirmed repaired in the draft PR:** health attribution; unexpected empty source classification; salary currency, grade and unknown-unit presentation; obvious error/login-page quarantine; URL consistency for site/RSS; deadline cutoff enforcement; unknown-versus-rolling display; strict cross-format checks; policy-dependent rejection reconsideration; split of permanent completed-PhD research staff from PhD studentships; removal of unsafe field assumption on general university Workday boards; complete archive diagnostics.

**Still unresolved:** verified field corrections to individual previously published vacancies; full vacancy-specific ATS URLs; appropriate reclassification of historically incorrect employer/degree fields; coverage of provider failures; actual live bot/X delivery; active life-sciences expansion on main. No merge, production overwrite or external correction is claimed.

The evidence ledger at **review/2026-10-11/verified-output-findings.json** records each high-priority case and explicitly distinguishes parser fixes from data still awaiting source re-extraction. The durable publication logs must not be rewritten to hide previously incorrect output.
