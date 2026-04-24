"""
Database agents for the Hybrid Fast Workflow.

Each agent encapsulates access to one data source:
- PageIndexAgent : file-hierarchy MCTS via codebase-vector-rag CLI subprocess
- VectorAgent    : semantic search via direct Qdrant MCP session (qdrant-find)
- GraphAgent     : CPG queries via Neo4j MCP session + schema-aware ReAct loop
"""
import asyncio
import json
import logging
import os
import subprocess
import tempfile
from typing import Any, Dict

from src.core.graph_rag.adapters.mcp_adapter import MCPCypherAdapter
from src.core.graph_rag.adapters.session_pool import MCPSessionPool
from src.core.graph_rag.core.config import SystemConfig
from src.core.graph_rag.schema.dynamic_schema_manager import DynamicSchemaManager
from src.core.graph_rag.tools.manager import ToolManager
from src.core.hybrid_fast_workflow.utils import parse_llm_json
from src.core.retrieval.hybrid_vector_retriever import HybridVectorRetriever

logger = logging.getLogger(__name__)

# ── PageIndex ────────────────────────────────────────────────────────────────

class PageIndexAgent:
    """Calls codebase-vector-rag --retriever pageindex as a subprocess."""

    async def run(self, query: str, config: Dict[str, Any], context: str = "") -> Dict[str, Any]:
        project_path = config.get("project_path", "/opt/HelloWorldApp")
        mcts_iterations = config.get("mcts_iterations", 20)
        codebase_rag_config = config.get("codebase_rag_config")

        cli = ["codebase-vector-rag"]
        if codebase_rag_config:
            cli += ["--config", codebase_rag_config]
        cli += [
            "query", query,
            "--retriever", "pageindex",
            "--project-path", str(project_path),
            "--mcts-iterations", str(mcts_iterations),
            "--output-format", "json",
        ]

        logger.info(f"[PageIndexAgent] {' '.join(cli)}")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".stderr", delete=False) as f:
            stderr_path = f.name
            result = subprocess.run(cli, text=True, stdout=subprocess.PIPE, stderr=f, check=False)

        with open(stderr_path) as f:
            stderr_text = f.read()
        os.unlink(stderr_path)

        if result.returncode != 0:
            logger.error(f"[PageIndexAgent] CLI failed: {stderr_text[:500]}")
            return {"answer": "", "raw_results": [], "error": stderr_text[:500], "sufficient": False}

        try:
            data = json.loads(result.stdout)
            return {
                "answer": data.get("response") or data.get("answer", ""),
                "raw_results": data.get("results", []),
                "confidence": data.get("confidence_score", 0.0),
                "sufficient": True,
            }
        except json.JSONDecodeError as e:
            return {"answer": "", "raw_results": [], "error": str(e), "sufficient": False}


# ── Vector ───────────────────────────────────────────────────────────────────

class VectorAgent:
    """
    Hybrid vector retrieval agent using HybridVectorRetriever.

    Calls qdrant-find via MCP, applies BM25 post-scoring and RRF reranking
    through the shared HybridVectorRetriever — no subprocess needed.
    """

    async def run(self, query: str, config: Dict[str, Any], context: str = "") -> Dict[str, Any]:
        qdrant_config_path = config.get("qdrant_config_path", "/opt/genpod/qdrant_config.json")
        collection_name = config.get("collection_name", "HelloWorldApp_pageindex_v3")
        top_k = config.get("max_results", 5)

        with open(qdrant_config_path) as f:
            cfg = json.load(f)

        pool = MCPSessionPool(cfg, sse_timeout=300)
        session_id, session = await pool.acquire_session("vector_agent")

        try:
            search_query = query if not context else f"{query}\n\nContext: {context}"
            logger.info(f"[VectorAgent] hybrid search: {query[:80]}")

            retriever = HybridVectorRetriever(session, collection_name)
            results = await retriever.search(search_query, top_k=top_k)

            summary = "\n\n".join(r["content"] for r in results)
            logger.info(f"[VectorAgent] {len(results)} results after BM25+RRF reranking")
            return {"answer": summary, "raw_results": results, "sufficient": bool(results)}

        except Exception as e:
            logger.error(f"[VectorAgent] failed: {e}")
            return {"answer": "", "raw_results": [], "error": str(e), "sufficient": False}
        finally:
            await pool.release_session(session_id)


# ── Graph ────────────────────────────────────────────────────────────────────

_GRAPH_AGENT_SYSTEM = """\
You are a Graph Analysis Agent for code analysis. You answer questions about a codebase \
by querying a Code Property Graph (CPG) stored in Neo4j.

The CPG is a custom, language-agnostic universal graph. Node labels, relationship types, \
and property names may not match what you expect — you must discover them through the \
schema tools before writing any Cypher.

**Reasoning requirement**
Before each tool call or query, think through your reasoning explicitly. Ask yourself:
- What am I trying to find?
- Which node types or relationships might hold this information?
- What properties on those nodes are relevant?
- Does the schema confirm my assumptions?

**Schema discovery workflow**
1. Use get_node_labels to see what node types exist
2. Use get_node_properties to understand what properties each node type carries and their meaning
3. Use relationship tools if you need to traverse edges
4. Only then write and execute a Cypher query using schema-confirmed elements

**Critical rules**
- Never assume a property exists — always confirm with get_node_properties first
- Never assume what a property contains — read its description
- If your first query returns empty results, reason about why and try a different approach
- Properties may contain rich data beyond simple identifiers — explore them

**Output**
Return your findings as a clear plain-text summary of what you found, including relevant \
values from the query results.\
"""

_GRAPH_AGENT_ALLOWED_TOOLS = [
    "get_node_labels",
    "get_node_properties",
    "get_valid_pairs",
    "validate_relationship_triplet",
    "get_outgoing_relationships",
    "get_incoming_relationships",
    "get_children_types",
    "get_leaf_nodes",
    "neo4j_execute_query",
]

# MCP-prefixed names used by the Claude SDK fallback
_GRAPH_AGENT_SDK_ALLOWED_TOOLS = [
    "mcp__schema_tools__get_node_labels",
    "mcp__schema_tools__get_node_properties",
    "mcp__schema_tools__get_valid_pairs",
    "mcp__schema_tools__validate_relationship_triplet",
    "mcp__schema_tools__get_outgoing_relationships",
    "mcp__schema_tools__get_incoming_relationships",
    "mcp__schema_tools__get_children_types",
    "mcp__schema_tools__get_leaf_nodes",
    "mcp__neo4j_memory__neo4j_execute_query",
]


class GraphAgent:
    """
    Schema-aware CPG agent using native OpenAI function-calling.

    Follows the same pattern as VectorAgent — all session lifecycle (MCP pool,
    schema manager, tool manager, LLM client) is managed internally inside run().
    No BaseAgent inheritance needed since there is no shared state or team context.

    Uses ResilientLLMClient (via SystemConfig.get_llm_config().create_client()) so
    Claude SDK fallback activates automatically, with set_tool_context() wiring
    schema tools in-process for the fallback path — exactly as the original
    graph_rag agents do.
    """

    def __init__(self, max_iterations: int = 15):
        self._max_iterations = max_iterations

    async def run(self, query: str, config: Dict[str, Any], context: str = "") -> Dict[str, Any]:
        neo4j_config_path = config.get("neo4j_config_path", "/opt/genpod/neo4j_config.json")
        schema_path = config.get("schema_path", "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml")

        with open(neo4j_config_path) as f:
            neo4j_cfg = json.load(f)

        pool = MCPSessionPool(neo4j_cfg, sse_timeout=300)
        session_id, session = await pool.acquire_session("graph_agent_fast")

        try:
            # Schema + tools — same setup as multi_agent_cot
            system_config = SystemConfig(
                mcp_config_path=neo4j_config_path,
                yaml_schema_path=schema_path,
                llm_config={"fallback_max_turns": self._max_iterations},
            )
            yaml_schema = system_config.get_yaml_schema()
            cypher_adapter = MCPCypherAdapter(session)
            schema_manager = DynamicSchemaManager(cypher_server=cypher_adapter, yaml_schema=yaml_schema)
            await schema_manager.initialize_background()
            tool_manager = ToolManager(session, schema_manager, agent_id="graph_agent_fast")
            llm_config = system_config.get_llm_config()
            client = llm_config.create_client()
            if hasattr(client, "enable_per_agent_mode"):
                client.enable_per_agent_mode()
            if hasattr(client, "set_tool_context"):
                client.set_tool_context(schema_manager, session)

            # Filter to only allowed tools
            tools = [
                t for t in tool_manager.tools
                if t.get("function", {}).get("name") in _GRAPH_AGENT_ALLOWED_TOOLS
            ]

            user_content = f"QUERY: {query}"
            if context:
                user_content += f"\n\nCONTEXT FROM PRIOR HOPS:\n{context}"

            messages = [
                {"role": "system", "content": _GRAPH_AGENT_SYSTEM},
                {"role": "user", "content": user_content},
            ]

            last_cypher = ""

            for attempt in range(self._max_iterations):
                logger.info(f"[GraphAgent] attempt {attempt + 1}/{self._max_iterations}")

                response = client.chat.completions.create(
                    model=llm_config.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.1,
                    agent_context={
                        "agent_id": "graph_agent_fast",
                        "allowed_tools": _GRAPH_AGENT_SDK_ALLOWED_TOOLS,
                    },
                )
                msg = response.choices[0].message

                if msg.tool_calls:
                    messages.append(msg)
                    for tc in msg.tool_calls:
                        tool_name = tc.function.name
                        try:
                            args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            args = {}
                        if tool_name == "neo4j_execute_query":
                            last_cypher = args.get("query", "")
                        try:
                            result = await tool_manager.execute_tool(tool_name, args)
                        except Exception as e:
                            result = json.dumps({"error": str(e)})
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })
                    continue

                # Final text answer
                answer = msg.content or ""
                logger.info(f"[GraphAgent] complete: {answer[:100]}")
                return {
                    "answer": answer,
                    "cypher_used": last_cypher,
                    "raw_results": [],
                    "sufficient": True,
                }

            return {"answer": "Graph agent exhausted retries.", "raw_results": [], "sufficient": False}

        except Exception as e:
            logger.error(f"[GraphAgent] failed: {e}")
            return {"answer": "", "raw_results": [], "error": str(e), "sufficient": False}
        finally:
            await pool.release_session(session_id)
