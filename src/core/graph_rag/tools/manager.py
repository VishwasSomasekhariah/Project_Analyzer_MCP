"""
Tool Manager for the Graph RAG Multi-Agent system.

Manages tools for agents with schema access and security validation.
Handles MCP tool calls with timeout, retry, and observer integration.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from src.core.graph_rag.core.exceptions import CypherSecurityError, ToolExecutionError
from src.core.graph_rag.validators.cypher_validator import CypherQueryValidator
from src.core.graph_rag.schema.dynamic_schema_manager import DynamicSchemaManager
from src.core.graph_rag.schema.schema_tools_langchain import create_schema_tools

if TYPE_CHECKING:
    from src.core.graph_rag.agents.cpg_observer import CPGObserverAgent


class ToolManager:
    """Manages tools for agents with schema access and security validation"""

    def __init__(
        self,
        mcp_session,
        schema_manager: DynamicSchemaManager,
        strict_security: bool = True,
        observer: Optional['CPGObserverAgent'] = None,
        agent_id: str = "unknown"
    ):
        """
        Initialize the ToolManager.

        Args:
            mcp_session: Active MCP session for tool execution
            schema_manager: DynamicSchemaManager for schema operations
            strict_security: If True, blocks dangerous queries
            observer: Optional CPG Observer for query tracking
            agent_id: Identifies which agent is using this ToolManager
        """
        self._session = mcp_session
        self._schema_manager = schema_manager
        self._query_validator = CypherQueryValidator(strict_mode=strict_security)
        self._tools: List[Dict] = []
        self._tool_map: Dict[str, Tuple[str, str]] = {}
        self._langchain_tools: Dict[str, Any] = {}
        self._logger = logging.getLogger(f"{__name__}.ToolManager")
        self._observer = observer  # Optional CPG Observer for query tracking
        self._agent_id = agent_id  # Identifies which agent is using this ToolManager
        self._current_sub_query: Optional[str] = None  # Current sub-query context
        self._build_tools()

    def set_context(self, agent_id: str = None, sub_query: str = None):
        """Set context for observation tracking"""
        if agent_id:
            self._agent_id = agent_id
        if sub_query:
            self._current_sub_query = sub_query

    def _build_tools(self):
        """Build tool definitions"""
        # MCP query tool
        self._tools.append({
            "type": "function",
            "function": {
                "name": "neo4j_execute_query",
                "description": "Execute a Cypher query against the Neo4j Code Property Graph to find ACTUAL code entities",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Cypher query to execute"
                        }
                    },
                    "required": ["query"]
                }
            }
        })
        self._tool_map['neo4j_execute_query'] = ('mcp', 'neo4j_execute_query')

        # Neo4j version detection tool - helps agents use correct Cypher syntax
        self._tools.append({
            "type": "function",
            "function": {
                "name": "neo4j_get_version",
                "description": "Get Neo4j database version and Cypher syntax guidance. Call this when writing queries with pattern counting or subqueries to ensure correct syntax.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        })
        self._tool_map['neo4j_get_version'] = ('mcp', 'neo4j_get_version')

        # Schema tools
        lc_tools = create_schema_tools(self._schema_manager)
        for tool in lc_tools:
            self._langchain_tools[tool.name] = tool
            schema = tool.args_schema.schema() if hasattr(tool, 'args_schema') else {"type": "object", "properties": {}}
            self._tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": schema
                }
            })
            self._tool_map[tool.name] = ('langchain', tool.name)

    @property
    def tools(self) -> List[Dict]:
        """Get the list of tool definitions"""
        return self._tools

    async def execute_tool(self, name: str, arguments: Dict) -> str:
        """
        Execute a tool by name with security validation and timeout/retry for MCP calls.

        Args:
            name: Tool name to execute
            arguments: Arguments to pass to the tool

        Returns:
            JSON string with the tool result

        Raises:
            ToolExecutionError: If tool is unknown
            CypherSecurityError: If query fails security validation
        """
        tool_info = self._tool_map.get(name)
        if tool_info is None:
            raise ToolExecutionError(f"Unknown tool: {name}")

        tool_type, tool_name = tool_info

        # SECURITY: Validate Cypher queries before execution
        if tool_name == 'neo4j_execute_query' and 'query' in arguments:
            query = arguments.get('query', '')
            try:
                self._query_validator.validate_or_raise(query)
            except CypherSecurityError as e:
                self._logger.warning(f"BLOCKED dangerous query: {query[:100]}...")
                return json.dumps({
                    "error": str(e),
                    "security_violation": True,
                    "blocked_query": query[:50] + "..." if len(query) > 50 else query
                })

        try:
            if tool_type == 'mcp':
                return await self._execute_mcp_tool(tool_name, arguments)
            elif tool_type == 'langchain':
                return await self._execute_langchain_tool(tool_name, arguments)

            return json.dumps({"error": f"Unknown tool type: {tool_type}"})

        except CypherSecurityError:
            raise  # Re-raise security errors
        except Exception as e:
            self._logger.error(f"Tool execution error ({name}): {e}")
            return json.dumps({"error": str(e)})

    async def _execute_mcp_tool(self, tool_name: str, arguments: Dict) -> str:
        """Execute an MCP tool with timeout and retry"""
        max_mcp_retries = 3
        mcp_timeout_seconds = 60  # 60 second timeout per attempt
        last_error = None

        query_start_time = time.time()
        for attempt in range(max_mcp_retries):
            try:
                result = await asyncio.wait_for(
                    self._session.call_tool(tool_name, arguments),
                    timeout=mcp_timeout_seconds
                )
                if hasattr(result, 'content') and result.content:
                    response_text = result.content[0].text

                    # Check for Cypher syntax errors in the response and propagate them clearly
                    if tool_name == 'neo4j_execute_query':
                        response_text = self._handle_cypher_response(response_text, arguments.get('query', ''))

                        # OBSERVER: Record this query execution (non-blocking)
                        if self._observer:
                            try:
                                execution_time_ms = int((time.time() - query_start_time) * 1000)
                                self._observer.observe_query(
                                    cypher_query=arguments.get('query', ''),
                                    result=response_text,
                                    agent_id=self._agent_id,
                                    sub_query=self._current_sub_query,
                                    execution_time_ms=execution_time_ms
                                )
                            except Exception as obs_err:
                                # Never let observer errors affect main workflow
                                self._logger.debug(f"Observer error (non-critical): {obs_err}")

                    return response_text
                return json.dumps({"error": "Empty MCP response"})

            except asyncio.TimeoutError as e:
                last_error = e
                self._logger.warning(f"MCP tool call timeout (attempt {attempt + 1}/{max_mcp_retries}): {tool_name}")
                if attempt < max_mcp_retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))  # Backoff
                    continue
            except Exception as e:
                # Catch connection errors and retry
                error_str = str(e).lower()
                if 'connection' in error_str or 'sse' in error_str or 'post_writer' in error_str:
                    last_error = e
                    self._logger.warning(f"MCP connection error (attempt {attempt + 1}/{max_mcp_retries}): {e}")
                    if attempt < max_mcp_retries - 1:
                        await asyncio.sleep(1.0 * (attempt + 1))  # Backoff
                        continue
                raise  # Non-connection errors should be raised immediately

        # All retries exhausted
        self._logger.error(f"MCP tool call failed after {max_mcp_retries} attempts: {last_error}")
        return json.dumps({"error": f"MCP call failed after {max_mcp_retries} retries: {last_error}"})

    async def _execute_langchain_tool(self, tool_name: str, arguments: Dict) -> str:
        """Execute a LangChain tool"""
        lc_tool = self._langchain_tools.get(tool_name)
        if lc_tool:
            result = await lc_tool.ainvoke(arguments)
            return json.dumps(result) if isinstance(result, dict) else str(result)
        return json.dumps({"error": f"Unknown LangChain tool: {tool_name}"})

    def _handle_cypher_response(self, response_text: str, query: str) -> str:
        """
        Handle Cypher query response - log errors but propagate original response.
        The original error from Neo4j/MCP is passed through unchanged for transparency.
        """
        try:
            response_data = json.loads(response_text)

            # Log errors for debugging but propagate original response unchanged
            if 'error' in response_data:
                error_msg = response_data.get('error', '')
                self._logger.warning(f"Cypher query error: {error_msg}")
                self._logger.debug(f"Failed query: {query}")

        except json.JSONDecodeError:
            pass

        # Always return the original response - let the agent see the real error
        return response_text


__all__ = ['ToolManager']
