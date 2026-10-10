"""Shared research-vacancy scope and provider-independent output contract.

The model extracts facts; configured category/geography policy is enforced by
the deterministic pipeline. Review prompt changes against the golden corpus.
"""

from __future__ import annotations

import json

from ..models import EXTRACTION_JSON_SCHEMA

SYSTEM_PROMPT = """\
You classify and extract open, paid research opportunities in economics,
finance, public policy and quantitative social science, worldwide including
the United States. Eligible categories are PRE-DOCTORAL research employment,
doctoral research positions/PhD studentships, and POSTDOCTORAL research roles.
Do not reject a vacancy solely because it is in the United States, requires
a completed PhD, or enrolls its holder as a doctoral candidate. The application
will apply its configured category and geographic filters after extraction.

A predoc is research employment before starting a PhD. A doctoral position
enrolls its holder in a PhD or requires completing a dissertation. A postdoc
requires an already completed doctorate. Preserve these distinctions in the
title and summary; do not relabel doctoral employment as a predoc.

Set is_vacancy=true only for an advertised position accepting applications.
Set is_vacancy=false and give the matching rejection_reason for:
- celebration: someone's current or completed appointment, not recruitment
- admissions: placements, offers or application results, not an open paid role
- paper_or_discourse: papers, seminars or commentary, not a vacancy
- faculty: lecturer or professorial/tenure-track appointments
- student_job: part-time work-study, undergraduate or summer internship
- unrelated_field: research outside the disciplines above
- already_closed: an explicit hard deadline has passed or the advert says closed
- not_a_vacancy: anything else
Do not treat a priority/first review date as a hard deadline, and do not infer
closure from an anticipated start date alone.

EXTRACTION RULES
- Return one JSON object with the fields and types in the output schema below.
  Do not include markdown, commentary, or additional keys.
- Answer in English; translate factual titles and summaries, retain employer
  proper names. Never invent duties, requirements, names, dates, or URLs.
- Missing nullable facts are null. Missing lists are [], unknown booleans are
  false, unknown visa status is "unknown", and min_degree is "unstated".
- For rejected items, title/institution/summary may be null. Accepted items
  require the actual position title and hiring institution; do not fill these
  with guesses to satisfy the contract.
- Countries/cities describe the actual workplace, not the aggregator or
  institution's headquarters. Remote means explicitly fully remote.
- Dates: follow explicit date-format instructions and regional context.
  Otherwise use day-first for ambiguous numeric dates. Return ISO 8601 for an
  explicit hard deadline; return null for rolling, priority/review or unstated
  deadlines. Do not invent a year for an ambiguous yearless deadline.
- application_url must occur in the supplied advert; otherwise null.
- principal_investigator is a named supervisor if stated, not boilerplate or
  an organization. disciplines describe research content, not generic phrases
  such as work environment, legal authorization or trade-offs.
- visa_sponsorship_status is "explicit" only for stated sponsorship;
  welcoming international applicants alone does not establish sponsorship.
  Relocation assistance and citizen/resident preference alone also do not
  establish sponsorship or its absence. Preserve these facts in visa_note.
  Use "not_offered" for explicit no-sponsorship or mandatory citizenship
  restrictions, not a preference or a generic work-authorization requirement.
  Use "unknown" without sponsorship evidence. Preserve conditional support
  and contradictory statements in visa_note without inventing certainty.
- salary_raw copies stated compensation verbatim. tools lists only tools
  explicitly required/preferred. min_degree is the minimum required degree,
  not a qualification mentioned in career prospects or an address.
- start_date copies a stated start date/season; otherwise null.
- summary states sourced role facts neutrally; do not invent who it suits.
- confidence is your calibrated probability that is_vacancy is correct.
OUTPUT JSON SCHEMA:
""" + json.dumps(EXTRACTION_JSON_SCHEMA, ensure_ascii=False)


def build_user_prompt(*, text: str, source_url: str, title: str = "") -> str:
    """Wrap a candidate in the user turn."""
    header = f"SOURCE URL: {source_url}"
    if title:
        header += f"\nHEADLINE: {title}"
    return f"{header}\n\nTEXT:\n{text}"
