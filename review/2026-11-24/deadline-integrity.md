# Shared job deadline integrity — 24 November 2026

## Behavior change

Free-text application cutoffs now use `parse_deadline_date`, separate from the
general date and posting-age parsers. A cutoff needs a complete, valid calendar
date with its own four-digit year. A numeric day/month pair must have only one
possible interpretation. These rules prevent both fabricated future years and
silent assumptions about the source's locale.

| Source text in a cutoff field | New result | Reason |
| --- | --- | --- |
| `15 January` | Unconfirmed; raw text retained | No explicit year |
| `5/24/27` | Unconfirmed; raw text retained | Century is not explicit |
| `03/04/2027` | Unconfirmed; raw text retained | Could be 3 April or 4 March |
| `2027-01-15` | 15 January 2027 | Fixed ISO order |
| `15/01/2027` or `01/15/2027` | 15 January 2027 | Only one valid numeric order |
| `11/11/2027` | 11 November 2027 | Both orders give the same date |
| `2027-15-01` | Unconfirmed | Invalid ISO is not repaired by swapping fields |
| `January 15, 2027 or February 1, 2027` | Unconfirmed | The field has competing cutoffs |
| `January 15, 2027 (2027-01-15)` | 15 January 2027 | Repeated evidence agrees |

The parser also rejects invalid leap/calendar dates, mixed numeric separators,
and a yearless date followed by a different fully qualified date in the same
field. It does not borrow an intake year or infer the next occurrence from the
current date. `extract_deadline` retains its `ref` argument for compatibility,
but a cutoff's year no longer depends on that value.

Every relevant application-cutoff field is checked before confirmation, including
later labels and incomplete numeric or month/year alternatives. A rejected field
retains its full conflicting evidence, so parsing a shortened excerpt cannot
restore its first date. Explicit requirements, qualifications, experience,
schedule, salary and contact sections end the date field; recognized funding and
other non-application deadlines do not compete with an application cutoff.

The shared extractor preserves an unconfirmed raw date snippet without supplying
a date value. Review dates and rolling recruitment retain their existing handling;
explicit priority dates and dates “for full consideration” are also treated as
review timing rather than final application cutoffs.
A separately labelled start/interview/posting date still ends the cutoff field,
so it cannot provide a missing deadline year. Priority and review qualifiers are
recognized before the label and after the date, including parenthesized roles.

## Caller impact

| Caller | Change |
| --- | --- |
| `boards.utils.dates.extract_deadline` | Uses strict cutoff parsing for labelled text |
| `boards.heuristics.apply_heuristics` | Inherits the strict parser; uncertain text cannot fill a deadline |
| `boards.heuristics.check_still_open` | An ambiguous or yearless date cannot expire a listing |
| `extract.heuristic` | Inherits the strict parser for extracted job-ad deadlines |
| RSS, text-table and selector-based board fields | Inherit the strict labelled extractor |
| `predoc_org` deadline/review fields | Uses the strict labelled extractor and preserves the original date role |
| `prospective_jobs` submit-by fallback | Uses strict parsing even when the source-specific instructions bypass the generic label matcher |
| `link_scan` bare-date option | Requires one unambiguous, explicit cutoff; no longer chooses the last of competing dates or overrides a labelled unknown/review cutoff |

`parse_date`, `find_dates`, `parse_posted`, `parse_iso_datetime` and the start-date
parser are unchanged. Relative ages such as “3 days ago”, “a week ago” and
“30+ days ago” keep their previous behavior. The general parser continues to
support yearless posting dates and two-digit years for its existing callers.
Structured ATS timestamps keep their separate parsing contract.

### PREDOC review roles

PREDOC previously mapped “First review date”, “Priority deadline” and the mixed
“Deadline/First Review Date” label to a single deadline value. This could turn a
review date into an expiry date even when its year was explicit. The parser now
keeps review fields separate from final cutoff fields. Review information remains
in `deadline_text` when there is no hard cutoff, and in the existing `extra`
dictionary as `predoc_review_note` when both are present. No new date is inferred.

The generated description keeps the source's original role labels. This matters
because shared enrichment reads that description again: renaming a review date
as an application deadline would recreate the error on a second pass. A mixed
label alone does not establish a hard cutoff, while explicit wording such as
“applications close on February 1, 2027” can establish one. A separate genuine
final deadline takes precedence without discarding the review note.

Repeated PREDOC labels retain every cutoff and review value in both the extracted
evidence and generated description. A leading phrase such as “For full
consideration” stays attached to its date instead of leaking into the previous
institution field. Bern's longer submit-instructions fallback also uses the
complete retained context and cannot override a rejection by the shared parser.

No journal, dashboard observation, delivery ledger or historical record was
modified. This governs subsequent extraction from observed source text; it does
not retrospectively assert that old stored values were corroborated or clear
existing dates without fetching their evidence.

## Verification and changed legacy expectations

The focused new regressions cover valid named and numeric dates, invalid dates,
year/order ambiguity, raw-evidence retention, reference-date independence,
relative posting dates, shared enrichment, expiry rechecks and all three migrated
source-specific paths. They use local HTML and stub detail readers only.

Five legacy assertions encoded the behavior being removed: a yearless `01 Oct`
cutoff, a PREDOC `5/24/27` cutoff, a KU `12-10-2026` cutoff and a rolling-recruitment
test using `01/11/2026`, plus a PREDOC first-review date treated as a hard cutoff.
Their evidence was not rewritten. The first three now
assert an unknown cutoff while preserving the observed text. The rolling test
still verifies precedence of a valid fixed deadline using ISO syntax, and a
separate regression verifies that rolling language cannot resolve numeric-order
ambiguity. Positive source-specific cases confirm that fully qualified cutoffs
continue to work. Additional role regressions verify first-review and priority
dates, mixed labels, a separately stated final cutoff, retained review notes and
the second enrichment pass over the generated source description.

The final focused suite and existing caller/integration regressions passed
**225 tests**. This includes complete Bern parsing, subsequent enrichment and
eligibility checks without an administrative end date, plus PREDOC repeated-field
and qualifier preservation. Ruff and mypy passed the affected source files. The
complete repository suite and standalone distribution are checked separately at
integration.

```sh
.venv/bin/python -m pytest -q tests/boards/test_deadline_evidence_20261124.py tests/boards/test_utils.py tests/boards/test_scrapers.py tests/boards/test_bern*.py tests/integration/test_review_deadline.py --tb=short
```
