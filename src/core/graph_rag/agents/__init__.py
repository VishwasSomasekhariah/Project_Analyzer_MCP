"""
Agents for the Graph RAG Multi-Agent system.

Includes Chain-of-Thought (CoT), Verification, Entity Resolution,
CPG Observer, and 4-Agent Team agents.
"""

from .base_agent import BaseAgent
from .cot_agent import CoTAgent
from .verification_agent import VerificationAgent
from .entity_resolution_agent import EntityResolutionAgent
from .cpg_observer import CPGObserverAgent

# 4-Agent Team
from .thinker_agent import ThinkerAgent
from .thinking_validator_agent import ThinkingValidatorAgent
from .cypher_validator_agent import CypherValidatorAgent
from .executor_verifier_agent import ExecutorVerifierAgent

__all__ = [
    'BaseAgent',
    'CoTAgent',
    'VerificationAgent',
    'EntityResolutionAgent',
    'CPGObserverAgent',
    # 4-Agent Team
    'ThinkerAgent',
    'ThinkingValidatorAgent',
    'CypherValidatorAgent',
    'ExecutorVerifierAgent',
]
