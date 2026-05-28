"""
Resilient LLM Service with Claude SDK fallback.

Wraps the existing LLMService and adds automatic fallback to Claude SDK
when OpenAI/Anthropic is unavailable. Adapted from genpod-semantic-rag's pattern.

For easy rollback: just switch back to using LLMService directly.
"""

import logging
from typing import Any, Dict, Optional

from openai import APIConnectionError, APIError, RateLimitError, APITimeoutError

# ClaudeSDKFallback is imported lazily inside _initialize_fallback to avoid circular imports

# Import LLMService and its response type
from .llm_service import LLMService, LLMResponse, LLMModel

logger = logging.getLogger(__name__)


class ResilientLLMService:
    """
    LLM service wrapper with automatic Claude SDK fallback.

    This is a drop-in replacement for LLMService that adds fallback capabilities.
    When OpenAI/Anthropic fails (connection error, rate limit, timeout), it
    automatically falls back to Claude SDK.

    Usage:
        # Instead of:
        llm_service = LLMService(config)

        # Use:
        llm_service = ResilientLLMService(config)

        # For easy rollback, just change back to LLMService
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the resilient LLM service.

        Args:
            config: Configuration dictionary with fallback settings
                   - use_claude_sdk_fallback: bool - Enable fallback (default: True)
                   # - fallback_model: str - Claude model (default: claude-sonnet-4-5-20250929)
                   - fallback_model: str - Claude model (default: claude-opus-4-6)
                   - fallback_system_prompt: str - System prompt for Claude (optional)
                   - fallback_max_turns: int - Max agentic turns (default: 10)
                   - fallback_timeout: int - Timeout in seconds (default: 300)
                   - mcp_config_path: str - Path to MCP config for Claude SDK (optional)
        """
        self._logger = logging.getLogger(f"{__name__}.ResilientLLMService")
        self.config = config or {}

        # Primary service (OpenAI/Anthropic)
        self._primary = LLMService(config)

        # Fallback client (Claude SDK) - only initialized if enabled
        self._fallback: Optional[Any] = None
        self._fallback_available = False

        # Circuit breaker state
        self._primary_disabled = False
        self._primary_disable_reason: Optional[str] = None

        # Initialize fallback if enabled (default: True)
        fallback_enabled = self.config.get("use_claude_sdk_fallback", True)
        if fallback_enabled:
            self._initialize_fallback()

        self._logger.info(
            f"ResilientLLMService initialized: "
            f"fallback_enabled={fallback_enabled}, "
            f"fallback_available={self._fallback_available}"
        )

    def _initialize_fallback(self) -> None:
        """Initialize the Claude SDK fallback client."""
        try:
            # Lazy import to avoid circular imports at module load time
            from .hybrid_workflow_V2.claude_sdk_fallback import ClaudeSDKFallback

            # Get MCP config path from config or auto-detect
            mcp_config_path = self.config.get("mcp_config_path")

            # Get fallback config
            model = self.config.get("fallback_model", "claude-sonnet-4-6")
            system_prompt = self.config.get("fallback_system_prompt", None)
            max_turns = self.config.get("fallback_max_turns", 10)
            timeout = self.config.get("fallback_timeout", 300)
            max_buffer_size = self.config.get("fallback_max_buffer_size", 10 * 1024 * 1024)

            self._fallback = ClaudeSDKFallback(
                model=model,
                system_prompt=system_prompt,
                max_turns=max_turns,
                mcp_config_path=mcp_config_path,
                max_buffer_size=max_buffer_size,
                timeout_seconds=timeout,
                block_builtin_tools=True,  # Block Claude's built-in tools
            )

            self._fallback_available = self._fallback.is_available
            if self._fallback_available:
                self._logger.info(f"✅ Claude SDK fallback initialized: model={model}")
            else:
                self._logger.warning(
                    "⚠️ Claude SDK not available (claude-agent-sdk not installed). "
                    "Install with: pip install claude-agent-sdk"
                )

        except Exception as e:
            self._logger.error(f"❌ Failed to initialize Claude SDK fallback: {e}")
            self._fallback_available = False

    # =========================================================================
    # Circuit Breaker Methods
    # =========================================================================

    def disable_primary(self, reason: str = "manually disabled") -> None:
        """
        Disable the primary LLM, forcing all calls to use fallback.

        Call this when you know the primary is down (rate limited, quota exceeded, etc.)
        to avoid repeated failed attempts.

        Args:
            reason: Why primary was disabled (for logging)
        """
        if not self._primary_disabled:
            self._primary_disabled = True
            self._primary_disable_reason = reason
            self._logger.warning(
                f"⚠️ Primary LLM disabled: {reason}. All calls will use fallback."
            )

    def enable_primary(self) -> None:
        """Re-enable the primary LLM."""
        if self._primary_disabled:
            self._primary_disabled = False
            self._logger.info(
                f"✅ Primary LLM re-enabled (was disabled: {self._primary_disable_reason})"
            )
            self._primary_disable_reason = None

    @property
    def is_primary_disabled(self) -> bool:
        """Check if primary LLM is currently disabled."""
        return self._primary_disabled

    # =========================================================================
    # Main API Methods with Fallback
    # =========================================================================

    async def generate_response(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: LLMModel = LLMModel.GPT4O,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        json_mode: bool = False,
        use_cache: bool = True
    ) -> LLMResponse:
        """
        Generate response with automatic Claude SDK fallback.

        This is the main method used by hybrid workflow nodes.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            model: LLM model to use
            max_tokens: Maximum tokens to generate
            temperature: Temperature for randomness
            json_mode: Force JSON response format
            use_cache: Whether to use caching

        Returns:
            LLMResponse with content and metadata
        """
        # If primary is disabled, go straight to fallback
        if self._primary_disabled:
            self._logger.debug(
                f"Primary LLM disabled ({self._primary_disable_reason}), using fallback"
            )
            return await self._generate_response_fallback(
                prompt, system_prompt, temperature, max_tokens, json_mode
            )

        # Try primary first
        try:
            self._logger.debug(f"🤖 Calling primary LLM: model={model.value}")
            response = await self._primary.generate_response(
                prompt=prompt,
                system_prompt=system_prompt,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
                use_cache=use_cache
            )

            # Check if primary returned an error
            if response.error:
                self._logger.warning(f"⚠️ Primary LLM returned error: {response.error}")
                self._handle_primary_error(response.error)
                if self._fallback_available:
                    return await self._generate_response_fallback(
                        prompt, system_prompt, temperature, max_tokens, json_mode
                    )

            return response

        except (APIConnectionError, APITimeoutError, RateLimitError) as e:
            self._logger.warning(
                f"⚠️ Primary LLM failed with recoverable error: {type(e).__name__}: {e}"
            )
            self._handle_rate_limit_error(e)
            if self._fallback_available:
                return await self._generate_response_fallback(
                    prompt, system_prompt, temperature, max_tokens, json_mode
                )
            raise

        except APIError as e:
            if hasattr(e, 'status_code') and e.status_code in (500, 502, 503, 504):
                self._logger.warning(f"⚠️ Primary LLM server error ({e.status_code}): {e}")
                if self._fallback_available:
                    return await self._generate_response_fallback(
                        prompt, system_prompt, temperature, max_tokens, json_mode
                    )
            raise

        except Exception as e:
            error_str = str(e).lower()
            if "429" in str(e) or "quota" in error_str or "rate" in error_str or "exceeded" in error_str:
                self._logger.warning(f"⚠️ Primary LLM failed with quota-like error: {e}")
                self.disable_primary(f"Quota/rate error: {type(e).__name__}")
                if self._fallback_available:
                    return await self._generate_response_fallback(
                        prompt, system_prompt, temperature, max_tokens, json_mode
                    )
            raise

    def _handle_primary_error(self, error: str) -> None:
        """Handle error returned by primary LLM."""
        error_lower = error.lower()
        if "429" in error or "quota" in error_lower or "rate" in error_lower or "exceeded" in error_lower:
            self.disable_primary(f"Primary returned error: {error}")

    def _handle_rate_limit_error(self, e: Exception) -> None:
        """Handle rate limit errors and potentially disable primary."""
        if isinstance(e, RateLimitError):
            error_msg = str(e).lower()
            if "quota" in error_msg or "exceeded" in error_msg:
                self.disable_primary(f"Quota exceeded: {type(e).__name__}")
            else:
                self.disable_primary(f"Rate limited: {type(e).__name__}")

    async def _generate_response_fallback(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        json_mode: bool
    ) -> LLMResponse:
        """Generate response using Claude SDK fallback."""
        if not self._fallback or not self._fallback_available:
            self._logger.error("❌ Fallback not available")
            return LLMResponse(
                content="",
                model="unknown",
                usage={},
                cost_estimate=0.0,
                latency_ms=0,
                provider="none",
                error="Fallback not available"
            )

        self._logger.info("=" * 80)
        self._logger.info("🔄 CLAUDE SDK FALLBACK ACTIVATED - Hybrid Workflow")
        self._logger.info("=" * 80)
        self._logger.info(f"📝 Prompt length: {len(prompt)} chars")
        if system_prompt:
            self._logger.info(f"⚙️  System prompt length: {len(system_prompt)} chars")
        self._logger.info(f"🌡️  Temperature: {temperature}")
        self._logger.info(f"🔢 Max tokens: {max_tokens}")
        self._logger.info(f"📋 JSON mode: {json_mode}")

        try:
            # Query Claude SDK
            self._logger.info("🚀 Sending request to Claude SDK...")

            # Prepare response format for JSON mode
            response_format = None
            if json_mode:
                response_format = {"type": "json_object"}

            response = self._fallback.query_sync(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                response_format=response_format,
            )

            self._logger.info("✅ Claude SDK response received successfully")
            self._logger.info(f"📏 Response length: {len(response.content)} chars")
            if response.usage:
                self._logger.info(f"💰 Token usage: {response.usage}")
            if response.cost_usd:
                self._logger.info(f"💵 Cost: ${response.cost_usd:.4f}")
            self._logger.info("=" * 80)

            # Strip markdown code fences if present (Claude sometimes adds them even with JSON mode)
            content = response.content or ""
            if content.startswith("```json"):
                # Remove ```json at start and ``` at end
                content = content[7:]  # Remove ```json\n
                if content.endswith("```"):
                    content = content[:-3]  # Remove ```
                content = content.strip()
                self._logger.info("📝 Stripped markdown code fences from JSON response")
            elif content.startswith("```"):
                # Remove ``` at start and end
                content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                self._logger.info("📝 Stripped markdown code fences from response")

            # Convert ClaudeSDKResponse to LLMResponse
            return LLMResponse(
                content=content,
                model=response.model,
                usage=response.usage or {},
                cost_estimate=response.cost_usd or 0.0,
                latency_ms=0,  # Claude SDK doesn't track this
                provider="claude_sdk",
                cached=False,
                error=None
            )

        except Exception as e:
            self._logger.error(f"❌ Claude SDK fallback failed: {e}")
            return LLMResponse(
                content="",
                model="unknown",
                usage={},
                cost_estimate=0.0,
                latency_ms=0,
                provider="claude_sdk",
                error=str(e)
            )

    # =========================================================================
    # Pass-through Methods for Compatibility
    # =========================================================================

    def get_usage_stats(self) -> Dict[str, Any]:
        """Get LLM usage statistics."""
        stats = self._primary.get_usage_stats()
        stats["fallback_enabled"] = self._fallback_available
        stats["primary_disabled"] = self._primary_disabled
        if self._primary_disabled:
            stats["primary_disable_reason"] = self._primary_disable_reason
        return stats

    def clear_cache(self):
        """Clear the response cache."""
        self._primary.clear_cache()
