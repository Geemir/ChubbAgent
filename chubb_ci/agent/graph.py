"""Compatibility shims for the original scaffold API.

The real implementations live in:
- :mod:`chubb_ci.agent.research_flow` — LangGraph research & discovery graphs
- :mod:`chubb_ci.agent.ingest_flow` — linear flows
- :mod:`chubb_ci.agent.service` — run lifecycle + human review

Use :func:`chubb_ci.agent.service.start_workflow` as the single entrypoint.
"""

from __future__ import annotations

from chubb_ci.agent.research_flow import build_research_graph  # noqa: F401
from chubb_ci.agent.service import start_workflow  # noqa: F401
