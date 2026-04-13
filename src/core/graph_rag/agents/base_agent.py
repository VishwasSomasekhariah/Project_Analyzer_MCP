"""
Base Agent class for the Graph RAG Multi-Agent system.

Provides common functionality for all agents including token tracking
and LLM communication.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.core.graph_rag.core.enums import AgentRole
from src.core.graph_rag.core.config import LLMConfig, SystemConfig
from src.core.graph_rag.core.metrics import TokenUsage, AggregatedTokenUsage


class BaseAgent(ABC):
    """Base class for all agents with token tracking"""

    # Shared token tracker across all agents (class-level)
    _token_tracker: Optional[AggregatedTokenUsage] = None

    @classmethod
    def set_token_tracker(cls, tracker: AggregatedTokenUsage) -> None:
        """Set a shared token tracker for all agents"""
        cls._token_tracker = tracker

    @classmethod
    def get_token_tracker(cls) -> Optional[AggregatedTokenUsage]:
        """Get the shared token tracker"""
        return cls._token_tracker

    def __init__(
        self,
        openai_client: OpenAI,
        llm_config: LLMConfig,
        role: AgentRole,
        config: SystemConfig,
        agent_id: Optional[str] = None
    ):
        """
        Initialize the base agent.

        Args:
            openai_client: OpenAI client instance
            llm_config: LLM configuration
            role: Agent role enum
            config: System configuration
            agent_id: Optional unique agent identifier
        """
        self._openai = openai_client
        self._llm_config = llm_config
        self._model = llm_config.model  # For backwards compatibility
        self._role = role
        self._config = config
        self._agent_id = agent_id or role.value
        self._logger = logging.getLogger(f"{__name__}.{role.value}")

    @property
    def role(self) -> AgentRole:
        return self._role

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @abstractmethod
    async def execute(self, *args, **kwargs) -> Any:
        """Execute the agent's primary function"""
        pass

    # Subclasses should define ALLOWED_TOOLS for per-agent SDK fallback
    ALLOWED_TOOLS: List[str] = []

    def _create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        response_format: Optional[Dict] = None
    ):
        """Create a chat completion with token tracking and LLM config parameters"""
        # Start with LLM config parameters (model, temperature, etc.)
        kwargs = self._llm_config.to_openai_kwargs()
        kwargs["messages"] = messages

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if response_format:
            kwargs["response_format"] = response_format

        # Add agent context for per-agent SDK fallback
        # This enables per-agent tool restrictions when Claude SDK is used
        # Use SDK_ALLOWED_TOOLS (fully qualified MCP names) if available,
        # otherwise fall back to ALLOWED_TOOLS (short names)
        sdk_tools = getattr(self, 'SDK_ALLOWED_TOOLS', None) or getattr(self, 'ALLOWED_TOOLS', None)
        if sdk_tools:
            kwargs["agent_context"] = {
                "agent_id": self._agent_id,
                "allowed_tools": sdk_tools
            }

        response = self._openai.chat.completions.create(**kwargs)

        # Track token usage
        if response.usage and self._token_tracker:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                model=self._model,
                agent_role=self._role.value,
                agent_id=self._agent_id
            )
            self._token_tracker.add(usage)

        return response


__all__ = ['BaseAgent']
