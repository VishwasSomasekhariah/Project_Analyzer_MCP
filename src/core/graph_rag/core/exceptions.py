"""
Custom exceptions for the Graph RAG Multi-Agent system.
"""


class MultiAgentError(Exception):
    """Base exception for multi-agent system"""
    pass


class AgentExecutionError(MultiAgentError):
    """Error during agent execution"""
    pass


class VerificationError(MultiAgentError):
    """Error during claim verification"""
    pass


class QueryDecompositionError(MultiAgentError):
    """Error during query decomposition"""
    pass


class ToolExecutionError(MultiAgentError):
    """Error during tool execution"""
    pass


class LLMResponseError(MultiAgentError):
    """Error parsing LLM response"""
    pass


class CypherSecurityError(MultiAgentError):
    """Security violation in Cypher query - attempted write operation"""
    pass


class ConfigurationError(MultiAgentError):
    """Configuration error - missing or invalid configuration"""
    pass


__all__ = [
    'MultiAgentError',
    'AgentExecutionError',
    'VerificationError',
    'QueryDecompositionError',
    'ToolExecutionError',
    'LLMResponseError',
    'CypherSecurityError',
    'ConfigurationError',
]
