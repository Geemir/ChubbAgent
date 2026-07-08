"""Import the 集宝 own-product catalog (ChubbProductsList.xlsx) into the database.

Sheet layout (sheet "chubb"):
  fixed column positions — 0:idx 1:型号 2:品牌 3:图片 4:防火等级 5:防盗等级
  6:高H(mm) 7:宽W(mm) 8:深D(mm) 9:净重(kg) 10:零售价(元) 11:订货周期(天) 12:容积(L,自动)
  A row whose 型号 is set but 品牌 is empty is a *series separator* (经典系列 / 轻奢系列 /
  防火柜系列) applying to the rows below it. "-" or blank cells mean "not rated".

Ratings are standardized at import via chubb_ci/normalize (fire_hours, security_score);
volume is recomputed from W×D×H and cross-checked against the sheet's own 容积 column.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from loguru import logger
from sqlmodel import Session, delete

from chubb_ci.diff.matching import normalize_product_key
from chubb_ci.normalize import fire_hours, security_score, volume_l
from chubb_ci.schemas.models import OwnProduct

_COLS = 13  # expected column count


def _cell(row, i: int):
    v = row[i] if i < len(row) else None
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, str):
        v = v.strip()
        if v in ("", "-", "—"):
            return None
    return v


def _num(row, i: int) -> float | None:
    v = _cell(row, i)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_catalog(path: str | Path) -> list[OwnProduct]:
    """Parse the xlsx into OwnProduct rows (not yet persisted)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    df = pd.read_excel(path, sheet_name=0, header=None)
    products: list[OwnProduct] = []
    seen_keys: set[str] = set()
    series: str | None = None
    header_seen = False

    for _, raw in df.iterrows():
        row = list(raw)
        model = _cell(row, 1)
        brand = _cell(row, 2)
        if model is None:
            continue
        if str(model).startswith("型号"):
            header_seen = True
            continue
        if not header_seen:
            continue
        if brand is None:
            series = str(model)  # series separator row
            continue

        fire_text = _cell(row, 4)
        sec_text = _cell(row, 5)
        h, w, d = _num(row, 6), _num(row, 7), _num(row, 8)
        weight, price = _num(row, 9), _num(row, 10)
        lead = _num(row, 11)
        vol_sheet = _num(row, 12)

        key = normalize_product_key(str(model))
        if key in seen_keys:
            logger.warning("duplicate model in catalog, keeping first: {}", model)
            continue
        seen_keys.add(key)

        vol = volume_l(w, d, h) or (round(vol_sheet, 1) if vol_sheet else None)
        # The security column mixes GB ("CSP B") and Euro ("欧标S2级") text; the
        # normalizer tries both interpretations, so one field is enough.
        sec_str = str(sec_text) if sec_text is not None else None
        is_gb = bool(sec_str) and ("CSP" in sec_str.upper() or "国标" in sec_str)

        products.append(OwnProduct(
            product_name=str(model),
            product_key=key,
            series=series,
            category="防火柜" if (series and "防火" in series) else "保险柜",
            price=price,
            width_mm=w,
            depth_mm=d,
            height_mm=h,
            capacity_l=vol,
            weight_kg=weight,
            fire_rating=str(fire_text) if fire_text is not None else None,
            gb_grade=sec_str if is_gb else None,
            euro_grade=sec_str if not is_gb else None,
            lead_time_days=int(lead) if lead is not None else 0,
            fire_hours=fire_hours(str(fire_text) if fire_text else None),
            security_score=security_score(sec_str),
        ))

    logger.info("parsed {} own products from {}", len(products), path.name)
    return products


def import_catalog(session: Session, path: str | Path) -> int:
    """Replace the OwnProduct table with the catalog contents. Returns row count."""
    products = parse_catalog(path)
    session.exec(delete(OwnProduct))
    for p in products:
        session.add(p)
    session.commit()
    return len(products)
