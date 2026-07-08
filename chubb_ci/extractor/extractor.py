"""Structured extraction with strict validation and a one-shot repair retry.

Flow: call LLM in JSON mode → parse → validate against :class:`ProductExtraction`.
If parsing/validation fails, send the error back once for repair. If it still fails,
return an empty result with an error (never poison the snapshot with garbage).
"""

from __future__ import annotations

import json

from loguru import logger
from pydantic import BaseModel, ValidationError

from chubb_ci.config.sources import Source
from chubb_ci.extractor.prompts import build_repair, build_system, build_user
from chubb_ci.llm.base import LLMClient, LLMError
from chubb_ci.schemas.models import ExtractedProduct, ProductExtraction


class ExtractionResult(BaseModel):
    products: list[ExtractedProduct] = []
    tokens_in: int = 0
    tokens_out: int = 0
    ok: bool = True
    error: str | None = None
    repaired: bool = False


def _extract_json_object(text: str) -> str:
    """Return the outermost ``{...}`` object from a possibly-noisy string."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return text[start : end + 1]


def _parse(text: str) -> ProductExtraction:
    obj = json.loads(_extract_json_object(text))
    return ProductExtraction.model_validate(obj)


def extract_products(
    llm: LLMClient,
    *,
    model: str,
    source: Source,
    url: str,
    page_text: str,
    domain_context: str,
    temperature: float = 0.0,
) -> ExtractionResult:
    """Extract validated products from one page's cleaned text."""
    system = build_system(domain_context)
    user = build_user(source, url, page_text)

    tokens_in = tokens_out = 0
    try:
        first = llm.complete(
            system=system, user=user, model=model, json_mode=True, temperature=temperature
        )
    except LLMError as exc:
        logger.error("extraction LLM call failed for {}: {}", url, exc)
        return ExtractionResult(ok=False, error=str(exc))

    tokens_in += first.tokens_in
    tokens_out += first.tokens_out

    try:
        parsed = _parse(first.content)
        return _finalize(parsed, source, url, tokens_in, tokens_out, repaired=False)
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        first_error = str(exc)
        logger.warning("extraction validation failed for {} ({}); attempting repair", url, exc)

    # --- one repair attempt ------------------------------------------------
    try:
        repair = llm.complete(
            system=system,
            user=build_repair(first_error, first.content),
            model=model,
            json_mode=True,
            temperature=temperature,
        )
    except LLMError as exc2:
        return ExtractionResult(ok=False, error=f"repair call failed: {exc2}",
                                tokens_in=tokens_in, tokens_out=tokens_out)

    tokens_in += repair.tokens_in
    tokens_out += repair.tokens_out
    try:
        parsed = _parse(repair.content)
        return _finalize(parsed, source, url, tokens_in, tokens_out, repaired=True)
    except (ValueError, ValidationError, json.JSONDecodeError) as exc3:
        logger.error("extraction still invalid after repair for {}: {}", url, exc3)
        return ExtractionResult(
            ok=False, error=f"invalid after repair: {exc3}",
            tokens_in=tokens_in, tokens_out=tokens_out,
        )


def _finalize(
    parsed: ProductExtraction,
    source: Source,
    url: str,
    tokens_in: int,
    tokens_out: int,
    *,
    repaired: bool,
) -> ExtractionResult:
    # Fill source_url when the model omitted it.
    for p in parsed.products:
        if not p.source_url:
            p.source_url = url
    return ExtractionResult(
        products=parsed.products,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        ok=True,
        repaired=repaired,
    )
