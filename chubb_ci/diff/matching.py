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
