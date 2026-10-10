"""Deterministic pre-model gate and rule score. Stdlib only.

This is the cheapest and most consequential filter in the pipeline. Every item
it rejects is a model request not spent, and the provider's free daily request
quota -- not runner minutes -- is the binding constraint on how many sources
this pipeline can watch.

It does three jobs:

1. **Reject** obvious non-vacancies (celebration posts, paper promotion,
   admissions chatter) and out-of-scope vacancies (postdoc, faculty, and
   crucially *PhD studentships*, which dominate European research portals and
   are the single largest false-positive class for this domain).
2. **Require** a positive hiring signal, in any of the seven languages these
   adverts actually appear in. A gate built only from negative patterns passes
   everything it has no rule for, which is the wrong default when the cost of a
   false positive is a model call.
3. **Score** what survives, on features that are independently checkable
   (deadline present, application URL present, employer named, imperative
   hiring verb). That score is blended with the model's self-reported
   confidence later, because an LLM's own confidence number is uncalibrated
   and thresholding on it alone is superstition.

Every pattern is scoped as tightly as the language allows. `\\bpostdoc\\b`
anywhere in the text would reject a perfectly good advert containing the line
"this is not a postdoctoral position".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textproc import language_hint, squish

__all__ = ["GateResult", "evaluate", "rule_score", "POSITIVE_TERMS", "HARD_REJECT"]

# --- positive signals -------------------------------------------------------
# A posting must contain at least one of these to be worth a model call.
POSITIVE_TERMS: dict[str, tuple[str, ...]] = {
    "en": (
        r"pre[- ]?doc(toral)?\b",
        r"\bpre[- ]?ph\.?d\b",
        r"\bpost-?bacc(alaureate)?\b",
        r"\bresearch assistant\b",
        r"\bresearch associate\b",
        r"\bresearch analyst\b",
        r"\bfull[- ]time (research )?(assistant|analyst)\b",
        r"\bresearch professional\b",
        r"\bpost[- ]?doc(toral)?\b",
        r"\bph\.?d\b",
        r"\bdoctoral\b",
        r"\bresearch fellow\b",
    ),
    "de": (
        r"wissenschaftliche[rn]?\s+(mitarbeiter|hilfskraft)",
        r"\bwiss\.?\s*mitarbeiter",
        r"\bforschungsassistent",
        r"\bpr[äa]doktoral",
        r"\btv-?l\s*e\s*13",
        r"\bpostdoktorand",
        r"\bdoktorand",
        r"\bpromotionsstelle",
    ),
    "fr": (
        r"ing[ée]nieur[e]?\s+d['’]?[ée]tudes",
        r"assistant[e]?\s+de\s+recherche",
        r"\bpr[ée]doctoral",
        r"charg[ée]\s+d['’]?[ée]tudes",
        r"\bpost-?doctorat\b",
        r"\bdoctorant",
    ),
    "es": (
        r"\bpredoctoral",
        r"ayudante\s+de\s+investigaci[óo]n",
        r"asistente\s+de\s+investigaci[óo]n",
        r"investigador[a]?\s+(junior|no\s+doctor)",
        r"\bposdoctorado\b",
        r"\bdoctorando",
    ),
    "it": (
        r"assegn(o|ista)\s+di\s+ricerca",
        r"assistente\s+di\s+ricerca",
        r"\bpre-?dottoral",
        r"\bpost-?dottorato\b",
        r"\bdottorato\b",
    ),
    "nl": (
        r"onderzoeksassistent",
        r"\bjunior\s+onderzoeker",
        r"\bpromovendus\b",
        r"\bpostdoc\b",
    ),
    "pt": (
        r"assistente\s+de\s+(investiga[çc][ãa]o|pesquisa)",
        r"\bbolseir[oa]\s+de\s+investiga",
        r"\bdoutorando\b",
    ),
}

# Hiring intent. Present in nearly every real advert, absent from chatter.
HIRING_VERBS: tuple[str, ...] = (
    r"\b(we|i)\s+(are|am)\s+(hiring|recruiting|looking for|seeking)\b",
    r"\bapplications?\s+(are\s+)?(invited|open|welcome)\b",
    r"\bapply (now|by|before|online|here)\b",
    r"\b(is|are)\s+(now\s+)?(recruiting|hiring|accepting applications)\b",
    r"\b(vacancy|vacancies|job opening|position available|open position)\b",
    r"\bseeks?\s+(to\s+)?(appoint|recruit|hire)\b",
    r"\bclosing date\b|\bapplication deadline\b|\bdeadline for applications\b",
    # non-English
    r"\bbewerbungsfrist\b|\bwir\s+suchen\b|\bstellenausschreibung\b|\bausschreibung\b",
    r"\bcandidatures?\b|\bnous\s+recherchons\b|\boffre\s+d['’]emploi\b|\bdate\s+limite\b",
    r"\bconvocatoria\b|\bse\s+busca\b|\bplazo\s+de\s+solicitud\b",
    r"\bbando\b|\bscadenza\b",
)

# --- hard rejects -----------------------------------------------------------
# Scoped so they match the *subject* of the post, not a passing mention.
#
# Three scopes, because real predoc adverts routinely say "you will work with
# PhD students and Assistant Professor X" or "ideal preparation for a PhD
# program". Scanning the whole body for "PhD program" / "assistant professor"
# rejected four out of five genuine CEMFI/UPF/LMU/Bocconi-style adverts.
#
# CHATTER  -- social-media talk (celebrations, admissions, papers, events).
#             Checked on short texts only (a tweet, a feed blurb): a full job
#             page that mentions "our new paper" is still a job page.
# TITLE    -- what the position *is*. A postdoc/PhD/faculty/student-job title
#             is rejected; faculty words are ignored when the title also names
#             a predoc/RA role ("Research Assistant, Chair of Finance").
# LEAD     -- the opening of the text when it announces the position itself
#             ("applications are invited for a fully funded PhD studentship").
CHATTER_REJECT: tuple[tuple[str, str], ...] = (
    # Someone talking about their own completed predoc.
    (r"\b(i|we)\s+(just\s+)?(finished|completed|wrapped up|am finishing)\s+(my|our|their)\s+"
     r"(pre-?doc|predoctoral|ra\b)", "celebration"),
    (r"\b(thrilled|excited|happy|proud)\s+to\s+(share|announce)\s+.{0,60}"
     r"(accepted|admitted|offer|starting)\b.{0,40}\bph\.?d\b", "admissions"),
    (r"\b(i|we)\s+(have\s+)?(been\s+)?(accepted|admitted)\s+(to|into)\b", "admissions"),
    (r"\bcongratulations?\b.{0,80}\b(predoc|ph\.?d|placement)\b", "congratulations"),
    # Paper / seminar / discourse.
    (r"\b(our|my|new)\s+(working\s+)?paper\b", "paper-promotion"),
    (r"\b(seminar|webinar|workshop|conference)\s+(announcement|series|registration)\b", "event"),
    (r"\bcall for (papers|abstracts|proposals)\b", "call-for-papers"),
)
CHATTER_MAX_CHARS = 1200  # longer than any tweet or feed blurb, shorter than a job page

# The look-behinds keep "Pre-doctoral Fellowship" / "Pre-PhD position" safe.
_PHD_JOB = (r"(?<!pre-)(?<!pre )\b(ph\.?d|doctoral)\s+"
            r"(studentships?|candidates?|positions?|"
            r"scholarships?|fellowships?|vacanc(y|ies)|openings?|researcher)\b|"
            r"\bdoktorand\w*|\bpromotionsstelle\b|\bdoctorant\w*|\bdottorand\w*|"
            r"\bcontrato\s+predoctoral\s+fpi\b")

TITLE_REJECT: tuple[tuple[str, str], ...] = (
    (r"\bpost-?doc", "postdoc"),
    (_PHD_JOB + r"|(?<!pre-)(?<!pre )\bph\.?d\s+students?\b", "phd-studentship"),
    (r"\b(undergraduate|work[- ]study|part[- ]time student|summer intern(ship)?|"
     r"student assistant|studentische)\b", "student-job"),
    (
        r"^(?:(?:our\s+|current\s+|former\s+|meet\s+(?:our|the)\s+|external\s+|academic\s+)?"
        r"(?:faculty|staff|people|team|alumni|directors|board)|"
        r"was\s+wir\s+bieten|studierende|diversit[äa]t|stellenangebote|"
        r"why\s+do\s+a\s+pre-?doc\??|ra\s+award\s+program|before\s+applying|"
        r"benefits|our\s+culture|work\s+with\s+us|join\s+us|contact\s+us|"
        r"postdocs?|faq|privacy\s+policy|asynchronous\s+courses|pre-?docs?\s+in\s+industry|"
        r".*pre-?doctoral\s+research\s+in\s+economics\s+\(pre\)\s+workshop.*|"
        r".*students\s+achieve\s+outstanding\s+placements.*)$",
        "not-a-vacancy",
    ),
)
# Only when the title names no predoc/RA role of its own.
TITLE_FACULTY = (r"\b(tenure[- ]track|(assistant|associate|full)\s+professor|professor(ship)?|"
                 r"lecturer|senior lecturer|reader in|chair in)\b")

LEAD_REJECT: tuple[tuple[str, str], ...] = (
    (r"\bpost-?doc(toral)?\s+(position|fellowship|vacancy|opening)s?\b", "postdoc"),
    (r"\b(fully[- ])?funded\s+(ph\.?d|doctoral)\b|" + _PHD_JOB, "phd-studentship"),
    (r"\b(tenure[- ]track|(assistant|associate|full)\s+professor(ship)?)\s+"
     r"(position|opening|vacancy|post)s?\b", "faculty"),
)
LEAD_CHARS = 280

# Whole text: a requirement, not a mention.
BODY_REJECT: tuple[tuple[str, str], ...] = (
    (r"\bph\.?d\s+(degree\s+)?(is\s+)?(required|mandatory|essential)\b|"
     r"\b(must|should)\s+(hold|have)\s+(a|an)\s+(ph\.?d|doctorate)\b|"
     r"\bcompleted\s+(ph\.?d|doctorate)\s+is\s+required\b", "phd-required"),
)

#: Kept for backwards compatibility with code that imported the old table.
HARD_REJECT: tuple[tuple[str, str], ...] = CHATTER_REJECT + TITLE_REJECT + LEAD_REJECT + BODY_REJECT

_POS_RE = {
    lang: re.compile("|".join(pats), re.IGNORECASE | re.UNICODE)
    for lang, pats in POSITIVE_TERMS.items()
}
_ANY_POS_RE = re.compile(
    "|".join(p for pats in POSITIVE_TERMS.values() for p in pats), re.IGNORECASE | re.UNICODE
)
_VERB_RE = re.compile("|".join(HIRING_VERBS), re.IGNORECASE | re.UNICODE)


def _compile(table: tuple[tuple[str, str], ...]) -> list[tuple[re.Pattern[str], str]]:
    return [(re.compile(p, re.IGNORECASE | re.UNICODE), label) for p, label in table]


_CHATTER_RE = _compile(CHATTER_REJECT)
_TITLE_RE = _compile(TITLE_REJECT)
_TITLE_FACULTY_RE = re.compile(TITLE_FACULTY, re.IGNORECASE | re.UNICODE)
_LEAD_RE = _compile(LEAD_REJECT)
_BODY_RE = _compile(BODY_REJECT)

_DEADLINE_RE = re.compile(
    r"\b(deadline|closing date|closes|apply by|until|bewerbungsfrist|date limite|"
    r"scadenza|plazo)\b|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)
_EMPLOYER_RE = re.compile(
    r"\b(universit|college|institute|school of|department of|faculty of|centre|center|"
    r"laborator|bank of|central bank|hochschule|université|universidad|università|"
    r"academy|research (group|unit|centre|center))\b",
    re.IGNORECASE,
)
_QUANT_RE = re.compile(
    r"\b(stata|matlab|python|r\b|julia|sql|econometric|regression|causal|"
    r"microdata|panel data|rct|difference[- ]in[- ]differences)\b",
    re.IGNORECASE,
)
_FIELD_RE = re.compile(
    r"\b(econom|finance|public polic|political scien|quantitative social|"
    r"development|labour|labor|industrial organi|behavio(u)?ral)\w*",
    re.IGNORECASE,
)

MIN_LENGTH = 40  # shorter than a tweet with a link; below this there is no signal


@dataclass(slots=True)
class GateResult:
    """Outcome of the deterministic gate."""

    passed: bool
    reason: str = ""
    language: str = "en"
    score: float = 0.0
    signals: list[str] = field(default_factory=list)

    @property
    def rejected(self) -> bool:
        return not self.passed


_EXCLUDED_URL_RX = re.compile(
    r"/people/(?:faculty/|staff/|index|$|\?)|"
    r"/faculty/(?:index|pages/profile|personal|$|\?)|"
    r"/staff/(?:index|directory|$|\?)|"
    r"/alumni/|/experts?/|"
    r"/news/stories/|"
    r"/was-wir-bieten|/diversitaet|/studierende|/stellenangebote|"
    r"/ra-matching|/learn-more|/before-applying|/courses|/private-firms|/pre-workshop|"
    r"facid=|facId=",
    re.IGNORECASE,
)


def _reject_reason(
    title: str,
    text: str,
    body: str,
    *,
    url: str = "",
    title_only: bool = False,
    allow_phd: bool = False,
    allow_postdoc: bool = False,
) -> str:
    """The first hard-reject label that applies, or ''.

    ``title_only`` is for job-board items: their text is a whole web page whose
    opening may be site navigation ("PhD positions | Postdocs | Jobs"), and the
    board scraper has already applied the PhD-required rule to it.
    """
    if url and _EXCLUDED_URL_RX.search(url):
        return "not-a-vacancy"
    if not title_only and (len(body) <= CHATTER_MAX_CHARS or not title):
        for pattern, label in _CHATTER_RE:
            if pattern.search(body):
                return label
    subject = title or squish(text)[:LEAD_CHARS]
    for pattern, label in _TITLE_RE:
        if pattern.search(subject):
            if label == "postdoc" and allow_postdoc:
                continue
            if label == "phd-studentship" and allow_phd:
                continue
            return label
    if _TITLE_FACULTY_RE.search(subject) and not _ANY_POS_RE.search(subject):
        return "faculty"
    if title_only and title:
        return ""
    lead = squish(text)[:LEAD_CHARS]
    for pattern, label in _LEAD_RE:
        if pattern.search(lead):
            if label == "postdoc" and allow_postdoc:
                continue
            if label == "phd-studentship" and allow_phd:
                continue
            return label
    for pattern, label in _BODY_RE:
        if pattern.search(body):
            if label == "phd-required" and (allow_postdoc or allow_phd):
                continue
            return label
    return ""


def evaluate(
    text: str,
    *,
    title: str = "",
    url: str = "",
    known_vacancy: bool = False,
    allow_phd: bool = False,
    allow_postdoc: bool = False,
) -> GateResult:
    """Decide whether `text` is worth a model call, and score it.

    ``known_vacancy`` is set for items from job boards (see boards/collector.py):
    the board itself is the hiring signal and the board scraper has already
    checked the role wording, so only the hard rejects apply.
    """
    body = squish(f"{title}\n{text}" if title else text)
    if len(body) < MIN_LENGTH and not (known_vacancy and title):
        return GateResult(False, "too-short", language_hint(body))

    lang = language_hint(body)

    reason = _reject_reason(
        squish(title),
        text,
        body,
        url=url,
        title_only=known_vacancy,
        allow_phd=allow_phd,
        allow_postdoc=allow_postdoc,
    )
    if reason:
        return GateResult(False, f"reject:{reason}", lang)

    if not known_vacancy:
        lang_pos = _POS_RE.get(lang)
        has_role = bool((lang_pos and lang_pos.search(body)) or _ANY_POS_RE.search(body))
        if not has_role:
            return GateResult(False, "no-role-term", lang)

        has_intent = bool(_VERB_RE.search(body))
        if not has_intent:
            return GateResult(False, "no-hiring-intent", lang)

    score, signals = rule_score(body, url=url, known_vacancy=known_vacancy)
    return GateResult(True, "", lang, score, signals)


def rule_score(
    text: str, *, url: str = "", known_vacancy: bool = False
) -> tuple[float, list[str]]:
    """Feature score in [0, 1] from independently checkable evidence.

    Weights are hand-set and documented rather than fitted, because there is no
    labelled corpus large enough to fit them honestly. They are deliberately
    coarse: this score exists to *moderate* the model's confidence, not to
    replace it. Re-tune against `tests/fixtures/golden.jsonl` via
    `predoc-pipeline eval` before changing them.
    """
    signals: list[str] = []
    score = 0.0

    if _ANY_POS_RE.search(text) or known_vacancy:
        score += 0.30
        signals.append("role-term")
    if _VERB_RE.search(text) or known_vacancy:
        score += 0.25
        signals.append("hiring-intent")
    if _DEADLINE_RE.search(text):
        score += 0.15
        signals.append("deadline")
    if _EMPLOYER_RE.search(text):
        score += 0.15
        signals.append("employer")
    if _FIELD_RE.search(text):
        score += 0.10
        signals.append("field")
    if _QUANT_RE.search(text):
        score += 0.05
        signals.append("quant-skills")
    if url:
        signals.append("has-url")

    return min(1.0, round(score, 4)), signals


def blend_confidence(model_confidence: float, rule: float, *, weight: float = 0.75) -> float:
    """Combine the model's confidence with the deterministic rule score.

    A weighted geometric-style blend: the arithmetic mean lets a confident
    model override a total absence of evidence, which is exactly the failure we
    are guarding against. Weighting towards the model keeps recall while the
    rule score can still veto.
    """
    m = min(max(float(model_confidence), 0.0), 1.0)
    r = min(max(float(rule), 0.0), 1.0)
    return float(round(m**weight * max(r, 0.05) ** (1.0 - weight), 4))
