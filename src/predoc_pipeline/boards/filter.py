"""Relevance scoring, region gating and expiry checks."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import FilterConfig
from .models import JobPostSchema
from .utils.dates import today
from .utils.geo import detect_location, region_from_url


def term_rx(term: str) -> re.Pattern[str]:
    """'pre-doctoral' matches 'pre-doctoral', 'pre doctoral', 'predoctoral'.

    A trailing * is a prefix match ('econom*' -> economics); a leading * also allows letters
    before the term ('*econom*' -> macroeconomics, socioeconomic, neuroeconomics).
    """
    t = term.strip().lower()
    infix, prefix = t.startswith("*"), t.endswith("*")
    t = t.strip("*")
    body = re.escape(t).replace(r"\-", r"[\s\-]?").replace(r"\ ", r"[\s\-]?")
    left = r"\w*" if infix else r"(?<![\w])"
    right = r"\w*" if prefix else r"(?![\w])"
    return re.compile(left + body + right, re.IGNORECASE)


# PhD-student positions (not pre-docs). The look-behinds keep "pre-PhD"/"pre-doctoral" safe.
PHD_POSITION = re.compile(
    r"(?<!pre-)(?<!pre )(?<!pre)\b(ph\.?d\.?|doctoral|doctorate)\s+(student|candidate|position|fellow(ship)?|"
    r"researcher|scholarship|studentship|programme|program|project)s?\b|\bdoktorand|\bdoctorant|\bdottorato",
    re.IGNORECASE,
)
HIRING_CUE = re.compile(
    r"hiring|apply|application|position|opening|vacanc|\bjob\b|looking\s+for|recruit|deadline|"
    r"join\s+(us|our|my)|seeking|opportunit|we\s+are\s+searching",
    re.IGNORECASE,
)


@dataclass
class Verdict:
    keep: bool
    score: int = 0
    strong: bool = False  # an unmistakable predoc term is in the title
    reason: str | None = None
    # Role matched but no economics/finance term yet: decide after reading the detail page.
    needs_field_check: bool = False
    notes: list[str] = field(default_factory=list)


class RelevanceFilter:
    def __init__(self, cfg: FilterConfig):
        self.cfg = cfg
        self.strong = [term_rx(t) for t in cfg.strong_terms]
        self.roles = [term_rx(t) for t in cfg.role_terms]
        self.fields_core = [term_rx(t) for t in cfg.field_terms]
        self.fields_weak = [term_rx(t) for t in cfg.field_terms_weak]
        self.fields = self.fields_core + self.fields_weak
        self.field_excl = [term_rx(t) for t in cfg.field_exclude_terms]
        self.exclude = [term_rx(t) for t in cfg.exclude_terms]
        self.emp_allow = [re.compile(p, re.IGNORECASE) for p in cfg.employer_allow_patterns]
        self.emp_names = [re.compile(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])") for n in cfg.employer_allow_names]
        self.emp_block = [re.compile(p, re.IGNORECASE) for p in cfg.employer_block_patterns]
        self.emp_banned = [re.compile(re.escape(n), re.IGNORECASE) for n in cfg.excluded_employers]

    @staticmethod
    def _any(pats: list[re.Pattern[str]], text: str) -> bool:
        return any(p.search(text) for p in pats)

    @staticmethod
    def _count(pats: list[re.Pattern[str]], text: str) -> int:
        return sum(len(p.findall(text)) for p in pats) if text else 0

    # ---- employer logic ---------------------------------------------------------------
    def employer_verdict(self, post: JobPostSchema) -> str | None:
        """None if the employer is acceptable, else a rejection reason.

        Kept: universities, business/economics schools, research institutes/centres.
        Dropped: banks, companies, consultancies, and anything in `excluded_employers` (e.g. J-PAL).
        Unknown employer: dropped only for sources that always name one (LinkedIn, social media).
        """
        inst = post.institution or ""
        haystack = " ".join((inst, post.title, post.url, post.extra.get("final_url", "")))
        if any(rx.search(haystack) for rx in self.emp_banned):
            return "excluded-employer"
        if not inst.strip():
            return "employer-unknown" if post.extra.get("employer_required") else None
        if any(rx.search(inst) for rx in self.emp_allow) or any(rx.search(inst) for rx in self.emp_names):
            return None
        if any(rx.search(inst) for rx in self.emp_block):
            return "industry-employer"
        return None if self.cfg.allow_private_sector else "not-academic-employer"

    def employer_is_academic(self, institution: str) -> bool:
        """True when the employer matches the academic allow-lists."""
        return any(rx.search(institution) for rx in self.emp_allow) or any(
            rx.search(institution) for rx in self.emp_names
        )

    # ---- field logic ------------------------------------------------------------------
    def field_verdict_short(self, text: str | None) -> str:
        """For short structured text (title, department, 'Fields of Research').

        'wanted'   any economics/business/pol-sci/law term present
        'unwanted' only excluded fields present (medicine, biology, engineering, psychology...)
        'unknown'  neither
        """
        if not text:
            return "unknown"
        if self._any(self.fields, text):
            return "wanted"
        return "unwanted" if self._any(self.field_excl, text) else "unknown"

    def field_verdict_long(self, text: str | None) -> str:
        """For a whole job-ad page, where menus and boilerplate add noise.

        'wanted' needs at least one core word (economics, finance, accounting, marketing, political
        science...) and at least two field words in total; everyday words like "policy", "business"
        or "politics" alone are not enough.
        """
        text = text or ""
        core, weak = self._count(self.fields_core, text), self._count(self.fields_weak, text)
        unwanted = self._count(self.field_excl, text)
        total = core + weak
        if unwanted > total:
            return "unwanted"
        if core >= 1 and total >= 2 and total > unwanted:
            return "wanted"
        return "unknown"

    # -------------------------------------------------------------------------------
    def evaluate(self, post: JobPostSchema, ref: date | None = None, require_role: bool = True) -> Verdict:
        """Title-level decision (cheap, before any detail page is fetched).

        ``require_role=False`` is used for positions another stage already judged to be a
        vacancy (the gate plus the extractor), e.g. a German "Wissenschaftliche Mitarbeiterin".
        """
        ref = ref or today()
        title = post.title
        context = " ".join(x for x in (post.department or "", post.fields_of_research or "",
                                        post.institution, post.description_snippet) if x)

        strong_t = self._any(self.strong, title)
        strong_c = self._any(self.strong, context)
        role_t = self._any(self.roles, title)
        role_c = self._any(self.roles, context)

        if self._any(self.exclude, title) and not strong_t:
            return Verdict(False, reason="excluded-title")
        employer_problem = self.employer_verdict(post)
        if employer_problem:
            return Verdict(False, reason=employer_problem)
        if self.cfg.exclude_phd_positions and PHD_POSITION.search(title) and not strong_t:
            return Verdict(False, reason="phd-position")
        is_social = bool(post.extra.get("social"))
        if is_social and not HIRING_CUE.search(post.description_snippet or title):
            return Verdict(False, reason="social-no-hiring-cue")

        # The job's own field description decides first: "Developmental psychology" -> reject,
        # even on econ-leaning boards like PREDOC.org that also carry psychology/medicine posts.
        primary = " ".join(x for x in (title, post.department or "", post.fields_of_research or "") if x)
        if self.field_verdict_short(primary) == "unwanted":
            return Verdict(False, reason="wrong-field")
        if self.field_verdict_long(context) == "unwanted":
            return Verdict(False, reason="wrong-field-context")
        field_t = self._any(self.fields, title)
        field_c = self.field_verdict_short(primary) == "wanted" or self.field_verdict_long(context) == "wanted"
        has_field = field_t or field_c or post.field_implied

        # Social posts have no real title: the whole text is fair game.
        if is_social:
            strong_t, role_t = strong_t or strong_c, role_t or role_c

        if require_role and not (strong_t or role_t or (post.field_implied and (strong_c or role_c))):
            return Verdict(False, reason="no-role-term")

        score = (50 if strong_t else 25 if strong_c else 0) + (30 if role_t else 10 if role_c else 0)
        score += 20 if field_t else 10 if (field_c or post.field_implied) else 0

        if post.date_posted and post.date_posted < ref - timedelta(days=self.cfg.max_age_days):
            return Verdict(False, score, reason="stale")
        if self.cfg.drop_expired and post.deadline and post.deadline < ref:
            return Verdict(False, score, reason="expired")
        return Verdict(True, score, strong=strong_t, needs_field_check=not has_field)


    # -------------------------------------------------------------------------------
    def assign_region(self, post: JobPostSchema) -> bool:
        """Fill post.country/region from location/institution fields. Returns True if found.

        A place named only in the title ("RA on Rwanda education data") is stored as a hint in
        post.extra["region_guess"] and never used to drop a job.
        """
        if post.region:
            return True
        country, region = detect_location(post.location, post.country, post.institution, post.department)
        if region:
            post.country = post.country if post.country and post.country not in ("Europe",) else country
            post.region = region
            return True
        country, region = region_from_url(post.url)  # e.g. a direct link to nd.edu or uzh.ch
        if region:
            post.country = post.country or (country if country not in ("Europe", "Other") else None)
            post.region = region
            return True
        _, guess = detect_location(post.title)
        if guess:
            post.extra["region_guess"] = guess
        return False

    def region_ok(self, post: JobPostSchema) -> tuple[bool, str | None]:
        if not post.region:
            return self.cfg.keep_unknown_region, None if self.cfg.keep_unknown_region else "unknown-region"
        if post.region in self.cfg.regions_include:
            return True, None
        return False, f"region-{post.region}"
