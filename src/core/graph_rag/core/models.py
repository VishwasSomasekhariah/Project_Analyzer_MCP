"""
Pydantic models for the Graph RAG Multi-Agent system.
"""

from typing import Any, Dict, List, Optional, TypedDict
from pydantic import BaseModel, ConfigDict, Field

from .enums import ConfidenceLevel, VerificationStatus


# =============================================================================
# CORE ENTITY MODELS
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
    correction_feedback: Optional[str] = Field(None, description="Feedback for CoT agent on how to correct query/approach")
    suggested_query: Optional[str] = Field(None, description="Corrected query suggestion from verifier")


# =============================================================================
# QUERY DECOMPOSITION MODELS
# =============================================================================

class SubQuery(BaseModel):
    """A decomposed sub-query with dependency tracking"""
    model_config = ConfigDict(frozen=True)

    id: int = Field(..., description="Unique ID for this sub-query (1-indexed)")
    query: str = Field(..., description="The sub-query text")
    focus: str = Field(..., description="What aspect this sub-query focuses on")
    priority: int = Field(default=1, ge=1, le=5, description="Priority 1-5")
    depends_on: List[int] = Field(default=[], description="IDs of sub-queries this depends on")


class QueryDecomposition(BaseModel):
    """Result of query decomposition"""
    model_config = ConfigDict(frozen=True)

    original_query: str = Field(..., description="Original user query")
    sub_queries: List[SubQuery] = Field(..., description="Decomposed sub-queries")
    reasoning: str = Field(..., description="Reasoning for decomposition")


# =============================================================================
# AGENT RESPONSE MODELS
# =============================================================================

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


# =============================================================================
# ENTITY RESOLUTION MODELS
# =============================================================================

class EntityCorrection(BaseModel):
    """A suggested correction for an entity name"""
    model_config = ConfigDict(frozen=True)

    original_term: str = Field(..., description="Original term from query")
    suggested_name: str = Field(..., description="Corrected/proper entity name")
    entity_type: str = Field(..., description="Type: class, function, variable, etc.")
    file_path: Optional[str] = Field(None, description="File where entity is defined")
    confidence_score: float = Field(default=0.0, description="Fuzzy match score")
    issue_type: str = Field(default="case_sensitivity", description="Issue: case_sensitivity, misspelling, etc.")


class ResolvedEntity(BaseModel):
    """An entity that was successfully resolved with its type context.

    This helps CoT agents understand what type of entity they're dealing with,
    e.g., 'HelloWorldApp' is a Project (query by file_path) not a Class (query by Type.name).
    """
    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="The entity name from the query")
    entity_type: str = Field(..., description="Type: Project, Namespace, File, Class, Function, etc.")
    file_path: Optional[str] = Field(None, description="File/directory path if available")
    query_hint: str = Field(..., description="Hint for how to query this entity in Cypher")
    domain_explanation: Optional[str] = Field(
        None,
        description="Domain-specific explanation of the entity and any relevant concepts mentioned in the query (e.g., cyclomatic complexity definition, architectural patterns)"
    )


class EntityResolutionResult(BaseModel):
    """Result from entity resolution agent"""
    model_config = ConfigDict(frozen=True)

    corrections: List[EntityCorrection] = Field(default_factory=list, description="Entity corrections found")
    has_issues: bool = Field(default=False, description="Whether any issues were found")
    corrected_query: Optional[str] = Field(None, description="Query with corrections applied")
    resolved_entities: List[ResolvedEntity] = Field(default_factory=list, description="Entities successfully resolved with their types")
    execution_time_ms: int = Field(default=0)


# =============================================================================
# CPG OBSERVER MODELS
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


# =============================================================================
# FINAL ANSWER AND CITATION MODELS
# =============================================================================

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


# Forward reference for AggregatedTokenUsage (defined in metrics.py)
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

    # Token usage for cost tracking (imported from metrics when needed)
    token_usage: Optional[Any] = Field(None, description="Token usage breakdown")

    # Performance metrics
    execution_time_ms: int = Field(default=0, description="Total execution time in milliseconds")
    sub_queries_count: int = Field(default=0, description="Number of sub-queries generated")
    llm_calls_count: int = Field(default=0, description="Total LLM API calls made")

    # Original query for reference
    original_query: str = Field(default="", description="The original user query")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return self.model_dump()


# =============================================================================
# 4-AGENT TEAM MODELS
# =============================================================================

class ProposedQuery(BaseModel):
    """A single proposed Cypher query with its reasoning and purpose."""
    model_config = ConfigDict(frozen=True)

    query_id: int = Field(..., description="Unique ID for this query within the plan (1-indexed)")
    purpose: str = Field(..., description="What information this query retrieves")
    reasoning: str = Field(..., description="Why this query is needed and how it helps answer the sub-query")
    cypher_query: str = Field(..., description="The Cypher query to execute")
    target_entities: List[str] = Field(
        default_factory=list,
        description="Names of entities being queried (classes, functions, etc.)"
    )
    expected_result_type: str = Field(
        default="list",
        description="Expected type of results: list, count, relationship, boolean"
    )
    depends_on: List[int] = Field(
        default_factory=list,
        description="IDs of queries this depends on (for query chaining)"
    )


class ThinkerOutput(BaseModel):
    """Output from Thinker Agent - reasoning chain and proposed Cypher queries."""
    model_config = ConfigDict(frozen=True)

    overall_reasoning: List[str] = Field(
        ...,
        description="Step-by-step reasoning about how to approach the sub-query"
    )
    approach_summary: str = Field(
        ...,
        description="Brief summary of the overall approach being taken"
    )
    proposed_queries: List[ProposedQuery] = Field(
        ...,
        description="List of Cypher queries to execute (can be 1 or more)"
    )
    total_queries: int = Field(
        default=1,
        description="Number of queries being proposed"
    )


class QueryValidationResult(BaseModel):
    """Validation result for a single query."""
    model_config = ConfigDict(frozen=True)

    query_id: int = Field(..., description="ID of the query being validated")
    approved: bool = Field(..., description="Whether this query passed validation")
    issues: List[str] = Field(default_factory=list, description="Issues found with this query")
    suggested_fix: Optional[str] = Field(None, description="Suggested fixed query if rejected")


class ValidationResultBase(BaseModel):
    """Base model for validator agent outputs."""
    model_config = ConfigDict(frozen=True)

    approved: bool = Field(..., description="Whether the overall validation passed")
    feedback: Optional[str] = Field(
        None,
        description="Explanation of why validation failed, if applicable"
    )
    specific_issues: List[str] = Field(
        default_factory=list,
        description="List of specific issues found"
    )
    suggested_corrections: Optional[str] = Field(
        None,
        description="Suggested corrections to fix the issues"
    )


class ThinkingValidationResult(ValidationResultBase):
    """Output from Thinking Validator Agent - validates reasoning approach."""

    reasoning_gaps: List[str] = Field(
        default_factory=list,
        description="Gaps in the reasoning chain"
    )
    missing_aspects: List[str] = Field(
        default_factory=list,
        description="Aspects of the query not addressed by the reasoning"
    )
    queries_coverage_issues: List[str] = Field(
        default_factory=list,
        description="Issues with how queries cover the sub-query requirements"
    )


class CypherValidationResult(ValidationResultBase):
    """Output from Cypher Validator Agent - validates query correctness."""

    query_results: List[QueryValidationResult] = Field(
        default_factory=list,
        description="Validation results for each proposed query"
    )
    invalid_nodes: List[str] = Field(
        default_factory=list,
        description="Node types used that don't exist in schema"
    )
    invalid_properties: List[str] = Field(
        default_factory=list,
        description="Properties used that don't exist for their node types"
    )
    invalid_relationships: List[str] = Field(
        default_factory=list,
        description="Relationships that don't exist or have wrong direction"
    )
    path_issues: List[str] = Field(
        default_factory=list,
        description="Issues with query paths (unreachable, wrong direction, etc.)"
    )
    observed_categorical_values: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Discovered valid values for categorical properties (e.g., {'Statement.statement_type': ['expression', 'declaration']})"
    )


class ExecutedQuery(BaseModel):
    """Result of executing a single query."""
    model_config = ConfigDict(frozen=True)

    query_id: int = Field(..., description="ID of the executed query")
    cypher_query: str = Field(..., description="The query that was executed")
    results: List[Dict[str, Any]] = Field(default_factory=list, description="Query results")
    result_count: int = Field(default=0, description="Number of results returned")
    execution_time_ms: int = Field(default=0, description="Query execution time")
    error: Optional[str] = Field(None, description="Error if query failed")


class FourAgentState(TypedDict, total=False):
    """
    LangGraph state for 4-agent workflow.

    Uses TypedDict with total=False to allow partial updates from nodes.
    Each node returns only the keys it modifies.
    """
    # Input (set at workflow start)
    sub_query: SubQuery
    context_from_previous: str
    schema_info: Dict[str, Any]

    # Thinker output (may contain multiple queries)
    thinker_output: Optional[ThinkerOutput]

    # Validation results
    thinking_validation: Optional[ThinkingValidationResult]
    cypher_validation: Optional[CypherValidationResult]

    # Execution results (multiple queries possible)
    executed_queries: List[ExecutedQuery]
    findings: List[Finding]

    # Control flow
    iteration_count: int
    max_iterations: int
    validation_history: List[Dict[str, Any]]  # Track all validation attempts for debugging

    # Token tracking (reference to shared tracker)
    token_usage: Any  # AggregatedTokenUsage - Any to avoid circular import

    # Error tracking
    errors: List[str]


class FourAgentWorkflowResult(BaseModel):
    """Result from a complete 4-agent workflow execution."""
    model_config = ConfigDict(frozen=True)

    findings: List[Finding] = Field(
        default_factory=list,
        description="Findings produced by the workflow"
    )
    iterations_used: int = Field(
        default=0,
        description="Number of thinker iterations used"
    )
    executed_queries: List[ExecutedQuery] = Field(
        default_factory=list,
        description="All queries that were executed"
    )
    validation_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="History of validation attempts"
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Any errors encountered"
    )
    execution_time_ms: int = Field(
        default=0,
        description="Total execution time in milliseconds"
    )


__all__ = [
    # Core entities
    'CodeEntity',
    'Finding',
    'VerificationResult',
    # Query decomposition
    'SubQuery',
    'QueryDecomposition',
    # Agent responses
    'WorkerResponse',
    'VerifierResponse',
    # Entity resolution
    'EntityCorrection',
    'ResolvedEntity',
    'EntityResolutionResult',
    # CPG Observer
    'QueryObservation',
    'CPGIssue',
    'ObserverReport',
    'ObserverMemory',
    # Final answer
    'FinalAnswer',
    'Citation',
    'ProductionResponse',
    # 4-Agent Team
    'ProposedQuery',
    'ThinkerOutput',
    'QueryValidationResult',
    'ValidationResultBase',
    'ThinkingValidationResult',
    'CypherValidationResult',
    'ExecutedQuery',
    'FourAgentState',
    'FourAgentWorkflowResult',
]
