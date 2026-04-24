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

from src.core.graph_rag.adapters.mcp_adapter import MCPCypherAdapter
from src.core.graph_rag.adapters.session_pool import MCPSessionPool
from src.core.graph_rag.core.config import SystemConfig
from src.core.graph_rag.schema.dynamic_schema_manager import DynamicSchemaManager
from src.core.graph_rag.tools.manager import ToolManager
from src.core.hybrid_fast_workflow.agents import GraphAgent, PageIndexAgent, VectorAgent
from src.core.hybrid_fast_workflow.models import HopEntry, OrchestratorState
from src.core.hybrid_fast_workflow.prompts import ORCHESTRATOR_SYSTEM, ORCHESTRATOR_USER, SYNTHESIZE_PROMPT
from src.core.hybrid_fast_workflow.utils import parse_llm_json
from src.core.resilient_llm_service import ResilientLLMService

logger = logging.getLogger(__name__)

_DEFAULT_MAX_HOPS = 5

# Schema tools the orchestrator may use to plan graph queries — no execute permission
_ORCHESTRATOR_ALLOWED_TOOLS = [
    "get_schema_overview",
    "get_node_labels",
    "get_node_properties",
    "get_outgoing_relationships",
    "get_incoming_relationships",
    "get_valid_pairs",
]
_ORCHESTRATOR_SDK_ALLOWED_TOOLS = [
    "mcp__schema_tools__get_schema_overview",
    "mcp__schema_tools__get_node_labels",
    "mcp__schema_tools__get_node_properties",
    "mcp__schema_tools__get_outgoing_relationships",
    "mcp__schema_tools__get_incoming_relationships",
    "mcp__schema_tools__get_valid_pairs",
]


def _format_hop_history(hops: list) -> str:
    if not hops:
        return "(none)"
    lines = []
    for i, hop in enumerate(hops, 1):
        lines.append(f"Hop {i} [{hop.agent.upper()}]\nQuery: {hop.query}\nResult:\n{hop.result}")
    return "\n\n".join(lines)


# ── Nodes ────────────────────────────────────────────────────────────────────

async def orchestrate_step(state: OrchestratorState) -> Dict:
    """
    Core reasoning node. Schema-aware orchestrator decides which agent to call next.

    Uses a ResilientLLMClient with CPG schema tools (no execute permission) so it
    can inspect node types/properties before formulating precise guidance for the
    graph agent — or pivot to vector/pageindex when graph can't answer.
    """
    user_query: str = state["user_query"]
    hop_history: list = state["hop_history"]
    hop_count: int = state["hop_count"]
    config: Dict = state["config"]

    max_hops = config.get("max_hops", _DEFAULT_MAX_HOPS)
    if hop_count >= max_hops:
        logger.info("[Orchestrator] max hops reached — forcing synthesize")
        return {"next_action": "synthesize"}

    # Use schema-aware client if available, otherwise fall back to llm_service
    orchestrator_client = config.get("_orchestrator_client")
    orchestrator_tools = config.get("_orchestrator_tools", [])
    llm_config = config.get("_orchestrator_llm_config")

    user_prompt = ORCHESTRATOR_USER.format(
        user_query=user_query,
        hop_count=hop_count,
        hop_history=_format_hop_history(hop_history),
    )

    messages = [
        {"role": "system", "content": ORCHESTRATOR_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    try:
        if orchestrator_client and llm_config:
            # Schema-aware path: client has schema tools available
            response = orchestrator_client.chat.completions.create(
                model=llm_config.model,
                messages=messages,
                tools=orchestrator_tools if orchestrator_tools else None,
                tool_choice="auto" if orchestrator_tools else None,
                temperature=0.1,
                agent_context={
                    "agent_id": "orchestrator",
                    "allowed_tools": _ORCHESTRATOR_SDK_ALLOWED_TOOLS,
                },
            )
            raw_content = response.choices[0].message.content or ""
        else:
            # Fallback: simple text completion via llm_service
            llm_service: Any = state["llm_service"]
            resp = await llm_service.generate_response(
                prompt=user_prompt,
                system_prompt=ORCHESTRATOR_SYSTEM,
                json_mode=True,
                temperature=0.1,
                max_tokens=2000,
                use_cache=False,
            )
            if resp.error:
                logger.error(f"[Orchestrator] LLM error: {resp.error}")
                return {"next_action": "synthesize", "error_log": state["error_log"] + [resp.error]}
            raw_content = resp.content
    except Exception as e:
        logger.error(f"[Orchestrator] client error: {e}")
        return {"next_action": "synthesize"}

    try:
        decision = parse_llm_json(raw_content)
    except (json.JSONDecodeError, ValueError):
        logger.warning(f"[Orchestrator] non-JSON decision: {raw_content[:200]}")
        return {"next_action": "synthesize"}

    # Log CoT thinking steps
    thinking = decision.get("thinking", [])
    if thinking:
        logger.info(f"[Orchestrator] reasoning ({len(thinking)} steps):")
        for step in thinking:
            logger.info(f"  • {step}")

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
        result = await GraphAgent().run(agent_query, config, context)
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

        # Build schema-aware orchestrator client (shared across all hops)
        neo4j_pool = None
        neo4j_session_id = None
        try:
            neo4j_config_path = config.get("neo4j_config_path", "/opt/genpod/neo4j_config.json")
            schema_path = config.get("schema_path", "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml")

            import json as _json
            with open(neo4j_config_path) as f:
                neo4j_cfg = _json.load(f)

            neo4j_pool = MCPSessionPool(neo4j_cfg, sse_timeout=300)
            neo4j_session_id, neo4j_session = await neo4j_pool.acquire_session("orchestrator")

            system_config = SystemConfig(
                mcp_config_path=neo4j_config_path,
                yaml_schema_path=schema_path,
                llm_config={"fallback_max_turns": 5},  # short turns — planning only
            )
            yaml_schema = system_config.get_yaml_schema()
            cypher_adapter = MCPCypherAdapter(neo4j_session)
            schema_manager = DynamicSchemaManager(cypher_server=cypher_adapter, yaml_schema=yaml_schema)
            await schema_manager.initialize_background()
            tool_manager = ToolManager(neo4j_session, schema_manager, agent_id="orchestrator")

            # Schema tools only — no execute permission
            orchestrator_tools = [
                t for t in tool_manager.tools
                if t.get("function", {}).get("name") in _ORCHESTRATOR_ALLOWED_TOOLS
            ]

            llm_config = system_config.get_llm_config()
            orchestrator_client = llm_config.create_client()
            if hasattr(orchestrator_client, "enable_per_agent_mode"):
                orchestrator_client.enable_per_agent_mode()
            if hasattr(orchestrator_client, "set_tool_context"):
                orchestrator_client.set_tool_context(schema_manager, neo4j_session)

            config["_orchestrator_client"] = orchestrator_client
            config["_orchestrator_tools"] = orchestrator_tools
            config["_orchestrator_llm_config"] = llm_config
            logger.info("[HybridFastWorkflow] schema-aware orchestrator initialized")

        except Exception as e:
            logger.warning(f"[HybridFastWorkflow] schema orchestrator init failed, using fallback: {e}")

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
        try:
            final_state = await self._workflow.ainvoke(initial_state)
        finally:
            if neo4j_pool and neo4j_session_id:
                await neo4j_pool.release_session(neo4j_session_id)

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
