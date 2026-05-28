"""
Enumerations for the Graph RAG Multi-Agent system.
"""

from enum import Enum


class ConfidenceLevel(str, Enum):
    """Confidence level for findings and verifications"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class VerificationStatus(str, Enum):
    """Status of claim verification"""
    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"
    PARTIALLY_VERIFIED = "partially_verified"
    NEEDS_CORRECTION = "needs_correction"  # Query logic is wrong, feedback provided
    ERROR = "error"


class AgentRole(str, Enum):
    """Role identifiers for different agent types"""
    TOT_ORCHESTRATOR = "tot_orchestrator"
    COT_AGENT = "cot_agent"
    VERIFIER = "verifier"
    ENTITY_RESOLVER = "entity_resolver"
    CPG_OBSERVER = "cpg_observer"
    IR_PLANNER = "ir_planner"  # New: IR-based query planner
    # 4-Agent Team roles
    THINKER = "thinker"
    THINKING_VALIDATOR = "thinking_validator"
    CYPHER_VALIDATOR = "cypher_validator"
    EXECUTOR_VERIFIER = "executor_verifier"


__all__ = [
    'ConfidenceLevel',
    'VerificationStatus',
    'AgentRole',
]
