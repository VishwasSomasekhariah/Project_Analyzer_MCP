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
from src.core.hybrid_fast_workflow.prompts import CONSENSUS_PROMPT, ORCHESTRATOR_SYSTEM, ORCHESTRATOR_USER, SYNTHESIZE_PROMPT
from src.core.hybrid_fast_workflow.utils import parse_llm_json
from src.core.resilient_llm_service import ResilientLLMService

logger = logging.getLogger(__name__)

_DEFAULT_MAX_HOPS = 5

# Complement agent for consensus check: whichever agent was NOT used in hop 1
_CONSENSUS_COMPLEMENT = {
    "pageindex": "graph",
    "vector": "graph",
    "graph": "vector",
}

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


async def _ensure_schema_client(config: Dict) -> None:
    """
    Lazily initialize the schema-aware orchestrator client the first time
    the orchestrator needs to reason about graph queries.
    Subsequent calls are no-ops (client already in config).
    """
    if config.get("_orchestrator_client"):
        return  # already initialized

    try:
        import json as _json
        neo4j_config_path = config.get("neo4j_config_path", "/opt/genpod/neo4j_config.json")
        schema_path = config.get("schema_path", "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml")

        with open(neo4j_config_path) as f:
            neo4j_cfg = _json.load(f)

        pool = MCPSessionPool(neo4j_cfg, sse_timeout=300)
        sid, session = await pool.acquire_session("orchestrator")
        config["_orchestrator_pool"] = pool
        config["_orchestrator_session_id"] = sid

        system_config = SystemConfig(
            mcp_config_path=neo4j_config_path,
            yaml_schema_path=schema_path,
            llm_config={"fallback_max_turns": 5},
        )
        yaml_schema = system_config.get_yaml_schema()
        cypher_adapter = MCPCypherAdapter(session)
        schema_manager = DynamicSchemaManager(cypher_server=cypher_adapter, yaml_schema=yaml_schema)
        await schema_manager.initialize_background()
        tool_manager = ToolManager(session, schema_manager, agent_id="orchestrator")

        orchestrator_tools = [
            t for t in tool_manager.tools
            if t.get("function", {}).get("name") in _ORCHESTRATOR_ALLOWED_TOOLS
        ]

        llm_config = system_config.get_llm_config()
        client = llm_config.create_client()
        if hasattr(client, "enable_per_agent_mode"):
            client.enable_per_agent_mode()
        if hasattr(client, "set_tool_context"):
            client.set_tool_context(schema_manager, session)

        config["_orchestrator_client"] = client
        config["_orchestrator_tools"] = orchestrator_tools
        config["_orchestrator_llm_config"] = llm_config
        logger.info("[Orchestrator] schema client initialized for graph-aware planning")

    except Exception as e:
        logger.warning(f"[Orchestrator] schema client init failed: {e}")


def _format_hop_history(hops: list) -> str:
    if not hops:
        return "(none)"
    lines = []
    for i, hop in enumerate(hops, 1):
        section = f"Hop {i} [{hop.agent.upper()}]\nQuery: {hop.query}\nResult:\n{hop.result}"
        if hop.citations:
            cit_lines = "\n".join(f"  • {c.format()}" for c in hop.citations)
            section += f"\nCitations:\n{cit_lines}"
        lines.append(section)
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

    # Initialize schema client on hop 0 so the orchestrator knows the CPG structure upfront.
    # Schema tools are only relevant when deciding to call the graph agent — the prompt
    # instructs the LLM to use them only in that context.
    if hop_count == 0:
        await _ensure_schema_client(config)

    orchestrator_client = config.get("_orchestrator_client")
    orchestrator_tools = config.get("_orchestrator_tools", [])
    llm_config = config.get("_orchestrator_llm_config")

    user_prompt = ORCHESTRATOR_USER.format(
        user_query=user_query,
        hop_count=hop_count,
        hop_history=_format_hop_history(hop_history),
    )
    consensus_note = state.get("consensus_note")
    if consensus_note:
        user_prompt += f"\n\nCONSENSUS CHECK NOTE:\n{consensus_note}\nUse this discrepancy to guide your next retrieval decision."

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

    # Pass hop_number into config so agents can stamp citations
    config["hop_number"] = state["hop_count"] + 1

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
        citations=result.get("citations", []),
        raw=result,
    )

    return {
        "hop_history": hop_history + [hop],
        "hop_count": state["hop_count"] + 1,
        "_pending_agent": None,
        "_pending_query": None,
    }


async def synthesize_answer(state: OrchestratorState) -> Dict:
    """Final LLM call — combines all hop results into a coherent referenced answer."""
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


async def consensus_check(state: OrchestratorState) -> Dict:
    """
    Single-hop consensus gate triggered when orchestrator wants to synthesize after exactly
    one agent call. Calls the complement agent with the same query and asks the LLM whether
    both results agree.

    Complement rule: pageindex/vector → graph, graph → vector.

    - consensus  → next_action = "synthesize" (proceed normally)
    - ambiguous  → next_action = "continue" (re-enter orchestrate_step with discrepancy note)

    Feature flag: config["enable_consensus_check"] (default True). Set False to skip.
    """
    user_query: str = state["user_query"]
    hop_history: list = state["hop_history"]
    llm_service: Any = state["llm_service"]
    config: Dict = state["config"]

    first_hop = hop_history[0]
    complement = _CONSENSUS_COMPLEMENT.get(first_hop.agent, "vector")

    logger.info(f"[ConsensusCheck] hop 1 used {first_hop.agent} — calling {complement} for consensus")

    config["hop_number"] = state["hop_count"] + 1
    context = _format_hop_history(hop_history)

    if complement == "graph":
        result = await GraphAgent().run(user_query, config, context)
    else:
        result = await VectorAgent().run(user_query, config, context)

    hop = HopEntry(
        agent=complement,
        query=user_query,
        result=result.get("answer", ""),
        citations=result.get("citations", []),
        raw=result,
    )
    updated_history = hop_history + [hop]
    updated_hop_count = state["hop_count"] + 1

    prompt = CONSENSUS_PROMPT.format(
        user_query=user_query,
        agent_1=first_hop.agent,
        query_1=first_hop.query,
        result_1=first_hop.result,
        citations_1="\n".join(c.format() for c in first_hop.citations) or "(none)",
        agent_2=complement,
        query_2=user_query,
        result_2=hop.result,
        citations_2="\n".join(c.format() for c in hop.citations) or "(none)",
    )

    resp = await llm_service.generate_response(
        prompt=prompt,
        system_prompt="You are a precise evidence evaluator. Output only valid JSON.",
        json_mode=True,
        temperature=0.0,
        max_tokens=500,
        use_cache=False,
    )

    verdict_data = {}
    if not resp.error:
        try:
            verdict_data = parse_llm_json(resp.content)
        except Exception:
            logger.warning(f"[ConsensusCheck] verdict parse failed: {resp.content[:100]}")

    verdict = verdict_data.get("verdict", "consensus")
    reasoning = verdict_data.get("reasoning", "")
    discrepancy = verdict_data.get("discrepancy", "")

    logger.info(f"[ConsensusCheck] verdict={verdict} — {reasoning}")

    if verdict == "consensus":
        return {
            "hop_history": updated_history,
            "hop_count": updated_hop_count,
            "next_action": "synthesize",
            "consensus_note": None,
        }

    note = (
        f"Consensus check found ambiguity after calling {first_hop.agent} and {complement}: "
        f"{discrepancy}"
    )
    logger.info(f"[ConsensusCheck] ambiguous — routing back to orchestrator: {note}")
    return {
        "hop_history": updated_history,
        "hop_count": updated_hop_count,
        "next_action": "continue",
        "consensus_note": note,
    }


def _route(state: OrchestratorState) -> str:
    action = state.get("next_action", "synthesize")
    if (
        action == "synthesize"
        and state.get("hop_count", 0) == 1
        and state["config"].get("enable_consensus_check", True)
    ):
        return "consensus_check"
    return action


def _consensus_route(state: OrchestratorState) -> str:
    return state.get("next_action", "synthesize")


# ── Workflow builder ─────────────────────────────────────────────────────────

def build_workflow() -> StateGraph:
    graph = StateGraph(OrchestratorState)

    graph.add_node("orchestrate_step", orchestrate_step)
    graph.add_node("call_agent", call_agent)
    graph.add_node("consensus_check", consensus_check)
    graph.add_node("synthesize_answer", synthesize_answer)

    graph.set_entry_point("orchestrate_step")

    graph.add_conditional_edges(
        "orchestrate_step",
        _route,
        {
            "call_agent": "call_agent",
            "synthesize": "synthesize_answer",
            "consensus_check": "consensus_check",
        },
    )
    graph.add_edge("call_agent", "orchestrate_step")
    graph.add_conditional_edges(
        "consensus_check",
        _consensus_route,
        {
            "synthesize": "synthesize_answer",
            "continue": "orchestrate_step",
        },
    )
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
        # Schema client is initialized lazily in orchestrate_step only when graph is considered
        config.setdefault("_orchestrator_pool", None)
        config.setdefault("_orchestrator_session_id", None)

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
            "consensus_note": None,
        }

        logger.info(f"[HybridFastWorkflow] starting: '{user_query}'")
        try:
            final_state = await self._workflow.ainvoke(initial_state)
        finally:
            # Release lazy-initialized orchestrator schema session if created
            pool = config.get("_orchestrator_pool")
            sid = config.get("_orchestrator_session_id")
            if pool and sid:
                await pool.release_session(sid)

        hops = final_state.get("hop_history", [])

        # Aggregate deduplicated citations across all hops
        seen_ids: set = set()
        all_citations = []
        for hop in hops:
            for c in hop.citations:
                if c.citation_id not in seen_ids:
                    seen_ids.add(c.citation_id)
                    all_citations.append({
                        "citation_id": c.citation_id,
                        "agent": c.agent,
                        "retrieval_method": c.retrieval_method,
                        "hop_number": c.hop_number,
                        "file_path": c.file_path,
                        "entity_name": c.entity_name,
                        "start_line": c.start_line,
                        "end_line": c.end_line,
                        "evidence_text": c.evidence_text,
                        "relevance_score": c.relevance_score,
                        "query_used": c.query_used,
                    })

        return {
            "status": "success",
            "user_query": user_query,
            "answer": final_state.get("final_answer", ""),
            # Alias for downstream compatibility with other RAG workflows
            "ai_response": final_state.get("final_answer", ""),
            "response": final_state.get("final_answer", ""),
            "hop_count": final_state.get("hop_count", 0),
            "hops": [
                {
                    "agent": h.agent,
                    "query": h.query,
                    "result": h.result,
                    "citations": [c.citation_id for c in h.citations],
                }
                for h in hops
            ],
            "citations": all_citations,
            # Citations exposed as raw_results for evaluation framework compatibility
            "raw_results": all_citations,
            "error_log": final_state.get("error_log", []),
        }
