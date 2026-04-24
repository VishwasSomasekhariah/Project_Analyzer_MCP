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
import re
import subprocess
import tempfile
from typing import Any, Dict

from src.core.graph_rag.adapters.session_pool import MCPSessionPool
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
The CPG is a custom language-agnostic universal graph — you MUST inspect the schema
before writing Cypher queries.

You have access to these tools (call them one at a time):
  get_node_labels              — list all node types in the CPG
  get_node_properties          — properties for a given node type
  get_valid_pairs              — valid (from, to) pairs for a relationship type
  validate_relationship_triplet — check if (from)-[rel]->(to) exists
  get_outgoing_relationships   — relationships leaving a node type
  get_incoming_relationships   — relationships entering a node type
  get_children_types           — child types in the hierarchy
  get_leaf_nodes               — leaf nodes in the hierarchy
  neo4j_execute_query          — execute a Cypher query against the CPG

At each step output EXACTLY one of these JSON formats (no markdown):

To call a tool:
{"action": "call_tool", "tool": "<tool_name>", "args": {<tool_args>}}

When you have a complete answer:
{"action": "answer", "answer": "<your findings>", "cypher_used": "<final cypher or empty>", "sufficient": true}\
"""


class GraphAgent:
    """
    Schema-aware CPG agent using a text-based ReAct loop.

    Uses DynamicSchemaManager schema tools + neo4j_execute_query.
    The llm_service passed in is ResilientLLMService — Claude SDK fallback
    activates automatically if the primary LLM fails.
    """

    def __init__(self, max_iterations: int = 5):
        self._max_iterations = max_iterations

    async def run(self, query: str, config: Dict[str, Any], context: str = "", llm_service: Any = None) -> Dict[str, Any]:
        neo4j_config_path = config.get("neo4j_config_path", "/opt/genpod/neo4j_config.json")
        schema_path = config.get("schema_path", "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml")

        with open(neo4j_config_path) as f:
            neo4j_cfg = json.load(f)

        pool = MCPSessionPool(neo4j_cfg, sse_timeout=300)
        session_id, session = await pool.acquire_session("graph_agent")

        try:
            schema_manager = DynamicSchemaManager(yaml_schema_path=schema_path)
            await schema_manager.initialize_background(session)
            tool_manager = ToolManager(session, schema_manager, agent_id="graph_agent")

            # Build ReAct conversation as a growing text prompt
            conversation = []
            user_prompt = f"QUERY: {query}"
            if context:
                user_prompt += f"\n\nCONTEXT FROM PRIOR HOPS:\n{context}"
            conversation.append(f"USER: {user_prompt}")

            for attempt in range(self._max_iterations):
                logger.info(f"[GraphAgent] attempt {attempt + 1}/{self._max_iterations}")

                full_prompt = "\n\n".join(conversation) + "\n\nASSISTANT:"

                # ResilientLLMService — Claude SDK fallback fires automatically
                llm_response = await llm_service.generate_response(
                    prompt=full_prompt,
                    system_prompt=_GRAPH_AGENT_SYSTEM,
                    json_mode=True,
                    temperature=0.1,
                    max_tokens=4000,
                    use_cache=False,
                )

                if llm_response.error:
                    logger.error(f"[GraphAgent] LLM error: {llm_response.error}")
                    break

                raw_content = llm_response.content
                conversation.append(f"ASSISTANT: {raw_content}")

                try:
                    action = parse_llm_json(raw_content)
                except (json.JSONDecodeError, ValueError):
                    logger.warning(f"[GraphAgent] non-JSON response: {raw_content[:200]}")
                    break

                if action.get("action") == "answer":
                    return {
                        "answer": action.get("answer", ""),
                        "cypher_used": action.get("cypher_used", ""),
                        "raw_results": [],
                        "sufficient": action.get("sufficient", True),
                    }

                if action.get("action") == "call_tool":
                    tool_name = action.get("tool", "")
                    tool_args = action.get("args", {})
                    try:
                        tool_result = await tool_manager.execute_tool(tool_name, tool_args)
                        conversation.append(f"TOOL ({tool_name}): {tool_result}")
                    except Exception as e:
                        conversation.append(f"TOOL ({tool_name}) ERROR: {str(e)}")

            return {
                "answer": "Graph agent exhausted retries without a conclusive answer.",
                "raw_results": [],
                "sufficient": False,
            }

        except Exception as e:
            logger.error(f"[GraphAgent] failed: {e}")
            return {"answer": "", "raw_results": [], "error": str(e), "sufficient": False}
        finally:
            await pool.release_session(session_id)
