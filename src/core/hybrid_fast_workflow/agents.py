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

from src.core.graph_rag.adapters.session_pool import MCPSessionPool
from src.core.graph_rag.core.config import SystemConfig
from src.core.graph_rag.schema.dynamic_schema_manager import DynamicSchemaManager
from src.core.graph_rag.tools.manager import ToolManager
from src.core.hybrid_fast_workflow.utils import parse_llm_json

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
    """Calls qdrant-find directly via a dedicated MCP session."""

    async def run(self, query: str, config: Dict[str, Any], context: str = "") -> Dict[str, Any]:
        qdrant_config_path = config.get("qdrant_config_path", "/opt/genpod/qdrant_config.json")
        collection_name = config.get("collection_name", "HelloWorldApp_pageindex_v3")
        limit = config.get("max_results", 5)

        with open(qdrant_config_path) as f:
            cfg = json.load(f)

        pool = MCPSessionPool(cfg, sse_timeout=300)
        session_id, session = await pool.acquire_session("vector_agent")

        try:
            search_query = query if not context else f"{query}\n\nContext: {context}"
            logger.info(f"[VectorAgent] qdrant-find: {query[:80]}")

            raw = await asyncio.wait_for(
                session.call_tool("qdrant-find", {
                    "query": search_query,
                    "collection_name": collection_name,
                    "limit": limit,
                }),
                timeout=120,
            )

            content = raw.content[0] if isinstance(raw.content, list) else raw.content
            text = content.text if hasattr(content, "text") else str(content)

            try:
                data = json.loads(text)
                results = data if isinstance(data, list) else data.get("results", [data])
            except json.JSONDecodeError:
                results = [{"content": text}]

            summary = "\n\n".join(
                r.get("document", r.get("content", str(r)))
                for r in results[:limit]
            )
            return {"answer": summary, "raw_results": results, "sufficient": bool(results)}

        except Exception as e:
            logger.error(f"[VectorAgent] failed: {e}")
            return {"answer": "", "raw_results": [], "error": str(e), "sufficient": False}
        finally:
            await pool.release_session(session_id)


# ── Graph ────────────────────────────────────────────────────────────────────

_GRAPH_AGENT_SYSTEM = """\
You are a schema-aware CPG (Code Property Graph) query agent.
The CPG is a custom language-agnostic universal graph.

You MUST inspect the schema before writing any Cypher query:
1. Call get_node_labels to see available node types
2. Call get_node_properties / get_outgoing_relationships to understand structure
3. Write and execute a schema-valid Cypher query via neo4j_execute_query
4. Return your findings as plain text\
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

    def __init__(self, max_iterations: int = 5):
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
            schema_manager = DynamicSchemaManager(yaml_schema_path=schema_path)
            await schema_manager.initialize_background(session)
            tool_manager = ToolManager(session, schema_manager, agent_id="graph_agent_fast")

            # ResilientLLMClient with Claude SDK fallback + in-process schema tools
            system_config = SystemConfig(
                mcp_config_path=neo4j_config_path,
                yaml_schema_path=schema_path,
            )
            llm_config = system_config.get_llm_config()
            client = llm_config.create_client()
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
