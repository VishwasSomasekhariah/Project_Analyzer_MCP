"""
Claude SDK Fallback Client for Hybrid Workflow.

Provides direct integration with Claude Agent SDK for fallback when
the primary LLM provider (OpenAI) is unavailable during query operations.

Copied from genpod-semantic-rag implementation for isolated testing.
This is ONLY used at query time for intent analysis, synthesis, and validation.
"""

import asyncio
import json
import logging
import concurrent.futures
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Claude's built-in tools that we want to block
# We're providing code context in the prompt, so Claude shouldn't need to read files
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
    "EnterPlanMode",
    "ExitPlanMode",
    "AskUserQuestion",
])


@dataclass
class ClaudeSDKResponse:
    """Response from Claude SDK formatted for compatibility with AIService."""

    content: str
    """The text response from Claude."""

    # model: str = "claude-sonnet-4-5-20250514"
    model: str = "claude-opus-4-6"
    """Model used for the response."""

    usage: Optional[Dict[str, Any]] = None
    """Token usage information."""

    cost_usd: Optional[float] = None
    """Cost of the request in USD."""

    session_id: Optional[str] = None
    """Claude SDK session ID for multi-turn conversations."""

    structured_output: Optional[Dict[str, Any]] = None
    """Structured output when using output_format (already validated JSON dict)."""


class ClaudeSDKFallback:
    """
    Direct Claude SDK fallback client for query-time LLM operations.

    Uses ClaudeSDKClient directly when OpenAI is unavailable.
    Designed for response generation, NOT for embeddings or preprocessing.

    Usage:
        fallback = ClaudeSDKFallback(
            model="claude-opus-4-6",
            system_prompt="You are a code analysis assistant..."
        )

        response = await fallback.query("Explain this code pattern")
        print(response.content)
    """

    def __init__(
        self,
        # model: str = "claude-sonnet-4-5-20250514",
        model: str = "claude-opus-4-6",
        system_prompt: Optional[str] = None,
        max_turns: int = 10,
        mcp_config_path: Optional[str] = None,
        mcp_servers: Optional[Dict[str, Dict[str, Any]]] = None,
        max_buffer_size: int = 10 * 1024 * 1024,  # 10MB default
        timeout_seconds: int = 300,
        block_builtin_tools: bool = True,  # Block Claude's built-in tools by default
        allowed_tools: Optional[List[str]] = None,
        disallowed_tools: Optional[List[str]] = None,
    ):
        """
        Initialize the Claude SDK fallback client.

        Args:
            model: Claude model to use
            system_prompt: System prompt for Claude
            max_turns: Maximum agentic turns
            mcp_config_path: Path to MCP config file (optional)
            mcp_servers: MCP server configurations (optional)
            max_buffer_size: Maximum JSON message buffer size
            timeout_seconds: Timeout for queries
            block_builtin_tools: If True, blocks Claude's built-in tools (Bash, Read, Write, etc.)
            allowed_tools: Whitelist of allowed tools (None = allow all non-blocked tools)
            disallowed_tools: Blacklist of disallowed tools
        """
        self._logger = logging.getLogger(f"{__name__}.ClaudeSDKFallback")

        # Claude SDK options
        self._model = model
        self._system_prompt = system_prompt
        self._max_turns = max_turns
        self._max_buffer_size = max_buffer_size
        self._timeout_seconds = timeout_seconds

        # Tool restrictions
        self._block_builtin_tools = block_builtin_tools
        self._allowed_tools = allowed_tools or []
        self._disallowed_tools = list(disallowed_tools or [])

        # Add built-in tools to disallowed list if blocking is enabled
        if block_builtin_tools:
            self._disallowed_tools.extend(CLAUDE_BUILTIN_TOOLS)
            self._logger.info(
                f"Blocking {len(CLAUDE_BUILTIN_TOOLS)} Claude built-in tools: "
                f"{', '.join(sorted(CLAUDE_BUILTIN_TOOLS))}"
            )

        # MCP configuration (optional)
        self._mcp_servers: Dict[str, Any] = {}
        if mcp_config_path:
            self._load_mcp_config(mcp_config_path)
        if mcp_servers:
            self._mcp_servers.update(mcp_servers)

        self._logger.info(
            f"ClaudeSDKFallback initialized: model={model}, "
            f"max_turns={max_turns}, mcp_servers={len(self._mcp_servers)}, "
            f"builtin_tools_blocked={block_builtin_tools}"
        )

    def _build_hooks(self, HookMatcher, SyncHookJSONOutput) -> Dict:
        """
        Build hooks configuration for tool blocking and transparency.

        Args:
            HookMatcher: HookMatcher class from claude_agent_sdk
            SyncHookJSONOutput: SyncHookJSONOutput class from claude_agent_sdk.types

        Returns:
            Dictionary of hooks compatible with ClaudeAgentOptions
        """
        if not self._block_builtin_tools:
            return {}

        hooks = {}

        # Pre-tool hook to block built-in tools and provide transparency
        async def pre_tool_hook_with_blocking(hook_input, tool_use_id, context):
            tool_name = hook_input.get("tool_name", "")
            tool_input = hook_input.get("tool_input", {})

            # Log all tool usage attempts for transparency
            self._logger.info("┌" + "─" * 78 + "┐")
            self._logger.info(f"│ 🔧 TOOL CALL ATTEMPT: {tool_name:<60} │")

            # Show tool arguments if present
            if tool_input:
                input_str = str(tool_input)[:60]
                self._logger.info(f"│    Arguments: {input_str:<60} │")

            # Block built-in tools
            if tool_name in CLAUDE_BUILTIN_TOOLS:
                self._logger.warning(f"│ 🚫 STATUS: BLOCKED{' ' * 62} │")
                self._logger.warning(f"│    Reason: Built-in tools are disabled - context provided{' ' * 13} │")
                self._logger.info("└" + "─" * 78 + "┘")

                # Return a hook response that blocks the tool
                return SyncHookJSONOutput(
                    continue_=True,  # Continue conversation but deny the tool
                    hookSpecificOutput={
                        'hookEventName': 'PreToolUse',
                        'permissionDecision': 'deny',
                        'permissionDecisionReason': (
                            f"Built-in tool '{tool_name}' is blocked. "
                            f"All code context is provided in the prompt - you don't need to read files."
                        )
                    }
                )

            # Allow the tool
            self._logger.info(f"│ ✅ STATUS: ALLOWED{' ' * 61} │")
            self._logger.info("└" + "─" * 78 + "┘")
            return SyncHookJSONOutput(continue_=True)

        hooks["PreToolUse"] = [
            HookMatcher(matcher=".*", hooks=[pre_tool_hook_with_blocking])
        ]

        return hooks

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

        Args:
            response_format: OpenAI-style response format dict

        Returns:
            Claude SDK compatible output_format dict or None
        """
        if not response_format:
            return None

        format_type = response_format.get("type")

        if format_type == "json_object":
            # Simple JSON object mode without schema
            self._logger.info("Enabling JSON output mode (json_object)")
            return {"type": "json_object"}

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
        temperature: float = 0.7,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> ClaudeSDKResponse:
        """
        Send a query to Claude via the SDK.

        Args:
            prompt: The user's query/prompt
            system_prompt: Override system prompt for this query
            max_turns: Override max turns for this query
            temperature: Sampling temperature (note: SDK may not support this directly)
            response_format: Optional OpenAI-style response format for structured output
                           Examples:
                           - {"type": "json_object"} - Simple JSON mode
                           - {"type": "json_schema", "json_schema": {"name": "...", "schema": {...}}}

        Returns:
            ClaudeSDKResponse with the response content and metadata
        """
        try:
            from claude_agent_sdk import (
                ClaudeSDKClient,
                ClaudeAgentOptions,
                AssistantMessage,
                ResultMessage,
                TextBlock,
                HookMatcher,
            )
            from claude_agent_sdk.types import SyncHookJSONOutput
        except ImportError as e:
            self._logger.error(f"claude_agent_sdk not installed: {e}")
            raise RuntimeError(
                "claude_agent_sdk is required for Claude SDK fallback. "
                "Install with: pip install genpod-semantic-rag[fallback]"
            ) from e

        effective_system_prompt = system_prompt or self._system_prompt

        # Build hooks with tool blocking
        hooks = self._build_hooks(HookMatcher, SyncHookJSONOutput)

        # Build output format for structured JSON responses
        output_format = self._build_output_format(response_format)

        # Build options
        options_kwargs = {
            "model": self._model,
            "system_prompt": effective_system_prompt,
            "max_turns": max_turns or self._max_turns,
            "max_buffer_size": self._max_buffer_size,
        }

        # Add MCP servers if configured
        if self._mcp_servers:
            options_kwargs["mcp_servers"] = self._mcp_servers

        # Add tool restrictions
        if self._allowed_tools:
            options_kwargs["allowed_tools"] = self._allowed_tools
        if self._disallowed_tools:
            options_kwargs["disallowed_tools"] = self._disallowed_tools

        # Add hooks for tool blocking and transparency
        if hooks:
            options_kwargs["hooks"] = hooks

        # Add output_format if JSON response is requested
        if output_format:
            options_kwargs["output_format"] = output_format

        options = ClaudeAgentOptions(**options_kwargs)

        # Detailed logging
        self._logger.info("─" * 80)
        self._logger.info("🤖 Claude SDK Query Configuration:")
        self._logger.info(f"   Model: {self._model}")
        self._logger.info(f"   Max turns: {max_turns or self._max_turns}")
        self._logger.info(f"   Temperature: {temperature}")
        self._logger.info(f"   JSON mode: {output_format is not None} {f'({output_format})' if output_format else ''}")
        self._logger.info(f"   Tool blocking enabled: {self._block_builtin_tools}")
        self._logger.info(f"   Disallowed tools: {len(self._disallowed_tools)} tools")
        self._logger.info(f"   Hooks enabled: {hooks is not None and len(hooks) > 0}")
        self._logger.info(f"   Prompt length: {len(prompt)} chars")
        self._logger.info(f"   System prompt length: {len(effective_system_prompt) if effective_system_prompt else 0} chars")
        self._logger.info("─" * 80)
        self._logger.info(f"📤 Prompt preview (first 300 chars):")
        self._logger.info(f"   {prompt[:300]}...")
        self._logger.info("─" * 80)

        response_text = ""
        result_message = None

        try:
            self._logger.info("🔌 Connecting to Claude SDK client...")
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)

                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                response_text += block.text

                    elif isinstance(message, ResultMessage):
                        result_message = message
                        # Debug logging for ResultMessage fields
                        self._logger.info(f"📩 ResultMessage received:")
                        self._logger.info(f"   - type: {type(message).__name__}")
                        self._logger.info(f"   - has structured_output: {hasattr(message, 'structured_output')}")
                        if hasattr(message, 'structured_output'):
                            self._logger.info(f"   - structured_output value: {message.structured_output}")
                        if hasattr(message, 'subtype'):
                            self._logger.info(f"   - subtype: {message.subtype}")
                        self._logger.info(f"   - dir(message): {[attr for attr in dir(message) if not attr.startswith('_')]}")

            response = ClaudeSDKResponse(
                content=response_text,
                model=self._model,
                usage=result_message.usage if result_message else None,
                cost_usd=result_message.total_cost_usd if result_message else None,
                session_id=result_message.session_id if result_message else None,
                structured_output=result_message.structured_output if result_message and hasattr(result_message, 'structured_output') else None,
            )

            # Detailed response logging
            self._logger.info("─" * 80)
            self._logger.info("✅ Claude SDK Response Received:")
            self._logger.info(f"   Response length: {len(response_text)} chars")
            if result_message:
                if result_message.usage:
                    self._logger.info(f"   Token usage: {result_message.usage}")
                if result_message.total_cost_usd:
                    self._logger.info(f"   Cost: ${result_message.total_cost_usd:.4f}")
                if result_message.session_id:
                    self._logger.info(f"   Session ID: {result_message.session_id}")
                if hasattr(result_message, 'structured_output') and result_message.structured_output:
                    self._logger.info(f"   ✨ Structured output: YES (already validated JSON)")
                    self._logger.info(f"   📊 Structured output preview: {str(result_message.structured_output)[:200]}")
            self._logger.info(f"📥 Complete Response Content:")
            self._logger.info(f"{response_text}")
            self._logger.info("─" * 80)

            return response

        except Exception as e:
            self._logger.error(f"Claude SDK query failed: {e}")
            raise

    def query_sync(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_turns: Optional[int] = None,
        temperature: float = 0.7,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> ClaudeSDKResponse:
        """
        Synchronous wrapper for query().

        Handles both cases:
        1. No running event loop: uses asyncio.run()
        2. Running event loop: runs in a separate thread

        Args:
            prompt: The user's query/prompt
            system_prompt: Override system prompt for this query
            max_turns: Override max turns for this query
            temperature: Sampling temperature
            response_format: Optional OpenAI-style response format for structured output
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
                    temperature=temperature,
                    response_format=response_format,
                )
            )

        # There's a running loop - run in a separate thread
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
                        temperature=temperature,
                        response_format=response_format,
                    )
                )
            finally:
                new_loop.close()

        # Use ThreadPoolExecutor to run in separate thread
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_thread)
            return future.result(timeout=self._timeout_seconds)

    @property
    def is_available(self) -> bool:
        """Check if Claude SDK is available."""
        try:
            import claude_agent_sdk
            return True
        except ImportError:
            return False

    @property
    def model(self) -> str:
        """Get the configured model."""
        return self._model


__all__ = ['ClaudeSDKFallback', 'ClaudeSDKResponse']
