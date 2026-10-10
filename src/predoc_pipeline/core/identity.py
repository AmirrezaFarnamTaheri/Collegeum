"""Shared institution aliases for board filtering and duplicate identity."""

from __future__ import annotations

import re
import unicodedata

INSTITUTION_ALIASES = {
    "lse": "london school of economics and political science",
    "london school of economics": "london school of economics and political science",
    "ucl": "university college london",
    "lbs": "london business school",
    "sse": "stockholm school of economics",
    "ucph": "university of copenhagen",
    "ku": "university of copenhagen",
    "upf": "universitat pompeu fabra",
    "bse": "barcelona school of economics",
    "ubc": "university of british columbia",
    "uoft": "university of toronto",
    "u of t": "university of toronto",
    "eui": "european university institute",
    "tse": "toulouse school of economics",
    "pse": "paris school of economics",
    "ifs": "institute for fiscal studies",
    "ecb": "european central bank",
}

_STOP = {"the", "of", "and", "for", "in", "at", "a", "an", "de", "la", "le", "du"}



def normalize_institution(name: str | None) -> str:
    value = unicodedata.normalize("NFKC", name or "")
    value = " ".join(value.split()).lower()
    value = INSTITUTION_ALIASES.get(value, value)
    words = re.sub(r"[^\w\s]", " ", value).split()
    return " ".join(word for word in words if word not in _STOP)
