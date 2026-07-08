"""Phase 2 (scaffold only): LangGraph competitor-discovery agent.

Not implemented in the MVP. This package defines the state, bounded-loop guards, and
node/interface contracts so the agent can be built later without reshaping Phase 1.
See ``chubb_ci/agent/README.md`` for the design.
"""

from chubb_ci.agent.state import (
    AgentBudget,
    AgentState,
    AgentStep,
    SearchProvider,
    SourcedFact,
)

__all__ = ["AgentBudget", "AgentState", "AgentStep", "SearchProvider", "SourcedFact"]
