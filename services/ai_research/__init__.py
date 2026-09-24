"""Evidence-grounded multi-agent AI research (server-side only).

Architecture (TradingAgents concepts adapted, independently implemented):

    Providers -> normalization -> provenance -> analytics
        -> FinanceTerminalDataAdapter (services/ai_research/adapter.py)
        -> evidence context (context.py)
        -> role agents (agents.py) via LLM abstraction (llm.py)
        -> claim grounding (grounding.py) + citations (citations.py)
        -> structured report (schemas.py) -> cache (cache.py)

The terminal's provider orchestrator remains the sole source of market
truth. The LLM never fetches market data itself; it only interprets the
evidence context handed to it. No LangGraph / third-party dependency:
the workflow is a small deterministic role pipeline (stdlib only).

Concepts reused from TradingAgents (Apache-2.0, TauricResearch, v0.4.0):
role decomposition (market / fundamental / news analysts, bull / bear
researchers, research manager, risk) and debate-then-synthesize flow.
Deliberately excluded: trade execution, trader order sizing, portfolio
manager approval, backtesting with live-data replay, LangGraph
checkpointing, and TradingAgents' own provider/tool integrations (ours
already exist and are preserved).
"""

from __future__ import annotations
