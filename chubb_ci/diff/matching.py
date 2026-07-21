"""Product identity: turn a display name into a stable matching key.

Deterministic and language-aware (keeps CJK characters, drops noise/whitespace/
punctuation and full-width variants) so the same product matches across snapshots
even when surrounding marketing text shifts.
"""

from __future__ import annotations

import re
import unicodedata

# Characters that are pure noise for identity purposes.
_PUNCT = re.compile(r"[\s　\-_/\\|,，、。.（）()\[\]【】《》\"'“”‘’!！?？:：;；~～*#]+")


def normalize_product_key(name: str | None) -> str:
    """Return a normalized identity key for a product name.

    - Unicode NFKC folding (full-width → half-width, etc.)
    - lowercase
    - strip whitespace and common punctuation
    - collapse repeats

    Empty / None names yield ``""`` (callers treat that as "unmatchable").
    """
    if not name:
        return ""
    folded = unicodedata.normalize("NFKC", name).lower()
    stripped = _PUNCT.sub("", folded)
    return stripped.strip()


# Alphanumeric model codes (AE881, 4116G, BGX-D1-800, FDX-A/D-30, D-73II).
_MODEL_RE = re.compile(
    r"[A-Za-z]{1,6}(?:[-/][A-Za-z0-9]+)*\d[A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*"
    r"|\d{3,}[A-Za-z]+"
)
_HEIGHT_RE = re.compile(r"^[hH]\d+$")


def model_code(name: str | None) -> str | None:
    """Extract a product's model code for cross-platform matching.

    The same SKU carries different marketing titles on JD/Tmall/苏宁 but shares a model
    code (得力AE881 / 甬康达BGX-D1-800). Returns the first code-like token, skipping pure
    size tokens (H360 height, 63L capacity). None when no code is present (系列 names).
    """
    if not name:
        return None
    s = unicodedata.normalize("NFKC", name).upper()
    for tok in _MODEL_RE.findall(s):
        t = tok.strip("-/")
        if len(t) < 3 or _HEIGHT_RE.match(t) or "CM" in t:
            continue
        if t.endswith("L") and t[:-1].isdigit():   # capacity like 63L
            continue
        return t
    return None
