"""
Claude SDK Fallback Client.

Provides direct integration with Claude Agent SDK for fallback when
the primary LLM provider (OpenAI) is unavailable.

This bypasses the adapter server and uses ClaudeSDKClient directly,
connecting to MCP servers for tool access.

Integrates with existing guardrails:
- CypherQueryValidator: Blocks dangerous write operations
- InputPromptValidator: Blocks prompt injection attempts
- CPGObserverAgent: Tracks query execution for analysis
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Union, TYPE_CHECKING
from dataclasses import dataclass, field

from src.core.graph_rag.validators.cypher_validator import CypherQueryValidator
from src.core.graph_rag.validators.input_validator import InputPromptValidator
from src.core.graph_rag.core.exceptions import CypherSecurityError

if TYPE_CHECKING:
    from src.core.graph_rag.agents.cpg_observer import CPGObserverAgent
    from src.core.graph_rag.schema.dynamic_schema_manager import DynamicSchemaManager

logger = logging.getLogger(__name__)

# Claude Code's built-in tools that should be blocked by default
# We only want MCP tools to be used, not filesystem/shell access
CLAUDE_BUILTIN_TOOLS = frozenset([
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "LS",
    "MultiEdit",
    "NotebookRead",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
    "TodoRead",
    "TodoWrite",
    "Task",
])

# SDK-internal tools that should always be allowed (used by SDK itself)
SDK_INTERNAL_TOOLS = frozenset([
    "StructuredOutput",  # Used by SDK for structured output responses
    "ListMcpResourcesTool",  # Used by SDK for MCP discovery
    "ListMcpToolsTool",  # Used by SDK for MCP tool discovery
])


@dataclass
class ClaudeSDKResponse:
    """Response from Claude SDK formatted for compatibility with existing workflow."""

    content: str
    """The text response from Claude."""

    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    """Any tool calls made by Claude (for logging/audit)."""

    # model: str = "claude-sonnet-4-20250514"
    model: str = "claude-opus-4-6"
    """Model used for the response."""

    usage: Optional[Dict[str, Any]] = None
    """Token usage information."""

    cost_usd: Optional[float] = None
    """Cost of the request in USD."""

    session_id: Optional[str] = None
    """Claude SDK session ID for multi-turn conversations."""

    blocked_queries: List[str] = field(default_factory=list)
    """Queries that were blocked by security validation."""

    observed_queries: int = 0
    """Number of queries tracked by observer."""


class ClaudeSDKFallback:
    """
    Direct Claude SDK fallback client with full guardrails integration.

    Uses ClaudeSDKClient directly instead of going through an adapter server.
    Connects to MCP servers for tool access (neo4j, qdrant, etc.)

    Security Features:
    - CypherQueryValidator: Blocks CREATE, MERGE, DELETE, etc.
    - InputPromptValidator: Blocks prompt injection attempts
    - CPGObserverAgent: Tracks all query execution for analysis
    - Tool whitelist/blacklist support

    Usage:
        fallback = ClaudeSDKFallback(
            mcp_config_path="/path/to/mcp_config.json",
            system_prompt="You are a code analysis assistant...",
            strict_security=True
        )

        response = await fallback.query("What classes are in the codebase?")
        print(response.content)
    """

    def __init__(
        self,
        mcp_config_path: Optional[str] = None,
        mcp_servers: Optional[Dict[str, Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        # model: str = "claude-sonnet-4-20250514",
        model: str = "claude-opus-4-6",
        max_turns: int = 10,
        max_budget_usd: Optional[float] = None,
        allowed_tools: Optional[List[str]] = None,
        disallowed_tools: Optional[List[str]] = None,
        block_builtin_tools: bool = True,  # Block Claude's Bash, Read, Write, etc.
        pre_tool_hook: Optional[Callable] = None,
        post_tool_hook: Optional[Callable] = None,
        working_directory: Optional[str] = None,
        max_buffer_size: int = 10 * 1024 * 1024,  # 10MB default (SDK default is 1MB)
        # Security options
        strict_security: bool = True,
        validate_prompts: bool = True,
        validate_cypher: bool = True,
        # Observer integration
        observer: Optional['CPGObserverAgent'] = None,
        agent_id: str = "claude-sdk-fallback",
        # Schema context and in-process tools
        schema_manager: Optional['DynamicSchemaManager'] = None,
        mcp_session=None,  # MCP session for query execution
    ):
        """
        Initialize the Claude SDK fallback client.

        Args:
            mcp_config_path: Path to MCP config JSON file
            mcp_servers: MCP server configurations (alternative to config file)
            system_prompt: System prompt for Claude
            model: Claude model to use
            max_turns: Maximum agentic turns
            max_budget_usd: Maximum cost budget
            allowed_tools: Whitelist of allowed tools
            disallowed_tools: Blacklist of disallowed tools
            pre_tool_hook: Hook called before tool execution (for validation)
            post_tool_hook: Hook called after tool execution (for logging/audit)
            working_directory: Working directory for Claude operations
            max_buffer_size: Maximum JSON message buffer size in bytes (default 10MB)
            strict_security: If True, blocks dangerous operations; if False, only warns
            validate_prompts: If True, validates prompts for injection attacks
            validate_cypher: If True, validates Cypher queries for write operations
            observer: Optional CPG Observer for query tracking
            agent_id: Identifies this client for observer tracking
            schema_manager: Optional schema manager for context injection and in-process tools
            mcp_session: Optional MCP session for query execution via in-process tools
        """
        self._logger = logging.getLogger(f"{__name__}.ClaudeSDKFallback")

        # Security validators (create early - needed for tools server)
        self._strict_security = strict_security
        self._validate_prompts = validate_prompts
        self._validate_cypher = validate_cypher
        self._cypher_validator = CypherQueryValidator(strict_mode=strict_security)
        self._prompt_validator = InputPromptValidator(strict_mode=strict_security)

        # MCP configuration
        self._mcp_servers: Dict[str, Any] = {}
        if mcp_config_path:
            self._load_mcp_config(mcp_config_path)
        if mcp_servers:
            self._mcp_servers.update(mcp_servers)

        # Schema context and session for in-process tools
        self._schema_manager = schema_manager
        self._mcp_session = mcp_session
        self._inprocess_tools_server = None

        # Create in-process SDK tools server if schema_manager is provided
        # NOTE: Only schema tools are in-process (they use schema_manager directly).
        # MCP-dependent tools (neo4j_execute_query, fuzzy_search) must go through
        # external MCP servers configured via mcp_config_path or mcp_servers.
        if schema_manager:
            try:
                from src.core.graph_rag.core.sdk_tools import create_sdk_tools_server, get_schema_tool_names

                self._inprocess_tools_server = create_sdk_tools_server(
                    schema_manager=schema_manager,
                    name="schema_tools",
                    version="1.0.0"
                )

                # Add in-process tools server alongside external MCP servers
                # - External MCP server (neo4j_memory): Direct Neo4j access for query execution
                # - In-process tools (schema_tools): Schema discovery tools only
                self._mcp_servers["schema_tools"] = self._inprocess_tools_server

                # Get the in-process schema tool names
                inprocess_tool_names = get_schema_tool_names(server_name="schema_tools")

                self._logger.info(
                    f"Created in-process SDK tools server with {len(inprocess_tool_names)} tools: "
                    f"{', '.join(inprocess_tool_names[:5])}..."
                )

                # Add external MCP server tool names to allowed_tools
                # This ensures Claude can use both schema tools AND neo4j query tools
                external_mcp_tools = []
                for server_name in self._mcp_servers.keys():
                    if server_name != "cpg_tools":  # Skip in-process server
                        # Add common neo4j_memory tools
                        external_mcp_tools.extend([
                            f"mcp__{server_name}__neo4j_execute_query",
                            f"mcp__{server_name}__neo4j_fuzzy_search",
                            f"mcp__{server_name}__resolve_symbol",
                            f"mcp__{server_name}__neo4j_search_code",
                        ])

                # Combine in-process and external MCP tool names
                all_allowed_tools = inprocess_tool_names + external_mcp_tools

                # Override allowed_tools if not explicitly provided
                if not allowed_tools:
                    allowed_tools = all_allowed_tools
                    self._logger.info(f"Set allowed_tools to {len(allowed_tools)} tools (in-process + external MCP)")

            except Exception as e:
                self._logger.warning(f"Failed to create in-process SDK tools server: {e}")
                # Fall back to using external MCP servers

        # Claude SDK options
        self._system_prompt = system_prompt
        self._model = model
        self._max_turns = max_turns
        self._max_budget_usd = max_budget_usd
        self._allowed_tools = allowed_tools or []
        self._working_directory = working_directory or str(Path.cwd())
        self._max_buffer_size = max_buffer_size

        # Build disallowed tools list - optionally include Claude's built-in tools
        self._block_builtin_tools = block_builtin_tools
        self._disallowed_tools = list(disallowed_tools or [])
        if block_builtin_tools:
            # Add all Claude built-in tools to disallowed list
            self._disallowed_tools.extend(CLAUDE_BUILTIN_TOOLS)
            self._logger.info(
                f"Blocking {len(CLAUDE_BUILTIN_TOOLS)} Claude built-in tools: "
                f"{', '.join(sorted(CLAUDE_BUILTIN_TOOLS))}"
            )

        # User-provided hooks
        self._user_pre_tool_hook = pre_tool_hook
        self._user_post_tool_hook = post_tool_hook

        # Observer integration
        self._observer = observer
        self._agent_id = agent_id
        self._current_sub_query: Optional[str] = None

        # Track tool calls and blocked queries for audit
        self._tool_calls_log: List[Dict[str, Any]] = []
        self._blocked_queries: List[str] = []
        self._observed_query_count: int = 0

        self._logger.info(
            f"ClaudeSDKFallback initialized with {len(self._mcp_servers)} MCP servers, "
            f"strict_security={strict_security}, validate_cypher={validate_cypher}, "
            f"in_process_tools={self._inprocess_tools_server is not None}"
        )

    def _load_mcp_config(self, config_path: str) -> None:
        """Load MCP server configuration from JSON file."""
        try:
            path = Path(config_path)
            if not path.exists():
                self._logger.warning(f"MCP config file not found: {config_path}")
                return

            with open(path) as f:
                config = json.load(f)

            # Handle both formats: {"mcpServers": {...}} and direct {...}
            if "mcpServers" in config:
                self._mcp_servers = config["mcpServers"]
            else:
                self._mcp_servers = config

            self._logger.info(
                f"Loaded MCP config with servers: {list(self._mcp_servers.keys())}"
            )
        except Exception as e:
            self._logger.error(f"Failed to load MCP config: {e}")

    def add_mcp_server(self, name: str, config: Dict[str, Any]) -> None:
        """Add an MCP server configuration."""
        self._mcp_servers[name] = config
        self._logger.info(f"Added MCP server: {name}")

    def remove_mcp_server(self, name: str) -> None:
        """Remove an MCP server configuration."""
        if name in self._mcp_servers:
            del self._mcp_servers[name]
            self._logger.info(f"Removed MCP server: {name}")

    def set_allowed_tools(self, tools: List[str]) -> None:
        """Set the list of allowed tools."""
        self._allowed_tools = tools

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt."""
        self._system_prompt = prompt

    def set_context(self, agent_id: str = None, sub_query: str = None) -> None:
        """Set context for observation tracking."""
        if agent_id:
            self._agent_id = agent_id
        if sub_query:
            self._current_sub_query = sub_query

    def set_observer(self, observer: 'CPGObserverAgent') -> None:
        """Set the CPG observer for query tracking."""
        self._observer = observer

    def set_schema_manager(self, schema_manager: 'DynamicSchemaManager') -> None:
        """Set the schema manager for context injection."""
        self._schema_manager = schema_manager

    def _build_system_prompt_with_context(self, base_prompt: Optional[str]) -> str:
        """Build system prompt with schema context and tool guidance."""
        parts = []

        if base_prompt:
            parts.append(base_prompt)

        # Add explicit tool guidance when in-process tools are available
        if self._inprocess_tools_server and self._allowed_tools:
            tool_list = ", ".join(self._allowed_tools[:7])
            parts.append(
                "\n\n## CRITICAL: TOOL RESTRICTIONS\n"
                "**YOU ARE OPERATING IN A RESTRICTED ENVIRONMENT.**\n\n"
                "ALLOWED tools (use ONLY these):\n"
                f"  {tool_list}\n\n"
                "Tool purposes:\n"
                "- mcp__cpg_tools__get_node_labels: List node types in code graph\n"
                "- mcp__cpg_tools__get_node_properties: Get properties for a node type\n"
                "- mcp__cpg_tools__get_valid_pairs: Get valid relationship patterns\n"
                "- mcp__cpg_tools__get_schema_overview: Get high-level schema overview\n"
                "- mcp__cpg_tools__neo4j_execute_query: Execute Cypher queries\n"
                "- mcp__cpg_tools__neo4j_fuzzy_search: Search for code entities by name\n"
                "- mcp__neo4j_memory__neo4j_execute_query: Execute Cypher queries (external)\n\n"
                "**FORBIDDEN - WILL BE BLOCKED:**\n"
                "- Bash, Read, Write, Glob, Grep, Edit, LS, Task, TodoWrite, TodoRead\n"
                "- WebFetch, WebSearch, NotebookEdit, NotebookRead, MultiEdit\n"
                "- ANY file system operations\n\n"
                "**DO NOT ATTEMPT TO USE FORBIDDEN TOOLS.** They WILL fail. "
                "If a CPG tool returns an error, try a different CPG tool or query, NOT a filesystem tool."
            )

        # Add schema context if available
        if self._schema_manager:
            try:
                schema_summary = self._get_schema_summary()
                if schema_summary:
                    parts.append("\n\n## Available Schema\n" + schema_summary)
            except Exception as e:
                self._logger.debug(f"Could not get schema summary: {e}")

        # Add security reminders
        parts.append(
            "\n\n## IMPORTANT SECURITY RULES\n"
            "- You are in READ-ONLY mode. DO NOT attempt CREATE, MERGE, SET, DELETE, or REMOVE operations.\n"
            "- All Cypher queries must be read-only (MATCH, RETURN, WITH, WHERE, etc.).\n"
            "- If you need to modify data, inform the user that write operations are not allowed.\n"
            "- Keep query results focused - use LIMIT clauses to avoid returning excessive data."
        )

        return "\n".join(parts)

    def _get_schema_summary(self) -> str:
        """Get a summary of the schema for context."""
        if not self._schema_manager:
            return ""

        try:
            node_types = list(self._schema_manager._node_properties.keys())
            rel_types = list(self._schema_manager._relationship_properties.keys())

            summary = f"Node types: {', '.join(node_types[:15])}"
            if len(node_types) > 15:
                summary += f" (and {len(node_types) - 15} more)"

            summary += f"\nRelationship types: {', '.join(rel_types[:10])}"
            if len(rel_types) > 10:
                summary += f" (and {len(rel_types) - 10} more)"

            return summary
        except Exception:
            return ""

    def _validate_prompt(self, prompt: str) -> None:
        """Validate prompt for injection attacks."""
        if not self._validate_prompts:
            return

        try:
            self._prompt_validator.validate_or_raise(prompt)
        except CypherSecurityError as e:
            self._logger.warning(f"Prompt blocked by security validator: {e}")
            raise

    def _validate_cypher_query(self, query: str) -> bool:
        """
        Validate a Cypher query for security.

        Returns True if query is safe, False if blocked.
        """
        if not self._validate_cypher:
            return True

        is_safe, error_message = self._cypher_validator.validate(query)
        if not is_safe:
            self._logger.warning(f"Cypher query blocked: {error_message}")
            self._logger.debug(f"Blocked query: {query[:200]}...")
            self._blocked_queries.append(query[:100])
            return False

        return True

    def _observe_query(
        self,
        cypher_query: str,
        result: str,
        execution_time_ms: int,
        had_error: bool = False,
        error_message: Optional[str] = None
    ) -> None:
        """Record a query execution with the observer."""
        if not self._observer:
            return

        try:
            self._observer.observe_query(
                cypher_query=cypher_query,
                result=result,
                agent_id=self._agent_id,
                sub_query=self._current_sub_query,
                execution_time_ms=execution_time_ms,
                had_error=had_error,
                error_message=error_message
            )
            self._observed_query_count += 1
        except Exception as e:
            # Never let observer errors affect main workflow
            self._logger.debug(f"Observer error (non-critical): {e}")

    def _build_json_instructions(self, response_format: Optional[Dict[str, Any]]) -> str:
        """
        Build JSON output instructions to add to the system prompt.

        The detailed schema is already in the agent's prompt, so this provides
        clear instructions for Claude to output JSON after gathering information.
        """
        if not response_format:
            return ""

        format_type = response_format.get("type", "text")

        if format_type in ("json_object", "json_schema"):
            return (
                "\n\n## CRITICAL: JSON OUTPUT REQUIRED\n"
                "Your final response MUST be a valid JSON object. Follow these rules:\n"
                "1. You may use tools to gather information first\n"
                "2. After gathering information, you MUST output the JSON result as text\n"
                "3. Do NOT finish with only tool calls - you MUST output JSON text at the end\n"
                "4. Output pure JSON only - no markdown code blocks, no explanations\n"
                "5. The JSON must match the format specified in the task\n\n"
                "IMPORTANT: Your response is not complete until you output the JSON object as text."
            )

        return ""

    def _extract_json_from_response(self, text: str) -> Optional[str]:
        """
        Try to extract JSON from response text that may contain other content.

        Returns the JSON string if found, or None if no valid JSON found.
        """
        import re

        if not text or not text.strip():
            return None

        text = text.strip()

        # First, try the whole text as JSON
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in text
        # Look for patterns like {...} that span multiple lines
        json_patterns = [
            r'(\{[\s\S]*\})',  # Match { ... } including newlines
            r'```json\s*([\s\S]*?)\s*```',  # Markdown code block
            r'```\s*([\s\S]*?)\s*```',  # Generic code block
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    json.loads(match)
                    return match
                except json.JSONDecodeError:
                    continue

        return None

    def _build_output_format(self, response_format: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Build native output_format dict for ClaudeAgentOptions from response_format.

        Converts OpenAI-style response_format to Claude SDK's output_format parameter.
        Returns a dict compatible with Claude Agent SDK's output_format parameter,
        or None if no structured output is needed.

        Claude SDK output_format expects:
        {
            "type": "json_schema",
            "schema": {...}  # Direct schema, not wrapped in json_schema
        }

        Note: OpenAI uses {"type": "json_schema", "json_schema": {"name": ..., "schema": ...}}
        but Claude SDK uses {"type": "json_schema", "schema": ...} directly.
        """
        if not response_format:
            return None

        format_type = response_format.get("type", "text")

        if format_type == "text":
            return None

        if format_type == "json_object":
            # For json_object without a specific schema, DON'T use SDK's structured output.
            # The minimal {"type": "object"} schema causes Claude to call StructuredOutput
            # tool with the schema itself as the data, not the actual JSON content.
            # Instead, rely on JSON instructions in the prompt - Claude will output JSON as text.
            self._logger.info("Enabling JSON output mode (json_object via prompt, not SDK StructuredOutput)")
            return None

        if format_type == "json_schema":
            json_schema = response_format.get("json_schema", {})
            schema = json_schema.get("schema", {})
            name = json_schema.get("name", "structured_response")
            if schema:
                self._logger.info(f"Enabling JSON output mode (json_schema: {name})")
                # Claude SDK expects schema directly, not wrapped in json_schema object
                return {
                    "type": "json_schema",
                    "schema": schema
                }

        return None

    async def query(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_turns: Optional[int] = None,
        session_id: Optional[str] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> ClaudeSDKResponse:
        """
        Send a query to Claude via the SDK with full security validation.

        Args:
            prompt: The user's query/prompt
            system_prompt: Override system prompt for this query
            max_turns: Override max turns for this query
            session_id: Resume a previous session
            response_format: OpenAI-style response format (e.g., {"type": "json_object"})

        Returns:
            ClaudeSDKResponse with the response content and metadata

        Raises:
            CypherSecurityError: If prompt fails security validation
        """
        # Reset tracking for this query
        self._tool_calls_log = []
        self._blocked_queries = []
        self._observed_query_count = 0

        # Validate prompt for injection attacks
        self._validate_prompt(prompt)

        # Check if JSON output is requested
        wants_json = response_format and response_format.get("type") in ("json_object", "json_schema")

        try:
            from claude_agent_sdk import (
                ClaudeSDKClient,
                ClaudeAgentOptions,
                AssistantMessage,
                ResultMessage,
                TextBlock,
                ToolUseBlock,
                ToolResultBlock,
                HookMatcher,
            )
            from claude_agent_sdk.types import SyncHookJSONOutput
        except ImportError as e:
            self._logger.error(f"claude_agent_sdk not installed: {e}")
            raise RuntimeError(
                "claude_agent_sdk is required for Claude SDK fallback. "
                "Install with: pip install claude-agent-sdk"
            ) from e

        # Build hooks with security validation
        hooks = self._build_hooks_with_security(HookMatcher, SyncHookJSONOutput)

        # Build system prompt with context and JSON instructions if needed
        effective_system_prompt = self._build_system_prompt_with_context(
            system_prompt or self._system_prompt
        )

        # Add JSON output instructions if structured output is requested
        if wants_json:
            json_instructions = self._build_json_instructions(response_format)
            if json_instructions:
                effective_system_prompt = (effective_system_prompt or "") + json_instructions

        # Build output format for structured JSON responses
        output_format = self._build_output_format(response_format)

        # Build options
        options_kwargs = {
            "model": self._model,
            "system_prompt": effective_system_prompt,
            "mcp_servers": self._mcp_servers if self._mcp_servers else None,
            "allowed_tools": self._allowed_tools if self._allowed_tools else None,
            "disallowed_tools": self._disallowed_tools if self._disallowed_tools else None,
            "max_turns": max_turns or self._max_turns,
            "max_budget_usd": self._max_budget_usd,
            "cwd": self._working_directory,
            "hooks": hooks if hooks else None,
            "max_buffer_size": self._max_buffer_size,
        }

        # Honour CLAUDE_CLI_PATH so an authenticated wrapper is used instead of the
        # bundled ELF binary (which may not be logged in in service/systemd contexts).
        # The SDK checks for its bundled ELF binary before honoring cli_path, so we
        # patch _find_bundled_cli to return None, forcing it to fall through to cli_path.
        _cli_path = os.environ.get("CLAUDE_CLI_PATH")
        if _cli_path:
            options_kwargs["cli_path"] = _cli_path
            try:
                from claude_agent_sdk._internal.transport import subprocess_cli
                subprocess_cli.SubprocessCLITransport._find_bundled_cli = lambda self: None
            except Exception:
                pass

        # Add output_format if JSON response is requested
        if output_format:
            options_kwargs["output_format"] = output_format

        options = ClaudeAgentOptions(**options_kwargs)

        self._logger.info(f"Querying Claude SDK with prompt: {prompt[:100]}...")

        response_text = ""
        tool_calls = []
        result_message = None

        try:
            async with ClaudeSDKClient(options=options) as client:
                # Resume session if provided
                if session_id:
                    await client.query(prompt, session_id=session_id)
                else:
                    await client.query(prompt)

                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                # When JSON is expected, skip narrative text blocks
                                # Claude often outputs "Let me search...", "Now let me..." etc.
                                # which should not be included in JSON responses
                                if wants_json:
                                    text = block.text.strip()
                                    # Only accumulate text that looks like JSON
                                    if text.startswith('{') or text.startswith('['):
                                        response_text += block.text
                                    elif '{' in text or '[' in text:
                                        # Text contains JSON somewhere, keep it for extraction
                                        response_text += block.text
                                    else:
                                        # Skip narrative text when JSON is expected
                                        self._logger.debug(f"Skipping non-JSON text block: {text[:50]}...")
                                else:
                                    response_text += block.text
                            elif isinstance(block, ToolUseBlock):
                                tool_calls.append({
                                    "id": block.id,
                                    "name": block.name,
                                    "input": block.input
                                })
                                # Log tool use as it happens
                                self._logger.debug(f"Tool use detected: {block.name} (id: {block.id})")
                            elif isinstance(block, ToolResultBlock):
                                # Log tool results for audit
                                self._tool_calls_log.append({
                                    "tool_use_id": block.tool_use_id,
                                    "content": block.content[:500] if block.content else None,
                                    "is_error": block.is_error
                                })

                    elif isinstance(message, ResultMessage):
                        result_message = message
                        # Check for structured output (native SDK support for JSON responses)
                        if hasattr(message, 'structured_output') and message.structured_output is not None:
                            # Use structured output as the response (guaranteed valid JSON)
                            response_text = json.dumps(message.structured_output)
                            self._logger.info("Using native structured_output from SDK (JSON)")
                        elif wants_json:
                            # Log why structured_output wasn't used
                            has_attr = hasattr(message, 'structured_output')
                            value = getattr(message, 'structured_output', 'N/A') if has_attr else 'N/A'
                            self._logger.debug(
                                f"structured_output not available: has_attr={has_attr}, value={value}"
                            )

            # If JSON output was requested but no structured_output, try to extract JSON
            if wants_json and response_text:
                extracted_json = self._extract_json_from_response(response_text)
                if extracted_json:
                    self._logger.info("Extracted JSON from response text")
                    response_text = extracted_json
                else:
                    self._logger.warning("JSON output requested but could not extract valid JSON from response")

            # Handle case where JSON was expected but response is empty after tool calls
            # This happens when Claude makes tool calls but doesn't produce a final JSON answer
            if wants_json and not response_text and tool_calls:
                self._logger.info(
                    "JSON output requested but response is empty after tool calls. "
                    "Prompting for final JSON response..."
                )
                # Need to create a new client for the follow-up since the original connection is closed
                follow_up_session_id = result_message.session_id if result_message else None
                self._logger.info(f"Follow-up needed - session_id={follow_up_session_id}, tool_calls={len(self._tool_calls_log)}")

                try:
                    # Use the SAME options as the original query to preserve conversation context
                    # CRITICAL: Use 'resume' parameter in options for session resumption (not session_id in query)
                    follow_up_system_prompt = (
                        (effective_system_prompt or "") +
                        "\n\n## CRITICAL: OUTPUT YOUR ANSWER NOW\n"
                        "You have gathered all necessary information. Now you MUST output your final answer "
                        "as a valid JSON object. Do NOT make any more tool calls. "
                        "Output ONLY the JSON, nothing else."
                    )

                    follow_up_options_kwargs = {
                        "model": self._model,
                        "system_prompt": follow_up_system_prompt,
                        "mcp_servers": self._mcp_servers if self._mcp_servers else None,
                        "allowed_tools": self._allowed_tools if self._allowed_tools else None,
                        "disallowed_tools": self._disallowed_tools if self._disallowed_tools else None,
                        "max_turns": 1,  # Single turn to force immediate output
                        "max_budget_usd": self._max_budget_usd,
                        "cwd": self._working_directory,
                        "hooks": hooks if hooks else None,
                        "max_buffer_size": self._max_buffer_size,
                    }

                    # CRITICAL: Use 'resume' parameter for session resumption
                    # This is how PerAgentSDKClient does it and it works
                    if follow_up_session_id:
                        follow_up_options_kwargs["resume"] = follow_up_session_id

                    if _cli_path:
                        follow_up_options_kwargs["cli_path"] = _cli_path

                    follow_up_options = ClaudeAgentOptions(**follow_up_options_kwargs)

                    # Build follow-up prompt - simpler now since session should have context
                    follow_up_prompt = (
                        "Based on all the information you gathered from your tool calls, "
                        "provide your final answer NOW as a valid JSON object. "
                        "Do NOT make any more tool calls - just output the JSON directly. "
                        "The JSON must match the format specified in the system prompt."
                    )

                    self._logger.info(f"Sending follow-up query with resume={follow_up_session_id}")

                    async with ClaudeSDKClient(options=follow_up_options) as follow_up_client:
                        await follow_up_client.query(follow_up_prompt)

                        async for message in follow_up_client.receive_response():
                            if isinstance(message, AssistantMessage):
                                for block in message.content:
                                    if isinstance(block, TextBlock):
                                        # Capture all text since we're forcing JSON output
                                        response_text += block.text
                            elif isinstance(message, ResultMessage):
                                result_message = message
                                if hasattr(message, 'structured_output') and message.structured_output is not None:
                                    response_text = json.dumps(message.structured_output)
                                    self._logger.info("Using native structured_output from follow-up query")

                    # Try to extract JSON from the follow-up response
                    if response_text:
                        extracted_json = self._extract_json_from_response(response_text)
                        if extracted_json:
                            self._logger.info(f"Extracted JSON from follow-up response ({len(extracted_json)} chars)")
                            response_text = extracted_json
                        else:
                            self._logger.warning(f"Could not extract JSON from follow-up response: {response_text[:200]}...")
                    else:
                        self._logger.warning("Follow-up response was empty")
                except Exception as e:
                    self._logger.warning(f"Follow-up query for JSON response failed: {e}")

            # Build response
            response = ClaudeSDKResponse(
                content=response_text,
                tool_calls=tool_calls,
                model=self._model,
                usage=result_message.usage if result_message else None,
                cost_usd=result_message.total_cost_usd if result_message else None,
                session_id=result_message.session_id if result_message else None,
                blocked_queries=self._blocked_queries.copy(),
                observed_queries=self._observed_query_count,
            )

            self._logger.info(
                f"Claude SDK response received: {len(response_text)} chars, "
                f"{len(tool_calls)} tool calls, {len(self._blocked_queries)} blocked queries"
            )

            # Log summary of all tool calls made
            if tool_calls:
                self._logger.info("📋 Tool calls summary:")
                for i, tc in enumerate(tool_calls, 1):
                    self._logger.info(f"   {i}. {tc['name']}")

            return response

        except Exception as e:
            self._logger.error(f"Claude SDK query failed: {e}")
            raise

    def _build_hooks_with_security(self, HookMatcher, SyncHookJSONOutput) -> Dict:
        """Build hook configuration with security validation integrated."""
        hooks = {}

        # Pre-tool hook with Cypher validation
        async def pre_tool_hook_with_security(hook_input, tool_use_id, context):
            tool_name = hook_input.get("tool_name", "")
            tool_input = hook_input.get("tool_input", {})

            # Log tool call details
            self._logger.info(f"🔧 TOOL CALL: {tool_name}")
            if tool_input:
                # Pretty print tool input, truncate if too long
                input_str = json.dumps(tool_input, indent=2)
                if len(input_str) > 500:
                    input_str = input_str[:500] + "... (truncated)"
                self._logger.info(f"   Input: {input_str}")

            # Always allow SDK internal tools (StructuredOutput, ListMcpResourcesTool, etc.)
            if tool_name in SDK_INTERNAL_TOOLS:
                self._logger.debug(f"   ✅ ALLOWED: SDK internal tool '{tool_name}'")
                return SyncHookJSONOutput(continue_=True)

            # BLOCK built-in tools (Bash, Read, Write, Glob, etc.)
            # This is the active enforcement since allowed_tools/disallowed_tools may not work
            if self._block_builtin_tools and tool_name in CLAUDE_BUILTIN_TOOLS:
                self._logger.warning(
                    f"   🚫 BLOCKED: Built-in tool '{tool_name}' is not permitted. "
                    f"Only MCP tools are allowed."
                )
                # Use SyncHookJSONOutput with hookSpecificOutput for proper blocking
                return SyncHookJSONOutput(
                    continue_=True,  # Continue conversation but deny the tool
                    hookSpecificOutput={
                        'hookEventName': 'PreToolUse',
                        'permissionDecision': 'deny',
                        'permissionDecisionReason': f"Built-in tool '{tool_name}' is blocked. Use MCP tools (neo4j_memory or cpg_tools) to query the code property graph instead."
                    }
                )

            # Validate Cypher queries before execution
            if tool_name in ("neo4j_execute_query", "mcp__neo4j_memory__neo4j_execute_query"):
                query = tool_input.get("query", "")
                if query:
                    if not self._validate_cypher_query(query):
                        # Block the dangerous query
                        self._logger.warning(f"   ❌ BLOCKED: Query contains write operations")
                        return SyncHookJSONOutput(
                            continue_=True,
                            hookSpecificOutput={
                                'hookEventName': 'PreToolUse',
                                'permissionDecision': 'deny',
                                'permissionDecisionReason': "Query contains write operations which are not allowed in read-only mode."
                            }
                        )
                    else:
                        self._logger.info(f"   ✅ Query validated (read-only)")

            # Call user's pre-tool hook if provided
            if self._user_pre_tool_hook:
                try:
                    result = self._user_pre_tool_hook(tool_name, tool_input)
                    if result is False:
                        return SyncHookJSONOutput(
                            continue_=True,
                            hookSpecificOutput={
                                'hookEventName': 'PreToolUse',
                                'permissionDecision': 'deny',
                                'permissionDecisionReason': "Blocked by custom pre-tool validation hook"
                            }
                        )
                except Exception as e:
                    self._logger.error(f"User pre-tool hook error: {e}")

            # Allow the tool call - return SyncHookJSONOutput to continue
            # Note: returning None causes "'NoneType' object has no attribute 'items'" error
            return SyncHookJSONOutput(continue_=True)

        hooks["PreToolUse"] = [
            HookMatcher(matcher=".*", hooks=[pre_tool_hook_with_security])
        ]

        # Post-tool hook with observer integration
        async def post_tool_hook_with_observer(hook_input, tool_use_id, context):
            tool_name = hook_input.get("tool_name", "")
            tool_input = hook_input.get("tool_input", {})
            tool_response = hook_input.get("tool_response", [])

            # Log tool response summary
            response_str = str(tool_response)
            response_len = len(response_str)
            if response_len > 300:
                response_preview = response_str[:300] + f"... ({response_len} chars total)"
            else:
                response_preview = response_str
            self._logger.info(f"   📤 Response: {response_preview}")

            # Capture tool response for potential follow-up prompt context
            # This ensures we have tool results if session resumption fails
            if tool_response:
                # Extract text content from response
                content = ""
                if isinstance(tool_response, list):
                    for item in tool_response:
                        if isinstance(item, dict) and 'text' in item:
                            content += item['text']
                elif isinstance(tool_response, str):
                    content = tool_response
                else:
                    content = str(tool_response)

                self._tool_calls_log.append({
                    "tool_name": tool_name,
                    "content": content if content else None,  # No truncation - let context window errors guide us
                    "is_error": "error" in content.lower() if content else False
                })

            # Track query execution with observer
            if tool_name in ("neo4j_execute_query", "mcp__neo4j_memory__neo4j_execute_query"):
                query = tool_input.get("query", "")
                if query:
                    # Extract result summary
                    result_str = str(tool_response)[:1000] if tool_response else ""
                    had_error = "error" in result_str.lower()

                    self._observe_query(
                        cypher_query=query,
                        result=result_str,
                        execution_time_ms=0,  # Not available in hook
                        had_error=had_error
                    )

            # Call user's post-tool hook if provided
            if self._user_post_tool_hook:
                try:
                    self._user_post_tool_hook(tool_name, tool_input, tool_response)
                except Exception as e:
                    self._logger.error(f"User post-tool hook error: {e}")

            # Continue normally - return SyncHookJSONOutput
            return SyncHookJSONOutput(continue_=True)

        hooks["PostToolUse"] = [
            HookMatcher(matcher=".*", hooks=[post_tool_hook_with_observer])
        ]

        return hooks

    def query_sync(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_turns: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> ClaudeSDKResponse:
        """
        Synchronous wrapper for query().

        Handles both cases:
        1. No running event loop: uses asyncio.run()
        2. Running event loop: runs in a separate thread to avoid blocking

        Args:
            prompt: The user's query/prompt
            system_prompt: Override system prompt for this query
            max_turns: Override max turns for this query
            response_format: OpenAI-style response format (e.g., {"type": "json_object"})
        """
        try:
            # Check if there's already a running event loop
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop - safe to use asyncio.run()
            return asyncio.run(
                self.query(
                    prompt,
                    system_prompt=system_prompt,
                    max_turns=max_turns,
                    response_format=response_format
                )
            )

        # There's a running loop - run in a separate thread
        import concurrent.futures

        self._logger.debug("Running Claude SDK query in separate thread (async context detected)")

        def run_in_thread():
            """Run the async query in a new event loop in this thread."""
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(
                    self.query(
                        prompt,
                        system_prompt=system_prompt,
                        max_turns=max_turns,
                        response_format=response_format
                    )
                )
            finally:
                new_loop.close()

        # Use ThreadPoolExecutor to run in separate thread
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_thread)
            return future.result(timeout=300)  # 5 minute timeout

    def get_tool_calls_log(self) -> List[Dict[str, Any]]:
        """Get the log of tool calls from the last query."""
        return self._tool_calls_log.copy()

    def get_blocked_queries(self) -> List[str]:
        """Get queries that were blocked by security validation."""
        return self._blocked_queries.copy()

    @property
    def mcp_servers(self) -> Dict[str, Dict[str, Any]]:
        """Get configured MCP servers."""
        return self._mcp_servers.copy()

    @property
    def is_available(self) -> bool:
        """Check if Claude SDK is available."""
        try:
            import claude_agent_sdk
            return True
        except ImportError:
            return False


__all__ = ['ClaudeSDKFallback', 'ClaudeSDKResponse']
