"""Rating standardization: fire-resistance text → hours, anti-theft grades → ordinal score.

Rules follow the marketing framework (AnalyzeInformation.md §2):

* Fireproof text like ``UL 1h`` / ``UL 90min`` / ``欧标60min`` / ``国标120min`` becomes a
  float number of **fireproof hours** (0.5, 1.0, 1.5, 2.0 …).
* Anti-theft classifications map onto the ordinal **防盗等级分**:
  ``CSP/GB A / TL-15 = 1, GB B = 2, GB C = 3, 欧标 S2 = 4, Grade Ⅰ = 5 … Grade Ⅴ = 9``.

Everything is dict/regex-driven so the mapping is auditable and easily extended.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- fire hours
_HOURS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:h\b|hr|hour|小时)", re.IGNORECASE)
_MINUTES_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:min\b|mins|minute|分钟|分\b)", re.IGNORECASE)


def fire_hours(text: str | None) -> float | None:
    """Parse a fire-rating string into standardized fireproof hours.

    Handles ``UL 2h`` / ``UL 120min`` / ``欧标30min`` / ``国标 120 分钟`` / ``1小时`` /
    ``EN15659/30min``. Returns ``None`` for empty, "-", or unparseable text.
    """
    if not text:
        return None
    s = unicodedata.normalize("NFKC", str(text)).strip()
    if not s or s in {"-", "—", "无"}:
        return None

    m = _HOURS_RE.search(s)
    if m:
        return float(m.group(1))
    m = _MINUTES_RE.search(s)
    if m:
        return round(float(m.group(1)) / 60.0, 2)
    return None


# ------------------------------------------------------------ security score
# GB 10409 / CSP national grades.
_GB_SCORES: dict[str, int] = {"A": 1, "B": 2, "C": 3}

# European / US grades (EN 14450 S-levels, EN 1143-1 grades, UL TL ratings).
# Grade N maps to 4 + N (S2 = 4, Ⅰ = 5 … Ⅴ = 9, Ⅵ = 10); S1 sits one below S2.
_EURO_FIXED: dict[str, int] = {
    "S1": 3,
    "S2": 4,
    "TL15": 1,   # doc: CSP A / TL15 = 1
    "TL30": 2,
    "TRTL30": 3,
}

_ROMAN: dict[str, int] = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
    "Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4, "Ⅴ": 5, "Ⅵ": 6,
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
}

# NOTE: no leading \b — Python treats CJK as word chars, so "欧标S2" has no word
# boundary before the "S" and \b-anchored patterns silently fail.
_GB_RE = re.compile(r"(?:国标|GB|CSP)?\s*([ABC])\s*级?\s*$", re.IGNORECASE)
_S_RE = re.compile(r"S\s*([12])(?![0-9])", re.IGNORECASE)
_TL_RE = re.compile(r"(TRTL|TL)\s*-?\s*(15|30)", re.IGNORECASE)
# "G1级" / "Grade II" / "EN1143-1 III" / "欧标一级" / "0级–6级"
_GRADE_RE = re.compile(
    r"(?:G|GRADE|等级|欧标)\s*-?\s*([0-6]|[IViv]+|[Ⅰ-Ⅵ]|[一二三四五六])\s*级?",
    re.IGNORECASE,
)
_TRAILING_GRADE_RE = re.compile(r"\b([0-6]|[IV]{1,3}|[Ⅰ-Ⅵ])\s*级?\s*$")


def _euro_grade_to_score(n: int) -> int:
    """EN 1143-1 grade N → ordinal score (grade 0 = 4, grade N = 4 + N, capped at 10)."""
    return min(4 + n, 10) if n > 0 else 4


def _parse_euro(text: str) -> int | None:
    s = unicodedata.normalize("NFKC", text).strip().upper()
    if not s or s in {"-", "—", "无"}:
        return None

    m = _TL_RE.search(s)
    if m:
        key = (m.group(1) + m.group(2)).replace("-", "").upper()
        return _EURO_FIXED.get(key)
    m = _S_RE.search(s)
    if m:
        return _EURO_FIXED[f"S{m.group(1)}"]
    m = _GRADE_RE.search(s)
    if m:
        token = m.group(1).upper()
        if token.isdigit():
            return _euro_grade_to_score(int(token))
        if token in _ROMAN:
            return _euro_grade_to_score(_ROMAN[token])
    m = _TRAILING_GRADE_RE.search(s)
    if m:
        token = m.group(1).upper()
        if token.isdigit():
            return _euro_grade_to_score(int(token))
        if token in _ROMAN:
            return _euro_grade_to_score(_ROMAN[token])
    return None


def _parse_gb(text: str) -> int | None:
    s = unicodedata.normalize("NFKC", text).strip().upper()
    if not s or s in {"-", "—", "无"}:
        return None
    m = _GB_RE.search(s)
    if m:
        return _GB_SCORES.get(m.group(1).upper())
    return None


def security_score(gb_grade: str | None, euro_grade: str | None = None) -> int | None:
    """Return the ordinal 防盗等级分 for a product's stated anti-theft grades.

    Both the national (GB/CSP) and the European/US grade are parsed when present;
    the **higher** score wins (a product certified to both is as strong as its best
    certification). Returns ``None`` when neither text parses.
    """
    scores: list[int] = []
    if gb_grade:
        # A combined field like "CSP B" or "欧标S2级" may land in either argument.
        s = _parse_gb(gb_grade)
        if s is None:
            s = _parse_euro(gb_grade)
        if s is not None:
            scores.append(s)
    if euro_grade:
        s = _parse_euro(euro_grade)
        if s is None:
            s = _parse_gb(euro_grade)
        if s is not None:
            scores.append(s)
    return max(scores) if scores else None
