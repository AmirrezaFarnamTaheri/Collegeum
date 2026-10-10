"""Tiny gazetteer: map free-text locations / institution names to (country, region).

Regions used across the bot: "UK", "Europe", "Canada", "US", "Other".
Order matters only for readability; detection picks the earliest match in the text.
"""
from __future__ import annotations

import re
from functools import lru_cache

# (pattern, country, region). Patterns are matched case-insensitively on word boundaries.
_ENTRIES: list[tuple[str, str, str]] = []


def _add(region: str, country: str, *patterns: str) -> None:
    for p in patterns:
        _ENTRIES.append((p, country, region))


# ---------------- United Kingdom ----------------
_add("UK", "United Kingdom", "united kingdom", "u\\.k\\.", "uk", "england", "scotland", "wales",
     "northern ireland", "great britain", "london", "oxford", "cambridge(?!,?\\s*(ma|massachusetts))",
     "edinburgh", "glasgow", "manchester", "warwick", "coventry", "bristol", "birmingham", "leeds",
     "nottingham", "exeter", "st andrews", "durham", "lse", "ucl", "imperial college", "king's college london",
     "london business school", "queen mary", "institute for fiscal studies", "bank of england",
     "resolution foundation", "national institute of economic and social research", "niesr", "sussex",
     "essex", "york", "bath", "southampton", "sheffield", "lancaster", "kent", "belfast", "aberdeen")

# ---------------- Canada ----------------
_add("Canada", "Canada", "canada", "canadian", "toronto", "vancouver", "montreal", "montréal", "ottawa",
     "calgary", "edmonton", "quebec", "québec", "british columbia", "ubc", "mcgill", "concordia",
     "western university", "university of western ontario", "london,? on(tario)?", "waterloo",
     "queen's university", "kingston,? on", "simon fraser", "hec montr[ée]al", "universit[ée] de montr[ée]al",
     "bank of canada", "statistics canada", "ontario", "alberta", "manitoba", "saskatchewan", "nova scotia",
     "halifax", "winnipeg", "victoria,? bc", "\\bbc\\b,? canada", "rotman", "sauder", "hamilton,? on", "mcmaster")

# ---------------- Continental Europe (+ CH, NO, IS) ----------------
_EUROPE = {
    "Germany": ["germany", "deutschland", "berlin", "munich", "münchen", "mannheim", "bonn", "frankfurt",
                "hamburg", "cologne", "köln", "heidelberg", "kiel", "halle", "magdeburg", "dresden", "leipzig",
                "zew", "diw", "ifo institute", "briq", "iwh", "rwi", "essen", "goethe university", "lmu",
                "tübingen", "tuebingen", "konstanz", "göttingen", "nuremberg", "nürnberg", "iab", "bundesbank",
                "european central bank", "ecb", "max planck"],
    "France": ["france", "paris", "toulouse", "lyon", "marseille", "sciences po", "tse", "pse", "crest",
               "insead", "hec paris", "banque de france", "dauphine", "grenoble", "strasbourg", "lille",
               "bordeaux", "oecd"],
    "Spain": ["spain", "españa", "barcelona", "madrid", "valencia", "bilbao", "seville", "sevilla",
              "pompeu fabra", "upf", "bse", "cemfi", "crei", "uab", "iae-csic", "carlos iii", "uc3m",
              "esade", "iese", "banco de españa", "oviedo", "uniovi", "navarra", "alicante"],
    "Italy": ["italy", "italia", "milan", "milano", "rome", "roma", "bocconi", "turin", "torino",
              "bologna", "florence", "firenze", "european university institute", "eui", "padova", "padua",
              "venice", "venezia", "naples", "napoli", "banca d'italia", "bank of italy", "collegio carlo alberto",
              "einaudi institute", "eief"],
    "Netherlands": ["netherlands", "holland", "amsterdam", "rotterdam", "tilburg", "utrecht", "leiden",
                    "groningen", "maastricht", "nijmegen", "eindhoven", "the hague", "den haag", "erasmus",
                    "tinbergen", "de nederlandsche bank", "cpb", "vu amsterdam", "wageningen"],
    "Belgium": ["belgium", "brussels", "bruxelles", "leuven", "ghent", "gent", "antwerp", "louvain", "bruegel",
                "national bank of belgium"],
    "Switzerland": ["switzerland", "schweiz", "suisse", "zurich", "zürich", "geneva", "genève", "lausanne",
                    "basel", "bern", "st\\. gallen", "st gallen", "lugano", "eth", "epfl", "unil", "hec lausanne",
                    "graduate institute", "bank for international settlements", "snb"],
    "Austria": ["austria", "österreich", "vienna", "wien", "graz", "innsbruck", "salzburg", "linz", "iiasa",
                "laxenburg", "wu vienna", "ihs"],
    "Sweden": ["sweden", "sverige", "stockholm", "gothenburg", "göteborg", "uppsala", "lund", "umeå",
               "linköping", "örebro", "hhs", "stockholm school of economics", "iies", "ifau", "sveriges riksbank",
               "riksbank"],
    "Denmark": ["denmark", "danmark", "copenhagen", "københavn", "aarhus", "odense", "aalborg", "cbs",
                "ucph", "danmarks nationalbank", "rockwool"],
    "Norway": ["norway", "norge", "oslo", "bergen", "trondheim", "tromsø", "stavanger", "nhh", "ntnu",
               "bi norwegian", "norges bank", "frisch centre", "nmbu"],
    "Finland": ["finland", "suomi", "helsinki", "espoo", "turku", "tampere", "aalto", "vatt", "etla",
                "bank of finland"],
    "Iceland": ["iceland", "reykjavik"],
    "Ireland": ["ireland", "dublin", "cork", "galway", "maynooth", "limerick", "trinity college dublin",
                "ucd", "esri", "central bank of ireland"],
    "Portugal": ["portugal", "lisbon", "lisboa", "porto", "coimbra", "nova sbe", "católica lisbon",
                 "banco de portugal", "braga"],
    "Poland": ["poland", "polska", "warsaw", "warszawa", "krakow", "kraków", "wroclaw", "poznan", "gdansk"],
    "Czechia": ["czech republic", "czechia", "prague", "praha", "brno", "cerge"],
    "Hungary": ["hungary", "budapest", "corvinus", "ceu", "central european university"],
    "Greece": ["greece", "athens", "thessaloniki"],
    "Cyprus": ["cyprus", "nicosia"],
    "Luxembourg": ["luxembourg", "european investment bank"],
    "Estonia": ["estonia", "tallinn", "tartu"],
    "Latvia": ["latvia", "riga"],
    "Lithuania": ["lithuania", "vilnius"],
    "Slovenia": ["slovenia", "ljubljana"],
    "Slovakia": ["slovakia", "bratislava"],
    "Croatia": ["croatia", "zagreb"],
    "Romania": ["romania", "bucharest", "cluj"],
    "Bulgaria": ["bulgaria", "sofia"],
    "Malta": ["malta", "valletta"],
}
for _country, _pats in _EUROPE.items():
    _add("Europe", _country, *_pats)
_add("Europe", "Europe", "europe", "european union", "(?-i:EU)", "eea", "emea")

# ---------------- United States (to exclude) ----------------
_add("US", "United States", "united states", "u\\.s\\.a?\\.?", "usa", "new york", "nyc", "boston",
     "chicago", "stanford", "harvard", "princeton", "yale", "columbia university", "columbia business school",
     "mit", "massachusetts", "berkeley", "california", "ucla", "wharton", "pennsylvania", "philadelphia",
     "washington,? dc", "washington d\\.c\\.", "federal reserve", "federal reserve bank", "nber",
     "dartmouth", "brown university", "cornell", "duke", "northwestern", "university of michigan",
     "ann arbor", "texas", "atlanta", "georgia", "florida", "seattle", "san francisco",
     "los angeles", "illinois", "ohio", "minnesota", "wisconsin", "maryland", "virginia", "north carolina",
     "new jersey", "connecticut", "new haven", "cambridge,? ma", "palo alto", "booth school",
     "kellogg", "world bank", "imf", "international monetary fund", "brookings", "rand corporation",
     "urban institute", "mathematica", "\\b[A-Z][a-z]+,\\s(?:NY|MA|CA|IL|PA|DC|NJ|CT|TX|MI|WA|NC|GA|MD|VA|RI|NH|MN|WI|OH|CO|UT|IN|MO|TN)\\b")

# More US universities / schools / research employers (so US posts are dropped without a page visit)
_add("US", "United States",
     "notre dame", "johns hopkins", "vanderbilt", "rice university", "emory", "georgetown", "carnegie mellon",
     "tufts", "boston university", "boston college", "northeastern university", "new york university", "nyu",
     "university of rochester", "syracuse", "purdue", "rutgers", "penn state", "pennsylvania state",
     "ohio state", "michigan state", "indiana university", "university of iowa", "iowa state",
     "university of arizona", "arizona state", "university of utah", "university of oregon",
     "university of colorado", "university of minnesota", "university of wisconsin", "washington university",
     "university of washington", "uchicago", "caltech", "usc", "university of southern california",
     "university of california", "uc berkeley", "uc davis", "uc irvine", "uc san diego", "ucsd",
     "uc santa barbara", "ucsb", "uc santa cruz", "uc riverside", "uc merced", "ucsf", "rady school",
     "haas school", "sloan school", "stern school", "fuqua", "tuck school", "ross school", "darden", "olin business",
     "mccombs", "harvard business school", "hbs", "stanford gsb", "kennedy school", "harris school",
     "heinz college", "opportunity insights", "development innovation lab", "becker friedman", "hoover institution",
     "federal reserve board", "board of governors", "brookings", "peterson institute", "american enterprise",
     "urban institute", "abt associates", "cornell", "dartmouth", "university of virginia",
     "university of north carolina", "unc", "duke university", "wake forest", "university of pennsylvania", "upenn",
     "university of maryland", "university of illinois", "university of chicago", "northwestern university",
     "university of texas", "texas a&m", "university of florida", "university of georgia", "georgia tech",
     "university of pittsburgh", "university of notre dame", "brigham young", "byu", "stanford university",
     "yale university", "princeton university", "harvard university", "columbia university", "mit sloan",
     "claremont", "pomona", "williams college", "amherst", "wellesley", "middlebury", "swarthmore",
     "san diego", "san jose", "los angeles", "new orleans", "st\\. louis", "saint louis", "pittsburgh", "baltimore",
     "denver", "houston", "dallas", "miami", "detroit", "minneapolis", "phoenix", "salt lake city", "nashville",
     "durham,? nc", "chapel hill", "princeton,? nj", "ithaca", "berkeley,? ca", "stanford,? ca", "evanston",
     "hanover,? nh", "providence,? ri", "new haven,? ct", "madison,? wi", "bloomington", "urbana", "champaign",
     "alabama", "alaska", "arizona", "arkansas", "colorado", "delaware", "hawaii", "idaho", "indiana",
     "iowa", "kansas", "kentucky", "louisiana", "maine", "michigan", "mississippi", "missouri", "montana",
     "nebraska", "nevada", "new hampshire", "new mexico", "north dakota", "oklahoma", "oregon", "rhode island",
     "south carolina", "south dakota", "tennessee", "utah", "vermont", "west virginia", "wyoming", "washington")

# ---------------- Other (to exclude) ----------------
_OTHER = ["australia", "sydney", "melbourne", "canberra", "new zealand", "auckland", "china", "beijing",
          "shanghai", "hong kong", "singapore", "japan", "tokyo", "korea", "seoul", "india", "delhi",
          "mumbai", "bangalore", "israel", "tel aviv", "jerusalem", "turkey", "istanbul", "ankara",
          "united arab emirates", "dubai", "abu dhabi", "qatar", "doha", "saudi arabia", "riyadh",
          "south africa", "cape town", "johannesburg", "kenya", "nairobi", "nigeria", "ghana", "rwanda",
          "brazil", "são paulo", "sao paulo", "rio de janeiro", "mexico", "chile", "santiago", "colombia",
          "bogot[aá]", "argentina", "buenos aires", "peru", "lima", "malaysia", "kuala lumpur", "lebanon",
          "beirut", "byblos", "pakistan", "bangladesh", "vietnam", "indonesia", "thailand", "philippines",
          "egypt", "cairo", "iran", "tehran"]
_OTHER_COUNTRIES = {
    "Australia": ["australia", "sydney", "melbourne", "canberra"],
    "New Zealand": ["new zealand", "auckland"],
    "China": ["china", "beijing", "shanghai"],
    "Singapore": ["singapore"],
    "Japan": ["japan", "tokyo"],
    "India": ["india", "delhi", "mumbai", "bangalore"],
    "Hong Kong": ["hong kong"],
    "South Korea": ["south korea", "seoul"],
    "Israel": ["israel", "tel aviv"],
    "Turkey": ["turkey", "istanbul", "ankara"],
    "United Arab Emirates": ["united arab emirates", "dubai", "abu dhabi"],
    "Qatar": ["qatar", "doha"],
    "Saudi Arabia": ["saudi arabia", "riyadh"],
    "South Africa": ["south africa", "cape town", "johannesburg"],
    "Kenya": ["kenya", "nairobi"],
    "Nigeria": ["nigeria"],
    "Ghana": ["ghana"],
    "Rwanda": ["rwanda"],
    "Brazil": ["brazil", "são paulo", "sao paulo", "rio de janeiro"],
    "Mexico": ["mexico"],
    "Chile": ["chile", "santiago"],
    "Colombia": ["colombia", "bogot[aá]"],
    "Argentina": ["argentina", "buenos aires"],
    "Peru": ["peru", "lima"],
    "Malaysia": ["malaysia", "kuala lumpur"],
    "Lebanon": ["lebanon", "beirut", "byblos"],
    "Pakistan": ["pakistan"],
    "Bangladesh": ["bangladesh"],
    "Vietnam": ["vietnam"],
    "Indonesia": ["indonesia"],
    "Thailand": ["thailand"],
    "Philippines": ["philippines"],
    "Egypt": ["egypt", "cairo"],
    "Iran": ["iran", "tehran"],
}
_specific_other = {pattern for patterns in _OTHER_COUNTRIES.values() for pattern in patterns}
for _country, _patterns in _OTHER_COUNTRIES.items():
    _add("Other", _country, *_patterns)
_add("Other", "Other", *(pattern for pattern in _OTHER if pattern not in _specific_other))


# Short acronyms are matched case-sensitively in UPPER CASE so that e.g. German "mit"
# ("with") is not read as MIT, and "eth"/"eu"/"uk" only match as proper acronyms.
ACRONYMS = {
    "nyu", "usc", "ucsd", "ucsb", "ucsf", "hbs", "unc", "byu", "upenn",
    "uk", "lse", "ucl", "ubc", "zew", "diw", "briq", "iwh", "rwi", "lmu", "iab", "ecb", "tse", "pse",
    "crest", "insead", "oecd", "upf", "bse", "cemfi", "crei", "uab", "uc3m", "eui", "eief", "cpb", "eth",
    "epfl", "unil", "snb", "ihs", "hhs", "iies", "ifau", "cbs", "ucph", "nhh", "ntnu", "nmbu", "vatt",
    "etla", "ucd", "esri", "cerge", "ceu", "eea", "emea", "usa", "nyc", "mit", "ucla", "nber", "imf",
    "niesr", "iiasa",
}


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[re.Pattern[str], str, str]]:
    out = []
    for pat, country, region in _ENTRIES:
        if pat in ACRONYMS:
            rx = re.compile(r"(?<![\w-])" + pat.upper() + r"(?![\w-])")
        elif "[A-Z]" in pat:
            rx = re.compile(r"(?<![\w-])" + pat + r"(?![\w-])")
        else:
            rx = re.compile(r"(?<![\w-])" + pat + r"(?![\w-])", re.IGNORECASE)
        out.append((rx, country, region))
    return out


def detect_all(text: str | None) -> list[tuple[int, str, str]]:
    """All (position, country, region) matches in text, sorted by position."""
    if not text:
        return []
    hits = []
    for rx, country, region in _compiled():
        m = rx.search(text)
        if m:
            hits.append((m.start(), country, region))
    return sorted(hits)


def detect_location(*texts: str | None) -> tuple[str | None, str | None]:
    """Return (country, region) using the first text that yields a match.

    Pass the most specific field first (explicit location, then institution, then title/snippet).
    Within one text the earliest match wins, but a country-level match beats the generic "Europe".
    """
    for text in texts:
        if not text:
            continue
        hits = detect_all(text)
        if not hits:
            continue
        # In an explicit comma-separated address, a named country suffix is
        # stronger evidence than an ambiguous city (London, Canada).
        for _, named_country, named_region in hits:
            if named_country in ("Europe", "Other"):
                continue
            if re.search(r",\s*" + re.escape(named_country) + r"\s*(?:$|[.\n])", text, re.I):
                return named_country, named_region
        specific = [h for h in hits if h[1] not in ("Europe",)]
        _, country, region = (specific or hits)[0]
        return country, region
    return None, None


def is_confident_single_region(text: str | None) -> tuple[str | None, str | None]:
    """For long detail-page text: only answer when every match points to one region."""
    hits = detect_all(text)
    regions = {h[2] for h in hits}
    if len(regions) == 1:
        specific = [h for h in hits if h[1] != "Europe"]
        _, country, region = (specific or hits)[0]
        return country, region
    return None, None


# ---------------- URL domains ----------------
# Hosts that say nothing about where the job is (link shorteners, job boards, application tools).
NEUTRAL_HOSTS = (
    "bit.ly", "tinyurl.com", "t.co", "forms.gle", "docs.google.com", "google.com", "linkedin.com", "jobs.ac.uk",
    "euraxess.ec.europa.eu", "econjobmarket.org", "inomics.com", "substack.com", "predoc.org", "interfolio.com",
    "qualtrics.com", "myworkdayjobs.com", "greenhouse.io", "lever.co", "smartrecruiters.com", "beapplied.com",
    "academicjobsonline.org", "academicpositions.com", "indeed.com", "glassdoor.com", "twitter.com", "x.com",
    "bsky.app", "theeconomicmisfit.com", "povertyactionlab.org", "europeanjobmarketofeconomists.org",
    "somma.es", "sharepoint.com", "dropbox.com", "typeform.com", "airtable.com", "jotform.com", "wix.com",
    "notion.site", "github.io", "oraclecloud.com", "successfactors.com", "taleo.net", "icims.com",
)
# .edu is normally American, but these European schools use it too.
EUROPEAN_EDU = {
    "upf.edu": "Spain", "iese.edu": "Spain", "esade.edu": "Spain", "ie.edu": "Spain", "eada.edu": "Spain",
    "insead.edu": "France", "hec.edu": "France", "essec.edu": "France", "edhec.edu": "France",
    "ceu.edu": "Austria", "tias.edu": "Netherlands", "cerge-ei.cz": "Czechia", "eui.eu": "Italy",
}
_EU_TLDS = {
    "de": "Germany", "fr": "France", "es": "Spain", "it": "Italy", "nl": "Netherlands", "be": "Belgium",
    "ch": "Switzerland", "at": "Austria", "se": "Sweden", "dk": "Denmark", "no": "Norway", "fi": "Finland",
    "ie": "Ireland", "pt": "Portugal", "pl": "Poland", "cz": "Czechia", "hu": "Hungary", "gr": "Greece",
    "lu": "Luxembourg", "ee": "Estonia", "lv": "Latvia", "lt": "Lithuania", "si": "Slovenia", "sk": "Slovakia",
    "hr": "Croatia", "ro": "Romania", "bg": "Bulgaria", "is": "Iceland", "cy": "Cyprus", "mt": "Malta",
    "eu": "Europe", "cat": "Spain",
}
_OTHER_TLDS = {"au", "nz", "cn", "jp", "kr", "sg", "hk", "in", "il", "tr", "br", "mx", "ar", "cl", "co", "za",
               "ae", "qa", "sa", "my", "th", "id", "ph", "vn", "pk", "tw", "ru", "ir", "eg", "ng", "ke"}


def region_from_url(url: str | None) -> tuple[str | None, str | None]:
    """Country/region implied by a URL's domain, e.g. nd.edu -> US, uzh.ch -> Switzerland."""
    if not url:
        return None, None
    from urllib.parse import urlsplit
    host = urlsplit(url).netloc.lower().split(":")[0]
    if not host or any(host == h or host.endswith("." + h) for h in NEUTRAL_HOSTS):
        return None, None
    for dom, country in EUROPEAN_EDU.items():
        if host == dom or host.endswith("." + dom):
            return country, "Europe"
    parts = host.split(".")
    tld = parts[-1]
    if len(parts) >= 3 and parts[-2] in ("edu", "ac", "gov", "org", "com", "co") and len(tld) == 2:
        tld = parts[-1]  # e.g. unimelb.edu.au -> au, ox.ac.uk -> uk
    elif tld in ("edu", "gov", "mil"):
        return "United States", "US"
    if tld == "uk":
        return "United Kingdom", "UK"
    if tld == "ca":
        return "Canada", "Canada"
    if tld == "us":
        return "United States", "US"
    if tld in _EU_TLDS:
        return _EU_TLDS[tld], "Europe"
    if tld in _OTHER_TLDS:
        return "Other", "Other"
    return None, None


_LOCATION_LABEL = re.compile(
    r"(?:\blocation|based\s+in|place\s+of\s+work|work\s+location|duty\s+station|job\s+location|"
    r"workplace|place\s+of\s+employment|city)\s*[:\-]\s*", re.IGNORECASE)
_US_SIGNALS = [re.compile(p, re.IGNORECASE if i else 0) for i, p in enumerate([
    r"\b(?:AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|"
    r"OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\s+\d{5}\b",
    r"e-?verify", r"equal\s+opportunity\s*/\s*affirmative\s+action", r"affirmative\s+action\s+employer",
    r"\$\s?\d{2},?\d{3}", r"\bUSD\b", r"u\.s\.\s+(?:citizens?|permanent\s+residents?)", r"\bfederal\s+work",
])]


def location_from_labels(text: str | None) -> tuple[str | None, str | None]:
    """'Location: Zurich, Switzerland' -> ('Switzerland', 'Europe'). First labelled location wins."""
    text = text or ""
    for m in _LOCATION_LABEL.finditer(text):
        country, region = detect_location(text[m.end(): m.end() + 80])
        if region:
            return country, region
    return None, None


def us_signal_count(text: str | None) -> int:
    return sum(1 for rx in _US_SIGNALS if rx.search(text or ""))
