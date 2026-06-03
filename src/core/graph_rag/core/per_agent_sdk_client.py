"""
Per-Agent Claude SDK Client with Session Management.

Provides session-based per-agent Claude SDK clients that:
1. Maintain separate sessions for each agent
2. Enforce per-agent tool restrictions
3. Preserve context across multiple queries within an agent session
4. Support session resumption and cleanup

This addresses the limitation where a shared SDK client loses per-agent
tool restrictions (documented in CLAUDE_SDK_INTEGRATION_CHALLENGES.md).

Usage:
    session_manager = AgentSessionManager()
    sdk_client = PerAgentSDKClient(
        mcp_config_path="/path/to/config.json",
        schema_manager=schema_manager,
        session_manager=session_manager
    )

    # Each agent gets its own session with its own tool restrictions
    response = await sdk_client.query(
        agent_id="ThinkerAgent",
        allowed_tools=ThinkerAgent.ALLOWED_TOOLS,
        prompt="Find all Function nodes..."
    )
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.graph_rag.schema.dynamic_schema_manager import DynamicSchemaManager
    from src.core.graph_rag.agents.cpg_observer import CPGObserverAgent

logger = logging.getLogger(__name__)


# Claude Code's built-in tools that should be blocked
CLAUDE_BUILTIN_TOOLS = frozenset([
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "LS", "MultiEdit",
    "NotebookRead", "NotebookEdit", "WebFetch", "WebSearch",
    "TodoRead", "TodoWrite", "Task",
])

# SDK-internal tools that should always be allowed (used by SDK itself)
SDK_INTERNAL_TOOLS = frozenset([
    "StructuredOutput",  # Used by SDK for structured output responses
    "ListMcpResourcesTool",  # Used by SDK for MCP discovery
    "ListMcpToolsTool",  # Used by SDK for MCP tool discovery
])


@dataclass
class AgentSession:
    """
    Represents a Claude SDK session for a specific agent.

    Each agent maintains its own session with:
    - Unique session_id (assigned by SDK on first query)
    - Agent-specific allowed tools
    - Query history and context preservation
    """
    agent_id: str
    session_id: Optional[str]  # None until first query returns
    allowed_tools: List[str]
    created_at: datetime
    last_used: datetime
    query_count: int = 0
    total_cost_usd: float = 0.0
    blocked_tool_attempts: int = 0

    def update_usage(self, cost: float = 0.0):
        """Update session usage statistics."""
        self.last_used = datetime.now()
        self.query_count += 1
        self.total_cost_usd += cost


class AgentSessionManager:
    """
    Manages Claude SDK sessions per agent.

    Key responsibilities:
    - Track session_id per agent for context preservation
    - Store agent-specific tool restrictions
    - Handle session lifecycle (create, resume, cleanup)
    - Provide metrics on session usage
    - Serialize SDK calls per-agent via locks (for parallel subquery safety)

    Thread-safe through asyncio.Lock.

    Parallel Safety:
    When multiple subqueries run in parallel, each may invoke the same agent
    (e.g., ThinkerAgent for SQ1 and SQ2). Claude SDK sessions are designed
    for sequential multi-turn conversations, not parallel requests. This
    manager provides per-agent locks to serialize SDK calls while still
    allowing context sharing across subqueries.
    """

    def __init__(self, max_age_seconds: int = 3600):
        """
        Initialize the session manager.

        Args:
            max_age_seconds: Maximum age for inactive sessions before cleanup (default: 1 hour)
        """
        self._sessions: Dict[str, AgentSession] = {}
        self._lock = asyncio.Lock()  # For session dict access
        self._agent_locks: Dict[str, asyncio.Lock] = {}  # Per-agent locks for SDK call serialization
        self._max_age_seconds = max_age_seconds
        self._logger = logging.getLogger(f"{__name__}.AgentSessionManager")

    async def get_session(
        self,
        agent_id: str,
        allowed_tools: List[str]
    ) -> Optional[str]:
        """
        Get session_id for an agent. Returns None for new sessions.

        If the agent doesn't have a session yet, one is created (without session_id,
        which will be set after the first query completes).

        Args:
            agent_id: Unique identifier for the agent (e.g., "ThinkerAgent")
            allowed_tools: List of tool names this agent is allowed to use

        Returns:
            session_id to resume existing session, or None for new session
        """
        async with self._lock:
            if agent_id not in self._sessions:
                # Create new session record
                self._sessions[agent_id] = AgentSession(
                    agent_id=agent_id,
                    session_id=None,
                    allowed_tools=allowed_tools,
                    created_at=datetime.now(),
                    last_used=datetime.now()
                )
                self._logger.info(
                    f"Created new session for agent '{agent_id}' with "
                    f"{len(allowed_tools)} allowed tools"
                )
                return None  # New session - no session_id to resume

            session = self._sessions[agent_id]
            session.last_used = datetime.now()

            # Check if tools have changed (shouldn't happen, but handle gracefully)
            if set(session.allowed_tools) != set(allowed_tools):
                self._logger.warning(
                    f"Agent '{agent_id}' tool config changed. "
                    f"Old: {len(session.allowed_tools)} tools, "
                    f"New: {len(allowed_tools)} tools. Creating new session."
                )
                # Create new session with updated tools
                session.session_id = None
                session.allowed_tools = allowed_tools
                session.query_count = 0
                return None

            self._logger.debug(
                f"Returning existing session for '{agent_id}': "
                f"session_id={session.session_id}, queries={session.query_count}"
            )
            return session.session_id

    async def update_session_id(
        self,
        agent_id: str,
        session_id: str,
        cost_usd: float = 0.0
    ):
        """
        Update session_id after first query completes.

        The SDK assigns a session_id when the first query is made.
        This method stores that ID for future session resumption.

        Args:
            agent_id: Agent identifier
            session_id: Session ID returned by SDK
            cost_usd: Cost of the query in USD
        """
        async with self._lock:
            if agent_id in self._sessions:
                session = self._sessions[agent_id]
                if session.session_id is None:
                    session.session_id = session_id
                    self._logger.info(
                        f"Session ID assigned for '{agent_id}': {session_id}"
                    )
                session.update_usage(cost_usd)

    async def record_blocked_tool(self, agent_id: str, tool_name: str):
        """Record when a tool is blocked for an agent."""
        async with self._lock:
            if agent_id in self._sessions:
                self._sessions[agent_id].blocked_tool_attempts += 1
                self._logger.debug(
                    f"Blocked tool '{tool_name}' for agent '{agent_id}'"
                )

    async def close_session(self, agent_id: str):
        """
        Close and remove a session for an agent.

        Args:
            agent_id: Agent identifier
        """
        async with self._lock:
            if agent_id in self._sessions:
                session = self._sessions[agent_id]
                self._logger.info(
                    f"Closing session for '{agent_id}': "
                    f"queries={session.query_count}, "
                    f"cost=${session.total_cost_usd:.4f}, "
                    f"blocked_tools={session.blocked_tool_attempts}"
                )
                del self._sessions[agent_id]

    async def cleanup_stale_sessions(self):
        """
        Remove sessions that haven't been used within max_age.

        Call periodically to prevent memory leaks from abandoned sessions.
        """
        async with self._lock:
            now = datetime.now()
            stale_agents = [
                agent_id for agent_id, session in self._sessions.items()
                if (now - session.last_used).total_seconds() > self._max_age_seconds
            ]

            for agent_id in stale_agents:
                session = self._sessions[agent_id]
                self._logger.info(
                    f"Cleaning up stale session for '{agent_id}' "
                    f"(last used: {session.last_used})"
                )
                del self._sessions[agent_id]

            if stale_agents:
                self._logger.info(
                    f"Cleaned up {len(stale_agents)} stale sessions"
                )

    async def close_all_sessions(self):
        """Close all active sessions. Call at workflow end."""
        async with self._lock:
            agent_ids = list(self._sessions.keys())

        for agent_id in agent_ids:
            await self.close_session(agent_id)

        self._logger.info("All agent sessions closed")

    async def get_session_stats(self) -> Dict[str, Any]:
        """
        Get statistics about all active sessions.

        Returns:
            Dictionary with session statistics per agent
        """
        async with self._lock:
            stats = {
                "total_sessions": len(self._sessions),
                "agents": {}
            }

            for agent_id, session in self._sessions.items():
                stats["agents"][agent_id] = {
                    "session_id": session.session_id,
                    "query_count": session.query_count,
                    "total_cost_usd": session.total_cost_usd,
                    "blocked_tool_attempts": session.blocked_tool_attempts,
                    "allowed_tools_count": len(session.allowed_tools),
                    "created_at": session.created_at.isoformat(),
                    "last_used": session.last_used.isoformat()
                }

            return stats

    def get_allowed_tools(self, agent_id: str) -> List[str]:
        """
        Get allowed tools for an agent (synchronous for hook usage).

        Returns empty list if agent not found.
        """
        if agent_id in self._sessions:
            return self._sessions[agent_id].allowed_tools.copy()
        return []

    async def get_agent_lock(self, agent_id: str) -> asyncio.Lock:
        """
        Get the lock for a specific agent.

        This lock should be acquired before making SDK calls to ensure
        serialized access to the agent's session. This is critical for
        parallel subquery execution where multiple subqueries may invoke
        the same agent type simultaneously.

        Usage:
            async with await session_manager.get_agent_lock("ThinkerAgent"):
                # SDK call here - serialized per agent
                response = await sdk_client.query(...)

        Args:
            agent_id: Agent identifier

        Returns:
            asyncio.Lock for the agent
        """
        async with self._lock:
            if agent_id not in self._agent_locks:
                self._agent_locks[agent_id] = asyncio.Lock()
                self._logger.debug(f"Created lock for agent '{agent_id}'")
            return self._agent_locks[agent_id]

    async def acquire_agent_lock(self, agent_id: str) -> None:
        """
        Acquire the lock for an agent (explicit acquire).

        Prefer using get_agent_lock() with async with for automatic release.
        """
        lock = await self.get_agent_lock(agent_id)
        await lock.acquire()
        self._logger.debug(f"Acquired lock for agent '{agent_id}'")

    def release_agent_lock(self, agent_id: str) -> None:
        """
        Release the lock for an agent (explicit release).

        Only call this if you used acquire_agent_lock().
        """
        if agent_id in self._agent_locks:
            try:
                self._agent_locks[agent_id].release()
                self._logger.debug(f"Released lock for agent '{agent_id}'")
            except RuntimeError:
                # Lock wasn't held
                pass


@dataclass
class PerAgentSDKResponse:
    """Response from per-agent SDK client."""
    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    # model: str = "claude-sonnet-4-20250514"
    model: str = "claude-opus-4-6"
    usage: Optional[Dict[str, Any]] = None
    cost_usd: float = 0.0
    session_id: Optional[str] = None
    agent_id: str = ""
    blocked_queries: List[str] = field(default_factory=list)
    blocked_tools: List[str] = field(default_factory=list)


class PerAgentSDKClient:
    """
    Claude SDK client with per-agent session management and tool restrictions.

    Each agent gets:
    - Its own session (context preserved across queries)
    - Its own tool whitelist (enforced via hooks)
    - Separate tracking/metrics

    This solves the problem of shared SDK clients losing per-agent tool restrictions.

    Usage:
        session_manager = AgentSessionManager()
        client = PerAgentSDKClient(
            mcp_config_path="/path/to/config.json",
            schema_manager=schema_manager,
            session_manager=session_manager
        )

        # ThinkerAgent query (uses in-process schema tools)
        response = await client.query(
            agent_id="ThinkerAgent",
            allowed_tools=["mcp__schema_tools__get_node_labels", ...],
            prompt="Find all classes...",
            system_prompt=THINKER_SYSTEM_PROMPT
        )

        # ExecutorAgent query (different session, different tools)
        response = await client.query(
            agent_id="ExecutorAgent",
            allowed_tools=["mcp__neo4j_memory__neo4j_execute_query", ...],
            prompt="Execute: MATCH (n:Function) RETURN n.name",
            system_prompt=EXECUTOR_SYSTEM_PROMPT
        )
    """

    def __init__(
        self,
        mcp_config_path: Optional[str] = None,
        mcp_servers: Optional[Dict[str, Any]] = None,
        schema_manager: Optional['DynamicSchemaManager'] = None,
        session_manager: Optional[AgentSessionManager] = None,
        # model: str = "claude-sonnet-4-20250514",
        model: str = "claude-opus-4-6",
        max_turns: int = 10,
        max_budget_usd: Optional[float] = None,
        block_builtin_tools: bool = True,
        strict_security: bool = True,
        validate_cypher: bool = True,
        observer: Optional['CPGObserverAgent'] = None,
        max_buffer_size: int = 10 * 1024 * 1024,
        allowed_mcp_servers: Optional[List[str]] = None,
    ):
        """
        Initialize the per-agent SDK client.

        Args:
            mcp_config_path: Path to MCP config JSON file
            mcp_servers: MCP server configurations
            schema_manager: Schema manager for context
            session_manager: Session manager (created if not provided)
            model: Claude model to use
            max_turns: Maximum agentic turns per query
            max_budget_usd: Maximum cost budget per query
            block_builtin_tools: Block Claude's built-in tools (Bash, Read, etc.)
            strict_security: Strict security mode
            validate_cypher: Validate Cypher queries for write operations
            observer: Optional CPG observer for query tracking
            max_buffer_size: Maximum JSON buffer size
            allowed_mcp_servers: Optional list of allowed MCP server names (e.g., ["neo4j_memory"])
        """
        self._logger = logging.getLogger(f"{__name__}.PerAgentSDKClient")

        # Session manager (create if not provided)
        self._session_manager = session_manager or AgentSessionManager()

        # MCP configuration with filtering
        self._mcp_servers: Dict[str, Any] = {}
        if mcp_config_path:
            self._load_mcp_config(mcp_config_path)
        if mcp_servers:
            self._mcp_servers.update(mcp_servers)

        # Apply MCP server filtering if specified
        if allowed_mcp_servers:
            original_servers = list(self._mcp_servers.keys())
            self._mcp_servers = {
                name: config
                for name, config in self._mcp_servers.items()
                if name in allowed_mcp_servers
            }
            if original_servers != list(self._mcp_servers.keys()):
                self._logger.info(
                    f"Filtered MCP servers: {original_servers} → {list(self._mcp_servers.keys())}"
                )

        # Create in-process schema tools if schema_manager is provided
        # These use schema_manager directly (synchronous Python) and work reliably
        # MCP-dependent tools (neo4j_execute_query, fuzzy_search) must go through
        # external MCP servers configured above
        self._inprocess_tools_server = None
        if schema_manager:
            self._create_inprocess_schema_tools(schema_manager)

        # SDK configuration
        self._schema_manager = schema_manager
        self._model = model
        self._max_turns = max_turns
        self._max_budget_usd = max_budget_usd
        self._block_builtin_tools = block_builtin_tools
        self._strict_security = strict_security
        self._validate_cypher = validate_cypher
        self._observer = observer
        self._max_buffer_size = max_buffer_size

        # Security validators
        from src.core.graph_rag.validators.cypher_validator import CypherQueryValidator
        self._cypher_validator = CypherQueryValidator(strict_mode=strict_security)

        # Track current agent context for hooks
        self._current_agent_id: Optional[str] = None
        self._current_allowed_tools: List[str] = []
        self._blocked_tools_log: List[str] = []

        self._logger.info(
            f"PerAgentSDKClient initialized with {len(self._mcp_servers)} MCP servers, "
            f"block_builtin_tools={block_builtin_tools}"
        )

    def _load_mcp_config(self, config_path: str) -> None:
        """Load MCP server configuration from JSON file."""
        try:
            path = Path(config_path)
            if not path.exists():
                self._logger.warning(f"MCP config not found: {config_path}")
                return

            with open(path) as f:
                config = json.load(f)

            if "mcpServers" in config:
                self._mcp_servers = config["mcpServers"]
            else:
                self._mcp_servers = config

            self._logger.info(f"Loaded MCP config: {list(self._mcp_servers.keys())}")
        except Exception as e:
            self._logger.error(f"Failed to load MCP config: {e}")

    def _create_inprocess_schema_tools(self, schema_manager) -> None:
        """
        Create in-process schema discovery tools.

        These tools use schema_manager directly (synchronous Python) and work
        reliably in the Claude SDK subprocess context. They provide agents
        with schema information without requiring external MCP calls.

        NOTE: MCP-dependent tools (neo4j_execute_query, neo4j_fuzzy_search)
        are NOT included here - they must go through external MCP servers.

        Args:
            schema_manager: DynamicSchemaManager instance for schema queries
        """
        try:
            from src.core.graph_rag.core.sdk_tools import create_sdk_tools_server

            self._inprocess_tools_server = create_sdk_tools_server(
                schema_manager=schema_manager,
                name="schema_tools",
                version="1.0.0"
            )

            # Add to MCP servers (alongside external servers like neo4j_memory)
            self._mcp_servers["schema_tools"] = self._inprocess_tools_server

            self._logger.info(
                "Created in-process schema tools server with tools: "
                "get_node_labels, get_valid_pairs, validate_relationship_triplet, "
                "get_node_properties, get_outgoing_relationships, get_incoming_relationships, "
                "get_schema_overview"
            )
        except Exception as e:
            self._logger.error(f"Failed to create in-process schema tools: {e}")

    def _create_tool_filter_hook(self, agent_id: str, allowed_tools: List[str]):
        """
        Create a pre-tool hook that enforces per-agent tool restrictions.

        This is the core enforcement mechanism since SDK's allowed_tools
        parameter is bugged (GitHub Issue #361).

        Args:
            agent_id: Agent identifier for logging
            allowed_tools: Tools this agent can use

        Returns:
            Async hook function for PreToolUse
        """
        async def pre_tool_hook(hook_input, tool_use_id, context):
            from claude_agent_sdk.types import SyncHookJSONOutput

            tool_name = hook_input.get("tool_name", "")
            tool_input = hook_input.get("tool_input", {})

            self._logger.info(f"[{agent_id}] Tool call: {tool_name}")

            # Always allow SDK internal tools (StructuredOutput, ListMcpResourcesTool, etc.)
            if tool_name in SDK_INTERNAL_TOOLS:
                self._logger.debug(f"[{agent_id}] ALLOWED: SDK internal tool '{tool_name}'")
                return SyncHookJSONOutput(continue_=True)

            # Block Claude's built-in tools
            if self._block_builtin_tools and tool_name in CLAUDE_BUILTIN_TOOLS:
                self._logger.warning(
                    f"[{agent_id}] BLOCKED: Built-in tool '{tool_name}'"
                )
                self._blocked_tools_log.append(tool_name)
                await self._session_manager.record_blocked_tool(agent_id, tool_name)

                return SyncHookJSONOutput(
                    continue_=True,
                    hookSpecificOutput={
                        'hookEventName': 'PreToolUse',
                        'permissionDecision': 'deny',
                        'permissionDecisionReason': (
                            f"Built-in tool '{tool_name}' is not allowed for {agent_id}. "
                            "Use MCP tools to query the code property graph."
                        )
                    }
                )

            # Check against agent's allowed tools
            if allowed_tools and tool_name not in allowed_tools:
                # Check if it's an MCP tool variant
                tool_base_name = tool_name.split("__")[-1] if "__" in tool_name else tool_name
                is_allowed_variant = any(
                    t.endswith(f"__{tool_base_name}") or t == tool_name
                    for t in allowed_tools
                )

                if not is_allowed_variant:
                    self._logger.warning(
                        f"[{agent_id}] BLOCKED: Tool '{tool_name}' not in allowed list"
                    )
                    self._blocked_tools_log.append(tool_name)
                    await self._session_manager.record_blocked_tool(agent_id, tool_name)

                    return SyncHookJSONOutput(
                        continue_=True,
                        hookSpecificOutput={
                            'hookEventName': 'PreToolUse',
                            'permissionDecision': 'deny',
                            'permissionDecisionReason': (
                                f"Tool '{tool_name}' is not allowed for {agent_id}. "
                                f"Allowed tools: {', '.join(allowed_tools[:5])}..."
                            )
                        }
                    )

            # Validate Cypher queries
            if self._validate_cypher and "execute_query" in tool_name.lower():
                query = tool_input.get("query", "")
                if query:
                    is_safe, error_msg = self._cypher_validator.validate(query)
                    if not is_safe:
                        self._logger.warning(
                            f"[{agent_id}] BLOCKED: Unsafe Cypher query - {error_msg}"
                        )
                        return SyncHookJSONOutput(
                            continue_=True,
                            hookSpecificOutput={
                                'hookEventName': 'PreToolUse',
                                'permissionDecision': 'deny',
                                'permissionDecisionReason': f"Query blocked: {error_msg}"
                            }
                        )

            self._logger.debug(f"[{agent_id}] ALLOWED: {tool_name}")
            return SyncHookJSONOutput(continue_=True)

        return pre_tool_hook

    async def query(
        self,
        agent_id: str,
        allowed_tools: List[str],
        prompt: str,
        system_prompt: Optional[str] = None,
        max_turns: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> PerAgentSDKResponse:
        """
        Execute a query for a specific agent with per-agent tool restrictions.

        Key features:
        - Session is maintained per agent (context preserved)
        - Tool restrictions enforced via hooks (per-agent whitelist)
        - Built-in tools blocked (Bash, Read, Write, etc.)
        - Serialized per-agent via locks (safe for parallel subqueries)

        Parallel Safety:
        When multiple subqueries run in parallel and invoke the same agent
        (e.g., SQ1.ThinkerAgent and SQ2.ThinkerAgent), this method acquires
        a per-agent lock to serialize SDK calls. This ensures:
        - No concurrent access to the same session
        - Context from earlier calls benefits later calls
        - Claude SDK multi-turn semantics are preserved

        Args:
            agent_id: Unique identifier for the agent
            allowed_tools: Tools this agent is allowed to use
            prompt: The query prompt
            system_prompt: Optional system prompt
            max_turns: Override max turns for this query
            response_format: OpenAI-style response format

        Returns:
            PerAgentSDKResponse with content and metadata
        """
        self._blocked_tools_log = []

        # Check if JSON output is expected
        wants_json = response_format and response_format.get("type") in ("json_object", "json_schema")

        try:
            from claude_agent_sdk import (
                ClaudeSDKClient,
                ClaudeAgentOptions,
                AssistantMessage,
                ResultMessage,
                TextBlock,
                ToolUseBlock,
                HookMatcher,
            )
            from claude_agent_sdk.types import SyncHookJSONOutput
        except ImportError as e:
            raise RuntimeError(
                "claude_agent_sdk is required. Install with: pip install claude-agent-sdk"
            ) from e

        # Acquire per-agent lock to serialize SDK calls for parallel safety
        # This ensures only one subquery's call to this agent runs at a time
        agent_lock = await self._session_manager.get_agent_lock(agent_id)

        self._logger.info(
            f"[{agent_id}] Waiting for agent lock (parallel safety)..."
        )

        async with agent_lock:
            self._logger.info(f"[{agent_id}] Lock acquired, starting query")

            # Get session_id for this agent (None if new session)
            session_id = await self._session_manager.get_session(agent_id, allowed_tools)

            self._logger.info(
                f"[{agent_id}] Query starting - "
                f"session_id={session_id or 'new'}, "
                f"allowed_tools={len(allowed_tools)}"
            )

            # Create per-agent tool filter hook
            tool_filter_hook = self._create_tool_filter_hook(agent_id, allowed_tools)

            # Build system prompt with tool guidance
            effective_system_prompt = self._build_agent_system_prompt(
                agent_id, allowed_tools, system_prompt
            )

            # Build hooks
            hooks = {
                "PreToolUse": [
                    HookMatcher(matcher=".*", hooks=[tool_filter_hook])
                ]
            }

            # Build options
            options_kwargs = {
                "model": self._model,
                "system_prompt": effective_system_prompt,
                "mcp_servers": self._mcp_servers if self._mcp_servers else None,
                "allowed_tools": allowed_tools if allowed_tools else None,
                "max_turns": max_turns or self._max_turns,
                "max_budget_usd": self._max_budget_usd,
                "hooks": hooks,
                "max_buffer_size": self._max_buffer_size,
            }

            # Add output_format for structured JSON responses
            # Claude SDK expects: {"type": "json_schema", "schema": {...}}
            # NOT the OpenAI format: {"type": "json_schema", "json_schema": {"name": ..., "schema": ...}}
            if response_format:
                format_type = response_format.get("type", "text")
                if format_type == "json_object":
                    # For json_object without a specific schema, DON'T use SDK's structured output.
                    # The minimal {"type": "object"} schema causes Claude to call StructuredOutput
                    # tool with the schema itself as the data, not the actual JSON content.
                    self._logger.info(f"[{agent_id}] JSON output via prompt (not SDK StructuredOutput)")
                elif format_type == "json_schema":
                    json_schema = response_format.get("json_schema", {})
                    schema = json_schema.get("schema", {})
                    name = json_schema.get("name", "structured_response")
                    if schema:
                        # Claude SDK expects schema directly, not wrapped
                        options_kwargs["output_format"] = {
                            "type": "json_schema",
                            "schema": schema
                        }
                        self._logger.info(f"[{agent_id}] Structured output enabled: {name}")

            # Add session resumption if we have a session_id
            if session_id:
                options_kwargs["resume"] = session_id

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

            options = ClaudeAgentOptions(**options_kwargs)

            response_text = ""
            tool_calls = []
            result_message = None
            new_session_id = None

            try:
                async with ClaudeSDKClient(options=options) as client:
                    await client.query(prompt)

                    async for message in client.receive_response():
                        if isinstance(message, AssistantMessage):
                            for block in message.content:
                                if isinstance(block, TextBlock):
                                    # When JSON is expected, skip narrative text blocks
                                    if wants_json:
                                        text = block.text.strip()
                                        # Only accumulate text that looks like JSON
                                        if text.startswith('{') or text.startswith('['):
                                            response_text += block.text
                                        elif '{' in text or '[' in text:
                                            response_text += block.text
                                        else:
                                            self._logger.debug(
                                                f"[{agent_id}] Skipping non-JSON text: {text[:50]}..."
                                            )
                                    else:
                                        response_text += block.text
                                elif isinstance(block, ToolUseBlock):
                                    tool_calls.append({
                                        "id": block.id,
                                        "name": block.name,
                                        "input": block.input
                                    })

                        elif isinstance(message, ResultMessage):
                            result_message = message
                            new_session_id = message.session_id

                            # Use structured output if available
                            if hasattr(message, 'structured_output') and message.structured_output:
                                response_text = json.dumps(message.structured_output)
                                self._logger.info(f"[{agent_id}] Using native structured_output from SDK")
                            elif wants_json:
                                # Log why structured_output wasn't used for debugging
                                has_attr = hasattr(message, 'structured_output')
                                value = getattr(message, 'structured_output', 'N/A') if has_attr else 'N/A'
                                self._logger.debug(
                                    f"[{agent_id}] structured_output not available: "
                                    f"has_attr={has_attr}, value={value}"
                                )

                # If JSON was expected, try to extract valid JSON from response
                if wants_json and response_text:
                    extracted = self._extract_json_from_response(response_text)
                    if extracted:
                        self._logger.info(f"[{agent_id}] Extracted JSON from response text")
                        response_text = extracted
                    else:
                        self._logger.warning(
                            f"[{agent_id}] JSON expected but could not extract valid JSON"
                        )

                # Update session manager with new session_id
                if new_session_id:
                    cost = result_message.total_cost_usd if result_message else 0.0
                    await self._session_manager.update_session_id(
                        agent_id, new_session_id, cost
                    )

                response = PerAgentSDKResponse(
                    content=response_text,
                    tool_calls=tool_calls,
                    model=self._model,
                    usage=result_message.usage if result_message else None,
                    cost_usd=result_message.total_cost_usd if result_message else 0.0,
                    session_id=new_session_id,
                    agent_id=agent_id,
                    blocked_tools=self._blocked_tools_log.copy()
                )

                self._logger.info(
                    f"[{agent_id}] Query complete - "
                    f"{len(response_text)} chars, "
                    f"{len(tool_calls)} tool calls, "
                    f"{len(self._blocked_tools_log)} blocked tools"
                )

                return response

            except Exception as e:
                self._logger.error(f"[{agent_id}] Query failed: {e}")
                raise

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

    def _build_agent_system_prompt(
        self,
        agent_id: str,
        allowed_tools: List[str],
        base_prompt: Optional[str]
    ) -> str:
        """Build system prompt with agent-specific tool guidance."""
        parts = []

        if base_prompt:
            parts.append(base_prompt)

        # Add agent-specific tool restrictions
        tool_list = ", ".join(allowed_tools[:7])
        parts.append(
            f"\n\n## AGENT: {agent_id} - TOOL RESTRICTIONS\n"
            f"You are operating as {agent_id} with restricted tool access.\n\n"
            f"ALLOWED tools (use ONLY these):\n  {tool_list}\n\n"
            "**FORBIDDEN - WILL BE BLOCKED:**\n"
            "- Bash, Read, Write, Glob, Grep, Edit, LS, Task, TodoWrite\n"
            "- Any tool not in your allowed list\n\n"
            "If a tool is blocked, use a different allowed tool. "
            "DO NOT repeatedly try blocked tools."
        )

        # Add security rules
        parts.append(
            "\n\n## SECURITY RULES\n"
            "- READ-ONLY mode: No CREATE, MERGE, SET, DELETE, REMOVE operations\n"
            "- Use LIMIT clauses to avoid excessive data\n"
            "- Report if write operations are requested"
        )

        return "\n".join(parts)

    async def close_agent_session(self, agent_id: str):
        """Close the session for a specific agent."""
        await self._session_manager.close_session(agent_id)

    async def close_all_sessions(self):
        """Close all agent sessions. Call at workflow end."""
        await self._session_manager.close_all_sessions()

    async def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics about all agent sessions."""
        return await self._session_manager.get_session_stats()

    @property
    def session_manager(self) -> AgentSessionManager:
        """Get the session manager instance."""
        return self._session_manager


__all__ = [
    'AgentSession',
    'AgentSessionManager',
    'PerAgentSDKClient',
    'PerAgentSDKResponse',
]
