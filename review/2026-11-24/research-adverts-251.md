# Research-advert review — 24 November 2026

**Distinct research adverts checked: 251 of 251.** Every selected identity has
a completed assessment and timestamped evidence or an explicit access outcome.
The count is derived by an offline audit, not maintained as a handwritten total.

**134 adverts retain matching, substantive body evidence.** Completing a check
does not establish that its page is readable, its applications are open, or its
research field is eligible for Collegeum. The review keeps those claims separate.

## Results

| Review outcome | Distinct adverts | What the evidence establishes |
| --- | ---: | --- |
| Readable advert | 114 | A matching, substantive advert body was captured and reviewed. Current application availability is a separate question. |
| Explicitly closed advert | 24 | The matching primary advert contains a closed notice or a verified elapsed application cutoff. Twenty retain their substantive bodies; four retain a closure notice and identity only. |
| Access unavailable | 69 | Robots policy, provider refusal or an access challenge prevents a usable advert check. No access bypass or successful body verification is claimed. |
| Fetch failed | 11 | The bounded request failed; four are newly researched university adverts. |
| Removed endpoint | 14 | The requested endpoint returned HTTP 404 or 410. This does not establish why recruitment ended. |
| Unverified response | 19 | An HTTP 200 response did not establish a matching advert body. This includes soft missing pages, redirects and application shells. |
| **Completed assessments** | **251** | **134 include a full body; 117 do not.** |

The [complete review](research-adverts-251.json) records each identity, employer,
source, primary URL, reviewed aliases, original capture time, outcome, eligibility
assessment, response status and evidence. Successful captures include byte counts
and SHA-256 hashes. Short literal excerpts preserve the evidence without copying
whole employer adverts into the repository.

The evidence was captured on 24 November 2026. This is a dated research record,
not a live count of open jobs. The normal scheduled collector remains responsible
for future observations, eligibility, extraction, duplicate detection and
publication. These records are separate from the **251-programme PhD admissions
catalogue** and do not change its confirmed-deadline count.

## How the cohort was selected

| Cohort component | Adverts |
| --- | ---: |
| ESMT Berlin, Indian School of Business and WU Vienna, from the first source expansion | 21 |
| University of Vienna, University of Amsterdam, Maastricht University and Utrecht University, from the second source expansion | 60 |
| Existing direct-link research journal identities, ordered by newest durable journal ID after identity review | 170 |
| **Fixed target** | **251** |

The existing-journal candidate inventory contained 189 records. The selection
includes every distinct research advert from both new-source batches, then fills
the remaining 170 places by journal ID. Successful access is not a selection
criterion. Sixteen additional distinct journal checks are retained separately in
the JSON and do not inflate the 251-advert cohort.

Identity review resolved the following cases:

- J-PAL journal record **31** links to the exact University of Zurich requisition
  in journal record **278**. They count once. The J-PAL page retains the advert;
  the employer endpoint returned HTTP 410. Both observations remain recorded,
  and application availability is unconfirmed.
- Carlo Alberto record **223** is a general assistantship scheme with a hiring
  request form for professors. It is excluded from the individual-advert cohort.
- AcademicTransfer record **455** strongly overlaps with the new official Utrecht
  Generative AI research-assistant advert in title, substantive body, deadline and
  named contact. The journal copy is conservatively excluded. No shared
  requisition URL is asserted without that evidence.
- Fifteen proven German-language versions of Vienna vacancies are recorded as
  aliases of the matching employer Job ID. They do not add fifteen adverts.

Same titles alone do not establish duplicate identity. In particular, the two WU
requisitions with matching titles remain separate because their actual employer
requisition IDs differ.

## Source expansion and eligibility

The [first expansion](official-source-expansion.md) added three employer sources.
The [second expansion](official-source-expansion-round2.md) adds four more, with
bounded pagination, matching primary advert identities and full-detail gates.
The source registry now contains **151 boards, of which 82 are enabled**. The
69 previously disabled boards retain their existing status.

Across the 81 newly researched source adverts, **27 pass the collector's gates**:
17 from the first expansion and 10 from the second. Forty-eight are rejected by
the existing subject/role checks and six are deferred: two elapsed-start adverts
from the first expansion and four failed captures from the second. These are
collector candidates, not a claim of 27 new published or previously unseen jobs.

The 170 selected historical journal identities have a separate purpose: checking
their evidence and current response state. Their earlier publication is not
repeated here, and they are not included in the 27-candidate claim. The Zurich
mirror has an additional explicit deferral because its employer application
endpoint is gone.

## Capture and review boundaries

The existing bounded official-source reader fetched independently identified
public URLs after checking robots policy. Requests were paced by host;
same-host redirects were validated; provider denials stopped later requests.
Existing captures were reused with their original capture timestamps. Access
decisions record the governing policy or refusal receipt and explicitly say when
no advert request was sent.

The normal pipeline HTTP client's outbound destination guard could not resolve
public DNS in this workspace. That guard was preserved. Permitted research
captures were replayed offline through the adapters and collector; this is not
reported as a live production collection run. No notifications, publication or
deployment were performed by the review.

The journal-body review verified primary headings, requisition IDs, matching
structured data or scoped advert containers. A JavaScript application shell,
generic career index, hidden description or unrelated sidebar is insufficient.
Historical journal deadlines, elapsed starts, yearless dates, priority review
dates and standalone `validThrough` metadata do not establish closure.

## Repeatable validation

```sh
python3 -S tools/audit_research_adverts.py
python3 -S tools/audit_research_adverts.py --json
```

The standard-library-only audit rejects incomplete outcomes, duplicate IDs and
aliases, shared successful advert captures, evidence from an unrelated URL,
unrelated access-policy receipts, invalid timestamps, unsupported success/closure
claims and contradictory body/outcome metadata. It derives the displayed count
from the valid individual observations. The committed cohort also runs in the
dependency-free core test gate.

When original captures are available, an additional check verifies their byte
counts, hashes and literal HTML/JSON excerpt plausibility:

```sh
python3 -S tools/audit_research_adverts.py --capture-dir /path/to/original/captures
```

For this review, that check verified **160 successful raw response captures**,
including responses that did not contain an advert. Hash validity alone does not
make a page an advert. PDF hashes are checked, while PDF text and employer-specific
body semantics remain separately recorded review judgments.

`--require-all-bodies` is a stricter, separate condition and **fails for this
review**, because only 134 of the 251 identities retain a matching full body.
Unavailable or closed-notice-only records are never promoted to satisfy it.
