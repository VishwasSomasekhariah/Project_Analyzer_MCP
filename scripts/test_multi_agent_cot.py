"""
Tree-of-Thought (ToT) Orchestrator with Chain-of-Thought (CoT) Agents
for Code Analysis over Neo4j Code Property Graph

Production-ready implementation with:
- Pydantic models for all data structures
- Structured LLM outputs with guardrails
- Comprehensive error handling and security validation
- Retry logic with exponential backoff
- Token usage tracking for transparency
- Type safety throughout

Architecture:
┌─────────────────────────────────────────────────────────────────┐
│                    ToT ORCHESTRATOR                             │
│  - Receives user query                                          │
│  - Tree-of-Thought decomposition into sub-queries               │
│  - Does NOT see graph schema (prevents schema/data confusion)   │
│  - Orchestrates CoT agents and verification                     │
│  - Synthesizes final answer about ACTUAL codebase               │
└─────────────────────────────────────────────────────────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │ CoT Agent #1 │  │ CoT Agent #2 │  │ CoT Agent #N │
    │  Has schema  │  │  Has schema  │  │  Has schema  │
    │  tools       │  │  tools       │  │  tools       │
    └──────────────┘  └──────────────┘  └──────────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │  VERIFICATION AGENT    │
                 │  Has schema tools      │
                 │  Verifies claims       │
                 └────────────────────────┘
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from functools import wraps

from pydantic import BaseModel, Field, field_validator, ConfigDict
from openai import OpenAI, APIError, RateLimitError, APIConnectionError

from mcp_use import MCPClient

from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
from src.core.workflow.schema_tools_langchain import create_schema_tools


# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

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


# =============================================================================
# ENUMS
# =============================================================================

class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"
    PARTIALLY_VERIFIED = "partially_verified"
    ERROR = "error"


class AgentRole(str, Enum):
    TOT_ORCHESTRATOR = "tot_orchestrator"
    COT_AGENT = "cot_agent"
    VERIFIER = "verifier"


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class CodeEntity(BaseModel):
    """Represents an actual code entity from the codebase"""
    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Name of the code entity")
    entity_type: str = Field(..., description="Type: class, function, interface, etc.")
    file_path: Optional[str] = Field(None, description="File path where entity is defined")
    node_id: Optional[int] = Field(None, description="Neo4j node ID")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Additional properties")


class Finding(BaseModel):
    """Structured finding from a worker agent"""
    model_config = ConfigDict(frozen=True)

    claim: str = Field(..., description="Natural language claim about the codebase")
    entities: List[CodeEntity] = Field(default_factory=list, description="Code entities involved")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Supporting data")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.MEDIUM)
    source_query: Optional[str] = Field(None, description="Cypher query that produced this")
    cot_agent_id: Optional[str] = Field(None, description="ID of CoT agent that produced this")


class VerificationResult(BaseModel):
    """Result from verification agent"""
    model_config = ConfigDict(frozen=True)

    claim: str = Field(..., description="The claim that was verified")
    status: VerificationStatus = Field(..., description="Verification status")
    verified_evidence: Dict[str, Any] = Field(default_factory=dict, description="Evidence from verification")
    explanation: str = Field(..., description="Explanation of verification result")
    verification_query: Optional[str] = Field(None, description="Query used for verification")


class SubQuery(BaseModel):
    """A decomposed sub-query"""
    model_config = ConfigDict(frozen=True)

    query: str = Field(..., description="The sub-query text")
    focus: str = Field(..., description="What aspect this sub-query focuses on")
    priority: int = Field(default=1, ge=1, le=5, description="Priority 1-5")


class QueryDecomposition(BaseModel):
    """Result of query decomposition"""
    model_config = ConfigDict(frozen=True)

    original_query: str = Field(..., description="Original user query")
    sub_queries: List[SubQuery] = Field(..., description="Decomposed sub-queries")
    reasoning: str = Field(..., description="Reasoning for decomposition")


class WorkerResponse(BaseModel):
    """Structured response from worker agent"""
    findings: List[Finding] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    iterations_used: int = Field(default=0)
    execution_time_ms: int = Field(default=0)


class VerifierResponse(BaseModel):
    """Structured response from verification agent"""
    result: VerificationResult
    execution_time_ms: int = Field(default=0)


class EntityCorrection(BaseModel):
    """A suggested correction for an entity name"""
    model_config = ConfigDict(frozen=True)

    original_term: str = Field(..., description="Original term from query")
    suggested_name: str = Field(..., description="Corrected/proper entity name")
    entity_type: str = Field(..., description="Type: class, function, variable, etc.")
    file_path: Optional[str] = Field(None, description="File where entity is defined")
    confidence_score: float = Field(default=0.0, description="Fuzzy match score")
    issue_type: str = Field(default="case_sensitivity", description="Issue: case_sensitivity, misspelling, etc.")


class EntityResolutionResult(BaseModel):
    """Result from entity resolution agent"""
    model_config = ConfigDict(frozen=True)

    corrections: List[EntityCorrection] = Field(default_factory=list, description="Entity corrections found")
    has_issues: bool = Field(default=False, description="Whether any issues were found")
    corrected_query: Optional[str] = Field(None, description="Query with corrections applied")
    execution_time_ms: int = Field(default=0)


# =============================================================================
# CPG OBSERVER DATA MODELS
# =============================================================================

class QueryObservation(BaseModel):
    """Record of a single query executed against the CPG"""
    timestamp: str = Field(..., description="ISO timestamp when query was executed")
    session_id: str = Field(..., description="Session ID for grouping observations")
    user_query: str = Field(..., description="Original user query")
    sub_query: Optional[str] = Field(None, description="Sub-query being answered")
    agent_id: str = Field(..., description="Which agent executed (CoT-1, Verifier, etc.)")
    cypher_query: str = Field(..., description="The actual Cypher query executed")
    result_count: int = Field(default=0, description="Number of results returned")
    is_empty: bool = Field(default=False, description="Was the result empty?")
    had_error: bool = Field(default=False, description="Did the query error?")
    error_message: Optional[str] = Field(None, description="Error message if any")
    execution_time_ms: int = Field(default=0, description="Query execution time")
    node_types_queried: List[str] = Field(default_factory=list, description="Node types in query")
    relationships_queried: List[str] = Field(default_factory=list, description="Relationships in query")
    properties_accessed: List[str] = Field(default_factory=list, description="Properties accessed")


class CPGIssue(BaseModel):
    """An identified issue or improvement opportunity in the CPG"""
    issue_id: str = Field(..., description="Unique ID for this issue")
    issue_type: str = Field(..., description="Type: missing_relationship, missing_property, inconsistency, missing_data, pattern_suggestion")
    severity: str = Field(default="medium", description="Severity: high, medium, low")
    description: str = Field(..., description="Description of the issue")
    evidence: List[str] = Field(default_factory=list, description="Queries/observations as evidence")
    suggested_fix: Optional[str] = Field(None, description="Suggested fix for CPG builder")
    related_nodes: List[str] = Field(default_factory=list, description="Related node types")
    related_relationships: List[str] = Field(default_factory=list, description="Related relationship types")
    detected_at: str = Field(..., description="When the issue was first detected")
    occurrence_count: int = Field(default=1, description="How many times observed")


class ObserverReport(BaseModel):
    """Report generated by CPG Observer Agent"""
    report_id: str = Field(..., description="Unique report ID")
    generated_at: str = Field(..., description="When report was generated")
    total_observations: int = Field(default=0, description="Total queries observed")
    total_sessions: int = Field(default=0, description="Number of user sessions observed")
    empty_result_rate: float = Field(default=0.0, description="% of queries returning empty")
    error_rate: float = Field(default=0.0, description="% of queries with errors")
    identified_issues: List[CPGIssue] = Field(default_factory=list, description="Issues found")
    query_patterns: Dict[str, int] = Field(default_factory=dict, description="Common query patterns")
    missing_relationships: List[str] = Field(default_factory=list, description="Relationships users expect but don't exist")
    missing_properties: List[str] = Field(default_factory=list, description="Properties users expect but don't exist")
    improvement_suggestions: List[str] = Field(default_factory=list, description="Actionable improvements")
    summary: str = Field(default="", description="Executive summary")


class ObserverMemory(BaseModel):
    """Persistent memory for the CPG Observer Agent - survives across sessions"""
    observations: List[QueryObservation] = Field(default_factory=list, description="All recorded observations")
    identified_issues: List[CPGIssue] = Field(default_factory=list, description="Identified issues")
    query_patterns: Dict[str, int] = Field(default_factory=dict, description="Pattern -> occurrence count")
    empty_result_queries: List[str] = Field(default_factory=list, description="Queries that returned empty")
    error_queries: List[str] = Field(default_factory=list, description="Queries that errored")
    schema_gaps_detected: List[str] = Field(default_factory=list, description="Missing schema elements")
    last_analysis_timestamp: Optional[str] = Field(None, description="When last analysis was run")
    session_count: int = Field(default=0, description="Total sessions observed")
    last_report: Optional[ObserverReport] = Field(None, description="Most recent report")


class FinalAnswer(BaseModel):
    """Final synthesized answer"""
    answer: str = Field(..., description="The synthesized answer")
    verified_claims: List[str] = Field(default_factory=list)
    unverified_claims: List[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.MEDIUM)
    total_findings: int = Field(default=0)
    verified_count: int = Field(default=0)


class Citation(BaseModel):
    """
    Citation for a claim in the response.
    Provides full traceability back to source code for manual verification.
    """
    claim: str = Field(..., description="The claim being cited")

    # Source location - where to find this in the codebase
    source_file: Optional[str] = Field(None, description="File path where evidence was found")
    source_line: Optional[int] = Field(None, description="Line number if available")
    source_location: Optional[str] = Field(None, description="Human-readable location string")

    # Entity details
    entity_name: Optional[str] = Field(None, description="Name of the code entity (class, method, etc.)")
    entity_type: Optional[str] = Field(None, description="Type of entity: Method, Class, File, etc.")

    # Evidence and verification
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Raw evidence from graph query")
    verification_status: VerificationStatus = Field(..., description="Whether claim was verified")
    verification_explanation: str = Field(default="", description="Why claim was verified/not verified")

    # Queries for reproducibility
    discovery_query: Optional[str] = Field(None, description="Cypher query that found this information")
    verification_query: Optional[str] = Field(None, description="Cypher query used to verify")

    # Metadata
    cot_agent_id: Optional[str] = Field(None, description="Which CoT agent produced this finding")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.MEDIUM)


class ProductionResponse(BaseModel):
    """
    Production-ready response from the ToT/CoT RAG Agent.
    Contains the answer, citations for traceability, and usage metrics.
    """
    # The answer
    answer: str = Field(..., description="The synthesized answer to the user's query")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.MEDIUM)

    # Citations - full traceability for each claim
    citations: List[Citation] = Field(default_factory=list, description="Citations with source locations")
    verified_count: int = Field(default=0, description="Number of verified citations")
    unverified_count: int = Field(default=0, description="Number of unverified citations")

    # Token usage for cost tracking
    token_usage: Optional[AggregatedTokenUsage] = Field(None, description="Token usage breakdown")

    # Performance metrics
    execution_time_ms: int = Field(default=0, description="Total execution time in milliseconds")
    sub_queries_count: int = Field(default=0, description="Number of sub-queries generated")
    llm_calls_count: int = Field(default=0, description="Total LLM API calls made")

    # Original query for reference
    original_query: str = Field(default="", description="The original user query")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return self.model_dump()


class MCPServerConfig(BaseModel):
    """Configuration for an MCP server connection"""
    model_config = ConfigDict(frozen=False, extra='allow')

    type: str = Field(default="http", description="Transport type: http, stdio")
    url: Optional[str] = Field(None, description="URL for HTTP/SSE transport")
    command: Optional[str] = Field(None, description="Command for stdio transport")
    args: List[str] = Field(default_factory=list, description="Arguments for stdio command")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables")


class MCPConfig(BaseModel):
    """
    MCP configuration - can be passed directly as dict or loaded from file.

    Example direct usage:
        config = SystemConfig(
            mcp_config={
                "mcpServers": {
                    "neo4j_memory": {"type": "http", "url": "http://localhost:8100/sse"}
                }
            }
        )

    Example file usage:
        config = SystemConfig(mcp_config_path="neo4j_config.json")
    """
    model_config = ConfigDict(frozen=False, populate_by_name=True)

    servers: Dict[str, MCPServerConfig] = Field(
        default_factory=dict,
        alias="mcpServers",
        description="Map of server name to server config"
    )

    @classmethod
    def from_file(cls, path: str) -> "MCPConfig":
        """Load MCP config from a JSON file"""
        with open(path, 'r') as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPConfig":
        """Create MCP config from a dictionary"""
        return cls(**data)


class LLMConfig(BaseModel):
    """
    Configuration for LLM model and parameters.

    Supports OpenAI and OpenAI-compatible APIs (Azure, Groq, Together AI, local LLMs).

    Examples:
        # OpenAI (default)
        llm_config = {"model": "gpt-4o", "temperature": 0.0}

        # Azure OpenAI
        llm_config = {
            "model": "gpt-4o",
            "base_url": "https://your-resource.openai.azure.com",
            "api_key": "your-azure-key"
        }

        # Groq
        llm_config = {
            "model": "llama-3.1-70b-versatile",
            "base_url": "https://api.groq.com/openai/v1",
            "api_key": "your-groq-key"
        }

        # Local Ollama (with OpenAI adapter)
        llm_config = {
            "model": "llama3",
            "base_url": "http://localhost:11434/v1",
            "api_key": "ollama"  # Ollama doesn't need real key
        }

        # Google Gemini (OpenAI-compatible API)
        llm_config = {
            "model": "gemini-1.5-pro",  # or gemini-1.5-flash
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "api_key": "your-google-api-key"
        }
    """
    model_config = ConfigDict(frozen=False)

    model: str = Field(default="gpt-4o", description="Model name")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(default=None, description="Max tokens in response")
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Top-p sampling")
    frequency_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0, description="Frequency penalty")
    presence_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0, description="Presence penalty")
    seed: Optional[int] = Field(default=None, description="Random seed for reproducibility")

    # Provider configuration for non-OpenAI providers
    base_url: Optional[str] = Field(default=None, description="Custom API base URL for OpenAI-compatible providers")
    api_key: Optional[str] = Field(default=None, description="API key (defaults to OPENAI_API_KEY env var)")

    def to_openai_kwargs(self) -> Dict[str, Any]:
        """Convert to OpenAI API kwargs, excluding None values"""
        kwargs = {"model": self.model, "temperature": self.temperature}
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.top_p is not None:
            kwargs["top_p"] = self.top_p
        if self.frequency_penalty is not None:
            kwargs["frequency_penalty"] = self.frequency_penalty
        if self.presence_penalty is not None:
            kwargs["presence_penalty"] = self.presence_penalty
        if self.seed is not None:
            kwargs["seed"] = self.seed
        return kwargs

    def create_client(self) -> OpenAI:
        """Create an OpenAI client configured for this LLM provider"""
        client_kwargs = {}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        if self.api_key:
            client_kwargs["api_key"] = self.api_key
        return OpenAI(**client_kwargs)


class SystemConfig(BaseModel):
    """
    Configuration for the multi-agent system.

    MCP and Schema can be configured via:
    - Direct dict (mcp_config, yaml_schema)
    - File paths (mcp_config_path, yaml_schema_path)

    LLM can be configured via:
    - Direct dict/object (llm_config) with model, temperature, etc.
    - Simple model name (llm_model) for backwards compatibility

    Examples:
        # Using file paths (backwards compatible)
        config = SystemConfig(
            mcp_config_path="neo4j_config.json",
            yaml_schema_path="/path/to/schema.yaml",
            llm_model="gpt-4o"
        )

        # Using direct config dicts
        config = SystemConfig(
            mcp_config={
                "mcpServers": {
                    "neo4j_memory": {"type": "http", "url": "http://localhost:8100/sse"}
                }
            },
            yaml_schema={"nodes": {...}, "relationships": {...}},
            llm_config={"model": "gpt-4o", "temperature": 0.0}
        )
    """
    model_config = ConfigDict(frozen=False)

    # MCP Configuration - either pass config dict directly or provide path
    mcp_config: Optional[Dict[str, Any]] = Field(default=None, description="MCP config dict (takes precedence)")
    mcp_config_path: Optional[str] = Field(default=None, description="Path to MCP config JSON file")

    # Schema Configuration - either pass dict directly or provide path
    yaml_schema: Optional[Dict[str, Any]] = Field(default=None, description="YAML schema as dict (takes precedence)")
    yaml_schema_path: Optional[str] = Field(default=None, description="Path to YAML schema file")

    # LLM Configuration - either pass config dict or use simple model name
    llm_config: Optional[Dict[str, Any]] = Field(default=None, description="LLM config dict {model, temperature, ...}")
    llm_model: str = Field(default="gpt-4o", description="Simple model name (used if llm_config not provided)")

    # Agent behavior settings
    max_cot_iterations: int = Field(default=10, ge=1, le=25, description="Max iterations per CoT agent")
    max_verifier_iterations: int = Field(default=5, ge=1, le=15, description="Max iterations for verifier")
    max_retries: int = Field(default=3, ge=1, le=5, description="Max retries on API errors")
    retry_delay_base: float = Field(default=1.0, ge=0.1, le=10.0, description="Base delay for exponential backoff")
    parallel_cot_agents: bool = Field(default=True, description="Run CoT agents in parallel")
    max_parallel_workers: int = Field(default=3, ge=1, le=10, description="Max concurrent CoT agents (prevents resource exhaustion)")
    max_sub_queries: int = Field(default=8, ge=1, le=15, description="Max sub-queries ToT can generate (prevents cost explosion)")
    verification_enabled: bool = Field(default=True, description="Enable verification step")
    entity_resolution_enabled: bool = Field(default=True, description="Enable entity resolution for case sensitivity and typos")

    def get_llm_config(self) -> LLMConfig:
        """Get effective LLM config (explicit config dict or from simple model name)"""
        if self.llm_config:
            return LLMConfig(**self.llm_config)
        return LLMConfig(model=self.llm_model)

    def get_mcp_config_dict(self) -> Dict[str, Any]:
        """Get effective MCP config as dict (explicit dict or from file path)"""
        if self.mcp_config:
            return self.mcp_config
        if self.mcp_config_path:
            with open(self.mcp_config_path, 'r') as f:
                return json.load(f)
        raise ConfigurationError("Either mcp_config or mcp_config_path must be provided")

    def get_yaml_schema(self) -> Dict[str, Any]:
        """Get effective YAML schema (explicit dict or from file path)"""
        if self.yaml_schema:
            return self.yaml_schema
        if self.yaml_schema_path:
            import yaml
            with open(self.yaml_schema_path, 'r') as f:
                return yaml.safe_load(f)
        raise ConfigurationError("Either yaml_schema or yaml_schema_path must be provided")


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


# =============================================================================
# RETRY DECORATOR
# =============================================================================

def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """Decorator for retry with exponential backoff"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (RateLimitError, APIConnectionError) as e:
                    last_exception = e
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                except APIError as e:
                    logger.error(f"API error (not retrying): {e}")
                    raise AgentExecutionError(f"API error: {e}") from e
            raise AgentExecutionError(f"Max retries exceeded: {last_exception}") from last_exception
        return wrapper
    return decorator


# =============================================================================
# CYPHER QUERY VALIDATOR - SECURITY GUARDRAIL
# =============================================================================

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
        self._logger = logging.getLogger(f"{__name__}.PromptValidator")
        import re
        self._injection_regexes = [
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
            return True, None  # Empty input is safe (will be rejected elsewhere)

        # Check for prompt injection patterns
        for regex in self._injection_regexes:
            if regex.search(user_input):
                return False, "Input rejected: Potential prompt injection detected."

        # Check for suspicious keywords
        input_lower = user_input.lower()
        found_suspicious = [kw for kw in self.SUSPICIOUS_KEYWORDS if kw in input_lower]
        if len(found_suspicious) >= 2:  # Multiple suspicious keywords
            return False, f"Input rejected: Suspicious keywords detected: {found_suspicious}"

        return True, None

    def validate_or_raise(self, user_input: str) -> None:
        """Validate and raise CypherSecurityError if unsafe."""
        is_safe, error_message = self.validate(user_input)
        if not is_safe:
            self._logger.warning(f"User input blocked: {error_message}")
            self._logger.debug(f"Blocked input: {user_input[:100]}...")
            if self._strict_mode:
                raise CypherSecurityError(error_message)

    def sanitize(self, user_input: str) -> str:
        """
        Sanitize user input by removing potentially dangerous content.
        Use when you want to clean input rather than reject it.
        """
        import re
        sanitized = user_input

        # Remove HTML-style comments
        sanitized = re.sub(r'<!--.*?-->', '', sanitized, flags=re.DOTALL)

        # Remove instruction tags
        sanitized = re.sub(r'\[INST\].*?\[/INST\]', '', sanitized, flags=re.DOTALL)
        sanitized = re.sub(r'<\|.*?\|>', '', sanitized, flags=re.DOTALL)

        # Remove embedded code blocks that look like Cypher write operations
        sanitized = re.sub(
            r'```(?:cypher)?\s*(CREATE|MERGE|SET|DELETE|REMOVE).*?```',
            '[CODE BLOCK REMOVED]',
            sanitized,
            flags=re.DOTALL | re.IGNORECASE
        )

        return sanitized.strip()


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
        import re
        self._injection_regexes = [
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
        import re
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
            import re
            pattern = r'\b' + keyword.replace(' ', r'\s+') + r'\b'
            if re.search(pattern, normalized_query):
                return f"SECURITY VIOLATION: Write operation '{keyword}' is not allowed. This system is read-only."

        return None

    def _check_schema_keywords(self, normalized_query: str) -> Optional[str]:
        """Check for schema modification keywords"""
        for keyword in self.SCHEMA_KEYWORDS:
            import re
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

    def validate_or_raise(self, query: str) -> None:
        """
        Validate query and raise CypherSecurityError if unsafe.

        Args:
            query: The Cypher query to validate

        Raises:
            CypherSecurityError: If the query is not safe
        """
        is_safe, error_message = self.validate(query)
        if not is_safe:
            self._logger.error(f"Query blocked: {error_message}")
            self._logger.debug(f"Blocked query: {query[:200]}...")
            if self._strict_mode:
                raise CypherSecurityError(error_message)
            else:
                self._logger.warning(f"Non-strict mode: {error_message}")


# =============================================================================
# MCP ADAPTER
# =============================================================================

class MCPCypherAdapter:
    """Adapts MCP session to DynamicSchemaManager interface"""

    def __init__(self, mcp_session):
        self._session = mcp_session

    async def execute_query(self, query: str, params: Optional[dict] = None) -> dict:
        """Execute a Cypher query via MCP"""
        try:
            result = await self._session.call_tool('neo4j_execute_query', {'query': query})
            if hasattr(result, 'content') and result.content:
                raw = json.loads(result.content[0].text)
                return {
                    'data': raw.get('results', raw.get('data', [])),
                    'status': 'success' if not raw.get('error') else 'error',
                    'error': raw.get('error')
                }
            return {'data': [], 'status': 'error', 'error': 'Empty response'}
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            return {'data': [], 'status': 'error', 'error': str(e)}


# =============================================================================
# MCP SESSION POOL
# =============================================================================

class MCPSessionPool:
    """
    Manages multiple MCP sessions for parallel agent execution.
    Each parallel CoT agent gets its own session to prevent SSE stream conflicts.
    """

    def __init__(self, mcp_config_dict: Dict[str, Any]):
        """
        Initialize the session pool.

        Args:
            mcp_config_dict: MCP configuration dictionary with mcpServers
        """
        self._config_dict = mcp_config_dict
        self._server_name = list(mcp_config_dict.get('mcpServers', {}).keys())[0]
        self._active_sessions: Dict[str, Any] = {}  # session_id -> (client, session)
        self._logger = logging.getLogger(f"{__name__}.MCPSessionPool")

        # Write temp config file for MCPClient (it requires a file path)
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(mcp_config_dict, f)
            self._temp_config_path = f.name

    async def acquire_session(self, session_id: Optional[str] = None) -> Tuple[str, Any]:
        """
        Acquire a new MCP session.

        Args:
            session_id: Optional unique identifier for the session

        Returns:
            Tuple of (session_id, mcp_session)
        """
        if session_id is None:
            session_id = f"session_{len(self._active_sessions) + 1}_{id(asyncio.current_task())}"

        # Create new client and session
        client = MCPClient.from_config_file(self._temp_config_path)
        session = await client.create_session(self._server_name)

        self._active_sessions[session_id] = (client, session)
        self._logger.debug(f"Acquired MCP session: {session_id}")

        return session_id, session

    async def release_session(self, session_id: str) -> None:
        """
        Release and close an MCP session.

        Args:
            session_id: The session identifier to release
        """
        if session_id not in self._active_sessions:
            self._logger.warning(f"Session {session_id} not found in pool")
            return

        client, session = self._active_sessions.pop(session_id)
        try:
            await client.close_session(self._server_name)
            self._logger.debug(f"Released MCP session: {session_id}")
        except Exception as e:
            self._logger.warning(f"Error closing session {session_id}: {e}")

    async def release_all(self) -> None:
        """Release all active sessions."""
        session_ids = list(self._active_sessions.keys())
        for session_id in session_ids:
            await self.release_session(session_id)

    @property
    def active_count(self) -> int:
        """Number of active sessions."""
        return len(self._active_sessions)


# =============================================================================
# BASE AGENT
# =============================================================================

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


# =============================================================================
# TOOL MANAGER
# =============================================================================

class ToolManager:
    """Manages tools for agents with schema access and security validation"""

    def __init__(
        self,
        mcp_session,
        schema_manager: DynamicSchemaManager,
        strict_security: bool = True,
        observer: Optional['CPGObserverAgent'] = None,
        agent_id: str = "unknown"
    ):
        self._session = mcp_session
        self._schema_manager = schema_manager
        self._query_validator = CypherQueryValidator(strict_mode=strict_security)
        self._tools: List[Dict] = []
        self._tool_map: Dict[str, Tuple[str, str]] = {}
        self._langchain_tools: Dict[str, Any] = {}
        self._logger = logging.getLogger(f"{__name__}.ToolManager")
        self._observer = observer  # Optional CPG Observer for query tracking
        self._agent_id = agent_id  # Identifies which agent is using this ToolManager
        self._current_sub_query: Optional[str] = None  # Current sub-query context
        self._build_tools()

    def set_context(self, agent_id: str = None, sub_query: str = None):
        """Set context for observation tracking"""
        if agent_id:
            self._agent_id = agent_id
        if sub_query:
            self._current_sub_query = sub_query

    def _build_tools(self):
        """Build tool definitions"""
        # MCP query tool
        self._tools.append({
            "type": "function",
            "function": {
                "name": "neo4j_execute_query",
                "description": "Execute a Cypher query against the Neo4j Code Property Graph to find ACTUAL code entities",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Cypher query to execute"
                        }
                    },
                    "required": ["query"]
                }
            }
        })
        self._tool_map['neo4j_execute_query'] = ('mcp', 'neo4j_execute_query')

        # Schema tools
        lc_tools = create_schema_tools(self._schema_manager)
        for tool in lc_tools:
            self._langchain_tools[tool.name] = tool
            schema = tool.args_schema.schema() if hasattr(tool, 'args_schema') else {"type": "object", "properties": {}}
            self._tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": schema
                }
            })
            self._tool_map[tool.name] = ('langchain', tool.name)

    @property
    def tools(self) -> List[Dict]:
        return self._tools

    async def execute_tool(self, name: str, arguments: Dict) -> str:
        """Execute a tool by name with security validation and timeout/retry for MCP calls"""
        tool_info = self._tool_map.get(name)
        if tool_info is None:
            raise ToolExecutionError(f"Unknown tool: {name}")

        tool_type, tool_name = tool_info

        # SECURITY: Validate Cypher queries before execution
        if tool_name == 'neo4j_execute_query' and 'query' in arguments:
            query = arguments.get('query', '')
            try:
                self._query_validator.validate_or_raise(query)
            except CypherSecurityError as e:
                self._logger.warning(f"BLOCKED dangerous query: {query[:100]}...")
                return json.dumps({
                    "error": str(e),
                    "security_violation": True,
                    "blocked_query": query[:50] + "..." if len(query) > 50 else query
                })

        try:
            if tool_type == 'mcp':
                # MCP tool calls with timeout and retry for connection errors
                max_mcp_retries = 3
                mcp_timeout_seconds = 60  # 60 second timeout per attempt
                last_error = None

                query_start_time = time.time()
                for attempt in range(max_mcp_retries):
                    try:
                        result = await asyncio.wait_for(
                            self._session.call_tool(tool_name, arguments),
                            timeout=mcp_timeout_seconds
                        )
                        if hasattr(result, 'content') and result.content:
                            response_text = result.content[0].text

                            # Check for Cypher syntax errors in the response and propagate them clearly
                            if tool_name == 'neo4j_execute_query':
                                response_text = self._handle_cypher_response(response_text, arguments.get('query', ''))

                                # OBSERVER: Record this query execution (non-blocking)
                                if self._observer:
                                    try:
                                        execution_time_ms = int((time.time() - query_start_time) * 1000)
                                        self._observer.observe_query(
                                            cypher_query=arguments.get('query', ''),
                                            result=response_text,
                                            agent_id=self._agent_id,
                                            sub_query=self._current_sub_query,
                                            execution_time_ms=execution_time_ms
                                        )
                                    except Exception as obs_err:
                                        # Never let observer errors affect main workflow
                                        self._logger.debug(f"Observer error (non-critical): {obs_err}")

                            return response_text
                        return json.dumps({"error": "Empty MCP response"})

                    except asyncio.TimeoutError as e:
                        last_error = e
                        self._logger.warning(f"MCP tool call timeout (attempt {attempt + 1}/{max_mcp_retries}): {tool_name}")
                        if attempt < max_mcp_retries - 1:
                            await asyncio.sleep(1.0 * (attempt + 1))  # Backoff
                            continue
                    except Exception as e:
                        # Catch connection errors and retry
                        error_str = str(e).lower()
                        if 'connection' in error_str or 'sse' in error_str or 'post_writer' in error_str:
                            last_error = e
                            self._logger.warning(f"MCP connection error (attempt {attempt + 1}/{max_mcp_retries}): {e}")
                            if attempt < max_mcp_retries - 1:
                                await asyncio.sleep(1.0 * (attempt + 1))  # Backoff
                                continue
                        raise  # Non-connection errors should be raised immediately

                # All retries exhausted
                self._logger.error(f"MCP tool call failed after {max_mcp_retries} attempts: {last_error}")
                return json.dumps({"error": f"MCP call failed after {max_mcp_retries} retries: {last_error}"})

            elif tool_type == 'langchain':
                lc_tool = self._langchain_tools.get(tool_name)
                if lc_tool:
                    result = await lc_tool.ainvoke(arguments)
                    return json.dumps(result) if isinstance(result, dict) else str(result)

            return json.dumps({"error": f"Unknown tool type: {tool_type}"})

        except CypherSecurityError:
            raise  # Re-raise security errors
        except Exception as e:
            self._logger.error(f"Tool execution error ({name}): {e}")
            return json.dumps({"error": str(e)})

    def _handle_cypher_response(self, response_text: str, query: str) -> str:
        """
        Handle Cypher query response - log errors but propagate original response.
        The original error from Neo4j/MCP is passed through unchanged for transparency.
        """
        try:
            response_data = json.loads(response_text)

            # Log errors for debugging but propagate original response unchanged
            if 'error' in response_data:
                error_msg = response_data.get('error', '')
                self._logger.warning(f"Cypher query error: {error_msg}")
                self._logger.debug(f"Failed query: {query}")

        except json.JSONDecodeError:
            pass

        # Always return the original response - let the agent see the real error
        return response_text


# =============================================================================
# COT AGENT (Chain-of-Thought)
# =============================================================================

class CoTAgent(BaseAgent):
    """
    Chain-of-Thought Agent - Has schema tools access.
    Executes sub-queries using step-by-step reasoning and returns findings about ACTUAL code entities.
    """

    SYSTEM_PROMPT = """You are a Data Retrieval Agent for code analysis. Your job is to find ACTUAL code entities from the codebase stored in a Neo4j Code Property Graph.

CRITICAL RULES:
1. Return information about ACTUAL code in the codebase:
   - Real class names (e.g., "WorkerA", "Helper", "WorkerFactory")
   - Real function names (e.g., "CreateWorkers", "FormatMessage")
   - Real file paths (e.g., "HelloWorldApp/WorkerA.cs")
   - Real code snippets from the 'body' property
   - Real relationships between actual code entities

2. DO NOT describe the graph schema structure. Never say:
   - "Type nodes contain Function nodes" [WRONG]
   - "The CALLS relationship connects Function to Function" [WRONG]

3. INSTEAD say things like:
   - "The WorkerFactory class contains the CreateWorkers method" [CORRECT]
   - "WorkerA.DoWork calls Helper.FormatMessage" [CORRECT]

4. Use schema tools to write correct Cypher queries, but findings must be about actual code.

OUTPUT FORMAT (JSON):
{
  "findings": [
    {
      "claim": "Clear statement about actual code",
      "entities": [
        {"name": "EntityName", "entity_type": "class/function/etc", "file_path": "path/to/file.cs"}
      ],
      "evidence": {"property_name": "value from graph"},
      "confidence": "high/medium/low",
      "source_query": "MATCH query used"
    }
  ]
}"""

    def __init__(
        self,
        tool_manager: ToolManager,
        openai_client: OpenAI,
        llm_config: LLMConfig,
        config: SystemConfig,
        cot_agent_id: str
    ):
        super().__init__(openai_client, llm_config, AgentRole.COT_AGENT, config, agent_id=cot_agent_id)
        self._tool_manager = tool_manager
        self._cot_agent_id = cot_agent_id

    @retry_with_backoff(max_retries=3)
    async def execute(self, subquery: SubQuery) -> WorkerResponse:
        """Execute a sub-query using chain-of-thought reasoning"""
        start_time = time.time()
        self._logger.info(f"CoT Agent {self._cot_agent_id} executing: {subquery.query[:50]}...")

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": f"Find information for: {subquery.query}\n\nFocus area: {subquery.focus}"}
        ]

        findings = []
        errors = []
        iterations = 0

        for iteration in range(self._config.max_cot_iterations):
            iterations = iteration + 1

            try:
                response = self._create_chat_completion(
                    messages=messages,
                    tools=self._tool_manager.tools,
                    tool_choice="auto"
                )

                msg = response.choices[0].message

                # Check if done
                if not msg.tool_calls:
                    if msg.content:
                        findings = self._parse_findings(msg.content)
                    break

                # Execute tool calls
                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": msg.tool_calls
                })

                for tool_call in msg.tool_calls:
                    try:
                        args = json.loads(tool_call.function.arguments)
                        result = await self._tool_manager.execute_tool(
                            tool_call.function.name, args
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result
                        })
                    except Exception as e:
                        errors.append(f"Tool error ({tool_call.function.name}): {str(e)}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps({"error": str(e)})
                        })

            except Exception as e:
                errors.append(f"Iteration {iteration} error: {str(e)}")
                self._logger.error(f"CoT Agent error: {e}")

        execution_time = int((time.time() - start_time) * 1000)

        # Add cot_agent_id to findings
        for finding in findings:
            finding_dict = finding.model_dump()
            finding_dict['cot_agent_id'] = self._cot_agent_id
            findings[findings.index(finding)] = Finding(**finding_dict)

        return WorkerResponse(
            findings=findings,
            errors=errors,
            iterations_used=iterations,
            execution_time_ms=execution_time
        )

    def _parse_findings(self, response: str) -> List[Finding]:
        """Parse LLM response into structured findings with guardrails"""
        findings = []

        # Try JSON parsing first
        try:
            # Find JSON in response
            start_idx = response.find('{')
            end_idx = response.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = response[start_idx:end_idx]
                data = json.loads(json_str)

                if 'findings' in data:
                    for f in data['findings']:
                        entities = []
                        for e in f.get('entities', []):
                            entities.append(CodeEntity(
                                name=e.get('name', 'unknown'),
                                entity_type=e.get('entity_type', 'unknown'),
                                file_path=e.get('file_path'),
                                node_id=e.get('node_id'),
                                properties=e.get('properties', {})
                            ))

                        findings.append(Finding(
                            claim=f.get('claim', ''),
                            entities=entities,
                            evidence=f.get('evidence', {}),
                            confidence=ConfidenceLevel(f.get('confidence', 'medium')),
                            source_query=f.get('source_query'),
                            cot_agent_id=self._cot_agent_id
                        ))
                    return findings
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self._logger.warning(f"JSON parsing failed: {e}")

        # Fallback: create single finding from response
        if response.strip():
            findings.append(Finding(
                claim=response,
                entities=[],
                evidence={"raw_response": response},
                confidence=ConfidenceLevel.LOW,
                source_query=None,
                cot_agent_id=self._cot_agent_id
            ))

        return findings


# =============================================================================
# VERIFICATION AGENT
# =============================================================================

class VerificationAgent(BaseAgent):
    """
    Verification Agent - Has schema tools access.
    Verifies claims by independently querying the graph.
    """

    SYSTEM_PROMPT = """You are a Verification Agent. Your job is to independently verify claims about a codebase.

PROCESS:
1. Receive a claim and evidence
2. Use schema tools to understand how to query for this information
3. Write and execute a Cypher query to independently verify the claim
4. Compare your findings with the provided evidence
5. Return verification result

OUTPUT FORMAT (JSON):
{
  "status": "verified" | "not_verified" | "partially_verified",
  "explanation": "Why you reached this conclusion",
  "verified_evidence": {"data from your verification query"},
  "verification_query": "MATCH query you used"
}

Be strict - only verify claims supported by actual data in the graph."""

    def __init__(
        self,
        tool_manager: ToolManager,
        openai_client: OpenAI,
        llm_config: LLMConfig,
        config: SystemConfig
    ):
        super().__init__(openai_client, llm_config, AgentRole.VERIFIER, config)
        self._tool_manager = tool_manager

    @retry_with_backoff(max_retries=3)
    async def execute(self, finding: Finding) -> VerifierResponse:
        """Verify a finding"""
        start_time = time.time()
        self._logger.info(f"Verifying: {finding.claim[:50]}...")

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": f"""Verify this claim:

CLAIM: {finding.claim}

PROVIDED EVIDENCE:
{json.dumps(finding.evidence, indent=2)}

ENTITIES MENTIONED:
{json.dumps([e.model_dump() for e in finding.entities], indent=2)}

Independently verify this claim by querying the graph."""}
        ]

        for iteration in range(self._config.max_verifier_iterations):
            try:
                response = self._create_chat_completion(
                    messages=messages,
                    tools=self._tool_manager.tools,
                    tool_choice="auto"
                )

                msg = response.choices[0].message

                if not msg.tool_calls:
                    result = self._parse_verification(finding.claim, msg.content)
                    execution_time = int((time.time() - start_time) * 1000)
                    return VerifierResponse(result=result, execution_time_ms=execution_time)

                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": msg.tool_calls
                })

                for tool_call in msg.tool_calls:
                    args = json.loads(tool_call.function.arguments)
                    result = await self._tool_manager.execute_tool(
                        tool_call.function.name, args
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })

            except Exception as e:
                self._logger.error(f"Verification error: {e}")

        # Max iterations reached
        execution_time = int((time.time() - start_time) * 1000)
        return VerifierResponse(
            result=VerificationResult(
                claim=finding.claim,
                status=VerificationStatus.ERROR,
                verified_evidence={},
                explanation="Max iterations reached",
                verification_query=None
            ),
            execution_time_ms=execution_time
        )

    def _parse_verification(self, claim: str, response: str) -> VerificationResult:
        """Parse verification response with guardrails"""
        # Try JSON parsing
        try:
            start_idx = response.find('{')
            end_idx = response.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                data = json.loads(response[start_idx:end_idx])
                return VerificationResult(
                    claim=claim,
                    status=VerificationStatus(data.get('status', 'not_verified')),
                    verified_evidence=data.get('verified_evidence', {}),
                    explanation=data.get('explanation', ''),
                    verification_query=data.get('verification_query')
                )
        except (json.JSONDecodeError, ValueError) as e:
            self._logger.warning(f"JSON parsing failed: {e}")

        # Fallback parsing
        response_lower = response.lower()
        if 'verified' in response_lower and 'not' not in response_lower:
            status = VerificationStatus.VERIFIED
        elif 'partially' in response_lower:
            status = VerificationStatus.PARTIALLY_VERIFIED
        else:
            status = VerificationStatus.NOT_VERIFIED

        return VerificationResult(
            claim=claim,
            status=status,
            verified_evidence={},
            explanation=response,
            verification_query=None
        )


# =============================================================================
# ENTITY RESOLUTION AGENT
# =============================================================================

class EntityResolutionAgent(BaseAgent):
    """
    Entity Resolution Agent - ONLY has access to neo4j_fuzzy_search.

    Purpose:
    - Detect case sensitivity issues (e.g., 'workerz' vs 'WorkerZ')
    - Detect misspellings (e.g., 'Hellper' vs 'Helper')
    - Suggest corrections WITHOUT answering the query

    This agent runs after query decomposition to validate entity names
    before CoT agents execute. It prevents wasted iterations on wrong names.
    """

    SYSTEM_PROMPT = """You are an Entity Resolution Agent. Your ONLY job is to verify entity names from queries.

CRITICAL RULES:
1. You have TWO tools:
   - neo4j_fuzzy_search: For finding classes, functions, variables (indexed nodes)
   - neo4j_execute_query: For checking Project, Namespace, File nodes (not in fuzzy index)
2. Use these tools to check if mentioned entities exist in the codebase
3. Report issues for ANY of these scenarios:
   - case_sensitivity: Entity exists but with different casing
   - misspelling: Entity exists but with different spelling
   - not_found_similar_exists: Entity does NOT exist, but similar entities DO exist
   - resolved: Entity was found successfully (e.g., as a Project or Namespace)
4. DO NOT answer the user's question - only identify name issues
5. DO NOT try to understand what the code does - just verify names exist

PROCESS:
1. Extract potential entity names from the query (class names, function names, project names, etc.)
2. For each entity name:
   a. FIRST check if it's a Project, Namespace, or File using neo4j_execute_query:
      - Project: MATCH (p:Project) WHERE p.name CONTAINS '<name>' RETURN p.name, p.file_path LIMIT 5
      - Namespace: MATCH (n:Namespace) WHERE n.name CONTAINS '<name>' RETURN n.name, n.file_path LIMIT 5
      - File: MATCH (f:File) WHERE f.name CONTAINS '<name>' RETURN f.name, f.file_path LIMIT 5
   b. If NOT found as Project/Namespace/File, use neo4j_fuzzy_search for types/functions
3. Analyze the results:
   - If found as Project/Namespace/File → resolved (no correction needed, but note the entity type)
   - Check if ANY result has the EXACT same name (different case) → case_sensitivity
   - Check if ANY result has a SIMILAR name (1-2 chars different) → misspelling
   - If NO exact/similar match but results exist → not_found_similar_exists (suggest alternatives)
4. IMPORTANT: If the entity is found as a Project, treat it as resolved - the query is valid

OUTPUT FORMAT (JSON):
{
  "corrections": [
    {
      "original_term": "<term from query>",
      "suggested_name": "<correct name OR comma-separated alternatives>",
      "entity_type": "<class/function/variable/etc>",
      "file_path": "<path if available>",
      "confidence_score": <0.0-1.0>,
      "issue_type": "<case_sensitivity|misspelling|not_found_similar_exists>"
    }
  ],
  "has_issues": true,
  "corrected_query": "<original query with corrections OR note about alternatives>"
}

If entity exists exactly as queried (no issues):
{
  "corrections": [],
  "has_issues": false,
  "corrected_query": null
}"""

    def __init__(
        self,
        mcp_session,
        openai_client: OpenAI,
        llm_config: LLMConfig,
        config: SystemConfig
    ):
        super().__init__(openai_client, llm_config, AgentRole.COT_AGENT, config, agent_id="EntityResolver")
        self._session = mcp_session
        self._build_tools()

    def _build_tools(self):
        """Build tool definitions - fuzzy search AND cypher for Project/Namespace/File"""
        self._tools = [
            {
                "type": "function",
                "function": {
                    "name": "neo4j_fuzzy_search",
                    "description": "Fuzzy search for code entities (classes, functions, variables). Does NOT include Project, Namespace, or File nodes.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "search_term": {
                                "type": "string",
                                "description": "Name to search for (e.g., 'workerz', 'Helper.FormatMessage')"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum results (default: 15)",
                                "default": 15
                            },
                            "min_score": {
                                "type": "number",
                                "description": "Minimum relevance score (default: 0.5)",
                                "default": 0.5
                            }
                        },
                        "required": ["search_term"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "neo4j_execute_query",
                    "description": "Execute a Cypher query to check for Project, Namespace, or File nodes. Use this FIRST to check if entity is a project/namespace/file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Cypher query to execute. Use for checking Project/Namespace/File nodes."
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

    async def _execute_tool(self, name: str, arguments: Dict) -> str:
        """Execute fuzzy search or cypher query tool via MCP"""
        if name not in ("neo4j_fuzzy_search", "neo4j_execute_query"):
            return json.dumps({"error": f"Unknown tool: {name}"})

        try:
            # For cypher queries, validate it's a safe read-only query
            if name == "neo4j_execute_query":
                query = arguments.get("query", "").upper()
                # Only allow read queries for entity resolution
                if any(kw in query for kw in ["DELETE", "CREATE", "SET", "MERGE", "REMOVE", "DROP"]):
                    return json.dumps({"error": "Only read queries allowed for entity resolution"})

            result = await self._session.call_tool(name, arguments)
            if hasattr(result, 'content') and result.content:
                return result.content[0].text
            return json.dumps({"error": "Empty MCP response"})
        except Exception as e:
            self._logger.error(f"Tool execution error ({name}): {e}")
            return json.dumps({"error": str(e)})

    @retry_with_backoff(max_retries=3)
    async def execute(self, query: str, sub_queries: Optional[List[SubQuery]] = None) -> EntityResolutionResult:
        """
        Check for entity name issues in query and sub-queries.

        Args:
            query: Original user query
            sub_queries: Optional decomposed sub-queries to also check

        Returns:
            EntityResolutionResult with any corrections found
        """
        start_time = time.time()
        self._logger.info("Entity Resolution Agent checking query...")

        # Build prompt with query and sub-queries
        query_text = f"Original query: {query}"
        if sub_queries:
            query_text += "\n\nDecomposed sub-queries:"
            for i, sq in enumerate(sub_queries):
                query_text += f"\n{i+1}. {sq.query}"

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": f"Check for entity name issues in:\n\n{query_text}"}
        ]

        # Limited iterations - this should be quick
        max_iterations = 5
        for iteration in range(max_iterations):
            try:
                response = self._create_chat_completion(
                    messages=messages,
                    tools=self._tools,
                    tool_choice="auto"
                )

                msg = response.choices[0].message

                # Check if done (no tool calls)
                if not msg.tool_calls:
                    if msg.content:
                        result = self._parse_result(msg.content)
                        result_dict = result.model_dump()
                        result_dict['execution_time_ms'] = int((time.time() - start_time) * 1000)
                        return EntityResolutionResult(**result_dict)
                    break

                # Execute tool calls
                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": msg.tool_calls
                })

                for tool_call in msg.tool_calls:
                    args = json.loads(tool_call.function.arguments)
                    result = await self._execute_tool(tool_call.function.name, args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })

            except Exception as e:
                self._logger.error(f"Entity resolution error: {e}")

        execution_time = int((time.time() - start_time) * 1000)
        return EntityResolutionResult(
            corrections=[],
            has_issues=False,
            corrected_query=None,
            execution_time_ms=execution_time
        )

    def _parse_result(self, response: str) -> EntityResolutionResult:
        """Parse LLM response into EntityResolutionResult"""
        try:
            start_idx = response.find('{')
            end_idx = response.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                data = json.loads(response[start_idx:end_idx])

                corrections = []
                for c in data.get('corrections', []):
                    corrections.append(EntityCorrection(
                        original_term=c.get('original_term', ''),
                        suggested_name=c.get('suggested_name', ''),
                        entity_type=c.get('entity_type', 'unknown'),
                        file_path=c.get('file_path'),
                        confidence_score=c.get('confidence_score', 0.0),
                        issue_type=c.get('issue_type', 'unknown')
                    ))

                return EntityResolutionResult(
                    corrections=corrections,
                    has_issues=data.get('has_issues', len(corrections) > 0),
                    corrected_query=data.get('corrected_query'),
                    execution_time_ms=0  # Set by caller
                )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self._logger.warning(f"Failed to parse entity resolution response: {e}")

        return EntityResolutionResult(
            corrections=[],
            has_issues=False,
            corrected_query=None,
            execution_time_ms=0
        )


# =============================================================================
# CPG OBSERVER AGENT
# =============================================================================

class CPGObserverAgent:
    """
    Passive observer that monitors the RAG system to identify CPG improvements.

    Does NOT interfere with the main workflow - collects observations non-blockingly.
    Has its own MCP session for exploration and persistent memory across sessions.

    Key Capabilities:
    1. Non-blocking observation collection via async queue
    2. Persistent memory across sessions (file-based JSON)
    3. Cypher exploration tools for CPG introspection
    4. Neo4j function/procedure discovery tools
    5. Pattern detection (empty results, errors, missing relationships)
    6. LLM-powered analysis and report generation
    """

    ANALYSIS_PROMPT = """You are a CPG Quality Analyst. Analyze query observations to identify improvements for the Code Property Graph.

OBSERVATIONS DATA:
{observations_summary}

CURRENT SCHEMA:
{schema_summary}

TASK: Analyze the patterns and identify:
1. Missing relationships that queries expect but don't exist
2. Missing properties that would be useful
3. Inconsistencies in the data model
4. Patterns of empty results indicating data gaps
5. Suggested improvements for the CPG builder

OUTPUT FORMAT (JSON):
{{
  "identified_issues": [
    {{
      "issue_type": "missing_relationship|missing_property|inconsistency|data_gap|pattern_suggestion",
      "severity": "high|medium|low",
      "description": "Clear description of the issue",
      "evidence": ["query patterns or observations as evidence"],
      "suggested_fix": "How to fix this in the CPG builder",
      "related_nodes": ["affected node types"],
      "related_relationships": ["affected relationships"]
    }}
  ],
  "improvement_suggestions": ["actionable suggestions for CPG enhancement"],
  "summary": "Executive summary of findings"
}}"""

    def __init__(
        self,
        mcp_session,
        openai_client: OpenAI,
        llm_config: LLMConfig,
        memory_file: str = "cpg_observer_memory.json",
        max_memory_observations: int = 1000
    ):
        self._session = mcp_session
        self._openai = openai_client
        self._llm_config = llm_config
        self._memory_file = Path(memory_file)
        self._max_observations = max_memory_observations
        self._logger = logging.getLogger(f"{__name__}.cpg_observer")

        # Async queue for non-blocking observation collection
        self._observation_queue: asyncio.Queue[QueryObservation] = asyncio.Queue()

        # Current session tracking
        self._current_session_id = str(uuid.uuid4())[:8]
        self._current_user_query: Optional[str] = None

        # Load persistent memory
        self._memory = self._load_memory()
        self._memory.session_count += 1

        # Build tools for CPG exploration
        self._tools = self._build_tools()

        self._logger.info(f"CPG Observer initialized (session: {self._current_session_id}, "
                         f"prior observations: {len(self._memory.observations)})")

    def _load_memory(self) -> ObserverMemory:
        """Load persistent memory from file"""
        if self._memory_file.exists():
            try:
                with open(self._memory_file, 'r') as f:
                    data = json.load(f)
                return ObserverMemory(**data)
            except Exception as e:
                self._logger.warning(f"Failed to load observer memory: {e}. Starting fresh.")
        return ObserverMemory()

    def save_memory(self):
        """Save memory to file for persistence"""
        try:
            # Trim observations if exceeding limit (keep most recent)
            if len(self._memory.observations) > self._max_observations:
                self._memory.observations = self._memory.observations[-self._max_observations:]

            with open(self._memory_file, 'w') as f:
                json.dump(self._memory.model_dump(), f, indent=2, default=str)
            self._logger.debug(f"Observer memory saved ({len(self._memory.observations)} observations)")
        except Exception as e:
            self._logger.error(f"Failed to save observer memory: {e}")

    def _build_tools(self) -> List[Dict]:
        """Build tools for CPG exploration"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "cpg_execute_query",
                    "description": "Execute a Cypher query to explore CPG structure and data",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Cypher query to execute"
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cpg_get_schema",
                    "description": "Get the current CPG schema (node types, relationships, properties)",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cpg_count_nodes",
                    "description": "Count nodes by type in the CPG",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_type": {
                                "type": "string",
                                "description": "Node type to count (e.g., 'Type', 'Function'). Leave empty to count all types."
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cpg_list_functions",
                    "description": "List available Neo4j functions. Use substring filter to search for specific functions.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filter_substring": {
                                "type": "string",
                                "description": "Optional substring to filter function names (e.g., 'apoc', 'string', 'list')"
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cpg_list_procedures",
                    "description": "List available Neo4j procedures (stored procedures). Use substring filter to search for specific procedures.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filter_substring": {
                                "type": "string",
                                "description": "Optional substring to filter procedure names (e.g., 'apoc', 'db', 'meta')"
                            }
                        }
                    }
                }
            }
        ]

    async def _execute_tool(self, name: str, arguments: Dict) -> str:
        """Execute observer's exploration tools"""
        try:
            if name == "cpg_execute_query":
                query = arguments.get("query", "")
                # Only allow read queries
                query_upper = query.upper()
                if any(kw in query_upper for kw in ["DELETE", "CREATE", "SET", "MERGE", "REMOVE", "DROP"]):
                    return json.dumps({"error": "Only read queries allowed for observer"})

                result = await self._session.call_tool("neo4j_execute_query", {"query": query})
                if hasattr(result, 'content') and result.content:
                    return result.content[0].text
                return json.dumps({"error": "Empty response"})

            elif name == "cpg_get_schema":
                # Get schema via APOC
                query = "CALL apoc.meta.schema() YIELD value RETURN value"
                result = await self._session.call_tool("neo4j_execute_query", {"query": query})
                if hasattr(result, 'content') and result.content:
                    return result.content[0].text
                return json.dumps({"error": "Schema not available"})

            elif name == "cpg_count_nodes":
                node_type = arguments.get("node_type")
                if node_type:
                    query = f"MATCH (n:{node_type}) RETURN count(n) as count"
                else:
                    query = "MATCH (n) RETURN labels(n)[0] as type, count(n) as count ORDER BY count DESC"
                result = await self._session.call_tool("neo4j_execute_query", {"query": query})
                if hasattr(result, 'content') and result.content:
                    return result.content[0].text
                return json.dumps({"error": "Count failed"})

            elif name == "cpg_list_functions":
                # SHOW FUNCTIONS with optional filter
                filter_substring = arguments.get("filter_substring", "")
                if filter_substring:
                    query = f"SHOW FUNCTIONS YIELD name WHERE name CONTAINS '{filter_substring}' RETURN name"
                else:
                    query = "SHOW FUNCTIONS YIELD name RETURN name LIMIT 100"
                result = await self._session.call_tool("neo4j_execute_query", {"query": query})
                if hasattr(result, 'content') and result.content:
                    return result.content[0].text
                return json.dumps({"error": "Failed to list functions"})

            elif name == "cpg_list_procedures":
                # SHOW PROCEDURES with optional filter
                filter_substring = arguments.get("filter_substring", "")
                if filter_substring:
                    query = f"SHOW PROCEDURES YIELD name WHERE name CONTAINS '{filter_substring}' RETURN name"
                else:
                    query = "SHOW PROCEDURES YIELD name RETURN name LIMIT 100"
                result = await self._session.call_tool("neo4j_execute_query", {"query": query})
                if hasattr(result, 'content') and result.content:
                    return result.content[0].text
                return json.dumps({"error": "Failed to list procedures"})

            return json.dumps({"error": f"Unknown tool: {name}"})
        except Exception as e:
            self._logger.error(f"Observer tool error ({name}): {e}")
            return json.dumps({"error": str(e)})

    def set_current_query(self, user_query: str):
        """Set the current user query context for observations"""
        self._current_user_query = user_query

    def _extract_query_components(self, cypher_query: str) -> Tuple[List[str], List[str], List[str]]:
        """Extract node types, relationships, and properties from a Cypher query"""
        node_types = []
        relationships = []
        properties = []

        # Extract node types (pattern: (n:NodeType) or :NodeType)
        node_pattern = r':([A-Z][a-zA-Z0-9_]*)'
        node_matches = re.findall(node_pattern, cypher_query)
        node_types = list(set(node_matches))

        # Extract relationships (pattern: -[:REL_TYPE]-> or -[r:REL_TYPE]->)
        rel_pattern = r'\[:?([A-Z_]+)\]'
        rel_matches = re.findall(rel_pattern, cypher_query)
        relationships = list(set(rel_matches))

        # Extract properties (pattern: .property_name or {property: value})
        prop_pattern1 = r'\.([a-z_][a-zA-Z0-9_]*)'
        prop_pattern2 = r'\{([a-z_][a-zA-Z0-9_]*):'
        prop_matches = re.findall(prop_pattern1, cypher_query) + re.findall(prop_pattern2, cypher_query)
        properties = list(set(prop_matches))

        return node_types, relationships, properties

    def observe_query(
        self,
        cypher_query: str,
        result: str,
        agent_id: str,
        sub_query: Optional[str] = None,
        execution_time_ms: int = 0
    ):
        """
        Record an observation of a query execution.
        This method is NON-BLOCKING - it queues the observation for async processing.
        """
        try:
            # Parse result to determine if empty or error
            result_count = 0
            is_empty = False
            had_error = False
            error_message = None

            try:
                result_data = json.loads(result) if isinstance(result, str) else result
                if isinstance(result_data, dict):
                    if 'error' in result_data:
                        had_error = True
                        error_message = result_data.get('error', '')[:200]
                    elif 'results' in result_data:
                        result_count = len(result_data.get('results', []))
                        is_empty = result_count == 0
                    else:
                        # Try to count items
                        result_count = len(result_data) if isinstance(result_data, (list, dict)) else 1
                        is_empty = result_count == 0
                elif isinstance(result_data, list):
                    result_count = len(result_data)
                    is_empty = result_count == 0
            except (json.JSONDecodeError, TypeError):
                # If we can't parse, check for common error indicators
                if isinstance(result, str):
                    if 'error' in result.lower() or 'exception' in result.lower():
                        had_error = True
                        error_message = result[:200]
                    elif result.strip() in ('[]', '{}', '', 'null'):
                        is_empty = True

            # Extract query components
            node_types, relationships, properties = self._extract_query_components(cypher_query)

            # Create observation
            observation = QueryObservation(
                timestamp=datetime.utcnow().isoformat(),
                session_id=self._current_session_id,
                user_query=self._current_user_query or "",
                sub_query=sub_query,
                agent_id=agent_id,
                cypher_query=cypher_query,
                result_count=result_count,
                is_empty=is_empty,
                had_error=had_error,
                error_message=error_message,
                execution_time_ms=execution_time_ms,
                node_types_queried=node_types,
                relationships_queried=relationships,
                properties_accessed=properties
            )

            # Add to memory (non-blocking)
            self._memory.observations.append(observation)

            # Track patterns
            pattern_key = f"{','.join(sorted(node_types))}-{','.join(sorted(relationships))}"
            self._memory.query_patterns[pattern_key] = self._memory.query_patterns.get(pattern_key, 0) + 1

            # Track issues
            if is_empty:
                if cypher_query not in self._memory.empty_result_queries:
                    self._memory.empty_result_queries.append(cypher_query)
            if had_error:
                if cypher_query not in self._memory.error_queries:
                    self._memory.error_queries.append(cypher_query)

            self._logger.debug(f"Observed query from {agent_id}: empty={is_empty}, error={had_error}")

        except Exception as e:
            self._logger.error(f"Error recording observation: {e}")

    async def analyze_and_report(self, force: bool = False) -> Optional[ObserverReport]:
        """
        Analyze collected observations and generate an improvement report.
        Uses LLM to identify patterns and suggest improvements.

        Args:
            force: If True, generate report even with few observations
        """
        # Check if we have enough observations
        if len(self._memory.observations) < 5 and not force:
            self._logger.info("Not enough observations for analysis (need at least 5)")
            return None

        self._logger.info(f"Analyzing {len(self._memory.observations)} observations...")

        # Build observations summary for LLM
        empty_count = sum(1 for o in self._memory.observations if o.is_empty)
        error_count = sum(1 for o in self._memory.observations if o.had_error)
        total = len(self._memory.observations)

        # Collect common patterns
        all_node_types = {}
        all_relationships = {}
        all_properties = {}
        for obs in self._memory.observations:
            for nt in obs.node_types_queried:
                all_node_types[nt] = all_node_types.get(nt, 0) + 1
            for rel in obs.relationships_queried:
                all_relationships[rel] = all_relationships.get(rel, 0) + 1
            for prop in obs.properties_accessed:
                all_properties[prop] = all_properties.get(prop, 0) + 1

        # Get sample empty/error queries (most recent)
        sample_empty = self._memory.empty_result_queries[-5:] if self._memory.empty_result_queries else []
        sample_errors = self._memory.error_queries[-5:] if self._memory.error_queries else []

        observations_summary = f"""
Total Observations: {total}
Sessions: {self._memory.session_count}
Empty Result Rate: {(empty_count/total*100) if total > 0 else 0:.1f}%
Error Rate: {(error_count/total*100) if total > 0 else 0:.1f}%

Most Queried Node Types:
{json.dumps(dict(sorted(all_node_types.items(), key=lambda x: -x[1])[:10]), indent=2)}

Most Queried Relationships:
{json.dumps(dict(sorted(all_relationships.items(), key=lambda x: -x[1])[:10]), indent=2)}

Most Accessed Properties:
{json.dumps(dict(sorted(all_properties.items(), key=lambda x: -x[1])[:10]), indent=2)}

Sample Empty Result Queries:
{json.dumps(sample_empty, indent=2)}

Sample Error Queries:
{json.dumps(sample_errors, indent=2)}

Query Patterns (by frequency):
{json.dumps(dict(sorted(self._memory.query_patterns.items(), key=lambda x: -x[1])[:10]), indent=2)}
"""

        # Get current schema for context
        schema_summary = "Schema not available"
        try:
            schema_result = await self._execute_tool("cpg_get_schema", {})
            schema_summary = schema_result[:2000] if len(schema_result) > 2000 else schema_result
        except Exception as e:
            self._logger.warning(f"Failed to get schema for analysis: {e}")

        # Call LLM for analysis
        try:
            prompt = self.ANALYSIS_PROMPT.format(
                observations_summary=observations_summary,
                schema_summary=schema_summary
            )

            response = self._openai.chat.completions.create(
                model=self._llm_config.model,
                temperature=0.1,  # Low temp for analytical task
                messages=[
                    {"role": "system", "content": "You are a CPG Quality Analyst providing actionable recommendations."},
                    {"role": "user", "content": prompt}
                ]
            )

            content = response.choices[0].message.content

            # Parse LLM response
            start_idx = content.find('{')
            end_idx = content.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                analysis = json.loads(content[start_idx:end_idx])

                # Create issues from analysis
                identified_issues = []
                for issue_data in analysis.get('identified_issues', []):
                    issue = CPGIssue(
                        issue_id=str(uuid.uuid4())[:8],
                        issue_type=issue_data.get('issue_type', 'pattern_suggestion'),
                        severity=issue_data.get('severity', 'medium'),
                        description=issue_data.get('description', ''),
                        evidence=issue_data.get('evidence', []),
                        suggested_fix=issue_data.get('suggested_fix'),
                        related_nodes=issue_data.get('related_nodes', []),
                        related_relationships=issue_data.get('related_relationships', []),
                        detected_at=datetime.utcnow().isoformat(),
                        occurrence_count=1
                    )
                    identified_issues.append(issue)

                # Create report
                report = ObserverReport(
                    report_id=str(uuid.uuid4())[:8],
                    generated_at=datetime.utcnow().isoformat(),
                    total_observations=total,
                    total_sessions=self._memory.session_count,
                    empty_result_rate=(empty_count/total*100) if total > 0 else 0,
                    error_rate=(error_count/total*100) if total > 0 else 0,
                    identified_issues=identified_issues,
                    query_patterns=dict(sorted(self._memory.query_patterns.items(), key=lambda x: -x[1])[:20]),
                    missing_relationships=[],  # Will be populated by issues
                    missing_properties=[],
                    improvement_suggestions=analysis.get('improvement_suggestions', []),
                    summary=analysis.get('summary', 'Analysis complete.')
                )

                # Update memory
                self._memory.identified_issues.extend(identified_issues)
                self._memory.last_analysis_timestamp = datetime.utcnow().isoformat()
                self._memory.last_report = report

                # Save memory
                self.save_memory()

                self._logger.info(f"Analysis complete: {len(identified_issues)} issues identified")
                return report

        except Exception as e:
            self._logger.error(f"LLM analysis failed: {e}")

        return None

    async def explore_cpg(self, exploration_query: str) -> str:
        """
        Explore the CPG using a natural language query.
        The observer can use this to investigate issues or answer questions about the CPG structure.
        """
        self._logger.info(f"Exploring CPG: {exploration_query}")

        messages = [
            {"role": "system", "content": """You are a CPG Explorer. Use the provided tools to answer questions about the Code Property Graph structure.
Available tools:
- cpg_execute_query: Execute Cypher queries
- cpg_get_schema: Get the CPG schema
- cpg_count_nodes: Count nodes by type
- cpg_list_functions: List available Neo4j functions (filter with substring)
- cpg_list_procedures: List available Neo4j procedures (filter with substring)

Be thorough but efficient. Use simple queries first, then more complex ones if needed."""},
            {"role": "user", "content": exploration_query}
        ]

        max_iterations = 5
        for _ in range(max_iterations):
            response = self._openai.chat.completions.create(
                model=self._llm_config.model,
                temperature=0.0,
                messages=messages,
                tools=self._tools,
                tool_choice="auto"
            )

            msg = response.choices[0].message

            if not msg.tool_calls:
                return msg.content or "Exploration complete."

            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": msg.tool_calls
            })

            for tool_call in msg.tool_calls:
                args = json.loads(tool_call.function.arguments)
                result = await self._execute_tool(tool_call.function.name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })

        return "Exploration reached iteration limit."

    def get_stats(self) -> Dict[str, Any]:
        """Get current observer statistics"""
        total = len(self._memory.observations)
        empty_count = sum(1 for o in self._memory.observations if o.is_empty)
        error_count = sum(1 for o in self._memory.observations if o.had_error)

        return {
            "session_id": self._current_session_id,
            "total_observations": total,
            "total_sessions": self._memory.session_count,
            "empty_result_count": empty_count,
            "error_count": error_count,
            "empty_result_rate": f"{(empty_count/total*100) if total > 0 else 0:.1f}%",
            "error_rate": f"{(error_count/total*100) if total > 0 else 0:.1f}%",
            "unique_patterns": len(self._memory.query_patterns),
            "identified_issues": len(self._memory.identified_issues),
            "last_analysis": self._memory.last_analysis_timestamp,
            "memory_file": str(self._memory_file)
        }

    def print_report(self, report: Optional[ObserverReport] = None):
        """Print a human-readable report"""
        report = report or self._memory.last_report
        if not report:
            print("No report available. Run analyze_and_report() first.")
            return

        print(f"\n{'='*70}")
        print("CPG OBSERVER REPORT")
        print(f"{'='*70}")
        print(f"Report ID: {report.report_id}")
        print(f"Generated: {report.generated_at}")
        print(f"\n--- STATISTICS ---")
        print(f"Total Observations: {report.total_observations}")
        print(f"Total Sessions: {report.total_sessions}")
        print(f"Empty Result Rate: {report.empty_result_rate:.1f}%")
        print(f"Error Rate: {report.error_rate:.1f}%")

        print(f"\n--- IDENTIFIED ISSUES ({len(report.identified_issues)}) ---")
        for issue in report.identified_issues:
            print(f"\n[{issue.severity.upper()}] {issue.issue_type}")
            print(f"  Description: {issue.description}")
            if issue.suggested_fix:
                print(f"  Suggested Fix: {issue.suggested_fix}")
            if issue.related_nodes:
                print(f"  Related Nodes: {', '.join(issue.related_nodes)}")

        print(f"\n--- IMPROVEMENT SUGGESTIONS ---")
        for i, suggestion in enumerate(report.improvement_suggestions, 1):
            print(f"{i}. {suggestion}")

        print(f"\n--- SUMMARY ---")
        print(report.summary)
        print(f"{'='*70}\n")


# =============================================================================
# ToT ORCHESTRATOR (Tree-of-Thought)
# =============================================================================

class ToTOrchestrator(BaseAgent):
    """
    Tree-of-Thought Orchestrator - NO schema access.
    Decomposes queries using tree-of-thought reasoning, orchestrates CoT agents, synthesizes answers.
    """

    DECOMPOSITION_PROMPT = """You are a Query Decomposition Agent. Break down the user's question into specific sub-queries.

Each sub-query should:
1. Be specific and answerable
2. Focus on finding ACTUAL code entities (classes, functions, files, relationships)
3. Together cover all aspects of the original question

OUTPUT FORMAT (JSON):
{
  "sub_queries": [
    {"query": "specific question", "focus": "what aspect this covers", "priority": 1-5}
  ],
  "reasoning": "why you decomposed it this way"
}"""

    SYNTHESIS_PROMPT = """You are a Code Analysis Expert synthesizing findings about a codebase.

RULES:
1. Only include VERIFIED information
2. Talk about ACTUAL code entities (real class names, function names, files)
3. DO NOT describe graph schema or database structure
4. Be specific with names, file paths, and code details
5. Mention uncertainty for unverified claims

OUTPUT FORMAT (JSON):
{
  "answer": "comprehensive answer about the actual codebase",
  "verified_claims": ["list of verified facts"],
  "unverified_claims": ["list of unverified claims"],
  "confidence": "high/medium/low"
}"""

    def __init__(self, openai_client: OpenAI, llm_config: LLMConfig, config: SystemConfig):
        super().__init__(openai_client, llm_config, AgentRole.TOT_ORCHESTRATOR, config)

    async def execute(self, *args, **kwargs):
        """Not used directly - supervisor has specific methods"""
        pass

    def decompose_query(self, user_query: str) -> QueryDecomposition:
        """Decompose user query into sub-queries"""
        self._logger.info("Decomposing query...")

        try:
            response = self._create_chat_completion(
                messages=[
                    {"role": "system", "content": self.DECOMPOSITION_PROMPT},
                    {"role": "user", "content": user_query}
                ]
            )

            content = response.choices[0].message.content

            # Parse JSON
            start_idx = content.find('{')
            end_idx = content.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                data = json.loads(content[start_idx:end_idx])

                sub_queries = [
                    SubQuery(
                        query=sq.get('query', ''),
                        focus=sq.get('focus', ''),
                        priority=sq.get('priority', 1)
                    )
                    for sq in data.get('sub_queries', [])
                ]

                return QueryDecomposition(
                    original_query=user_query,
                    sub_queries=sub_queries,
                    reasoning=data.get('reasoning', '')
                )

        except Exception as e:
            self._logger.error(f"Decomposition error: {e}")

        # Fallback
        return QueryDecomposition(
            original_query=user_query,
            sub_queries=[SubQuery(query=user_query, focus="entire question", priority=1)],
            reasoning="Fallback - using original query"
        )

    def synthesize_answer(
        self,
        user_query: str,
        verified_findings: List[Tuple[Finding, VerificationResult]]
    ) -> FinalAnswer:
        """Synthesize final answer from verified findings"""
        self._logger.info("Synthesizing final answer...")

        # Build findings summary
        findings_text = ""
        verified_claims = []
        unverified_claims = []

        for finding, verification in verified_findings:
            if verification.status == VerificationStatus.VERIFIED:
                status_icon = "[OK]"
                verified_claims.append(finding.claim)
            elif verification.status == VerificationStatus.PARTIALLY_VERIFIED:
                status_icon = "~"
                verified_claims.append(f"(partial) {finding.claim}")
            else:
                status_icon = "[X]"
                unverified_claims.append(finding.claim)

            findings_text += f"\n{status_icon} {finding.claim}\n"
            findings_text += f"  Evidence: {json.dumps(finding.evidence)}\n"
            findings_text += f"  Entities: {[e.name for e in finding.entities]}\n"

        try:
            response = self._create_chat_completion(
                messages=[
                    {"role": "system", "content": self.SYNTHESIS_PROMPT},
                    {"role": "user", "content": f"""Original Question: {user_query}

Findings:
{findings_text}

Synthesize a comprehensive answer."""}
                ]
            )

            content = response.choices[0].message.content

            # Parse JSON
            try:
                start_idx = content.find('{')
                end_idx = content.rfind('}') + 1
                if start_idx != -1 and end_idx > start_idx:
                    data = json.loads(content[start_idx:end_idx])
                    return FinalAnswer(
                        answer=data.get('answer', content),
                        verified_claims=data.get('verified_claims', verified_claims),
                        unverified_claims=data.get('unverified_claims', unverified_claims),
                        confidence=ConfidenceLevel(data.get('confidence', 'medium')),
                        total_findings=len(verified_findings),
                        verified_count=len(verified_claims)
                    )
            except (json.JSONDecodeError, ValueError):
                pass

            return FinalAnswer(
                answer=content,
                verified_claims=verified_claims,
                unverified_claims=unverified_claims,
                confidence=ConfidenceLevel.MEDIUM,
                total_findings=len(verified_findings),
                verified_count=len(verified_claims)
            )

        except Exception as e:
            self._logger.error(f"Synthesis error: {e}")
            return FinalAnswer(
                answer=f"Error synthesizing answer: {e}",
                verified_claims=[],
                unverified_claims=[],
                confidence=ConfidenceLevel.LOW,
                total_findings=len(verified_findings),
                verified_count=0
            )


# =============================================================================
# MULTI-AGENT ORCHESTRATOR
# =============================================================================

class MultiAgentCoT:
    """
    Multi-Agent Tree-of-Thought / Chain-of-Thought System.
    Coordinates ToT Orchestrator, CoT Agents, and Verification Agent.
    """

    def __init__(self, config: Optional[SystemConfig] = None, enable_observer: bool = True):
        self._config = config or SystemConfig()
        self._mcp_client: Optional[MCPClient] = None
        self._mcp_session = None
        self._session_pool: Optional[MCPSessionPool] = None  # Pool for parallel CoT agents
        self._schema_manager: Optional[DynamicSchemaManager] = None
        self._tool_manager: Optional[ToolManager] = None
        self._tot_orchestrator: Optional[ToTOrchestrator] = None
        self._verifier: Optional[VerificationAgent] = None
        self._entity_resolver: Optional[EntityResolutionAgent] = None
        self._cpg_observer: Optional[CPGObserverAgent] = None  # CPG Quality Observer
        self._enable_observer = enable_observer  # Flag to enable/disable observer
        self._input_validator = InputPromptValidator(strict_mode=True)
        self._initialized = False
        self._logger = logging.getLogger(f"{__name__}.orchestrator")
        self._openai: Optional[OpenAI] = None  # Created during initialize() from LLM config
        self._llm_config: Optional[LLMConfig] = None

        # Initialize token tracker for transparency
        self._token_tracker = AggregatedTokenUsage()
        BaseAgent.set_token_tracker(self._token_tracker)

    async def initialize(self):
        """Initialize all components"""
        if self._initialized:
            return

        self._logger.info("Initializing Multi-Agent System...")

        # Get effective LLM config and create client
        self._llm_config = self._config.get_llm_config()
        self._openai = self._llm_config.create_client()

        # Initialize MCP - supports both direct config dict and file path
        mcp_config_dict = self._config.get_mcp_config_dict()

        # Write temp config file for MCPClient (it requires a file path)
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(mcp_config_dict, f)
            temp_config_path = f.name

        self._mcp_client = MCPClient.from_config_file(temp_config_path)
        server_name = list(mcp_config_dict.get('mcpServers', {}).keys())[0]
        self._mcp_session = await self._mcp_client.create_session(server_name)
        self._logger.info(f"MCP session established: {server_name}")

        # Initialize schema manager - supports both direct dict and file path
        cypher_adapter = MCPCypherAdapter(self._mcp_session)
        yaml_schema = self._config.get_yaml_schema()

        self._schema_manager = DynamicSchemaManager(
            cypher_server=cypher_adapter,
            yaml_schema=yaml_schema
        )
        await self._schema_manager.initialize_background()
        self._logger.info(f"Schema loaded: {len(self._schema_manager._reconciled_schema.get('nodes', {}))} node types")

        # Initialize CPG Observer Agent (if enabled) - monitors queries to identify CPG improvements
        if self._enable_observer:
            self._cpg_observer = CPGObserverAgent(
                mcp_session=self._mcp_session,
                openai_client=self._openai,
                llm_config=self._llm_config,
                memory_file="cpg_observer_memory.json"
            )
            self._logger.info("CPG Observer Agent initialized")

        # Initialize tool manager (for verification agent - uses main session)
        # Observer is passed to enable non-blocking query tracking
        self._tool_manager = ToolManager(
            self._mcp_session,
            self._schema_manager,
            observer=self._cpg_observer,
            agent_id="Verifier"
        )

        # Initialize session pool for parallel CoT agents
        self._session_pool = MCPSessionPool(mcp_config_dict)

        # Initialize agents with LLM config
        self._tot_orchestrator = ToTOrchestrator(
            self._openai, self._llm_config, self._config
        )
        self._verifier = VerificationAgent(
            self._tool_manager, self._openai, self._llm_config, self._config
        )

        # Initialize entity resolution agent (uses main session - only has fuzzy search)
        if self._config.entity_resolution_enabled:
            self._entity_resolver = EntityResolutionAgent(
                self._mcp_session, self._openai, self._llm_config, self._config
            )
            self._logger.info("Entity Resolution Agent initialized")

        self._initialized = True
        self._logger.info(f"Multi-Agent System initialized! (model: {self._llm_config.model}, temp: {self._llm_config.temperature})")

    def _create_cot_agent(self, cot_agent_id: str) -> CoTAgent:
        """Create a Chain-of-Thought agent"""
        return CoTAgent(
            self._tool_manager,
            self._openai,
            self._llm_config,
            self._config,
            cot_agent_id
        )

    async def run(self, user_query: str) -> ProductionResponse:
        """Run the multi-agent system on a query. Returns ProductionResponse with citations."""
        if not self._initialized:
            await self.initialize()

        # SECURITY: Validate user input before processing
        try:
            self._input_validator.validate_or_raise(user_query)
        except CypherSecurityError as e:
            self._logger.warning(f"User query rejected: {e}")
            return ProductionResponse(
                answer=f"Query rejected for security reasons: {e}",
                confidence=ConfidenceLevel.LOW,
                citations=[],
                verified_count=0,
                unverified_count=0,
                token_usage=self._token_tracker,
                execution_time_ms=0,
                sub_queries_count=0,
                llm_calls_count=0,
                original_query=user_query
            )

        # Sanitize input (remove hidden instructions, etc.)
        sanitized_query = self._input_validator.sanitize(user_query)
        if sanitized_query != user_query:
            self._logger.info("User input was sanitized")

        start_time = time.time()

        # OBSERVER: Set the current user query context for observation tracking
        if self._cpg_observer:
            self._cpg_observer.set_current_query(sanitized_query)

        print(f"\n{'='*70}")
        print("ToT/CoT MULTI-AGENT SYSTEM")
        print(f"{'='*70}")
        print(f"Query: {sanitized_query}")

        # Step 1: Decompose query
        print(f"\n[DECOMPOSE] STEP 1: Decomposing query...")
        decomposition = self._tot_orchestrator.decompose_query(sanitized_query)

        # SECURITY: Limit sub-queries to prevent cost explosion attacks
        original_count = len(decomposition.sub_queries)
        if original_count > self._config.max_sub_queries:
            self._logger.warning(
                f"Sub-query limit exceeded: {original_count} > {self._config.max_sub_queries}. "
                "Truncating to prevent resource exhaustion."
            )
            # Keep highest priority sub-queries (sorted by priority)
            decomposition.sub_queries = sorted(
                decomposition.sub_queries, key=lambda sq: sq.priority
            )[:self._config.max_sub_queries]
            print(f"   Sub-queries: {len(decomposition.sub_queries)} (truncated from {original_count})")
        else:
            print(f"   Sub-queries: {len(decomposition.sub_queries)}")
        for i, sq in enumerate(decomposition.sub_queries):
            print(f"   {i+1}. [{sq.focus}] {sq.query}")

        # Step 1.5: Entity Resolution (optional - checks for case sensitivity / typos)
        effective_query = sanitized_query
        if self._config.entity_resolution_enabled and self._entity_resolver:
            print(f"\n[RESOLVE] STEP 1.5: Checking entity names...")
            resolution_result = await self._entity_resolver.execute(
                sanitized_query, decomposition.sub_queries
            )
            if resolution_result.has_issues:
                print(f"   Found {len(resolution_result.corrections)} entity name issues:")
                for correction in resolution_result.corrections:
                    print(f"   - '{correction.original_term}' → '{correction.suggested_name}' ({correction.issue_type})")
                if resolution_result.corrected_query:
                    effective_query = resolution_result.corrected_query
                    print(f"   Corrected query: {effective_query}")
                    # Re-decompose with corrected query
                    print(f"   Re-decomposing with corrected entity names...")
                    decomposition = self._tot_orchestrator.decompose_query(effective_query)
                    # SECURITY: Limit sub-queries to prevent cost explosion attacks
                    if len(decomposition.sub_queries) > self._config.max_sub_queries:
                        decomposition.sub_queries = sorted(
                            decomposition.sub_queries, key=lambda sq: sq.priority
                        )[:self._config.max_sub_queries]
                    for i, sq in enumerate(decomposition.sub_queries):
                        print(f"   {i+1}. [{sq.focus}] {sq.query}")
            else:
                print(f"   No entity name issues found ({resolution_result.execution_time_ms}ms)")

        # Step 2: Execute sub-queries with CoT Agents
        print(f"\n[COT] STEP 2: CoT Agents executing sub-queries...")
        all_findings: List[Finding] = []

        if self._config.parallel_cot_agents:
            # Parallel execution - each CoT agent gets its own MCP session
            # Session lifecycle is managed within each parallel task to avoid
            # anyio cancel scope issues (sessions must close in same task they were created)

            # SECURITY: Semaphore limits concurrent workers to prevent resource exhaustion
            # This protects against:
            # 1. Cloud cost explosion from too many concurrent LLM calls
            # 2. MCP server connection exhaustion
            # 3. Memory pressure from too many concurrent agents
            worker_semaphore = asyncio.Semaphore(self._config.max_parallel_workers)
            print(f"   Max parallel workers: {self._config.max_parallel_workers}")

            async def execute_with_session(subquery: SubQuery, agent_idx: int) -> WorkerResponse:
                """Execute a CoT agent with its own MCP session, respecting concurrency limits."""
                async with worker_semaphore:  # Limit concurrent execution
                    cot_agent_id = f"CoT-{agent_idx + 1}"
                    session_id = None
                    try:
                        # Acquire session within this task
                        session_id, session = await self._session_pool.acquire_session(cot_agent_id)

                        # Create tool manager with dedicated session (shares schema manager)
                        # Pass observer for query tracking (non-blocking)
                        tool_manager = ToolManager(
                            session,
                            self._schema_manager,
                            observer=self._cpg_observer,
                            agent_id=cot_agent_id
                        )
                        # Set sub-query context for detailed observation tracking
                        tool_manager.set_context(sub_query=subquery.query)

                        # Create and execute CoT agent
                        cot_agent = CoTAgent(
                            tool_manager,
                            self._openai,
                            self._llm_config,
                            self._config,
                            cot_agent_id
                        )
                        return await cot_agent.execute(subquery)
                    finally:
                        # Release session within same task (important for anyio cancel scopes)
                        if session_id:
                            try:
                                await self._session_pool.release_session(session_id)
                            except Exception as e:
                                self._logger.warning(f"Session cleanup warning for {session_id}: {e}")

            # Execute all agents in parallel, each managing its own session
            # Note: While all tasks start, the semaphore ensures only max_parallel_workers run concurrently
            tasks = [execute_with_session(sq, i) for i, sq in enumerate(decomposition.sub_queries)]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for i, resp in enumerate(responses):
                if isinstance(resp, Exception):
                    print(f"   CoT Agent {i+1}: ERROR - {resp}")
                else:
                    print(f"   CoT Agent {i+1}: {len(resp.findings)} findings ({resp.execution_time_ms}ms)")
                    all_findings.extend(resp.findings)
        else:
            # Sequential execution - uses shared session (no session pool needed)
            for i, sq in enumerate(decomposition.sub_queries):
                cot_agent = self._create_cot_agent(f"CoT-{i+1}")
                resp = await cot_agent.execute(sq)
                print(f"   CoT Agent {i+1}: {len(resp.findings)} findings ({resp.execution_time_ms}ms)")
                all_findings.extend(resp.findings)

        # Step 3: Verify findings
        verified_findings: List[Tuple[Finding, VerificationResult]] = []

        if self._config.verification_enabled and all_findings:
            print(f"\n[VERIFY] STEP 3: Verifying {len(all_findings)} findings...")
            for finding in all_findings:
                print(f"   Verifying: {finding.claim[:50]}...")
                resp = await self._verifier.execute(finding)
                status_icon = "[OK]" if resp.result.status == VerificationStatus.VERIFIED else "[X]"
                print(f"   {status_icon} {resp.result.status.value} ({resp.execution_time_ms}ms)")
                verified_findings.append((finding, resp.result))
        else:
            # Skip verification
            for finding in all_findings:
                verified_findings.append((finding, VerificationResult(
                    claim=finding.claim,
                    status=VerificationStatus.VERIFIED,
                    verified_evidence={},
                    explanation="Verification skipped"
                )))

        # Step 4: Build citations from findings + verification results
        citations: List[Citation] = []
        for finding, verification in verified_findings:
            citation = self._build_citation(finding, verification)
            citations.append(citation)

        # Step 5: Synthesize answer
        print(f"\n[SYNTHESIS] STEP 5: Synthesizing final answer...")
        final_answer = self._tot_orchestrator.synthesize_answer(sanitized_query, verified_findings)

        elapsed = time.time() - start_time
        execution_time_ms = int(elapsed * 1000)

        # Build production response
        verified_count = sum(1 for c in citations if c.verification_status == VerificationStatus.VERIFIED)
        unverified_count = len(citations) - verified_count

        production_response = ProductionResponse(
            answer=final_answer.answer,
            confidence=final_answer.confidence,
            citations=citations,
            verified_count=verified_count,
            unverified_count=unverified_count,
            token_usage=self._token_tracker,
            execution_time_ms=execution_time_ms,
            sub_queries_count=len(decomposition.sub_queries),
            llm_calls_count=self._token_tracker.call_count,
            original_query=sanitized_query
        )

        # Print results for CLI usage
        self._print_results(production_response)

        # OBSERVER: Save memory after each run for persistence
        if self._cpg_observer:
            self._cpg_observer.save_memory()
            stats = self._cpg_observer.get_stats()
            self._logger.info(f"CPG Observer: {stats['total_observations']} observations recorded")

        return production_response

    # =========================================================================
    # CPG OBSERVER PUBLIC API
    # =========================================================================

    async def get_observer_report(self, force: bool = False) -> Optional[ObserverReport]:
        """
        Generate and return a CPG improvement report from the observer.

        Args:
            force: If True, generate report even with few observations
        Returns:
            ObserverReport with identified issues and improvement suggestions
        """
        if not self._cpg_observer:
            self._logger.warning("CPG Observer is not enabled")
            return None
        return await self._cpg_observer.analyze_and_report(force=force)

    def get_observer_stats(self) -> Optional[Dict[str, Any]]:
        """Get current observer statistics"""
        if not self._cpg_observer:
            return None
        return self._cpg_observer.get_stats()

    def print_observer_report(self):
        """Print the latest observer report to console"""
        if not self._cpg_observer:
            print("CPG Observer is not enabled")
            return
        self._cpg_observer.print_report()

    async def explore_cpg(self, question: str) -> str:
        """
        Use the observer to explore the CPG and answer a question.

        Args:
            question: Natural language question about the CPG structure
        Returns:
            Answer from the observer's exploration
        """
        if not self._cpg_observer:
            return "CPG Observer is not enabled"
        return await self._cpg_observer.explore_cpg(question)

    @property
    def observer(self) -> Optional[CPGObserverAgent]:
        """Direct access to the CPG Observer Agent (if enabled)"""
        return self._cpg_observer

    def _build_citation(self, finding: Finding, verification: VerificationResult) -> Citation:
        """Build a Citation from a Finding and its VerificationResult"""
        # Extract primary entity info if available
        entity_name = None
        entity_type = None
        source_file = None
        source_line = None

        if finding.entities:
            primary_entity = finding.entities[0]
            entity_name = primary_entity.name
            entity_type = primary_entity.entity_type
            source_file = primary_entity.file_path
            # Try to get line number from properties
            if primary_entity.properties:
                source_line = primary_entity.properties.get('lineNumber') or primary_entity.properties.get('line')

        # Build human-readable source location
        source_location = None
        if source_file:
            source_location = source_file
            if source_line:
                source_location = f"{source_file}:{source_line}"

        return Citation(
            claim=finding.claim,
            source_file=source_file,
            source_line=source_line,
            source_location=source_location,
            entity_name=entity_name,
            entity_type=entity_type,
            evidence=finding.evidence,
            verification_status=verification.status,
            verification_explanation=verification.explanation,
            discovery_query=finding.source_query,
            verification_query=verification.verification_query,
            cot_agent_id=finding.cot_agent_id,
            confidence=finding.confidence
        )

    def _print_results(self, response: ProductionResponse) -> None:
        """Print results to console for CLI usage"""
        print(f"\n{'='*70}")
        print(f"FINAL ANSWER ({response.execution_time_ms / 1000:.2f}s)")
        print(f"{'='*70}")
        print(response.answer)

        print(f"\n{'='*70}")
        print("CITATIONS")
        print(f"{'='*70}")
        for i, citation in enumerate(response.citations, 1):
            status_icon = "[OK]" if citation.verification_status == VerificationStatus.VERIFIED else "[X]"
            print(f"\n{i}. {status_icon} {citation.claim}")
            if citation.source_location:
                print(f"   Location: {citation.source_location}")
            if citation.entity_name:
                print(f"   Entity: {citation.entity_name} ({citation.entity_type})")
            if citation.verification_explanation:
                print(f"   Verification: {citation.verification_explanation}")
            if citation.discovery_query:
                print(f"   Discovery Query: {citation.discovery_query}")
            if citation.verification_query:
                print(f"   Verification Query: {citation.verification_query}")

        print(f"\n{'='*70}")
        print("SUMMARY")
        print(f"{'='*70}")
        print(f"Time: {response.execution_time_ms / 1000:.2f}s")
        print(f"Sub-queries: {response.sub_queries_count}")
        print(f"Total citations: {len(response.citations)}")
        print(f"Verified: {response.verified_count}/{len(response.citations)}")
        print(f"Confidence: {response.confidence.value}")

        # Token usage transparency
        if response.token_usage:
            print(f"\n{'='*70}")
            print("TOKEN USAGE")
            print(f"{'='*70}")
            print(f"Total tokens: {response.token_usage.total_tokens:,}")
            print(f"  Prompt tokens: {response.token_usage.total_prompt_tokens:,}")
            print(f"  Completion tokens: {response.token_usage.total_completion_tokens:,}")
            print(f"LLM calls: {response.token_usage.call_count}")
            if response.token_usage.by_agent_role:
                print(f"By role:")
                for role, tokens in response.token_usage.by_agent_role.items():
                    print(f"  {role}: {tokens:,} tokens")


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Test the ToT/CoT multi-agent system"""

    # Example 1: Using file paths (backwards compatible)
    config = SystemConfig(
        mcp_config_path="neo4j_config.json",
        yaml_schema_path="/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml",
        llm_model="gpt-4o",
        max_cot_iterations=10,
        max_verifier_iterations=5,
        parallel_cot_agents=True,
        verification_enabled=True
    )

    # Example 2: Using direct config dicts (alternative)
    # config = SystemConfig(
    #     mcp_config={
    #         "mcpServers": {
    #             "neo4j_memory": {"type": "http", "url": "http://localhost:8100/sse"}
    #         }
    #     },
    #     yaml_schema_path="/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml",
    #     llm_config={"model": "gpt-4o", "temperature": 0.0},
    #     max_cot_iterations=10,
    #     verification_enabled=True
    # )

    system = MultiAgentCoT(config)
    await system.initialize()

    # Test queries
    queries = [
        "Analyze the overall architecture of the HelloWorldApp."
        # "What is the exact method signature of the CreateWorkers method in the WorkerFactory class?",
        # "What are the two parameters passed to Helper.FormatMessage?",
        # "What is the role of WorkerZ in the project?"
    ]

    for query in queries:
        response = await system.run(query)

        # Demonstrate production API response structure
        print(f"\n{'='*70}")
        print("PRODUCTION API RESPONSE (JSON)")
        print(f"{'='*70}")

        # Export to JSON (what a caller would receive)
        response_dict = response.model_dump()

        # Pretty print a summary of what the caller receives
        print(f"Response contains:")
        print(f"  - answer: {len(response.answer)} chars")
        print(f"  - confidence: {response.confidence.value}")
        print(f"  - citations: {len(response.citations)} items")
        print(f"  - token_usage: {response.token_usage.total_tokens:,} total tokens")
        print(f"  - execution_time_ms: {response.execution_time_ms}")
        print(f"  - original_query: '{response.original_query}'")

        # Optionally save full response to file
        output_file = "production_response.json"
        with open(output_file, 'w') as f:
            # Convert to JSON-serializable format
            json.dump(response_dict, f, indent=2, default=str)
        print(f"\nFull response saved to: {output_file}")
        print(f"\n{'='*70}\n")


if __name__ == "__main__":
    asyncio.run(main())
