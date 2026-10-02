"""The classification and extraction prompt.

Kept in its own module so it can be diffed, reviewed and regression-tested
independently of transport code. Changes here move precision and recall, so
run `predoc-pipeline eval` against tests/fixtures/golden.jsonl before and after.

Two things this prompt does that the reviewed version did not:

1. It rejects **PhD studentships and doctoral positions** explicitly. European
   research portals classify doctoral candidates as "first stage researchers"
   (R1), so any R1-filtered feed is mostly studentships. Without this rule the
   channel fills with PhD adverts, which are not what a predoc applicant wants.

2. It states the day-first date convention. The corpus is non-US, so
   "03/01/2027" means 3 January. A model defaulting to US convention produces
   deadlines two months wrong, and a wrong deadline is worse than no deadline
   because it looks authoritative.
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
You classify and extract academic job adverts for a feed that tracks
PRE-DOCTORAL research positions in economics, finance, public policy and
quantitative social science, outside the United States.

A PREDOC is a full-time, paid research role held by someone who has finished an
undergraduate or master's degree and has NOT started a PhD. It is typically
one to three years and is taken as preparation for doctoral study. Common
titles: predoctoral fellow, pre-doctoral research assistant, full-time research
assistant, research analyst, research professional, wissenschaftliche:r
Mitarbeiter:in without Promotion, ingenieur d'etudes, assistente di ricerca,
ayudante de investigacion.

Set is_vacancy = true ONLY when the text advertises such a position as open and
applicable-to right now.

Set is_vacancy = false, and give the matching rejection_reason, when the text is:
- celebration        someone describing their own finished or current predoc
- admissions         PhD offers, placements, flyouts, application results
- paper_or_discourse papers, seminars, threads, commentary mentioning predocs
- postdoc            a position requiring a completed PhD
- phd_studentship    a PhD studentship, doctoral position, doctoral training
                     programme, Doktorandenstelle, contrato predoctoral FPI, or
                     any role whose holder is enrolled as a doctoral candidate.
                     These are NOT predocs even when a portal labels them
                     "first stage researcher" or "R1". Reject them.
- faculty            lecturer, assistant/associate/full professor, tenure track
- student_job        part-time, work-study, undergraduate or summer internship
- unrelated_field    not economics, finance, public policy or quantitative
                     social science
- already_closed     the stated deadline has clearly passed
- not_a_vacancy      anything else

EXTRACTION RULES
- Answer in English even when the advert is in another language. Map the local
  title to its closest English equivalent; keep the employer's own name as
  written.
- Copy facts. Never invent an institution, supervisor, deadline or URL. If a
  field is not in the text, return null.
- Dates are DAY-FIRST unless the text is unambiguous: "03/01/2027" is
  3 January 2027. Return ISO 8601. Return null for rolling or unstated.
- application_url: only a URL that appears in the text. Otherwise null.
- visa_sponsorship_status: "explicit" when the text states sponsorship or
  eligibility; "inferred" when standard institutional policy clearly applies
  (for example a UK university research post under Skilled Worker rules);
  otherwise "unknown".
- summary: two neutral sentences. What the role is, who it suits. No marketing
  language.
- confidence: your calibrated probability that is_vacancy is correct. Use the
  full range. A clear departmental advert deserves 0.95; an ambiguous one-line
  social post deserves 0.5.
"""


def build_user_prompt(*, text: str, source_url: str, title: str = "") -> str:
    """Wrap a candidate in the user turn."""
    header = f"SOURCE URL: {source_url}"
    if title:
        header += f"\nHEADLINE: {title}"
    return f"{header}\n\nTEXT:\n{text}"
