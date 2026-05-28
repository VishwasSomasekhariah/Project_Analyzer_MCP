"""
Token usage and performance metrics for the Graph RAG Multi-Agent system.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    """Token usage tracking for a single LLM call"""
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    model: str = Field(default="")
    agent_role: str = Field(default="")
    agent_id: Optional[str] = Field(default=None)


class AggregatedTokenUsage(BaseModel):
    """Aggregated token usage across all agents"""
    total_prompt_tokens: int = Field(default=0)
    total_completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    by_agent_role: Dict[str, int] = Field(default_factory=dict)
    by_agent_id: Dict[str, int] = Field(default_factory=dict)
    call_count: int = Field(default=0)
    details: List[TokenUsage] = Field(default_factory=list)

    def add(self, usage: TokenUsage) -> None:
        """Add token usage from a single call"""
        self.total_prompt_tokens += usage.prompt_tokens
        self.total_completion_tokens += usage.completion_tokens
        self.total_tokens += usage.total_tokens
        self.call_count += 1

        # Track by role
        if usage.agent_role:
            self.by_agent_role[usage.agent_role] = self.by_agent_role.get(usage.agent_role, 0) + usage.total_tokens

        # Track by agent ID
        if usage.agent_id:
            self.by_agent_id[usage.agent_id] = self.by_agent_id.get(usage.agent_id, 0) + usage.total_tokens

        self.details.append(usage)


__all__ = [
    'TokenUsage',
    'AggregatedTokenUsage',
]
