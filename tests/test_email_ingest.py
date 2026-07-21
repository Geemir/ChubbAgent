"""Tests for the 竞品促销邮件 ingest (IMAP parse → LLM extract → 邮件订阅 records)."""

from __future__ import annotations

import json
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from chubb_ci.crawler.email_ingest import (
    parse_email_bytes,
    run_email_ingest,
    sender_company,
)
from chubb_ci.llm.fake import FakeLLM
from chubb_ci.schemas.models import EmailRecord, ProductRecord
from chubb_ci.storage.db import init_db, session_scope


def _promo_eml(subject: str = "618大促：全场保险柜低至5折",
               sender: str = "得力安防 <newsletter@deli-safe.example>",
               message_id: str = "<promo-618@deli-safe.example>") -> bytes:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = sender
    msg["Message-ID"] = message_id
    msg["Date"] = "Thu, 10 Jul 2026 09:30:00 +0800"
    msg.attach(MIMEText("纯文本版：得力4116G 保险柜 到手价 ¥1,599", "plain", "utf-8"))
    msg.attach(MIMEText(
        "<html><body><h1>618 大促</h1>"
        "<p>得力4116G 电子密码保险柜，到手价 <b>¥1,599</b>（原价 ¥1,999）。</p>"
        "<p>限时三天，指纹款 4117G ¥1,899。</p></body></html>",
        "html", "utf-8"))
    return msg.as_bytes()


def test_parse_email_decodes_headers_and_prefers_html():
    mail = parse_email_bytes(_promo_eml())
    assert mail.subject == "618大促：全场保险柜低至5折"
    assert "得力安防" in mail.sender
    assert mail.message_id == "<promo-618@deli-safe.example>"
    assert mail.received_at is not None and mail.received_at.year == 2026
    assert "4116G" in mail.text and "1,599" in mail.text  # html body extracted


def test_sender_company_strips_address():
    assert sender_company('得力安防 <a@deli.example>') == "得力安防"
    assert sender_company('"AIPU" <news@aipu.example>') == "AIPU"
    assert sender_company("bare@addr.example") == "bare@addr.example"
    assert sender_company("") == "邮件订阅"


def _fake_llm() -> FakeLLM:
    products = {"products": [{
        "product_name": "得力4116G 电子密码保险柜", "category": "保险柜",
        "price": 1599, "currency": "CNY", "promotion": "618大促 5折起",
    }]}
    return FakeLLM(handler=lambda *_: json.dumps(products, ensure_ascii=False))


def test_run_email_ingest_lands_records_and_dedups(settings):
    init_db(settings)
    mail = parse_email_bytes(_promo_eml())

    s1 = run_email_ingest(settings, llm=_fake_llm(), emails=[mail])
    assert s1.processed == 1 and s1.products == 1 and not s1.errors

    with session_scope(settings) as session:
        from sqlmodel import select

        rec = session.exec(select(ProductRecord)).all()[-1]
        assert rec.channel == "邮件订阅"
        assert rec.company == "得力安防"          # From display name
        assert rec.price == 1599
        assert rec.snapshot_id is not None        # provenance snapshot exists
        email_row = session.exec(select(EmailRecord)).one()
        assert email_row.num_products == 1 and email_row.status == "ok"

    # same Message-ID again → dedup, no double ingestion
    s2 = run_email_ingest(settings, llm=_fake_llm(), emails=[mail])
    assert s2.skipped_duplicates == 1 and s2.processed == 0


def test_run_email_ingest_empty_body_marked_empty(settings):
    init_db(settings)
    msg = MIMEText("", "plain", "utf-8")
    msg["Subject"] = "（空）"
    msg["From"] = "x <x@example.com>"
    msg["Message-ID"] = "<empty@example.com>"
    mail = parse_email_bytes(msg.as_bytes())
    s = run_email_ingest(settings, llm=_fake_llm(), emails=[mail])
    assert s.processed == 0
    with session_scope(settings) as session:
        from sqlmodel import select

        row = session.exec(select(EmailRecord)).one()
        assert row.status == "empty"
