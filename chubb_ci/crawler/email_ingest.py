"""Subscription-mailbox ingest: competitor promo emails → 邮件订阅-channel records.

A dedicated mailbox (recommended: a 163.com box using its IMAP 授权码) subscribes to
competitor newsletters / marketplace 店铺关注 mails. This module polls it over IMAP,
parses each message deterministically (headers + HTML→text), dedups by Message-ID
(:class:`EmailRecord`), and hands the body to the standard LLM extractor — promos and
prices land as 邮件订阅-channel :class:`ProductRecord` rows with full provenance.

Security note (AGENTS.md): email bodies are UNTRUSTED data. They are only ever passed
to the extractor as page text — never interpreted as instructions or fetched links.

163.com gotcha: NetEase rejects IMAP clients that don't announce themselves via the
RFC 2971 ``ID`` command ("Unsafe Login. Please contact kefu@188.com"). ``_send_id``
handles that; it is a harmless no-op on other providers.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
from dataclasses import dataclass, field
from datetime import datetime
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from loguru import logger
from sqlmodel import select

from chubb_ci.config.settings import Settings
from chubb_ci.config.sources import FetcherKind, PageType, Source
from chubb_ci.crawler.content import extract_main_text
from chubb_ci.schemas.models import EmailRecord, Snapshot, SnapshotStatus
from chubb_ci.storage.repositories import Repository


@dataclass
class ParsedEmail:
    message_id: str
    sender: str = ""
    subject: str = ""
    received_at: datetime | None = None
    text: str = ""


@dataclass
class EmailIngestSummary:
    fetched: int = 0
    skipped_duplicates: int = 0
    processed: int = 0
    products: int = 0
    errors: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ parsing
def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:  # noqa: BLE001 - malformed headers must never kill the run
        return value.strip()


def _best_body(msg: email.message.Message) -> str:
    """Prefer the HTML part (promos are HTML) cleaned to main text; fall back to plain."""
    html, plain = None, None
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        ctype = part.get_content_type()
        if ctype not in ("text/html", "text/plain"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if ctype == "text/html" and html is None:
            html = text
        elif ctype == "text/plain" and plain is None:
            plain = text
    if html:
        cleaned = extract_main_text(html, url="email://message")
        if cleaned.strip():
            return cleaned
    return (plain or "").strip()


def parse_email_bytes(raw: bytes) -> ParsedEmail:
    """RFC822 bytes → :class:`ParsedEmail` (pure; used by tests with .eml fixtures)."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    received = None
    try:
        if msg.get("Date"):
            received = parsedate_to_datetime(msg["Date"])
    except (TypeError, ValueError):
        received = None
    return ParsedEmail(
        message_id=_decode(msg.get("Message-ID")) or "",
        sender=_decode(msg.get("From")),
        subject=_decode(msg.get("Subject")),
        received_at=received,
        text=_best_body(msg),
    )


def sender_company(sender: str) -> str:
    """Display name of the From header ("得力办公 <a@deli.com>" → "得力办公")."""
    name = sender.split("<")[0].strip().strip('"').strip()
    return name or sender.strip() or "邮件订阅"


# ------------------------------------------------------------------ IMAP
_ID_ARGS = ('("name" "chubb-ci" "version" "0.1" "vendor" "chubbsafes-internal" '
            '"contact" "admin")')


def _send_id(conn: imaplib.IMAP4) -> None:
    """RFC 2971 client identification — 163/126 refuse SELECT until the client IDs itself.

    imaplib doesn't know the ``ID`` verb (it's not in ``imaplib.Commands``), so we register
    it for the authenticated states first, then send it. Harmless no-op on other providers.
    """
    imaplib.Commands.setdefault("ID", ("AUTH", "SELECTED", "NONAUTH"))
    try:
        conn._simple_command("ID", _ID_ARGS)  # noqa: SLF001 - no public ID helper
        conn._untagged_response("OK", [None], "ID")  # noqa: SLF001 - consume "* ID (...)"
    except Exception as exc:  # noqa: BLE001
        logger.debug("IMAP ID command not accepted (fine outside 163): {}", exc)


def fetch_recent_emails(settings: Settings, limit: int | None = None) -> list[ParsedEmail]:
    """Fetch the newest N messages from the configured mailbox (read-only)."""
    if not settings.email_user or not settings.email_password:
        raise ValueError("邮箱未配置：请在 .env 设置 CHUBB_EMAIL_USER / CHUBB_EMAIL_PASSWORD")
    limit = limit or settings.email_max_messages
    conn = imaplib.IMAP4_SSL(settings.email_imap_host, settings.email_imap_port)
    try:
        conn.login(settings.email_user, settings.email_password)
        _send_id(conn)
        status, _ = conn.select(settings.email_folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"无法打开邮箱文件夹 {settings.email_folder}")
        status, data = conn.search(None, "ALL")
        if status != "OK":
            raise RuntimeError("IMAP SEARCH 失败")
        ids = data[0].split()
        out: list[ParsedEmail] = []
        for mid in reversed(ids[-limit:]):  # newest first
            status, msg_data = conn.fetch(mid, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            out.append(parse_email_bytes(msg_data[0][1]))
        return out
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ ingest flow
def run_email_ingest(
    settings: Settings,
    *,
    llm=None,
    emails: list[ParsedEmail] | None = None,
    limit: int | None = None,
) -> EmailIngestSummary:
    """Process mailbox messages → extract promos/products → 邮件订阅 records.

    ``emails`` may be supplied directly (tests / .eml replay); otherwise IMAP is polled.
    """
    from chubb_ci.extractor.extractor import extract_products
    from chubb_ci.llm.factory import build_llm, resolve_model
    from chubb_ci.pipeline import _to_record
    from chubb_ci.storage.db import session_scope

    summary = EmailIngestSummary()
    if emails is None:
        emails = fetch_recent_emails(settings, limit)
    summary.fetched = len(emails)
    if not emails:
        return summary

    llm = llm or build_llm(settings)
    model = resolve_model(settings, "extract")
    domain_context = settings.load_domain_context()

    with session_scope(settings) as session:
        repo = Repository(session)
        for mail in emails:
            key = mail.message_id or f"no-id:{mail.sender}|{mail.subject}"
            exists = session.exec(
                select(EmailRecord).where(EmailRecord.message_id == key)).first()
            if exists:
                summary.skipped_duplicates += 1
                continue

            record = EmailRecord(message_id=key, sender=mail.sender,
                                 subject=mail.subject, received_at=mail.received_at)
            if not mail.text.strip():
                record.status = "empty"
                session.add(record)
                session.commit()
                continue

            company = sender_company(mail.sender)
            source = Source(
                name="email-subscribe", company=company, channel="邮件订阅",
                page_type=PageType.CAMPAIGN, fetcher=FetcherKind.LOCAL,
                urls=["email://inbox"],
                notes="竞品订阅邮箱（促销/新品邮件）",
            )
            page_text = f"邮件主题: {mail.subject}\n\n{mail.text}"
            result = extract_products(
                llm, model=model, source=source, url=f"email://{key}",
                page_text=page_text[: settings.max_extract_chars],
                domain_context=domain_context, temperature=settings.llm_temperature,
            )
            if not result.ok:
                record.status = "error"
                record.error = result.error
                session.add(record)
                session.commit()
                summary.errors.append(f"{mail.subject}: {result.error}")
                continue

            snapshot = repo.add_snapshot(Snapshot(
                source_name="email-subscribe", company=company,
                url=f"email://{mail.sender}", page_type=PageType.CAMPAIGN.value,
                channel="邮件订阅", status=SnapshotStatus.OK.value,
                num_products=len(result.products),
            ))
            rows = [_to_record(p, snapshot_id=snapshot.id, run_id=None, source=source)
                    for p in result.products]
            repo.add_products(rows)

            record.snapshot_id = snapshot.id
            record.num_products = len(rows)
            session.add(record)
            session.commit()
            summary.processed += 1
            summary.products += len(rows)
            logger.info("邮件已入库：{} → {} 款产品/促销", mail.subject, len(rows))
    return summary
