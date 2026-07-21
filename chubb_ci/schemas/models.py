"""Data model.

Two families of schemas live here:

* **Wire schema** (:class:`ExtractedProduct`, :class:`ProductExtraction`) — the strict
  JSON the LLM must return. Field descriptions double as prompt documentation.
* **ORM tables** (:class:`CrawlRun`, :class:`Snapshot`, :class:`ProductRecord`,
  :class:`DiffEvent`, :class:`Report`) — persisted snapshots + detected changes.

Keeping wire and storage schemas separate (rather than one shared class) means the LLM
never sees database ids and the DB can evolve independently of the prompt.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

import re

from pydantic import BaseModel, Field as PydField, field_validator
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Timezone-aware current UTC timestamp."""
    return datetime.now(timezone.utc)


# =========================================================================
# Enums
# =========================================================================
class EventType(StrEnum):
    NEW_PRODUCT = "new_product"
    DISCONTINUED = "discontinued"
    PRICE_CHANGE = "price_change"
    PROMOTION_CHANGE = "promotion_change"
    SPEC_CHANGE = "spec_change"
    STOCK_CHANGE = "stock_change"


class SnapshotStatus(StrEnum):
    OK = "ok"
    SKIPPED = "skipped"  # content unchanged since last crawl
    ERROR = "error"
    BLOCKED = "blocked"  # anti-bot / captcha / login wall


class ReportType(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


# =========================================================================
# Wire schema (LLM output). Descriptions are surfaced in the prompt.
# =========================================================================
class ExtractedProduct(BaseModel):
    """One product as extracted by the LLM from a competitor page."""

    product_name: str = PydField(description="产品名称/系列/型号，保留中文原文")
    series: str | None = PydField(default=None, description="所属产品系列（若页面标注）")
    category: str | None = PydField(
        default=None, description="品类，如 保险柜/防火柜/金库门/保管箱/ATM/锁具"
    )
    price: float | None = PydField(
        default=None, description="含税零售价数字（不含货币符号）；无则 null"
    )
    currency: str = PydField(default="CNY", description="货币，中国市场默认 CNY")
    promotion: str | None = PydField(default=None, description="促销措辞，如 满3000减300 / 618特惠")
    promotion_end_date: str | None = PydField(default=None, description="促销结束日期 YYYY-MM-DD 或原文")
    launch_date: str | None = PydField(default=None, description="上市/发布日期（若页面提及）")
    availability: str | None = PydField(default=None, description="库存/状态：有货/缺货/预售/下架")
    key_features: list[str] = PydField(default_factory=list, description="关键卖点/特性列表")
    gb_grade: str | None = PydField(default=None, description="GB 10409 防盗等级 A/B/C（若标注）")
    euro_grade: str | None = PydField(
        default=None, description="欧标/美标防盗等级，如 EN1143-1 级别 / S1 / TL-15"
    )
    fire_rating: str | None = PydField(default=None, description="防火等级/时长，如 EN1047-1 / 30min")
    capacity_l: float | None = PydField(default=None, description="容积（升 L），若标注")
    weight_kg: float | None = PydField(default=None, description="净重（千克 kg），若标注")
    width_mm: float | None = PydField(default=None, description="内部宽度 W（毫米 mm），若标注")
    depth_mm: float | None = PydField(default=None, description="内部深度 D（毫米 mm），若标注")
    height_mm: float | None = PydField(default=None, description="内部高度 H（毫米 mm），若标注")
    lock_type: str | None = PydField(default=None, description="锁具类型：电子/机械/指纹/双保险 等")
    lead_time_days: int | None = PydField(default=None, description="订货周期/交货期（天），若标注")
    sales_volume: int | None = PydField(default=None, description="销量/成交量数字（电商页面），若标注")
    status_label: str | None = PydField(default=None, description="页面标签：热卖/爆款/新品/限量 等")
    image_url: str | None = PydField(default=None, description="产品主图 URL（若能确定）")
    product_url: str | None = PydField(default=None, description="产品详情页 URL")
    source_url: str | None = PydField(default=None, description="该产品所在页面 URL")

    @field_validator("sales_volume", "lead_time_days", "price", "capacity_l",
                     "weight_kg", "width_mm", "depth_mm", "height_mm", mode="before")
    @classmethod
    def _coerce_number(cls, v):
        """LLMs return '1000+', '¥2,999', '约50' etc. — extract the leading number."""
        if v is None or isinstance(v, (int, float)):
            return v
        m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(v))
        return m.group(0).replace(",", "") if m else None

    def product_key(self) -> str:
        """Stable identity for matching across snapshots (normalized name)."""
        from chubb_ci.diff.matching import normalize_product_key

        return normalize_product_key(self.product_name)


class ProductExtraction(BaseModel):
    """Top-level LLM response envelope."""

    products: list[ExtractedProduct] = PydField(default_factory=list)


# =========================================================================
# ORM tables
# =========================================================================
class CrawlRun(SQLModel, table=True):
    """One execution of the pipeline (manual, daily, or weekly)."""

    id: int | None = Field(default=None, primary_key=True)
    kind: str = "manual"
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    status: str = "running"
    sources_ok: int = 0
    sources_failed: int = 0
    sources_blocked: int = 0
    sources_skipped: int = 0
    baselines: int = 0
    products_extracted: int = 0
    events_detected: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    est_cost_cny: float = 0.0
    error: str | None = None


class Snapshot(SQLModel, table=True):
    """A fetched-and-processed capture of one source at one point in time."""

    id: int | None = Field(default=None, primary_key=True)
    run_id: int | None = Field(default=None, foreign_key="crawlrun.id", index=True)
    source_name: str = Field(index=True)
    company: str = ""
    url: str = ""
    page_type: str = ""
    channel: str = ""
    crawl_time: datetime = Field(default_factory=utcnow)
    content_hash: str = Field(default="", index=True)
    raw_path: str | None = None
    status: str = SnapshotStatus.OK.value
    error: str | None = None
    num_products: int = 0


class ProductRecord(SQLModel, table=True):
    """A normalized product row belonging to a snapshot."""

    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: int | None = Field(default=None, foreign_key="snapshot.id", index=True)
    run_id: int | None = Field(default=None, index=True)
    source_name: str = Field(default="", index=True)
    company: str = Field(default="", index=True)
    channel: str = Field(default="", index=True)   # 官网/苏宁/京东/天猫/分析报告

    product_name: str = ""
    product_key: str = Field(default="", index=True)
    model_code: str | None = Field(default=None, index=True)  # cross-platform match key
    series: str | None = None
    category: str | None = None
    price: float | None = None
    currency: str = "CNY"
    promotion: str | None = None
    promotion_end_date: str | None = None
    launch_date: str | None = None
    availability: str | None = None
    key_features: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    gb_grade: str | None = None
    euro_grade: str | None = None
    fire_rating: str | None = None
    capacity_l: float | None = None
    weight_kg: float | None = None
    width_mm: float | None = None
    depth_mm: float | None = None
    height_mm: float | None = None
    lock_type: str | None = None
    lead_time_days: int | None = None
    sales_volume: int | None = None
    status_label: str | None = None
    image_url: str | None = None
    product_url: str | None = None
    source_url: str | None = None
    crawl_time: datetime = Field(default_factory=utcnow)
    # Computed by chubb_ci/normalize at ingest (never by the LLM).
    fire_hours: float | None = None
    security_score: int | None = None


class DiffEvent(SQLModel, table=True):
    """A deterministic change detected between two snapshots of a source."""

    id: int | None = Field(default=None, primary_key=True)
    run_id: int | None = Field(default=None, index=True)
    source_name: str = Field(default="", index=True)
    company: str = Field(default="", index=True)
    event_type: str = ""
    product_key: str = ""
    product_name: str = ""
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    pct_change: float | None = None
    channel: str = ""
    source_url: str | None = None
    detected_at: datetime = Field(default_factory=utcnow)


class Brand(SQLModel, table=True):
    """Strategic profile of a brand (competitor or our own), from config/brands.yaml."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    name_en: str | None = None
    is_own: bool = False
    is_focus: bool = False                  # 重点关注竞品 (user-labelled key competitor)
    positioning: str | None = None          # 品牌定位
    competition_tier: str | None = None     # 竞争层级
    target_audience: str | None = None      # 核心客群
    strengths: list[str] = Field(default_factory=list, sa_column=Column(JSON))      # 核心优势
    shortcomings: list[str] = Field(default_factory=list, sa_column=Column(JSON))   # 品牌短板
    price_architecture: list[dict] = Field(default_factory=list, sa_column=Column(JSON))  # 系列/价格带
    market_scale: str | None = None         # 规模/销量
    supply_chain: str | None = None         # 供应链/产地
    warranty: str | None = None             # 售后质保
    updated_at: datetime = Field(default_factory=utcnow)


class OwnProduct(SQLModel, table=True):
    """集宝 internal catalog row (imported from ChubbProductsList.xlsx)."""

    id: int | None = Field(default=None, primary_key=True)
    product_name: str = ""
    product_key: str = Field(default="", index=True)
    series: str | None = None
    category: str | None = None
    price: float | None = None              # 含税零售价 (RMB)
    currency: str = "CNY"
    width_mm: float | None = None
    depth_mm: float | None = None
    height_mm: float | None = None
    capacity_l: float | None = None
    weight_kg: float | None = None
    fire_rating: str | None = None
    gb_grade: str | None = None
    euro_grade: str | None = None
    lock_type: str | None = None
    lead_time_days: int = 0                 # 订货周期；0 = 现货 (domestic-stock advantage)
    status_label: str | None = None         # 热卖/价值最高/功能贴近
    fire_hours: float | None = None         # computed
    security_score: int | None = None       # computed
    imported_at: datetime = Field(default_factory=utcnow)


class CounterpartPair(SQLModel, table=True):
    """对标 mapping: one of our models ↔ a competitor's functional counterpart."""

    id: int | None = Field(default=None, primary_key=True)
    own_product_key: str = Field(index=True)
    comp_company: str = Field(index=True)
    comp_product_key: str = Field(index=True)
    note: str | None = None


class Insight(SQLModel, table=True):
    """A deterministic market insight (opportunity/anomaly), regenerated per run."""

    id: int | None = Field(default=None, primary_key=True)
    run_id: int | None = Field(default=None, index=True)
    insight_type: str = ""   # pricing_anomaly | market_gap | logistics_advantage
    severity: str = "Med"
    title: str = ""
    detail: str = ""
    company: str | None = None
    product_key: str | None = None
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    detected_at: datetime = Field(default_factory=utcnow)


class Report(SQLModel, table=True):
    """A generated executive report (daily digest or weekly deep-dive)."""

    id: int | None = Field(default=None, primary_key=True)
    run_id: int | None = Field(default=None, index=True)
    report_type: str = ReportType.DAILY.value
    period_start: datetime | None = None
    period_end: datetime | None = None
    title: str = ""
    content_md: str = ""
    model_used: str = ""
    num_events: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class AgentRun(SQLModel, table=True):
    """One execution of an agent workflow (ingest / scan / research / enrich / discover)."""

    id: int | None = Field(default=None, primary_key=True)
    workflow: str = ""                       # ingest | scan | research | enrich | discover
    goal: str = ""                           # human-readable goal / parameters
    status: str = "running"                  # running | done | failed
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    iterations: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cny: float = 0.0
    facts_total: int = 0
    facts_verified: int = 0
    facts_pending: int = 0
    result_md: str = ""                      # final report / drafted copy (markdown)
    error: str | None = None


class AgentStepRecord(SQLModel, table=True):
    """One live-log line of an agent run (persisted immediately for polling)."""

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    ts: datetime = Field(default_factory=utcnow)
    node: str = ""                           # 规划/搜索/抓取/抽取/核查/评估/报告/应用
    message: str = ""
    detail: str = ""


class PendingFact(SQLModel, table=True):
    """A sourced claim awaiting (or having received) human 采纳/驳回 review."""

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    subject: str = ""                        # brand or product the claim is about
    field: str = ""                          # e.g. price / fire_rating / positioning
    value: str = ""
    claim: str = ""                          # full human-readable claim
    sources: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    corroborations: int = 0
    confidence: float = 0.0
    status: str = "pending"                  # pending | verified | rejected | applied
    review_note: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class EmailRecord(SQLModel, table=True):
    """One processed subscription email (dedup by Message-ID; provenance for 邮件订阅)."""

    id: int | None = Field(default=None, primary_key=True)
    message_id: str = Field(default="", index=True, unique=True)
    sender: str = ""                         # From header (display + address)
    subject: str = ""
    received_at: datetime | None = None      # Date header (parsed, best-effort)
    processed_at: datetime = Field(default_factory=utcnow)
    snapshot_id: int | None = Field(default=None, foreign_key="snapshot.id")
    num_products: int = 0
    status: str = "ok"                       # ok | empty | error
    error: str | None = None


# =========================================================================
# Converters
# =========================================================================
def record_to_extracted(rec: ProductRecord) -> ExtractedProduct:
    """Map a stored :class:`ProductRecord` back to the wire schema (for diffing)."""
    return ExtractedProduct(
        product_name=rec.product_name,
        series=rec.series,
        category=rec.category,
        price=rec.price,
        currency=rec.currency,
        promotion=rec.promotion,
        promotion_end_date=rec.promotion_end_date,
        launch_date=rec.launch_date,
        availability=rec.availability,
        key_features=list(rec.key_features or []),
        gb_grade=rec.gb_grade,
        euro_grade=rec.euro_grade,
        fire_rating=rec.fire_rating,
        capacity_l=rec.capacity_l,
        weight_kg=rec.weight_kg,
        width_mm=rec.width_mm,
        depth_mm=rec.depth_mm,
        height_mm=rec.height_mm,
        lock_type=rec.lock_type,
        lead_time_days=rec.lead_time_days,
        sales_volume=rec.sales_volume,
        status_label=rec.status_label,
        image_url=rec.image_url,
        product_url=rec.product_url,
        source_url=rec.source_url,
    )
