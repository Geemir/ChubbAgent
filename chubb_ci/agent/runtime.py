"""Agent runtime: run lifecycle, live step logging, and budget accounting.

Every workflow gets an :class:`AgentContext`. Steps are committed to the DB the moment
they happen so the dashboard's run-log panel can poll and display progress in real time.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from loguru import logger
from sqlmodel import Session

from chubb_ci.agent.state import AgentBudget
from chubb_ci.config.settings import Settings
from chubb_ci.llm.base import LLMResponse
from chubb_ci.schemas.models import AgentRun, AgentStepRecord, PendingFact


class BudgetExceeded(RuntimeError):
    """Raised inside a workflow when the AgentBudget is exhausted."""


class AgentContext:
    """Carries the session, run row, budget and logger through a workflow."""

    def __init__(self, session: Session, settings: Settings, run: AgentRun) -> None:
        self.session = session
        self.settings = settings
        self.run = run
        self.budget = AgentBudget(
            max_iterations=settings.agent_max_iterations,
            max_cost_cny=settings.agent_max_cost_cny,
            max_seconds=settings.agent_max_seconds,
        )
        self._t0 = time.monotonic()

    # ------------------------------------------------------------- logging
    def log(self, node: str, message: str, detail: str = "") -> None:
        """Persist one live-log line immediately (visible to pollers)."""
        self.session.add(AgentStepRecord(
            run_id=self.run.id, node=node, message=message, detail=detail))
        self.session.commit()
        logger.info("[agent#{} {}] {}", self.run.id, node, message)

    # ------------------------------------------------------------ LLM cost
    def track(self, resp: LLMResponse) -> LLMResponse:
        """Accumulate token usage/cost from an LLM response onto the run."""
        self.run.tokens_in += resp.tokens_in
        self.run.tokens_out += resp.tokens_out
        s = self.settings
        self.run.cost_cny = round(
            self.run.tokens_in / 1_000_000 * s.llm_price_input_per_m
            + self.run.tokens_out / 1_000_000 * s.llm_price_output_per_m, 4)
        self.session.add(self.run)
        self.session.commit()
        return resp

    # -------------------------------------------------------------- budget
    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self._t0

    def check_budget(self) -> None:
        """Raise :class:`BudgetExceeded` when any hard cap is blown."""
        if self.budget.exhausted(
            iterations=self.run.iterations,
            cost_cny=self.run.cost_cny,
            elapsed_s=self.elapsed_s,
        ):
            raise BudgetExceeded(
                f"budget exhausted: iter={self.run.iterations}/{self.budget.max_iterations} "
                f"cost=¥{self.run.cost_cny}/{self.budget.max_cost_cny} "
                f"elapsed={self.elapsed_s:.0f}s/{self.budget.max_seconds}s"
            )

    # -------------------------------------------------------- pending facts
    def add_pending_fact(self, **kwargs) -> PendingFact:
        fact = PendingFact(run_id=self.run.id, **kwargs)
        self.session.add(fact)
        self.session.commit()
        self.session.refresh(fact)
        return fact


def create_run(session: Session, workflow: str, goal: str) -> AgentRun:
    run = AgentRun(workflow=workflow, goal=goal, status="running")
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def finish_run(ctx: AgentContext, *, status: str = "done", result_md: str = "",
               error: str | None = None) -> None:
    run = ctx.run
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    if result_md:
        run.result_md = result_md
    run.error = error
    ctx.session.add(run)
    ctx.session.commit()
