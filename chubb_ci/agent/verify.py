"""真实性核查 — the Verify node: deterministic-first authenticity checks.

Order of checks (per agent/README.md):
1. **Source presence** — a claim with no source is never accepted.
2. **Cross-source corroboration** — identical (subject, field, value) claims from
   independent sources merge; ≥2 distinct sources raises confidence.
3. **Consistency checks** — reuse chubb_ci/normalize: prices must be plausible numbers
   (and inside the brand's known price band when one exists), fire ratings must parse
   to hours, security grades must map to a score, dimensions/weights must be sane.

Facts at/above the threshold are auto-verified; the rest go to the human 采纳/驳回 queue.
No LLM is involved here — the optional contradiction pass lives in the flows.
"""

from __future__ import annotations

from pydantic import BaseModel

from chubb_ci.agent.state import SourcedFact
from chubb_ci.normalize import fire_hours, security_score

# Base confidence by extraction method.
BASE_STRUCTURED = 0.75   # deterministic table/spreadsheet parse
BASE_LLM = 0.5           # LLM extraction from unstructured text

_CORROBORATION_BONUS = 0.2
_CONSISTENCY_BONUS = 0.15
_CONSISTENCY_PENALTY = 0.4

_PRICE_SANE = (50.0, 5_000_000.0)          # CNY
_CAPACITY_SANE = (1.0, 5_000.0)            # liters
_WEIGHT_SANE = (1.0, 5_000.0)              # kg
_DIMENSION_SANE = (10.0, 10_000.0)         # mm


class VerifyResult(BaseModel):
    verified: list[SourcedFact] = []
    pending: list[SourcedFact] = []


def _num(value: str) -> float | None:
    try:
        return float(str(value).replace(",", "").replace("￥", "").replace("¥", "").strip())
    except (TypeError, ValueError):
        return None


def _consistency(fact: SourcedFact, known_price_band: tuple[float, float] | None) -> bool | None:
    """Field-specific sanity check. None = not checkable (neutral)."""
    f, v = fact.field, fact.value
    if f in ("price", "tax_price"):
        n = _num(v)
        if n is None or not (_PRICE_SANE[0] <= n <= _PRICE_SANE[1]):
            return False
        if known_price_band and known_price_band[0] > 0:
            low, high = known_price_band
            # Allow generous headroom around the brand's observed band.
            return (low * 0.1) <= n <= (high * 10)
        return True
    if f == "fire_rating":
        return fire_hours(v) is not None
    if f in ("gb_grade", "euro_grade", "security"):
        return security_score(v) is not None
    if f == "capacity_l":
        n = _num(v)
        return n is not None and _CAPACITY_SANE[0] <= n <= _CAPACITY_SANE[1]
    if f == "weight_kg":
        n = _num(v)
        return n is not None and _WEIGHT_SANE[0] <= n <= _WEIGHT_SANE[1]
    if f in ("width_mm", "depth_mm", "height_mm"):
        n = _num(v)
        return n is not None and _DIMENSION_SANE[0] <= n <= _DIMENSION_SANE[1]
    return None  # free-text fields (positioning, features…) — not checkable here


def _merge_key(fact: SourcedFact) -> tuple[str, str, str]:
    return (fact.subject.strip().lower(), fact.field, str(fact.value).strip().lower())


def verify_facts(
    facts: list[SourcedFact],
    *,
    threshold: float = 0.8,
    known_price_bands: dict[str, tuple[float, float]] | None = None,
) -> VerifyResult:
    """Merge, score and split facts into auto-verified vs pending-human-review."""
    known_price_bands = known_price_bands or {}

    # 1+2: merge identical claims, pooling their sources.
    merged: dict[tuple[str, str, str], SourcedFact] = {}
    for f in facts:
        key = _merge_key(f)
        if key in merged:
            existing = merged[key]
            existing.sources = sorted(set(existing.sources) | set(f.sources))
            existing.confidence = max(existing.confidence, f.confidence)
        else:
            merged[key] = f.model_copy(deep=True)

    result = VerifyResult()
    for fact in merged.values():
        fact.sources = sorted(set(s for s in fact.sources if s))
        fact.corroborations = len(fact.sources)

        if not fact.sources:  # rule 1: no source, no entry
            fact.confidence = 0.0
            fact.status = "pending"
            result.pending.append(fact)
            continue

        conf = fact.confidence or BASE_LLM
        if fact.corroborations >= 2:
            conf += _CORROBORATION_BONUS

        band = known_price_bands.get(fact.subject.strip().lower())
        check = _consistency(fact, band)
        if check is True:
            conf += _CONSISTENCY_BONUS
        elif check is False:
            conf -= _CONSISTENCY_PENALTY

        fact.confidence = round(max(0.0, min(1.0, conf)), 2)
        if fact.confidence >= threshold:
            fact.status = "verified"
            result.verified.append(fact)
        else:
            fact.status = "pending"
            result.pending.append(fact)
    return result
