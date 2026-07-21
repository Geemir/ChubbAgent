"""Application settings, loaded from environment / `.env` (prefix ``CHUBB_``).

Nothing here is hardcoded at call sites — every tunable lives on :class:`Settings`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root = two levels up from this file (chubb_ci/config/settings.py).
_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Central configuration object.

    Values are read from environment variables prefixed with ``CHUBB_`` or from a
    ``.env`` file in the project root. See ``.env.example`` for the full list.
    """

    model_config = SettingsConfigDict(
        env_prefix="CHUBB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM (provider-agnostic; see chubb_ci/llm/providers.py) --------------
    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    #: Empty string => use the provider preset default (providers.py).
    llm_base_url: str = ""
    llm_extract_model: str = ""
    llm_daily_model: str = ""
    llm_weekly_model: str = ""
    llm_timeout: int = 60
    llm_max_retries: int = 3
    llm_temperature: float = 0.0
    #: Rough prices for cost estimation only (CNY per 1M tokens).
    llm_price_input_per_m: float = 1.0
    llm_price_output_per_m: float = 2.0

    # --- Storage & paths ----------------------------------------------------
    data_dir: Path = Path("data")
    db_url: str = ""  # empty => sqlite in data_dir
    sources_file: Path = Path("config/sources.yaml")
    domain_context_file: Path = Path("config/domain/chubbsafes_context.md")

    # --- Crawler ------------------------------------------------------------
    request_timeout: int = 30
    rate_limit_delay: float = 2.0
    max_retries: int = 3
    #: Run Playwright headless. JD/Tmall soft-block headless Chromium even with valid
    #: cookies; set CHUBB_BROWSER_HEADLESS=false for manual JD/Tmall crawls on a desktop.
    browser_headless: bool = True
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
    respect_robots: bool = True

    # --- Extraction ---------------------------------------------------------
    #: Truncate main text before sending to the LLM (token/cost guard).
    max_extract_chars: int = 16000

    # --- Scheduler (cron: "m h dom mon dow") --------------------------------
    daily_cron: str = "30 2 * * *"
    weekly_cron: str = "0 3 * * 1"
    timezone: str = "Asia/Shanghai"

    # --- Reporting ----------------------------------------------------------
    #: Absolute price-change % below which a change is ignored as noise.
    price_change_min_pct: float = 0.0

    # --- Agent (Phase C) ------------------------------------------------------
    #: Web-search backend for research/discovery: "bocha" (needs key) or "none".
    search_provider: str = "none"
    search_api_key: str = ""
    agent_max_iterations: int = 4
    agent_max_cost_cny: float = 5.0
    agent_max_seconds: int = 600
    #: Verify-node confidence threshold: facts >= this auto-apply, below → human review.
    agent_verify_threshold: float = 0.8

    # --- Marketplace crawling -------------------------------------------------
    #: Max product detail pages to enrich (specs) per source per crawl (cost/anti-bot cap).
    detail_enrich_max: int = 5
    #: Optional external crawler microservice (ShilongLee-style) base URL; "" = disabled.
    external_crawler_url: str = ""

    # --- Email ingest (竞品促销邮件订阅) ---------------------------------------
    #: IMAP mailbox that subscribes to competitor newsletters/promos. Recommended:
    #: a dedicated 163.com box (use the IMAP 授权码 as the password, NOT the login
    #: password; enable IMAP/SMTP in 163 settings first). Empty user = disabled.
    email_imap_host: str = "imap.163.com"
    email_imap_port: int = 993
    email_user: str = ""
    email_password: str = ""       # 163 授权码 / app password
    email_folder: str = "INBOX"
    #: Max messages to process per run (newest first; cost guard).
    email_max_messages: int = 20

    # --- JD Union (京东联盟开放平台, official price API) -----------------------
    #: appkey/secret from union.jd.com/openplatform (导购媒体 registration).
    #: Empty key = disabled; the client degrades gracefully.
    jd_union_app_key: str = ""
    jd_union_app_secret: str = ""

    # ---------------------------------------------------------------- helpers
    def _resolve(self, p: Path) -> Path:
        """Resolve a possibly-relative path against the repo root."""
        return p if p.is_absolute() else (_ROOT / p)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def data_path(self) -> Path:
        return self._resolve(self.data_dir)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def raw_path(self) -> Path:
        return self.data_path / "raw"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reports_path(self) -> Path:
        return self.data_path / "reports"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sources_path(self) -> Path:
        return self._resolve(self.sources_file)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def domain_context_path(self) -> Path:
        return self._resolve(self.domain_context_file)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        if self.db_url:
            return self.db_url
        return f"sqlite:///{(self.data_path / 'chubb_ci.db').as_posix()}"

    def ensure_dirs(self) -> None:
        """Create the runtime data directories if missing."""
        for p in (self.data_path, self.raw_path, self.reports_path):
            p.mkdir(parents=True, exist_ok=True)

    def load_domain_context(self) -> str:
        """Return the ChubbSafes domain-context markdown (empty string if absent)."""
        path = self.domain_context_path
        return path.read_text(encoding="utf-8") if path.exists() else ""


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached :class:`Settings` instance."""
    return Settings()
