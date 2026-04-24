"""
Hybrid Fast Workflow Orchestrator

LangGraph-based ReAct orchestrator that routes queries across three database
agents (PageIndex, Vector, Graph) in a dynamic multi-hop trajectory.

Workflow:
    START
      ↓
    orchestrate_step  ←──────────────────┐
      │ LLM decides: call_agent | done   │
      ↓                                   │
    call_agent ────── appends result ─────┘
      │ (when done)
      ↓
    synthesize_answer
      ↓
    END
"""
import json
import logging
from typing import Any, Dict

from langgraph.graph import StateGraph, END

from src.core.hybrid_fast_workflow.agents import GraphAgent, PageIndexAgent, VectorAgent
from src.core.hybrid_fast_workflow.models import HopEntry, OrchestratorState
from src.core.hybrid_fast_workflow.prompts import ORCHESTRATOR_SYSTEM, ORCHESTRATOR_USER, SYNTHESIZE_PROMPT
from src.core.hybrid_fast_workflow.utils import parse_llm_json
from src.core.resilient_llm_service import ResilientLLMService

logger = logging.getLogger(__name__)

_DEFAULT_MAX_HOPS = 5


def _format_hop_history(hops: list) -> str:
    if not hops:
        return "(none)"
    lines = []
    for i, hop in enumerate(hops, 1):
        lines.append(f"Hop {i} [{hop.agent.upper()}]\nQuery: {hop.query}\nResult: {hop.result[:800]}")
    return "\n\n".join(lines)


# ── Nodes ────────────────────────────────────────────────────────────────────

async def orchestrate_step(state: OrchestratorState) -> Dict:
    """
    Core reasoning node. LLM decides which agent to call next or to synthesize.
    Output: updates next_action in state (routed via conditional edge).
    """
    llm_service: Any = state["llm_service"]
    user_query: str = state["user_query"]
    hop_history: list = state["hop_history"]
    hop_count: int = state["hop_count"]

    max_hops = state["config"].get("max_hops", _DEFAULT_MAX_HOPS)
    if hop_count >= max_hops:
        logger.info("[Orchestrator] max hops reached — forcing synthesize")
        return {"next_action": "synthesize"}

    prompt = ORCHESTRATOR_USER.format(
        user_query=user_query,
        hop_count=hop_count,
        hop_history=_format_hop_history(hop_history),
    )

    response = await llm_service.generate_response(
        prompt=prompt,
        system_prompt=ORCHESTRATOR_SYSTEM,
        json_mode=True,
        temperature=0.1,
        max_tokens=1000,
        use_cache=False,
    )

    if response.error:
        logger.error(f"[Orchestrator] LLM error: {response.error}")
        return {"next_action": "synthesize", "error_log": state["error_log"] + [response.error]}

    try:
        decision = parse_llm_json(response.content)
    except (json.JSONDecodeError, ValueError):
        logger.warning(f"[Orchestrator] non-JSON decision: {response.content[:200]}")
        return {"next_action": "synthesize"}

    action = decision.get("action", "synthesize")
    if action == "call_agent":
        return {
            "next_action": "call_agent",
            "_pending_agent": decision.get("agent", "pageindex"),
            "_pending_query": decision.get("query", user_query),
            "_pending_reasoning": decision.get("reasoning", ""),
        }

    return {"next_action": "synthesize"}


async def call_agent(state: OrchestratorState) -> Dict:
    """Dispatches to the chosen agent, appends result to hop_history."""
    agent_name: str = state.get("_pending_agent", "pageindex")
    agent_query: str = state.get("_pending_query", state["user_query"])
    llm_service: Any = state["llm_service"]
    config: Dict = state["config"]
    hop_history: list = state["hop_history"]
    context = _format_hop_history(hop_history)

    logger.info(f"[Orchestrator] calling {agent_name} agent: {agent_query[:80]}")

    if agent_name == "pageindex":
        result = await PageIndexAgent().run(agent_query, config, context)
    elif agent_name == "vector":
        result = await VectorAgent().run(agent_query, config, context)
    elif agent_name == "graph":
        result = await GraphAgent().run(agent_query, config, context, llm_service=llm_service)
    else:
        result = {"answer": f"Unknown agent: {agent_name}", "sufficient": False}

    hop = HopEntry(
        agent=agent_name,
        query=agent_query,
        result=result.get("answer", ""),
        raw=result,
    )

    return {
        "hop_history": hop_history + [hop],
        "hop_count": state["hop_count"] + 1,
        "_pending_agent": None,
        "_pending_query": None,
    }


async def synthesize_answer(state: OrchestratorState) -> Dict:
    """Final LLM call — combines all hop results into a coherent answer."""
    llm_service: Any = state["llm_service"]
    user_query: str = state["user_query"]
    hop_history: list = state["hop_history"]

    prompt = SYNTHESIZE_PROMPT.format(
        user_query=user_query,
        hop_history=_format_hop_history(hop_history),
    )

    response = await llm_service.generate_response(
        prompt=prompt,
        system_prompt="You are a precise code analyst. Synthesize the retrieval results into a clear, accurate answer.",
        json_mode=False,
        temperature=0.1,
        max_tokens=4000,
        use_cache=False,
    )

    answer = response.content if not response.error else f"Synthesis failed: {response.error}"
    logger.info(f"[Orchestrator] synthesis complete ({len(answer)} chars)")
    return {"final_answer": answer}


def _route(state: OrchestratorState) -> str:
    return state.get("next_action", "synthesize")


# ── Workflow builder ─────────────────────────────────────────────────────────

def build_workflow() -> StateGraph:
    graph = StateGraph(OrchestratorState)

    graph.add_node("orchestrate_step", orchestrate_step)
    graph.add_node("call_agent", call_agent)
    graph.add_node("synthesize_answer", synthesize_answer)

    graph.set_entry_point("orchestrate_step")

    graph.add_conditional_edges(
        "orchestrate_step",
        _route,
        {
            "call_agent": "call_agent",
            "synthesize": "synthesize_answer",
        },
    )
    graph.add_edge("call_agent", "orchestrate_step")
    graph.add_edge("synthesize_answer", END)

    return graph.compile()


# ── Public API ───────────────────────────────────────────────────────────────

class HybridFastWorkflow:
    """Entry point for the Hybrid Fast Workflow."""

    def __init__(self, max_hops: int = _DEFAULT_MAX_HOPS):
        self._workflow = build_workflow()
        self._max_hops = max_hops

    async def run_analysis(self, user_query: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
        llm_service = ResilientLLMService({})
        config = config or {}
        config.setdefault("max_hops", self._max_hops)

        initial_state: OrchestratorState = {
            "user_query": user_query,
            "llm_service": llm_service,
            "config": config,
            "hop_history": [],
            "final_answer": None,
            "error_log": [],
            "hop_count": 0,
            "next_action": None,
            "_pending_agent": None,
            "_pending_query": None,
            "_pending_reasoning": None,
        }

        logger.info(f"[HybridFastWorkflow] starting: '{user_query}'")
        final_state = await self._workflow.ainvoke(initial_state)

        hops = final_state.get("hop_history", [])
        return {
            "status": "success",
            "user_query": user_query,
            "answer": final_state.get("final_answer", ""),
            "hop_count": final_state.get("hop_count", 0),
            "hops": [
                {"agent": h.agent, "query": h.query, "result": h.result}
                for h in hops
            ],
            "error_log": final_state.get("error_log", []),
        }
