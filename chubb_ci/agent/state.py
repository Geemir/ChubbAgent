"""Agent state, budget guards, and provider interfaces (Phase 2 scaffold)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str = ""


@runtime_checkable
class SearchProvider(Protocol):
    """China-accessible web search (Bing/Bocha/Zhipu web-search). Pluggable."""

    def search(self, query: str, *, top_k: int = 10) -> list[SearchHit]: ...


class AgentBudget(BaseModel):
    """Hard bounds so the agent can never loop indefinitely."""

    max_iterations: int = 5
    max_depth: int = 2
    max_cost_cny: float = 5.0
    max_seconds: int = 300

    def exhausted(self, *, iterations: int, cost_cny: float, elapsed_s: float) -> bool:
        return (
            iterations >= self.max_iterations
            or cost_cny >= self.max_cost_cny
            or elapsed_s >= self.max_seconds
        )


class CandidateCompetitor(BaseModel):
    name: str
    url: str = ""
    rationale: str = ""
    category: str = ""
    confidence: float = 0.0


class SourcedFact(BaseModel):
    """A single extracted claim with provenance, for the 真实性核查 (Verify) node.

    Every fact the agent wants to persist must carry its source URL(s). The Verify
    node cross-checks facts across sources and assigns a confidence; anything below
    the auto-accept threshold is queued for human review (``status='pending'``)
    instead of silently entering the database.
    """

    claim: str                      # e.g. "百卫特 CL系列 零售价 ¥4,827"
    field: str = ""                 # target field (price / fire_rating / ...)
    value: str = ""
    subject: str = ""               # brand or product the claim is about
    sources: list[str] = Field(default_factory=list)   # URLs / document names
    corroborations: int = 0         # how many independent sources agree
    confidence: float = 0.0         # 0-1, set by the Verify node
    status: str = "pending"         # pending | verified | rejected
    review_note: str = ""           # human feedback when manually reviewed


class AgentStep(BaseModel):
    """One live-log entry — surfaced verbatim on the 研究智能体 page while running."""

    ts: str                         # ISO timestamp
    node: str                       # planner | search | fetch | extract | verify | evaluate | report
    message: str                    # human-readable, e.g. "抓取 burg.biz/products… (第2页)"
    detail: str = ""                # optional expanded detail (query used, URL, token cost)


class AgentState(BaseModel):
    """Mutable state threaded through the LangGraph nodes."""

    goal: str
    queries: list[str] = Field(default_factory=list)
    hits: list[SearchHit] = Field(default_factory=list)
    candidates: list[CandidateCompetitor] = Field(default_factory=list)
    facts: list[SourcedFact] = Field(default_factory=list)
    steps: list[AgentStep] = Field(default_factory=list)   # live activity log
    iterations: int = 0
    cost_cny: float = 0.0
    elapsed_s: float = 0.0
    done: bool = False
    final_report_md: str = ""
