"""Repository: all DB reads/writes for the pipeline, in one place."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, delete, select

from chubb_ci.schemas.models import (
    Brand,
    CounterpartPair,
    CrawlRun,
    DiffEvent,
    Insight,
    OwnProduct,
    ProductRecord,
    Report,
    Snapshot,
    SnapshotStatus,
    utcnow,
)


class Repository:
    """Thin data-access layer over a SQLModel :class:`Session`."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------- runs
    def create_run(self, kind: str) -> CrawlRun:
        run = CrawlRun(kind=kind, status="running")
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        return run

    def finish_run(self, run: CrawlRun, *, status: str = "ok", error: str | None = None) -> None:
        run.finished_at = utcnow()
        run.status = status
        run.error = error
        self.session.add(run)
        self.session.commit()

    # -------------------------------------------------------- snapshots
    def add_snapshot(self, snapshot: Snapshot) -> Snapshot:
        self.session.add(snapshot)
        self.session.commit()
        self.session.refresh(snapshot)
        return snapshot

    def last_snapshot(self, source_name: str) -> Snapshot | None:
        """Most recent snapshot for a source, any status (for hash comparison)."""
        stmt = (
            select(Snapshot)
            .where(Snapshot.source_name == source_name)
            .order_by(Snapshot.crawl_time.desc())  # type: ignore[union-attr]
        )
        return self.session.exec(stmt).first()

    def last_ok_snapshot(
        self, source_name: str, before_id: int | None = None
    ) -> Snapshot | None:
        """Most recent snapshot that actually produced products (status=ok)."""
        stmt = select(Snapshot).where(
            Snapshot.source_name == source_name,
            Snapshot.status == SnapshotStatus.OK.value,
        )
        if before_id is not None:
            stmt = stmt.where(Snapshot.id < before_id)
        stmt = stmt.order_by(Snapshot.crawl_time.desc())  # type: ignore[union-attr]
        return self.session.exec(stmt).first()

    # --------------------------------------------------------- products
    def add_products(self, records: list[ProductRecord]) -> None:
        for r in records:
            self.session.add(r)
        self.session.commit()

    def products_for_snapshot(self, snapshot_id: int) -> list[ProductRecord]:
        stmt = select(ProductRecord).where(ProductRecord.snapshot_id == snapshot_id)
        return list(self.session.exec(stmt).all())

    def products_for_run(self, run_id: int) -> list[ProductRecord]:
        stmt = select(ProductRecord).where(ProductRecord.run_id == run_id)
        return list(self.session.exec(stmt).all())

    def all_products(self) -> list[ProductRecord]:
        stmt = select(ProductRecord).order_by(ProductRecord.crawl_time)  # type: ignore[arg-type]
        return list(self.session.exec(stmt).all())

    # ----------------------------------------------------------- events
    def add_events(self, events: list[DiffEvent]) -> None:
        for e in events:
            self.session.add(e)
        self.session.commit()

    def recent_events(self, limit: int = 20) -> list[DiffEvent]:
        stmt = (
            select(DiffEvent)
            .order_by(DiffEvent.detected_at.desc())  # type: ignore[union-attr]
            .limit(limit)
        )
        return list(self.session.exec(stmt).all())

    def latest_run(self) -> CrawlRun | None:
        stmt = select(CrawlRun).order_by(CrawlRun.started_at.desc())  # type: ignore[union-attr]
        return self.session.exec(stmt).first()

    def events_for_run(self, run_id: int) -> list[DiffEvent]:
        stmt = select(DiffEvent).where(DiffEvent.run_id == run_id)
        return list(self.session.exec(stmt).all())

    def events_between(self, start: datetime, end: datetime) -> list[DiffEvent]:
        stmt = (
            select(DiffEvent)
            .where(DiffEvent.detected_at >= start, DiffEvent.detected_at <= end)
            .order_by(DiffEvent.company, DiffEvent.detected_at)  # type: ignore[arg-type]
        )
        return list(self.session.exec(stmt).all())

    # ------------------------------------------------- brands & catalog
    def all_brands(self) -> list[Brand]:
        return list(self.session.exec(select(Brand)).all())

    def brand_by_name(self, name: str) -> Brand | None:
        return self.session.exec(select(Brand).where(Brand.name == name)).first()

    def own_products(self) -> list[OwnProduct]:
        return list(self.session.exec(select(OwnProduct)).all())

    def counterpart_pairs(self) -> list[CounterpartPair]:
        return list(self.session.exec(select(CounterpartPair)).all())

    # ---------------------------------------------------------- insights
    def replace_insights(self, insights: list[Insight]) -> None:
        """Insights are a snapshot of current state: wipe and rewrite."""
        self.session.exec(delete(Insight))
        for i in insights:
            self.session.add(i)
        self.session.commit()

    def all_insights(self) -> list[Insight]:
        stmt = select(Insight).order_by(Insight.insight_type, Insight.title)  # type: ignore[arg-type]
        return list(self.session.exec(stmt).all())

    # ---------------------------------------------------------- reports
    def add_report(self, report: Report) -> Report:
        self.session.add(report)
        self.session.commit()
        self.session.refresh(report)
        return report

    def latest_report(self, report_type: str) -> Report | None:
        stmt = (
            select(Report)
            .where(Report.report_type == report_type)
            .order_by(Report.created_at.desc())  # type: ignore[union-attr]
        )
        return self.session.exec(stmt).first()
