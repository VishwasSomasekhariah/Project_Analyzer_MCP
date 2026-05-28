"""
Resilient LLM Client with automatic fallback support.

Provides an OpenAI-compatible client that automatically falls back to
Claude SDK (direct) when the primary LLM provider fails.

Fallback modes:
1. DIRECT (default): Uses ClaudeSDKClient directly with MCP servers
2. ADAPTER: Uses Claude Code OpenAI-compatible adapter server (legacy)

Per-Agent SDK Support:
When fallback_mode="direct", supports per-agent tool restrictions via
PerAgentSDKClient. Pass agent_context in create() calls to enable
per-agent session management and tool enforcement.
"""

import asyncio
import concurrent.futures
import logging
from typing import Any, Dict, List, Optional, Union, Literal, TYPE_CHECKING
from openai import OpenAI, APIConnectionError, APIError, RateLimitError, APITimeoutError

if TYPE_CHECKING:
    from .per_agent_sdk_client import PerAgentSDKClient, AgentSessionManager

logger = logging.getLogger(__name__)

# Fallback mode types
FallbackMode = Literal["direct", "adapter"]


class ResilientLLMClient:
    """
    OpenAI-compatible client with automatic fallback to Claude SDK.

    This is a drop-in replacement for the OpenAI client that:
    1. Tries the primary LLM provider (OpenAI, Azure, etc.) first
    2. Falls back to Claude SDK (direct) on failure
    3. Supports MCP server configuration for the fallback
    4. Supports validation hooks for guardrails

    Fallback Modes:
    - "direct" (default): Uses ClaudeSDKClient directly - no adapter server needed
    - "adapter" (legacy): Uses Claude Code OpenAI-compatible adapter server

    Usage:
        client = ResilientLLMClient(
            primary_config={"api_key": "sk-...", "base_url": None},
            fallback_mode="direct",  # Use Claude SDK directly
            mcp_config_path="/path/to/mcp_config.json"
        )

        # Use like normal OpenAI client
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Hello"}]
        )
    """

    def __init__(
        self,
        primary_config: Optional[Dict[str, Any]] = None,
        fallback_mode: FallbackMode = "direct",
        fallback_url: str = "http://localhost:8889/v1",
        # fallback_model: str = "claude-sonnet-4-20250514",
        fallback_model: str = "claude-opus-4-6",
        fallback_enabled: bool = True,
        mcp_config_path: Optional[str] = None,
        mcp_servers: Optional[Dict[str, Dict[str, Any]]] = None,
        allowed_mcp_servers: Optional[List[str]] = None,  # NEW: Filter MCP servers
        allowed_tools: Optional[List[str]] = None,
        system_prompt: Optional[str] = None,
        max_turns: int = 10,
        pre_tool_hook: Optional[Any] = None,
        post_tool_hook: Optional[Any] = None,
        # Security options (direct mode)
        strict_security: bool = True,
        validate_prompts: bool = True,
        validate_cypher: bool = True,
        max_buffer_size: int = 10 * 1024 * 1024,  # 10MB
        block_builtin_tools: bool = True,  # Block Claude's Bash, Read, Write, etc.
        # Observer integration (direct mode)
        observer: Optional[Any] = None,  # CPGObserverAgent
        agent_id: str = "resilient-llm-client",
        # Schema context and MCP session for in-process tools (direct mode)
        schema_manager: Optional[Any] = None,  # DynamicSchemaManager
        mcp_session: Optional[Any] = None,  # MCP session for in-process tools
    ):
        """
        Initialize the resilient LLM client.

        Args:
            primary_config: Configuration for primary OpenAI client (api_key, base_url, etc.)
            fallback_mode: "direct" (Claude SDK) or "adapter" (legacy adapter server)
            fallback_url: Base URL for adapter server (only used if fallback_mode="adapter")
            fallback_model: Model to use for fallback requests
            fallback_enabled: Whether to enable fallback (default: True)
            mcp_config_path: Path to MCP config file
            mcp_servers: MCP server configurations
            allowed_mcp_servers: Filter to only use specific MCP servers (e.g., ["neo4j_memory"])
            allowed_tools: List of allowed tools for fallback
            system_prompt: System prompt for Claude (direct mode)
            max_turns: Maximum agentic turns (direct mode)
            pre_tool_hook: Hook called before tool execution (direct mode)
            post_tool_hook: Hook called after tool execution (direct mode)
            strict_security: If True, blocks dangerous operations (direct mode)
            validate_prompts: If True, validates prompts for injection attacks (direct mode)
            validate_cypher: If True, validates Cypher queries for write operations (direct mode)
            max_buffer_size: Maximum JSON message buffer size in bytes (direct mode)
            block_builtin_tools: If True, blocks Claude's built-in tools (Bash, Read, Write, etc.)
            observer: Optional CPG Observer for query tracking (direct mode)
            agent_id: Identifies this client for observer tracking (direct mode)
            schema_manager: Optional schema manager for context injection and in-process tools (direct mode)
            mcp_session: Optional MCP session for in-process tools to execute queries (direct mode)
        """
        self._logger = logging.getLogger(f"{__name__}.ResilientLLMClient")

        # Circuit breaker: skip primary when known to be down
        # Initialize early so disable_primary() can be called during __init__
        self._primary_disabled = False
        self._primary_disable_reason: Optional[str] = None

        # Primary client configuration
        primary_config = primary_config or {}
        # Filter out None values
        primary_kwargs = {k: v for k, v in primary_config.items() if v is not None}

        # Try to create primary OpenAI client, gracefully handle missing API key
        try:
            self._primary = OpenAI(**primary_kwargs)
        except Exception as e:
            error_msg = str(e).lower()
            if "api_key" in error_msg or "api key" in error_msg:
                self._logger.warning(
                    f"Primary LLM client initialization failed (missing API key): {e}. "
                    f"All calls will use fallback if available."
                )
                self._primary = None
                self._primary_disabled = True
                self._primary_disable_reason = "No API key configured"
            else:
                # Re-raise other initialization errors
                raise

        # Fallback configuration
        self._fallback_mode = fallback_mode
        self._fallback_url = fallback_url
        self._fallback_model = fallback_model
        self._fallback_enabled = fallback_enabled
        self._fallback_available = False

        # MCP and tools configuration
        self._mcp_servers: Dict[str, Dict[str, Any]] = mcp_servers or {}
        self._allowed_mcp_servers: List[str] = allowed_mcp_servers or []  # NEW: Filter servers
        self._allowed_tools: List[str] = allowed_tools or []
        self._mcp_config_path = mcp_config_path
        self._system_prompt = system_prompt
        self._max_turns = max_turns
        self._pre_tool_hook = pre_tool_hook
        self._post_tool_hook = post_tool_hook

        # Security options (direct mode)
        self._strict_security = strict_security
        self._validate_prompts = validate_prompts
        self._validate_cypher = validate_cypher
        self._max_buffer_size = max_buffer_size
        self._block_builtin_tools = block_builtin_tools

        # Observer, schema context, and MCP session (direct mode)
        self._observer = observer
        self._agent_id = agent_id
        self._schema_manager = schema_manager
        self._mcp_session = mcp_session  # For in-process tools

        # Initialize fallback based on mode
        self._sdk_fallback = None  # ClaudeSDKFallback instance (direct mode)
        self._adapter_fallback = None  # OpenAI client (adapter mode)

        # Per-agent SDK client (optional, for per-agent tool restrictions)
        self._per_agent_sdk_client: Optional['PerAgentSDKClient'] = None
        self._per_agent_mode_enabled = False

        if fallback_enabled:
            self._initialize_fallback()

        # Create the chat.completions interface
        self.chat = _ChatNamespace(self)

    def _initialize_fallback(self) -> None:
        """Initialize the fallback client based on mode."""
        if self._fallback_mode == "direct":
            self._initialize_direct_fallback()
        else:
            self._initialize_adapter_fallback()

    def _initialize_direct_fallback(self) -> None:
        """Initialize Claude SDK direct fallback with full guardrails."""
        try:
            from .claude_sdk_fallback import ClaudeSDKFallback

            # Filter MCP servers if allowed_mcp_servers is specified (e.g., only ["neo4j_memory"])
            filtered_mcp_servers = self._mcp_servers
            if self._allowed_mcp_servers:
                filtered_mcp_servers = {
                    name: config
                    for name, config in self._mcp_servers.items()
                    if name in self._allowed_mcp_servers
                }
                if filtered_mcp_servers != self._mcp_servers:
                    self._logger.info(
                        f"Filtered MCP servers for fallback: {list(self._mcp_servers.keys())} → "
                        f"{list(filtered_mcp_servers.keys())}"
                    )

            self._sdk_fallback = ClaudeSDKFallback(
                # MCP configuration - only pass mcp_servers (already filtered), NOT mcp_config_path
                mcp_config_path=None if self._allowed_mcp_servers else self._mcp_config_path,
                mcp_servers=filtered_mcp_servers,
                # Claude SDK options
                system_prompt=self._system_prompt,
                model=self._fallback_model,
                max_turns=self._max_turns,
                allowed_tools=self._allowed_tools if self._allowed_tools else None,
                block_builtin_tools=self._block_builtin_tools,
                pre_tool_hook=self._pre_tool_hook,
                post_tool_hook=self._post_tool_hook,
                max_buffer_size=self._max_buffer_size,
                # Security options
                strict_security=self._strict_security,
                validate_prompts=self._validate_prompts,
                validate_cypher=self._validate_cypher,
                # Observer integration
                observer=self._observer,
                agent_id=self._agent_id,
                # Schema context and MCP session for in-process tools
                schema_manager=self._schema_manager,
                mcp_session=self._mcp_session,
            )

            self._fallback_available = self._sdk_fallback.is_available
            if self._fallback_available:
                self._logger.info(
                    f"Claude SDK direct fallback initialized "
                    f"(strict_security={self._strict_security}, validate_cypher={self._validate_cypher}, "
                    f"in_process_tools={self._mcp_session is not None})"
                )
            else:
                self._logger.warning("Claude SDK not available (claude_agent_sdk not installed)")

        except Exception as e:
            self._logger.error(f"Failed to initialize Claude SDK fallback: {e}")
            self._fallback_available = False

    def _initialize_adapter_fallback(self) -> None:
        """Initialize legacy adapter server fallback."""
        import httpx

        self._adapter_fallback = OpenAI(
            base_url=self._fallback_url,
            api_key="not-needed-for-local-adapter"
        )

        # Check if adapter server is running
        try:
            response = httpx.get(f"{self._fallback_url.rstrip('/v1')}/", timeout=2.0)
            if response.status_code == 200:
                self._fallback_available = True
                self._logger.info(f"Fallback adapter available at {self._fallback_url}")

                # Load MCP config if provided
                if self._mcp_config_path:
                    self.load_mcp_config(self._mcp_config_path)
        except Exception as e:
            self._logger.debug(f"Fallback adapter not available: {e}")
            self._fallback_available = False

    def _check_fallback_availability(self) -> bool:
        """Check if the fallback is available."""
        if self._fallback_mode == "direct":
            if self._sdk_fallback:
                self._fallback_available = self._sdk_fallback.is_available
            return self._fallback_available
        else:
            # Adapter mode - check HTTP endpoint
            import httpx
            try:
                response = httpx.get(f"{self._fallback_url.rstrip('/v1')}/", timeout=2.0)
                if response.status_code == 200:
                    self._fallback_available = True
                    return True
            except Exception as e:
                self._logger.debug(f"Fallback adapter not available: {e}")
            self._fallback_available = False
            return False

    # =========================================================================
    # MCP Server Management
    # =========================================================================

    def load_mcp_config(self, config_path: str) -> Dict[str, Any]:
        """
        Load MCP configuration from a JSON file.

        Args:
            config_path: Path to MCP config JSON file

        Returns:
            Status response
        """
        self._mcp_config_path = config_path

        if self._fallback_mode == "direct":
            # Direct mode: reload SDK fallback with new config
            if self._sdk_fallback:
                self._sdk_fallback._load_mcp_config(config_path)
                return {"status": "ok", "servers": list(self._sdk_fallback.mcp_servers.keys())}
            return {"status": "error", "message": "SDK fallback not initialized"}
        else:
            # Adapter mode: call adapter API
            if not self._fallback_available:
                self._check_fallback_availability()
                if not self._fallback_available:
                    self._logger.warning("Fallback adapter not available")
                    return {"status": "error", "message": "Fallback adapter not available"}

            import httpx
            try:
                base_url = self._fallback_url.rstrip('/v1')
                response = httpx.post(
                    f"{base_url}/v1/mcp/load",
                    json={"config_path": config_path},
                    timeout=10.0
                )
                result = response.json()
                self._logger.info(f"Loaded MCP config: {result}")
                return result
            except Exception as e:
                self._logger.error(f"Failed to load MCP config: {e}")
                return {"status": "error", "message": str(e)}

    def add_mcp_server(self, name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add an MCP server.

        Args:
            name: Server name (e.g., "neo4j_memory")
            config: Server config (e.g., {"type": "sse", "url": "http://localhost:8100/sse"})

        Returns:
            Status response
        """
        self._mcp_servers[name] = config

        if self._fallback_mode == "direct":
            if self._sdk_fallback:
                self._sdk_fallback.add_mcp_server(name, config)
            return {"status": "ok", "server": name}
        else:
            # Adapter mode
            if not self._fallback_available:
                self._check_fallback_availability()
                if not self._fallback_available:
                    return {"status": "error", "message": "Fallback adapter not available"}

            import httpx
            try:
                base_url = self._fallback_url.rstrip('/v1')
                response = httpx.post(
                    f"{base_url}/v1/mcp/servers",
                    json={name: config},
                    timeout=10.0
                )
                result = response.json()
                self._logger.info(f"Added MCP server '{name}': {result}")
                return result
            except Exception as e:
                self._logger.error(f"Failed to add MCP server: {e}")
                return {"status": "error", "message": str(e)}

    def remove_mcp_server(self, name: str) -> Dict[str, Any]:
        """
        Remove an MCP server.

        Args:
            name: Server name to remove

        Returns:
            Status response
        """
        self._mcp_servers.pop(name, None)

        if self._fallback_mode == "direct":
            if self._sdk_fallback:
                self._sdk_fallback.remove_mcp_server(name)
            return {"status": "ok", "removed": name}
        else:
            # Adapter mode
            if not self._fallback_available:
                return {"status": "error", "message": "Fallback adapter not available"}

            import httpx
            try:
                base_url = self._fallback_url.rstrip('/v1')
                response = httpx.delete(
                    f"{base_url}/v1/mcp/servers/{name}",
                    timeout=10.0
                )
                result = response.json()
                self._logger.info(f"Removed MCP server '{name}': {result}")
                return result
            except Exception as e:
                self._logger.error(f"Failed to remove MCP server: {e}")
                return {"status": "error", "message": str(e)}

    def list_mcp_servers(self) -> Dict[str, Any]:
        """List configured MCP servers."""
        if self._fallback_mode == "direct":
            if self._sdk_fallback:
                return {"status": "ok", "servers": self._sdk_fallback.mcp_servers}
            return {"status": "ok", "servers": self._mcp_servers}
        else:
            # Adapter mode
            if not self._fallback_available:
                return {"status": "error", "message": "Fallback adapter not available"}

            import httpx
            try:
                base_url = self._fallback_url.rstrip('/v1')
                response = httpx.get(f"{base_url}/v1/mcp/servers", timeout=5.0)
                return response.json()
            except Exception as e:
                return {"status": "error", "message": str(e)}

    # =========================================================================
    # Allowed Tools Management
    # =========================================================================

    def set_allowed_tools(self, tools: List[str]) -> None:
        """
        Set the list of allowed tools for fallback requests.

        Args:
            tools: List of tool names (e.g., ["mcp__neo4j_memory__neo4j_execute_query"])
        """
        self._allowed_tools = tools
        self._logger.info(f"Set allowed tools: {tools}")

    def add_allowed_tool(self, tool: str) -> None:
        """Add a tool to the allowed tools list."""
        if tool not in self._allowed_tools:
            self._allowed_tools.append(tool)

    def get_allowed_tools(self) -> List[str]:
        """Get the current list of allowed tools."""
        return self._allowed_tools.copy()

    # =========================================================================
    # Observer and Schema Management (direct mode)
    # =========================================================================

    def set_observer(self, observer: Any) -> None:
        """Set the CPG observer for query tracking (direct mode only)."""
        self._observer = observer
        if self._sdk_fallback and self._fallback_mode == "direct":
            self._sdk_fallback.set_observer(observer)

    def set_schema_manager(self, schema_manager: Any) -> None:
        """Set the schema manager for context injection (direct mode only)."""
        self._schema_manager = schema_manager
        if self._sdk_fallback and self._fallback_mode == "direct":
            self._sdk_fallback.set_schema_manager(schema_manager)

    def set_tool_context(self, schema_manager: Any, mcp_session: Any) -> None:
        """
        Set schema manager and MCP session to enable in-process tools for Claude SDK fallback.

        This method should be called after the orchestrator has initialized the MCP session
        and schema manager, allowing the Claude SDK fallback to use the same tools as the
        primary LLM (OpenAI) uses.

        Args:
            schema_manager: DynamicSchemaManager instance
            mcp_session: Active MCP session for query execution
        """
        self._schema_manager = schema_manager
        self._mcp_session = mcp_session

        # Re-initialize the SDK fallback to create in-process tools
        if self._fallback_mode == "direct" and self._fallback_enabled:
            self._logger.info("Re-initializing SDK fallback with in-process tools...")
            self._initialize_direct_fallback()
            if self._fallback_available:
                self._logger.info("SDK fallback updated with in-process tools")

        # Also update the per-agent SDK client with in-process schema tools.
        # enable_per_agent_mode() is called before set_tool_context() so the client
        # was originally created with schema_manager=None — patch it now.
        if self._per_agent_sdk_client is not None and schema_manager is not None:
            self._logger.info("Updating per-agent SDK client with in-process schema tools...")
            self._per_agent_sdk_client._schema_manager = schema_manager
            self._per_agent_sdk_client._create_inprocess_schema_tools(schema_manager)
            self._logger.info("Per-agent SDK client schema tools updated")

    def clear_tool_context(self) -> None:
        """
        Clear the tool context (schema manager and MCP session).

        This removes the in-process tools from the Claude SDK fallback,
        reverting to external MCP servers only.
        """
        self._schema_manager = None
        self._mcp_session = None

        # Re-initialize the SDK fallback without in-process tools
        if self._fallback_mode == "direct" and self._fallback_enabled:
            self._logger.info("Clearing in-process tools from SDK fallback...")
            self._initialize_direct_fallback()
            self._logger.info("SDK fallback cleared of in-process tools")

    def set_context(self, agent_id: str = None, sub_query: str = None) -> None:
        """Set context for observation tracking (direct mode only)."""
        if agent_id:
            self._agent_id = agent_id
        if self._sdk_fallback and self._fallback_mode == "direct":
            self._sdk_fallback.set_context(agent_id=agent_id, sub_query=sub_query)

    def get_blocked_queries(self) -> List[str]:
        """Get queries blocked by security validation (direct mode only)."""
        if self._sdk_fallback and self._fallback_mode == "direct":
            return self._sdk_fallback.get_blocked_queries()
        return []

    # =========================================================================
    # Per-Agent SDK Mode
    # =========================================================================

    def enable_per_agent_mode(
        self,
        session_manager: Optional['AgentSessionManager'] = None
    ) -> None:
        """
        Enable per-agent SDK fallback mode for per-agent tool restrictions.

        When enabled, SDK fallback calls can include agent context
        (agent_id and allowed_tools) for per-agent session management
        and tool enforcement.

        This solves the problem where a shared SDK client loses per-agent
        tool restrictions.

        Args:
            session_manager: Optional AgentSessionManager (created if not provided)
        """
        if self._fallback_mode != "direct":
            self._logger.warning(
                "Per-agent mode only works with fallback_mode='direct'. "
                f"Current mode: {self._fallback_mode}"
            )
            return

        try:
            from .per_agent_sdk_client import PerAgentSDKClient, AgentSessionManager

            # Create or use provided session manager
            if session_manager is None:
                session_manager = AgentSessionManager()

            # Create per-agent SDK client with same MCP server filtering
            self._per_agent_sdk_client = PerAgentSDKClient(
                mcp_config_path=self._mcp_config_path,
                mcp_servers=self._mcp_servers,
                schema_manager=self._schema_manager,
                session_manager=session_manager,
                model=self._fallback_model,
                max_turns=self._max_turns,
                max_budget_usd=None,
                block_builtin_tools=self._block_builtin_tools,
                strict_security=self._strict_security,
                validate_cypher=self._validate_cypher,
                observer=self._observer,
                max_buffer_size=self._max_buffer_size,
                allowed_mcp_servers=self._allowed_mcp_servers,  # Apply same filtering
            )

            self._per_agent_mode_enabled = True
            self._logger.info(
                "Per-agent SDK mode enabled - "
                "SDK fallback will use per-agent sessions and tool restrictions"
            )

        except ImportError as e:
            self._logger.error(f"Failed to enable per-agent mode: {e}")
        except Exception as e:
            self._logger.error(f"Error enabling per-agent mode: {e}")

    def disable_per_agent_mode(self) -> None:
        """Disable per-agent SDK mode."""
        self._per_agent_mode_enabled = False
        self._per_agent_sdk_client = None
        self._logger.info("Per-agent SDK mode disabled")

    @property
    def per_agent_mode_enabled(self) -> bool:
        """Check if per-agent mode is enabled."""
        return self._per_agent_mode_enabled

    def get_per_agent_sdk_client(self) -> Optional['PerAgentSDKClient']:
        """Get the per-agent SDK client (if enabled)."""
        return self._per_agent_sdk_client

    async def close_all_agent_sessions(self) -> None:
        """Close all agent sessions. Call at workflow end."""
        if self._per_agent_sdk_client:
            await self._per_agent_sdk_client.close_all_sessions()
            self._logger.info("All agent sessions closed")

    async def get_agent_session_stats(self) -> Dict[str, Any]:
        """Get statistics about all agent sessions."""
        if self._per_agent_sdk_client:
            return await self._per_agent_sdk_client.get_session_stats()
        return {"per_agent_mode": False}

    # =========================================================================
    # Circuit Breaker: Skip primary when known to be down
    # =========================================================================

    def disable_primary(self, reason: str = "manually disabled") -> None:
        """
        Disable the primary LLM, forcing all calls to use fallback.

        Call this when you know the primary is down (rate limited, quota exceeded, etc.)
        to avoid repeated failed attempts and latency.

        Args:
            reason: Why primary was disabled (for logging)
        """
        if not self._primary_disabled:
            self._primary_disabled = True
            self._primary_disable_reason = reason
            self._logger.warning(f"Primary LLM disabled: {reason}. All calls will use fallback.")

    def enable_primary(self) -> None:
        """
        Re-enable the primary LLM.

        Call this to retry the primary after it was disabled.
        """
        if self._primary_disabled:
            self._primary_disabled = False
            self._logger.info(f"Primary LLM re-enabled (was disabled: {self._primary_disable_reason})")
            self._primary_disable_reason = None

    @property
    def is_primary_disabled(self) -> bool:
        """Check if primary LLM is currently disabled."""
        return self._primary_disabled

    @property
    def primary_disable_reason(self) -> Optional[str]:
        """Get the reason why primary LLM was disabled."""
        return self._primary_disable_reason


# =========================================================================
# Chat Completions Interface (OpenAI-compatible)
# =========================================================================

class _CompletionsNamespace:
    """Namespace to mimic OpenAI's client.chat.completions structure."""

    def __init__(self, parent: "ResilientLLMClient"):
        self._parent = parent
        self._logger = logging.getLogger(f"{__name__}.Completions")

    def create(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        agent_context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Any:
        """
        Create a chat completion, with automatic fallback on failure.

        Args:
            messages: List of message dicts
            model: Model name (uses primary model, falls back to fallback_model)
            tools: List of tool definitions
            tool_choice: Tool choice strategy
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
            agent_context: Optional dict with agent_id and allowed_tools for per-agent SDK fallback
                          Example: {"agent_id": "ThinkerAgent", "allowed_tools": [...]}
            **kwargs: Additional arguments passed to the API

        Returns:
            OpenAI ChatCompletion response
        """
        # Store agent context for fallback
        self._current_agent_context = agent_context
        # Build kwargs for the API call
        api_kwargs = {"messages": messages}
        if model:
            api_kwargs["model"] = model
        if tools:
            api_kwargs["tools"] = tools
        if tool_choice:
            api_kwargs["tool_choice"] = tool_choice
        if temperature is not None:
            api_kwargs["temperature"] = temperature
        if max_tokens is not None:
            api_kwargs["max_tokens"] = max_tokens
        api_kwargs.update(kwargs)

        # Circuit breaker: skip primary if disabled
        if self._parent._primary_disabled:
            self._logger.debug(
                f"Primary LLM disabled ({self._parent._primary_disable_reason}), "
                f"using fallback directly"
            )
            if not self._parent._fallback_enabled:
                raise RuntimeError(
                    f"Primary LLM disabled ({self._parent._primary_disable_reason}) "
                    f"and fallback not enabled"
                )
            # Create a synthetic error for the fallback path
            synthetic_error = RuntimeError(f"Primary disabled: {self._parent._primary_disable_reason}")
            return self._try_fallback(api_kwargs, original_error=synthetic_error)

        # Safety check: if primary client is None (shouldn't happen if circuit breaker is set correctly)
        if self._parent._primary is None:
            self._logger.warning("Primary LLM client is None, using fallback")
            if not self._parent._fallback_enabled:
                raise RuntimeError("Primary LLM client is None and fallback not enabled")
            synthetic_error = RuntimeError("Primary client not initialized")
            return self._try_fallback(api_kwargs, original_error=synthetic_error)

        # Try primary client first
        try:
            self._logger.debug(f"Trying primary LLM with model: {api_kwargs.get('model', 'default')}")
            return self._parent._primary.chat.completions.create(**api_kwargs)

        except (APIConnectionError, APITimeoutError, RateLimitError) as e:
            # These are recoverable errors - try fallback
            self._logger.warning(f"Primary LLM failed with recoverable error: {type(e).__name__}: {e}")

            # Auto-disable primary on rate limit / quota exceeded
            if isinstance(e, RateLimitError):
                error_msg = str(e).lower()
                if "quota" in error_msg or "exceeded" in error_msg:
                    self._parent.disable_primary(f"Quota exceeded: {type(e).__name__}")
                else:
                    self._parent.disable_primary(f"Rate limited: {type(e).__name__}")

            if not self._parent._fallback_enabled:
                self._logger.error("Fallback disabled, re-raising exception")
                raise

            return self._try_fallback(api_kwargs, original_error=e)

        except APIError as e:
            # API errors might be recoverable depending on status code
            if e.status_code in (500, 502, 503, 504):
                self._logger.warning(f"Primary LLM server error ({e.status_code}): {e}")

                if not self._parent._fallback_enabled:
                    raise

                return self._try_fallback(api_kwargs, original_error=e)
            else:
                # Client errors (4xx) should not be retried
                self._logger.error(f"Primary LLM client error ({e.status_code}): {e}")
                raise

    def _try_fallback(self, api_kwargs: Dict[str, Any], original_error: Exception) -> Any:
        """
        Try the fallback.

        Args:
            api_kwargs: Original API kwargs
            original_error: The error that triggered fallback

        Returns:
            ChatCompletion-compatible response from fallback
        """
        # Check fallback availability
        if not self._parent._fallback_available:
            self._parent._check_fallback_availability()

        if not self._parent._fallback_available:
            self._logger.error("Fallback not available")
            raise original_error

        if self._parent._fallback_mode == "direct":
            return self._try_direct_fallback(api_kwargs, original_error)
        else:
            return self._try_adapter_fallback(api_kwargs, original_error)

    def _try_direct_fallback(self, api_kwargs: Dict[str, Any], original_error: Exception) -> Any:
        """
        Try Claude SDK direct fallback.

        Converts messages to a prompt and uses ClaudeSDKFallback.
        If per-agent mode is enabled and agent_context is provided, uses
        PerAgentSDKClient for per-agent tool restrictions.

        Returns an OpenAI-compatible response object.
        """
        self._logger.info("Falling back to Claude SDK (direct mode)")

        # Check if we should use per-agent mode
        agent_context = getattr(self, '_current_agent_context', None)
        if (self._parent._per_agent_mode_enabled and
            self._parent._per_agent_sdk_client and
            agent_context):
            return self._try_per_agent_fallback(api_kwargs, agent_context, original_error)

        # Use standard SDK fallback
        sdk_fallback = self._parent._sdk_fallback
        if not sdk_fallback:
            self._logger.error("SDK fallback not initialized")
            raise original_error

        # Convert messages to a prompt for Claude SDK
        messages = api_kwargs.get("messages", [])
        prompt = self._messages_to_prompt(messages)

        # Extract system prompt if present
        system_prompt = None
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content", "")
                break

        # Extract response_format for JSON output support
        response_format = api_kwargs.get("response_format")
        if response_format:
            self._logger.debug(f"Passing response_format to Claude SDK: {response_format}")

        try:
            # Run async query synchronously (handles nested event loops via threading)
            self._logger.debug(f"Invoking Claude SDK with prompt: {prompt[:100]}...")
            response = sdk_fallback.query_sync(
                prompt=prompt,
                system_prompt=system_prompt,
                response_format=response_format
            )

            # Convert to OpenAI-compatible response
            self._logger.info(f"Claude SDK fallback successful: {len(response.content)} chars response")
            return self._sdk_response_to_openai(response)

        except concurrent.futures.TimeoutError as timeout_error:
            self._logger.error("Claude SDK fallback timed out (300s limit)")
            raise original_error from timeout_error

        except Exception as fallback_error:
            self._logger.error(f"Claude SDK fallback failed: {type(fallback_error).__name__}: {fallback_error}")
            raise original_error from fallback_error

    def _try_per_agent_fallback(
        self,
        api_kwargs: Dict[str, Any],
        agent_context: Dict[str, Any],
        original_error: Exception
    ) -> Any:
        """
        Try per-agent SDK fallback with agent-specific tool restrictions.

        Uses PerAgentSDKClient for per-agent session management and
        tool enforcement.
        """
        agent_id = agent_context.get("agent_id", "unknown")
        allowed_tools = agent_context.get("allowed_tools", [])

        self._logger.info(
            f"Using per-agent SDK fallback for '{agent_id}' with "
            f"{len(allowed_tools)} allowed tools"
        )

        per_agent_client = self._parent._per_agent_sdk_client

        # Convert messages to a prompt
        messages = api_kwargs.get("messages", [])
        prompt = self._messages_to_prompt(messages)

        # Extract system prompt
        system_prompt = None
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content", "")
                break

        response_format = api_kwargs.get("response_format")

        try:
            # Run async query synchronously
            def run_query():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(
                        per_agent_client.query(
                            agent_id=agent_id,
                            allowed_tools=allowed_tools,
                            prompt=prompt,
                            system_prompt=system_prompt,
                            response_format=response_format
                        )
                    )
                finally:
                    loop.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_query)
                response = future.result(timeout=900)  # 15 min — CPG multi-agent queries can take 10+ min

            self._logger.info(
                f"Per-agent SDK fallback successful for '{agent_id}': "
                f"{len(response.content)} chars, "
                f"{len(response.blocked_tools)} tools blocked"
            )

            return self._per_agent_response_to_openai(response)

        except concurrent.futures.TimeoutError as timeout_error:
            self._logger.error(f"Per-agent SDK fallback timed out for '{agent_id}'")
            raise original_error from timeout_error

        except Exception as fallback_error:
            self._logger.error(
                f"Per-agent SDK fallback failed for '{agent_id}': "
                f"{type(fallback_error).__name__}: {fallback_error}"
            )
            raise original_error from fallback_error

    def _per_agent_response_to_openai(self, response) -> Any:
        """Convert PerAgentSDKResponse to OpenAI-compatible ChatCompletion."""
        from dataclasses import dataclass
        from typing import List, Optional
        import time

        @dataclass
        class Message:
            role: str = "assistant"
            content: str = ""
            tool_calls: Optional[List] = None

        @dataclass
        class Choice:
            index: int = 0
            message: Message = None
            finish_reason: str = "stop"

            def __post_init__(self):
                if self.message is None:
                    self.message = Message(tool_calls=None)

        @dataclass
        class Usage:
            prompt_tokens: int = 0
            completion_tokens: int = 0
            total_tokens: int = 0

        @dataclass
        class ChatCompletion:
            id: str = ""
            object: str = "chat.completion"
            created: int = 0
            model: str = ""
            choices: List[Choice] = None
            usage: Usage = None

            def __post_init__(self):
                if self.choices is None:
                    self.choices = []
                if self.usage is None:
                    self.usage = Usage()

        completion = ChatCompletion(
            id=f"per-agent-{response.agent_id}-{response.session_id or 'new'}",
            created=int(time.time()),
            model=response.model,
            choices=[
                Choice(
                    index=0,
                    message=Message(
                        role="assistant",
                        content=response.content,
                        tool_calls=None
                    ),
                    finish_reason="stop"
                )
            ],
            usage=Usage(
                prompt_tokens=response.usage.get("input_tokens", 0) if response.usage else 0,
                completion_tokens=response.usage.get("output_tokens", 0) if response.usage else 0,
                total_tokens=(
                    (response.usage.get("input_tokens", 0) + response.usage.get("output_tokens", 0))
                    if response.usage else 0
                )
            )
        )

        return completion

    def _try_adapter_fallback(self, api_kwargs: Dict[str, Any], original_error: Exception) -> Any:
        """Try legacy adapter server fallback."""
        self._logger.info(f"Falling back to Claude Code adapter at {self._parent._fallback_url}")

        # Prepare fallback request
        fallback_kwargs = api_kwargs.copy()

        # Override model with fallback model
        fallback_kwargs["model"] = self._parent._fallback_model

        # Add custom parameters via extra_body (Claude adapter specific)
        extra_body = fallback_kwargs.pop("extra_body", {}) or {}

        # Move response_format to extra_body for Claude adapter
        if "response_format" in fallback_kwargs:
            extra_body["response_format"] = fallback_kwargs.pop("response_format")
            self._logger.debug("Moved response_format to extra_body for Claude adapter")

        # Add MCP servers if configured
        if self._parent._mcp_servers:
            extra_body["mcp_servers"] = self._parent._mcp_servers

        # Add allowed tools if configured
        if self._parent._allowed_tools:
            extra_body["allowed_tools"] = self._parent._allowed_tools

        # Note: OpenAI-style 'tools' parameter is NOT supported by Claude adapter
        if "tools" in fallback_kwargs:
            self._logger.warning(
                "OpenAI-style 'tools' parameter detected but Claude adapter uses MCP tools. "
                "Tool calls will not be returned - Claude will handle tools internally if MCP is configured."
            )

        if extra_body:
            fallback_kwargs["extra_body"] = extra_body

        try:
            response = self._parent._adapter_fallback.chat.completions.create(**fallback_kwargs)
            self._logger.info("Fallback request successful")
            return response

        except Exception as fallback_error:
            self._logger.error(f"Fallback also failed: {fallback_error}")
            raise original_error from fallback_error

    def _messages_to_prompt(self, messages: List[Dict[str, Any]]) -> str:
        """Convert OpenAI-style messages to a single prompt string."""
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Skip system messages (handled separately)
            if role == "system":
                continue

            # Include assistant messages for context
            if role == "assistant":
                prompt_parts.append(f"Assistant: {content}")
            elif role == "user":
                prompt_parts.append(content)

        return "\n\n".join(prompt_parts)

    def _sdk_response_to_openai(self, sdk_response) -> Any:
        """
        Convert ClaudeSDKResponse to OpenAI-compatible ChatCompletion.

        Creates a mock object that matches the OpenAI response structure.
        """
        from dataclasses import dataclass
        from typing import List, Optional
        import time

        @dataclass
        class Message:
            role: str = "assistant"
            content: str = ""
            tool_calls: Optional[List] = None

        @dataclass
        class Choice:
            index: int = 0
            message: Message = None
            finish_reason: str = "stop"

            def __post_init__(self):
                if self.message is None:
                    self.message = Message(tool_calls=None)

        @dataclass
        class Usage:
            prompt_tokens: int = 0
            completion_tokens: int = 0
            total_tokens: int = 0

        @dataclass
        class ChatCompletion:
            id: str = ""
            object: str = "chat.completion"
            created: int = 0
            model: str = ""
            choices: List[Choice] = None
            usage: Usage = None

            def __post_init__(self):
                if self.choices is None:
                    self.choices = []
                if self.usage is None:
                    self.usage = Usage()

        # Build OpenAI-compatible response
        completion = ChatCompletion(
            id=f"claude-sdk-{sdk_response.session_id or 'fallback'}",
            created=int(time.time()),
            model=sdk_response.model,
            choices=[
                Choice(
                    index=0,
                    message=Message(
                        role="assistant",
                        content=sdk_response.content,
                        tool_calls=None  # Claude SDK handles tools internally via MCP
                    ),
                    finish_reason="stop"
                )
            ],
            usage=Usage(
                prompt_tokens=sdk_response.usage.get("input_tokens", 0) if sdk_response.usage else 0,
                completion_tokens=sdk_response.usage.get("output_tokens", 0) if sdk_response.usage else 0,
                total_tokens=(
                    (sdk_response.usage.get("input_tokens", 0) + sdk_response.usage.get("output_tokens", 0))
                    if sdk_response.usage else 0
                )
            )
        )

        self._logger.info(f"Claude SDK response converted: {len(sdk_response.content)} chars")
        return completion


class _ChatNamespace:
    """Namespace to mimic OpenAI's client.chat structure."""

    def __init__(self, parent: "ResilientLLMClient"):
        self._parent = parent
        self.completions = _CompletionsNamespace(parent)


# Type alias for backwards compatibility
FallbackLLMClient = ResilientLLMClient


__all__ = ['ResilientLLMClient', 'FallbackLLMClient', 'FallbackMode']
