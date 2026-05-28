#!/usr/bin/env python3
"""
Claude Code OpenAI-Compatible Adapter Server WITH MCP & DYNAMIC TOOL SUPPORT

Enhanced version that supports:
- External MCP servers (http, sse, stdio) via config
- Dynamically loading custom tools via API
- Per-request MCP configuration

Usage:
    # Start with MCP config
    CLAUDE_MCP_CONFIG=/path/to/neo4j_config.json python3 claude_code_openai_adapter_with_tools.py

    # Or configure MCP servers via API
    curl -X POST http://localhost:8889/v1/mcp/servers \
      -H "Content-Type: application/json" \
      -d '{"neo4j": {"type": "http", "url": "http://localhost:7474"}}'

    # Register a dynamic tool
    curl -X POST http://localhost:8889/v1/tools \
      -H "Content-Type: application/json" \
      -d '{
        "name": "get_weather",
        "description": "Get weather for a city",
        "input_schema": {"city": "str"},
        "code": "async def get_weather(args):\\n    return {\\"content\\": [{\\"type\\": \\"text\\", \\"text\\": f\\"Weather in {args[\\"city\\"]}: Sunny\\"}]}"
      }'

    # Use MCP tools in chat completion (tools auto-discovered from MCP servers)
    POST /v1/chat/completions with allowed_tools or mcp_servers
"""

import asyncio
import time
import uuid
import os
import json
import re
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Tuple
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
import uvicorn

try:
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        ResultMessage,
        TextBlock,
        ToolUseBlock,
        tool,
        create_sdk_mcp_server
    )
    from claude_agent_sdk.types import (
        HookMatcher,
        HookContext,
        PreToolUseHookInput,
        SyncHookJSONOutput,
    )
    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False


# ============================================================================
# Cypher Query Validator (Security Guardrail)
# ============================================================================

class CypherQueryValidator:
    """
    Security guardrail to ensure only READ operations are executed.
    Blocks all write, update, and delete operations on the graph.
    """

    # Dangerous Cypher keywords that modify the graph
    WRITE_KEYWORDS = frozenset([
        'CREATE',
        'MERGE',
        'SET',
        'DELETE',
        'DETACH DELETE',
        'REMOVE',
    ])

    # Schema modification keywords
    SCHEMA_KEYWORDS = frozenset([
        'CREATE INDEX',
        'CREATE CONSTRAINT',
        'DROP INDEX',
        'DROP CONSTRAINT',
        'DROP',
    ])

    # Administrative operations
    ADMIN_KEYWORDS = frozenset([
        'CALL dbms.',
        'CALL db.index.',
        'CALL db.constraint.',
        ':USE',
        ':BEGIN',
        ':COMMIT',
        ':ROLLBACK',
    ])

    # Potentially dangerous patterns (injection attempts)
    INJECTION_PATTERNS = [
        r';\s*(CREATE|MERGE|SET|DELETE|REMOVE|DROP)',  # Chained write commands
        r'\}\s*(CREATE|MERGE|SET|DELETE|REMOVE|DROP)',  # Breakout attempts
        r'UNION\s+ALL\s+(CREATE|MERGE|SET|DELETE)',  # UNION injection
        r'CALL\s*\{.*?(CREATE|MERGE|SET|DELETE)',  # Subquery write attempts
        r'FOREACH\s*\(.*?(CREATE|MERGE|SET|DELETE)',  # FOREACH write attempts
    ]

    def __init__(self, strict_mode: bool = True):
        """
        Initialize the validator.

        Args:
            strict_mode: If True, blocks ALL write operations.
                        If False, only logs warnings (not recommended for production).
        """
        self._strict_mode = strict_mode
        self._logger = logging.getLogger(f"{__name__}.CypherValidator")
        # Compile injection patterns for performance
        self._injection_regexes: List[re.Pattern] = [
            re.compile(pattern, re.IGNORECASE | re.DOTALL)
            for pattern in self.INJECTION_PATTERNS
        ]

    def validate(self, query: str) -> Tuple[bool, Optional[str]]:
        """
        Validate a Cypher query for security.

        Args:
            query: The Cypher query string to validate

        Returns:
            Tuple of (is_safe, error_message)
            - is_safe: True if query is safe to execute
            - error_message: Description of security violation if unsafe, None otherwise
        """
        if not query or not query.strip():
            return False, "Empty query"

        # Normalize query for analysis
        normalized = self._normalize_query(query)

        # Check for write keywords
        violation = self._check_write_keywords(normalized)
        if violation:
            return False, violation

        # Check for schema modification keywords
        violation = self._check_schema_keywords(normalized)
        if violation:
            return False, violation

        # Check for admin operations
        violation = self._check_admin_keywords(normalized)
        if violation:
            return False, violation

        # Check for injection patterns
        violation = self._check_injection_patterns(query)
        if violation:
            return False, violation

        return True, None

    def _normalize_query(self, query: str) -> str:
        """Normalize query for keyword detection"""
        # Remove string literals to avoid false positives
        # Remove single-quoted strings
        normalized = re.sub(r"'[^']*'", "''", query)
        # Remove double-quoted strings
        normalized = re.sub(r'"[^"]*"', '""', normalized)
        # Remove backtick-quoted identifiers
        normalized = re.sub(r'`[^`]*`', '``', normalized)
        # Convert to uppercase for keyword matching
        return normalized.upper()

    def _check_write_keywords(self, normalized_query: str) -> Optional[str]:
        """Check for write operation keywords"""
        for keyword in self.WRITE_KEYWORDS:
            # Use word boundary matching to avoid false positives
            pattern = r'\b' + keyword.replace(' ', r'\s+') + r'\b'
            if re.search(pattern, normalized_query):
                return f"SECURITY VIOLATION: Write operation '{keyword}' is not allowed. This system is read-only."

        return None

    def _check_schema_keywords(self, normalized_query: str) -> Optional[str]:
        """Check for schema modification keywords"""
        for keyword in self.SCHEMA_KEYWORDS:
            pattern = r'\b' + keyword.replace(' ', r'\s+') + r'\b'
            if re.search(pattern, normalized_query):
                return f"SECURITY VIOLATION: Schema modification '{keyword}' is not allowed."

        return None

    def _check_admin_keywords(self, normalized_query: str) -> Optional[str]:
        """Check for administrative operation keywords"""
        for keyword in self.ADMIN_KEYWORDS:
            if keyword.upper() in normalized_query:
                return f"SECURITY VIOLATION: Administrative operation '{keyword}' is not allowed."

        return None

    def _check_injection_patterns(self, original_query: str) -> Optional[str]:
        """Check for potential injection attack patterns"""
        for regex in self._injection_regexes:
            if regex.search(original_query):
                return "SECURITY VIOLATION: Potential injection attack detected. Query contains suspicious patterns."

        return None


# Global validator instance
_cypher_validator = CypherQueryValidator(strict_mode=True)


# ============================================================================
# Input Prompt Validator (Prompt Injection Prevention)
# ============================================================================

class InputPromptValidator:
    """
    Security guardrail to detect malicious user input prompts.
    Blocks prompt injection attempts and sneaky write requests.
    """

    # Patterns that indicate user trying to manipulate the agent
    PROMPT_INJECTION_PATTERNS = [
        # Direct write requests
        r'(?i)\b(create|insert|add|write|update|modify|delete|remove|drop)\s+(a\s+)?(new\s+)?(node|relationship|edge|index|constraint)',
        r'(?i)\b(add|insert)\s+(this|that|a|an|the)\s+\w+\s+(to|into)\s+(the\s+)?(graph|database|neo4j)',
        r'(?i)\brun\s+(this\s+)?(create|merge|set|delete|remove)',

        # Role override attempts
        r'(?i)ignore\s+(your\s+)?(previous|prior|above)\s+(instructions?|rules?|constraints?)',
        r'(?i)forget\s+(everything|all)\s+(you\s+)?know',
        r'(?i)you\s+are\s+now\s+(a|an)\s+\w+\s+(that\s+can|with\s+permission)',
        r'(?i)pretend\s+(you\s+)?(are|have|can)',
        r'(?i)act\s+as\s+(if\s+)?(you\s+)?(have|are|can)',
        r'(?i)bypass\s+(the\s+)?(security|validation|check|filter)',

        # System prompt extraction
        r'(?i)what\s+(is|are)\s+(your|the)\s+(system\s+)?prompt',
        r'(?i)show\s+me\s+(your|the)\s+(system\s+)?instructions?',
        r'(?i)repeat\s+(your|the)\s+(initial|system|first)\s+(prompt|instructions?)',

        # Cypher injection via natural language
        r'(?i)execute\s+(this|the\s+following)\s+(cypher|query):\s*["\']?(CREATE|MERGE|SET|DELETE)',
        r'(?i)run\s+(exactly|literally):\s*["\']?(CREATE|MERGE|SET|DELETE)',

        # Hidden instruction attempts
        r'<!--.*?(CREATE|MERGE|DELETE|ignore|bypass).*?-->',
        r'\[INST\].*?(CREATE|MERGE|DELETE|ignore).*?\[/INST\]',
    ]

    # Suspicious keywords that warrant extra scrutiny
    SUSPICIOUS_KEYWORDS = [
        'inject', 'injection', 'exploit', 'hack', 'bypass',
        'override', 'jailbreak', 'escape', 'privilege', 'admin',
        'sudo', 'root', 'execute raw', 'raw query', 'direct access'
    ]

    def __init__(self, strict_mode: bool = True):
        self._strict_mode = strict_mode
        self._injection_regexes: List[re.Pattern] = [
            re.compile(pattern, re.IGNORECASE | re.DOTALL)
            for pattern in self.PROMPT_INJECTION_PATTERNS
        ]

    def validate(self, user_input: str) -> Tuple[bool, Optional[str]]:
        """
        Validate user input for potential injection attacks.

        Returns:
            Tuple of (is_safe, error_message)
        """
        if not user_input or not user_input.strip():
            return True, None  # Empty input is safe

        # Check for prompt injection patterns
        for regex in self._injection_regexes:
            if regex.search(user_input):
                return False, "PROMPT INJECTION: Potential prompt manipulation detected."

        # Check for suspicious keywords (require 2+ to trigger)
        input_lower = user_input.lower()
        found_suspicious = [kw for kw in self.SUSPICIOUS_KEYWORDS if kw in input_lower]
        if len(found_suspicious) >= 2:
            return False, f"PROMPT INJECTION: Suspicious keywords detected: {found_suspicious}"

        return True, None


# Global input validator instance
_input_validator = InputPromptValidator(strict_mode=True)


# Tools that require Cypher query validation
# Maps tool name patterns to the parameter containing the query
CYPHER_QUERY_TOOLS = {
    # Standard neo4j server naming
    "mcp__neo4j__neo4j_execute_query": "query",
    "mcp__neo4j__neo4j_batch_execute_queries": "queries",
    # neo4j_memory server naming (common alias)
    "mcp__neo4j_memory__neo4j_execute_query": "query",
    "mcp__neo4j_memory__neo4j_batch_execute_queries": "queries",
    # Direct tool names (non-MCP)
    "neo4j_execute_query": "query",
    "neo4j_batch_execute_queries": "queries",
}

# ============================================================================
# Known MCP Server Tools (for auto-populating allowed_tools)
# ============================================================================
# Maps MCP server name patterns to their known READ-ONLY tools
# Write/delete operations are intentionally excluded for security

MCP_SERVER_TOOLS = {
    # Neo4j MCP server tools - READ ONLY (matches any server name containing "neo4j")
    "neo4j": [
        "neo4j_execute_query",      # Queries are validated by CypherQueryValidator hook
        "neo4j_get_version",
        "neo4j_get_schema",
    ],
    # Qdrant MCP server tools - READ ONLY (matches any server name containing "qdrant")
    # Note: Qdrant MCP uses hyphens in tool names (qdrant-find, not qdrant_find)
    "qdrant": [
        "qdrant-find",              # Search/retrieve vectors (read-only)
        "qdrant-list-collections",  # List collections (if available)
    ],
    # Chroma MCP server tools - READ ONLY (matches any server name containing "chroma")
    "chroma": [
        "chroma_query",             # Search/retrieve vectors
        "chroma_list_collections",  # List collections
        "chroma_get_collection",    # Get collection metadata
    ],
}


def get_tools_for_mcp_servers(server_names: List[str]) -> List[str]:
    """
    Get list of allowed READ-ONLY tools for the given MCP server names.
    Automatically maps server names to their known tools.
    Write/delete operations are excluded for security.

    Args:
        server_names: List of MCP server names (e.g., ["neo4j_memory", "qdrant_server"])

    Returns:
        List of fully qualified tool names (e.g., ["mcp__neo4j_memory__neo4j_execute_query"])
    """
    allowed_tools = []

    for server_name in server_names:
        server_name_lower = server_name.lower()

        # Check each known server type
        for server_type, tools in MCP_SERVER_TOOLS.items():
            if server_type in server_name_lower:
                # Add fully qualified tool names for this server
                for tool in tools:
                    qualified_name = f"mcp__{server_name}__{tool}"
                    if qualified_name not in allowed_tools:
                        allowed_tools.append(qualified_name)

    return allowed_tools


def _get_query_param_for_tool(tool_name: str) -> Optional[str]:
    """Get the query parameter name for a tool, handling various naming patterns."""
    # Direct match first
    if tool_name in CYPHER_QUERY_TOOLS:
        return CYPHER_QUERY_TOOLS[tool_name]

    # Pattern-based matching for any neo4j-like MCP server
    if "neo4j" in tool_name.lower():
        if "execute_query" in tool_name and "batch" not in tool_name.lower():
            return "query"
        if "batch_execute" in tool_name.lower() or "batch_queries" in tool_name.lower():
            return "queries"

    return None


async def pre_tool_use_hook(
    hook_input: PreToolUseHookInput,
    _tool_use_id: Optional[str],
    _context: HookContext
) -> SyncHookJSONOutput:
    """
    PreToolUse hook that validates Cypher queries before execution.

    This hook is called BEFORE each tool is executed, even for allowed tools.
    Blocks write operations (CREATE, MERGE, DELETE, etc.) on Neo4j.
    """
    logger = logging.getLogger(f"{__name__}.QueryValidator")
    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    # Check if this is a Neo4j query tool (using flexible pattern matching)
    query_param = _get_query_param_for_tool(tool_name)

    if query_param and query_param in tool_input:
        query_value = tool_input[query_param]

        queries_to_validate = []
        if isinstance(query_value, str):
            queries_to_validate = [query_value]
        elif isinstance(query_value, list):
            for q in query_value:
                if isinstance(q, str):
                    queries_to_validate.append(q)
                elif isinstance(q, dict) and "query" in q:
                    queries_to_validate.append(q["query"])

        for query in queries_to_validate:
            is_safe, error_message = _cypher_validator.validate(query)
            if not is_safe:
                logger.warning(f"BLOCKED query in {tool_name}: {error_message}")
                return SyncHookJSONOutput(
                    continue_=True,
                    decision="block",
                    reason=f"Query blocked: {error_message}",
                    systemMessage=f"Security: {error_message}"
                )

    return SyncHookJSONOutput(continue_=True)


# ============================================================================
# Request/Response Models
# ============================================================================

class Message(BaseModel):
    role: str
    content: str


class JsonSchema(BaseModel):
    """JSON Schema definition for structured output."""
    name: str
    description: Optional[str] = None
    schema_: Dict[str, Any] = Field(alias="schema")
    strict: Optional[bool] = False

    model_config = {"populate_by_name": True}


class ResponseFormat(BaseModel):
    """
    Response format specification for structured output.

    Supports:
    - {"type": "text"} - Default text response
    - {"type": "json_object"} - Force valid JSON output
    - {"type": "json_schema", "json_schema": {...}} - Force JSON matching a specific schema
    """
    type: str = "text"  # "text", "json_object", or "json_schema"
    json_schema: Optional[JsonSchema] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 4096
    stream: Optional[bool] = False

    # Structured output
    response_format: Optional[ResponseFormat] = None

    # MCP/Tool options
    mcp_servers: Optional[Dict[str, Any]] = None  # Per-request MCP config
    allowed_tools: Optional[List[str]] = None  # Specific tools to allow (e.g., ["mcp__neo4j__execute_query"])
    tools: Optional[List[str]] = None  # Legacy: dynamic tool names
    max_turns: Optional[int] = 10  # Max agentic turns
    permission_mode: str = "acceptEdits"  # Auto-accept tool uses (bypassPermissions blocked when running as root)
    enable_query_validation: bool = True  # ALWAYS enabled by default - validates Cypher queries to block write operations
    enable_input_validation: bool = True  # ALWAYS enabled by default - validates user input to block prompt injection


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: str


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Usage
    tools_used: Optional[List[str]] = None  # Track which tools were used


class StreamChoice(BaseModel):
    index: int
    delta: Dict[str, Any]
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[StreamChoice]


# ============================================================================
# Tool Management Models
# ============================================================================

class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]
    code: str  # Python code for the tool function


class ToolInfo(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]
    registered_at: float


class LoadConfigRequest(BaseModel):
    config_path: str


# ============================================================================
# MCP Server Registry
# ============================================================================

class McpServerRegistry:
    """Manages external MCP server configurations."""

    def __init__(self):
        self.servers: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def load_from_file(self, config_path: str) -> Dict[str, Any]:
        """Load MCP config from JSON file."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"MCP config not found: {config_path}")

        with open(path) as f:
            config = json.load(f)

        # Handle nested mcpServers format (Claude Code style)
        if "mcpServers" in config:
            servers = config["mcpServers"]
        else:
            servers = config

        async with self._lock:
            self.servers.update(servers)

        return servers

    async def add_server(self, name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Add or update an MCP server configuration."""
        async with self._lock:
            self.servers[name] = config
        return {"status": "success", "server": name, "config": config}

    async def remove_server(self, name: str) -> Dict[str, Any]:
        """Remove an MCP server configuration."""
        async with self._lock:
            if name not in self.servers:
                raise KeyError(f"Server '{name}' not found")
            del self.servers[name]
        return {"status": "success", "message": f"Server '{name}' removed"}

    def get_servers(self) -> Dict[str, Dict[str, Any]]:
        """Get all configured MCP servers."""
        return self.servers.copy()

    def get_merged_config(self, request_servers: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Merge global servers with per-request servers."""
        merged = self.servers.copy()
        if request_servers:
            merged.update(request_servers)
        return merged


# ============================================================================
# Dynamic Tool Registry (for in-process tools)
# ============================================================================

class ToolRegistry:
    """Manages dynamically loaded tools."""

    def __init__(self):
        self.tools: Dict[str, Callable] = {}
        self.tool_info: Dict[str, ToolInfo] = {}
        self.mcp_server = None
        self._lock = asyncio.Lock()

    async def register_tool(self, definition: ToolDefinition) -> dict:
        """Register a new tool from code."""
        async with self._lock:
            # Validate tool name
            if definition.name in self.tools:
                raise ValueError(f"Tool '{definition.name}' already exists")

            # Create namespace for tool execution
            namespace = {
                'tool': tool,
                '__builtins__': __builtins__,
            }

            try:
                # Execute the tool code
                exec(definition.code, namespace)

                # Find the tool function (should be the last defined function)
                tool_func = None
                for name, obj in namespace.items():
                    if callable(obj) and not name.startswith('_') and name != 'tool':
                        tool_func = obj
                        break

                if tool_func is None:
                    raise ValueError("No callable function found in tool code")

                # Wrap with @tool decorator
                decorated_func = tool(
                    name=definition.name,
                    description=definition.description,
                    input_schema=definition.input_schema
                )(tool_func)

                # Store the tool
                self.tools[definition.name] = decorated_func
                self.tool_info[definition.name] = ToolInfo(
                    name=definition.name,
                    description=definition.description,
                    input_schema=definition.input_schema,
                    registered_at=time.time()
                )

                # Recreate MCP server with all tools
                await self._rebuild_mcp_server()

                return {
                    "status": "success",
                    "message": f"Tool '{definition.name}' registered successfully",
                    "tool": self.tool_info[definition.name].model_dump()
                }

            except Exception as e:
                raise ValueError(f"Failed to register tool: {str(e)}")

    async def unregister_tool(self, tool_name: str) -> dict:
        """Remove a registered tool."""
        async with self._lock:
            if tool_name not in self.tools:
                raise ValueError(f"Tool '{tool_name}' not found")

            del self.tools[tool_name]
            del self.tool_info[tool_name]

            # Recreate MCP server
            await self._rebuild_mcp_server()

            return {
                "status": "success",
                "message": f"Tool '{tool_name}' removed"
            }

    async def _rebuild_mcp_server(self):
        """Rebuild the MCP server with current tools."""
        if self.tools:
            self.mcp_server = create_sdk_mcp_server(
                name="dynamic_tools",
                version="1.0.0",
                tools=list(self.tools.values())
            )
        else:
            self.mcp_server = None

    def get_tool_names(self) -> List[str]:
        """Get list of all tool names for ClaudeAgentOptions."""
        return [f"mcp__dynamic_tools__{name}" for name in self.tools.keys()]

    def list_tools(self) -> List[ToolInfo]:
        """List all registered tools."""
        return list(self.tool_info.values())


# ============================================================================
# Claude Agent SDK Adapter
# ============================================================================

class ClaudeCodeAdapter:
    """Adapter with MCP server and dynamic tool support."""

    MODEL_MAP = {
        "claude-sonnet-4.5": "claude-sonnet-4-5",
        "claude-haiku-4.5": "claude-haiku-4-5",
        "claude-opus-4.5": "claude-opus-4-5",
        "claude-3-5-sonnet-20241022": "claude-sonnet-4-5",
        "claude-3-haiku-20240307": "claude-haiku-4-5",
        "gpt-4o": "claude-sonnet-4-5",
        "gpt-4": "claude-sonnet-4-5",
        "gpt-4o-mini": "claude-haiku-4-5",
        "gpt-3.5-turbo": "claude-haiku-4-5",
    }

    def __init__(self, mcp_registry: McpServerRegistry, tool_registry: ToolRegistry):
        if not CLAUDE_SDK_AVAILABLE:
            raise RuntimeError("Claude Agent SDK not installed")
        self.mcp_registry = mcp_registry
        self.tool_registry = tool_registry

    def _map_model(self, model: str) -> str:
        return self.MODEL_MAP.get(model, "claude-haiku-4-5")

    def _format_messages(self, messages: List[Message]) -> str:
        prompt_parts = []
        for msg in messages:
            if msg.role == "system":
                prompt_parts.append(f"System: {msg.content}")
            elif msg.role == "user":
                prompt_parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                prompt_parts.append(f"Assistant: {msg.content}")
        return "\n\n".join(prompt_parts)

    def _build_output_format(self, response_format: Optional[ResponseFormat]) -> Optional[Dict[str, Any]]:
        """
        Build native output_format dict for ClaudeAgentOptions from response_format.

        Returns a dict compatible with Claude Agent SDK's output_format parameter,
        or None if no structured output is needed.
        """
        if not response_format or response_format.type == "text":
            return None

        if response_format.type == "json_object":
            # For json_object, use a permissive schema that accepts any valid JSON object
            return {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "additionalProperties": True
                }
            }

        if response_format.type == "json_schema" and response_format.json_schema:
            schema = response_format.json_schema
            return {
                "type": "json_schema",
                "schema": schema.schema_
            }

        return None

    def _build_options(self, request: ChatCompletionRequest) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions from request with MCP support."""
        logger = logging.getLogger(f"{__name__}.options")
        claude_model = self._map_model(request.model)

        options_kwargs = {
            "model": claude_model,
            "max_turns": request.max_turns or 10
        }

        # Merge MCP server configs (global + per-request)
        mcp_servers = self.mcp_registry.get_merged_config(request.mcp_servers)
        logger.info(f"MCP servers config: {mcp_servers}")

        # Add dynamic tools MCP server if tools are registered
        if self.tool_registry.mcp_server:
            mcp_servers["dynamic_tools"] = self.tool_registry.mcp_server

        # Set MCP servers if any are configured
        if mcp_servers:
            options_kwargs["mcp_servers"] = mcp_servers

        # Determine allowed tools
        if request.allowed_tools:
            # Explicit allowed_tools specified - use as-is
            options_kwargs["allowed_tools"] = request.allowed_tools
        elif request.tools:
            # Legacy: dynamic tool names
            available_tools = self.tool_registry.get_tool_names()
            requested_tools = [f"mcp__dynamic_tools__{t}" for t in request.tools]
            options_kwargs["allowed_tools"] = [t for t in requested_tools if t in available_tools]
        elif mcp_servers:
            # Auto-populate allowed_tools from known MCP server tools (READ-ONLY only)
            server_names = list(mcp_servers.keys())
            auto_allowed = get_tools_for_mcp_servers(server_names)
            if auto_allowed:
                logger.info(f"Auto-populated allowed_tools for servers {server_names}: {auto_allowed}")
                options_kwargs["allowed_tools"] = auto_allowed
            # If no known tools, don't set allowed_tools - let SDK handle discovery
        else:
            # No MCP servers and no tools = inference only
            options_kwargs["allowed_tools"] = []

        # Set permission mode (defaults to bypassPermissions since we have our own security hooks)
        options_kwargs["permission_mode"] = request.permission_mode

        # Add the PreToolUse hook for query validation (ALWAYS enabled by default)
        # This validates Cypher queries before execution to block write operations
        if request.enable_query_validation:
            # Use hooks for validation - works even with allowed_tools
            # Match any neo4j-related tool from any MCP server naming convention
            neo4j_hook_matcher = HookMatcher(
                matcher=".*neo4j.*execute.*",  # Regex pattern to catch all neo4j query tools
                hooks=[pre_tool_use_hook],
                timeout=30
            )
            options_kwargs["hooks"] = {
                "PreToolUse": [neo4j_hook_matcher]
            }

        # Add structured output format if specified (native SDK support)
        output_format = self._build_output_format(request.response_format)
        if output_format:
            options_kwargs["output_format"] = output_format
            logger.info(f"Using native structured output: {output_format}")

        logger.info(f"ClaudeAgentOptions: {options_kwargs}")
        return ClaudeAgentOptions(**options_kwargs)

    async def create_completion(
        self,
        request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Create chat completion with MCP and tool support."""
        prompt = self._format_messages(request.messages)

        # Validate user input for prompt injection (if enabled)
        if request.enable_input_validation:
            # Validate only the user messages, not the full formatted prompt
            for msg in request.messages:
                if msg.role == "user":
                    is_safe, error_msg = _input_validator.validate(msg.content)
                    if not is_safe:
                        logger = logging.getLogger(f"{__name__}.InputValidator")
                        logger.warning(f"BLOCKED input: {error_msg}")
                        # Return early with a security message
                        return ChatCompletionResponse(
                            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            created=int(time.time()),
                            model=self._map_model(request.model),
                            choices=[
                                Choice(
                                    index=0,
                                    message=Message(
                                        role="assistant",
                                        content=f"I cannot process this request. {error_msg}"
                                    ),
                                    finish_reason="stop"
                                )
                            ],
                            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                            tools_used=None
                        )

        options = self._build_options(request)

        response_text = ""
        tools_used = []
        prompt_tokens = 0
        completion_tokens = 0

        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            response_text += block.text
                        elif isinstance(block, ToolUseBlock):
                            tools_used.append(block.name)
                            response_text += f"\n[Tool: {block.name}]"

                elif isinstance(message, ResultMessage):
                    # Check for structured output (native SDK support)
                    if hasattr(message, 'structured_output') and message.structured_output is not None:
                        # Use structured output as the response (guaranteed valid JSON)
                        response_text = json.dumps(message.structured_output)
                        logger = logging.getLogger(f"{__name__}.StructuredOutput")
                        logger.info("Using native structured_output from SDK")

                    # Try to get actual token usage from result
                    if hasattr(message, 'usage') and message.usage:
                        prompt_tokens = getattr(message.usage, 'input_tokens', 0)
                        completion_tokens = getattr(message.usage, 'output_tokens', 0)
                    else:
                        prompt_tokens = len(prompt) // 4
                        completion_tokens = len(response_text) // 4

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
            created=int(time.time()),
            model=self._map_model(request.model),
            choices=[
                Choice(
                    index=0,
                    message=Message(role="assistant", content=response_text),
                    finish_reason="stop"
                )
            ],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens
            ),
            tools_used=tools_used if tools_used else None
        )

    async def create_completion_stream(
        self,
        request: ChatCompletionRequest
    ):
        """Create streaming completion with MCP and tool support."""
        prompt = self._format_messages(request.messages)

        # Validate user input for prompt injection (if enabled)
        if request.enable_input_validation:
            for msg in request.messages:
                if msg.role == "user":
                    is_safe, error_msg = _input_validator.validate(msg.content)
                    if not is_safe:
                        logger = logging.getLogger(f"{__name__}.InputValidator")
                        logger.warning(f"BLOCKED input (stream): {error_msg}")
                        # Yield error as stream chunk
                        error_chunk = ChatCompletionChunk(
                            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            created=int(time.time()),
                            model=self._map_model(request.model),
                            choices=[
                                StreamChoice(
                                    index=0,
                                    delta={"content": f"I cannot process this request. {error_msg}"},
                                    finish_reason="stop"
                                )
                            ]
                        )
                        yield f"data: {error_chunk.model_dump_json()}\n\n"
                        yield "data: [DONE]\n\n"
                        return

        options = self._build_options(request)

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        created = int(time.time())
        model = self._map_model(request.model)

        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            chunk = ChatCompletionChunk(
                                id=completion_id,
                                created=created,
                                model=model,
                                choices=[
                                    StreamChoice(index=0, delta={"content": block.text})
                                ]
                            )
                            yield f"data: {chunk.model_dump_json()}\n\n"
                        elif isinstance(block, ToolUseBlock):
                            # Emit tool use as a chunk
                            chunk = ChatCompletionChunk(
                                id=completion_id,
                                created=created,
                                model=model,
                                choices=[
                                    StreamChoice(index=0, delta={"content": f"\n[Tool: {block.name}]"})
                                ]
                            )
                            yield f"data: {chunk.model_dump_json()}\n\n"

        # Final chunk
        final_chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[StreamChoice(index=0, delta={}, finish_reason="stop")]
        )
        yield f"data: {final_chunk.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"


# ============================================================================
# FastAPI Server
# ============================================================================

mcp_registry = McpServerRegistry()
tool_registry = ToolRegistry()
adapter: ClaudeCodeAdapter = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global adapter

    if not CLAUDE_SDK_AVAILABLE:
        raise RuntimeError("Claude Agent SDK required. Install: pip install claude-agent-sdk")

    adapter = ClaudeCodeAdapter(mcp_registry, tool_registry)

    # Load MCP config from environment if specified
    mcp_config_path = os.getenv("CLAUDE_MCP_CONFIG")
    if mcp_config_path:
        try:
            servers = await mcp_registry.load_from_file(mcp_config_path)
            print(f"✅ Loaded MCP servers from {mcp_config_path}: {list(servers.keys())}")
        except Exception as e:
            print(f"⚠️  Failed to load MCP config: {e}")

    print("✅ Claude Code Adapter with MCP Support ready")

    yield

    print("Shutting down...")


app = FastAPI(
    title="Claude Code Adapter with MCP Support",
    description="OpenAI-compatible API with MCP server integration",
    version="3.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Server info and available endpoints."""
    return {
        "message": "Claude Code Adapter with MCP Support",
        "version": "3.0.0",
        "endpoints": {
            "chat": "/v1/chat/completions",
            "models": "/v1/models",
            "mcp_servers": {
                "list": "GET /v1/mcp/servers",
                "add": "POST /v1/mcp/servers",
                "remove": "DELETE /v1/mcp/servers/{name}",
                "load_config": "POST /v1/mcp/load"
            },
            "tools": {
                "list": "GET /v1/tools",
                "register": "POST /v1/tools",
                "remove": "DELETE /v1/tools/{name}"
            }
        },
        "mcp_servers": list(mcp_registry.get_servers().keys()),
        "dynamic_tools": [t.name for t in tool_registry.list_tools()]
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "claude-sonnet-4.5",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "claude-code"
            },
            {
                "id": "claude-haiku-4.5",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "claude-code"
            }
        ]
    }


@app.post("/v1/chat/completions")
async def create_chat_completion(request: ChatCompletionRequest):
    """OpenAI-compatible chat completions with optional tools."""
    if not adapter:
        raise HTTPException(status_code=500, detail="Adapter not initialized")

    try:
        if request.stream:
            return StreamingResponse(
                adapter.create_completion_stream(request),
                media_type="text/event-stream"
            )
        else:
            response = await adapter.create_completion(request)
            return response.model_dump()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Tool Management Endpoints
# ============================================================================

@app.get("/v1/tools")
async def list_tools():
    """List all registered tools."""
    tools = tool_registry.list_tools()
    return {
        "object": "list",
        "data": [t.model_dump() for t in tools]
    }


@app.post("/v1/tools")
async def register_tool(definition: ToolDefinition):
    """Register a new tool."""
    try:
        result = await tool_registry.register_tool(definition)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/v1/tools/{tool_name}")
async def delete_tool(tool_name: str):
    """Remove a registered tool."""
    try:
        result = await tool_registry.unregister_tool(tool_name)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# MCP Server Management Endpoints
# ============================================================================

@app.get("/v1/mcp/servers")
async def list_mcp_servers():
    """List all configured MCP servers."""
    servers = mcp_registry.get_servers()
    return {
        "object": "list",
        "data": [
            {"name": name, "config": config}
            for name, config in servers.items()
        ]
    }


@app.post("/v1/mcp/servers")
async def add_mcp_servers(servers: Dict[str, Dict[str, Any]]):
    """Add one or more MCP server configurations."""
    results = []
    for name, config in servers.items():
        result = await mcp_registry.add_server(name, config)
        results.append(result)
    return {"status": "success", "servers_added": list(servers.keys())}


@app.delete("/v1/mcp/servers/{server_name}")
async def remove_mcp_server(server_name: str):
    """Remove an MCP server configuration."""
    try:
        result = await mcp_registry.remove_server(server_name)
        return result
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/v1/mcp/load")
async def load_mcp_config(request: LoadConfigRequest):
    """Load MCP servers from a config file."""
    try:
        servers = await mcp_registry.load_from_file(request.config_path)
        return {
            "status": "success",
            "servers_loaded": list(servers.keys())
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    port = int(os.getenv("CLAUDE_ADAPTER_PORT", "8889"))

    print("=" * 70)
    print("CLAUDE CODE ADAPTER WITH MCP SUPPORT")
    print("=" * 70)
    print(f"\n🚀 Starting server on http://localhost:{port}")
    print("\n📝 Features:")
    print("  • OpenAI-compatible chat completions")
    print("  • External MCP server support (http, sse, stdio)")
    print("  • Dynamic tool registration")
    print("  • Per-request MCP configuration")
    print("\n💡 Configure MCP servers:")
    print("  • Set CLAUDE_MCP_CONFIG=/path/to/config.json")
    print("  • Or POST to /v1/mcp/servers")
    print("  • Or pass mcp_servers in each request")
    print("\n📋 Endpoints:")
    print("  • POST /v1/chat/completions - Chat with MCP tools")
    print("  • GET  /v1/mcp/servers      - List MCP servers")
    print("  • POST /v1/mcp/servers      - Add MCP servers")
    print("  • POST /v1/mcp/load         - Load from config file")
    print("  • GET  /v1/tools            - List dynamic tools")
    print("  • POST /v1/tools            - Register dynamic tool")
    print("=" * 70)

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
