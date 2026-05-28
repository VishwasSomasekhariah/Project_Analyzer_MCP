"""
Prompts module for the Graph RAG Multi-Agent system.

Centralized prompt management for all agents. Prompts can be imported
from here for use in agents or for customization.
"""

from src.core.graph_rag.prompts.agent_prompts import (
    TOT_DECOMPOSITION_PROMPT,
    TOT_SYNTHESIS_PROMPT,
    COT_SYSTEM_PROMPT,
    VERIFICATION_SYSTEM_PROMPT,
    ENTITY_RESOLUTION_SYSTEM_PROMPT,
    CPG_OBSERVER_ANALYSIS_PROMPT,
    PromptTemplates,
)

__all__ = [
    'TOT_DECOMPOSITION_PROMPT',
    'TOT_SYNTHESIS_PROMPT',
    'COT_SYSTEM_PROMPT',
    'VERIFICATION_SYSTEM_PROMPT',
    'ENTITY_RESOLUTION_SYSTEM_PROMPT',
    'CPG_OBSERVER_ANALYSIS_PROMPT',
    'PromptTemplates',
]
