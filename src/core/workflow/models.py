"""
Data models for the Adaptive CPG Agent Workflow.

This module contains all the data structures used throughout the workflow,
including schema analysis, exploration hypotheses, query strategies, and state management.
Uses Pydantic for enhanced validation, error handling, and type safety.
"""
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional, Literal, Annotated, Tuple
from typing_extensions import TypedDict
from langgraph.graph import add_messages
import logging

logger = logging.getLogger(__name__)


# No automatic reducers - manual aggregation in execute_batch_approaches
# Removed defensive merger functions since we're doing explicit manual aggregation


class SchemaAnalysis(BaseModel):
    """Analysis of CPG schema for query planning with validation"""
    relevant_node_types: List[str] = Field(..., min_items=1, description="List of relevant CPG node types")
    data_storage_candidates: Dict[str, List[str]] = Field(..., description="Potential data storage locations")
    node_attribute_mapping: Dict[str, List[str]] = Field(..., description="Mapping of relevant node types to their specific attributes")
    relationships_to_explore: List[str] = Field(..., min_items=0, description="Relevant CPG relationships (can be empty if none are needed)")
    reasoning: str = Field(..., min_length=10, description="Reasoning behind the analysis")
    
    # Store schema for validation - will be set during creation
    _schema: Optional[Dict[str, Any]] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    @validator('node_attribute_mapping')
    def validate_node_attribute_mapping(cls, v, values):
        """Validate that mapped attributes actually exist in the schema"""
        # Get schema from context if available (passed during validation)
        schema = getattr(cls, '_validation_schema', None)
        
        if not schema or 'nodes' not in schema:
            # If no schema available for validation, skip this check
            return v
            
        validation_errors = []
        
        for node_type, attributes in v.items():
            if node_type not in schema['nodes']:
                validation_errors.append(f"Node type '{node_type}' does not exist in schema")
                continue
                
            valid_attributes = schema['nodes'][node_type].get('attributes', [])
            invalid_attributes = [attr for attr in attributes if attr not in valid_attributes]
            
            if invalid_attributes:
                validation_errors.append(
                    f"Node type '{node_type}' does not have attributes: {invalid_attributes}. "
                    f"Valid attributes are: {valid_attributes}"
                )
        
        if validation_errors:
            raise ValueError(f"Schema validation errors: {'; '.join(validation_errors)}")
            
        return v

    @validator('relevant_node_types')
    def validate_node_types(cls, v):
        if not v or len(v) == 0:
            raise ValueError("Must specify at least one relevant node type")
        return v

    @validator('data_storage_candidates')
    def validate_storage_candidates(cls, v):
        if not v:
            raise ValueError("Must specify data storage candidates")
        
        # Check that at least one category has values (some categories can be empty)
        has_any_values = any(values and len(values) > 0 for values in v.values())
        if not has_any_values:
            raise ValueError("At least one storage candidate category must have values")
        
        return v


class ExplorationHypothesis(BaseModel):
    """Methodological approach for systematic workflow planning"""
    hypothesis: str = Field(..., min_length=10, description="The methodological approach name")
    likelihood: Literal['high', 'medium', 'low', 'systematic_enumeration'] = Field(..., description="Approach priority or systematic enumeration marker")
    reasoning: str = Field(..., min_length=10, description="Reasoning behind this methodological approach")
    target_nodes: List[str] = Field(..., min_items=1, description="Target CPG node types for this approach")
    path_type: Optional[str] = Field(default="general", description="Type of methodological approach (content_parsing, structural_navigation, etc.)")
    methodological_focus: Optional[str] = Field(default=None, description="Core methodological focus and strategy")
    schema_corrections: Optional[List[str]] = Field(default_factory=list, description="Schema corrections applied during audit")

    @validator('target_nodes')
    def validate_target_nodes(cls, v):
        if not v or len(v) == 0:
            raise ValueError("Must specify at least one target node")
        return v


class QueryStrategy(BaseModel):
    """Comprehensive strategy for executing discovery paths systematically"""
    strategy_name: str = Field(..., min_length=5, description="Name of the query strategy")
    approach: str = Field(..., min_length=10, description="High-level approach description")
    target_entities: List[str] = Field(default_factory=list, description="Target entities for the strategy")
    expected_query_count: int = Field(..., ge=1, le=30, description="Expected number of queries (increased for comprehensive coverage)")
    reasoning: str = Field(..., min_length=10, description="Reasoning for the strategy")
    covered_paths: Optional[List[str]] = Field(default_factory=list, description="Types of discovery paths this strategy covers")
    query_sequence: Optional[List[str]] = Field(default_factory=list, description="Planned sequence of query approaches")

    @validator('expected_query_count')
    def validate_query_count(cls, v):
        if v < 1:
            raise ValueError("Expected query count must be at least 1")
        if v > 20:
            raise ValueError("Expected query count should not exceed 20 for performance")
        return v


class ExecutionPlan(BaseModel):
    """Complete execution plan for comprehensive data discovery workflow"""
    primary_strategy: str = Field(..., min_length=5, description="Primary strategy to execute first")
    fallback_strategies: List[str] = Field(default_factory=list, description="Additional strategies to execute sequentially")
    execution_sequence: Optional[List[str]] = Field(default_factory=list, description="Planned execution sequence of all strategies")
    termination_criteria: List[str] = Field(..., min_items=1, description="When to stop exploration")
    estimated_iterations: int = Field(..., ge=1, le=50, description="Estimated total iterations across all strategies")

    @validator('termination_criteria')
    def validate_termination_criteria(cls, v):
        if not v or len(v) == 0:
            raise ValueError("Must specify at least one termination criterion")
        return v

    @validator('estimated_iterations')
    def validate_iterations(cls, v):
        if v < 1:
            raise ValueError("Must estimate at least 1 iteration")
        if v > 50:
            raise ValueError("Estimated iterations should not exceed 50 for performance")
        return v


class DiscoveryResearch(BaseModel):
    """Complete discovery research results with validation"""
    schema_analysis: SchemaAnalysis = Field(..., description="Schema analysis results")
    hypotheses: List[ExplorationHypothesis] = Field(..., min_items=1, description="Exploration hypotheses")
    strategies: List[QueryStrategy] = Field(..., min_items=1, description="Query strategies")
    execution_plan: ExecutionPlan = Field(..., description="Execution plan")

    @validator('hypotheses')
    def validate_hypotheses(cls, v):
        if not v or len(v) == 0:
            raise ValueError("Must have at least one exploration hypothesis")
        
        # Ensure we have at least one high-likelihood hypothesis
        high_likelihood_count = sum(1 for h in v if h.likelihood == 'high')
        if high_likelihood_count == 0:
            raise ValueError("Must have at least one high-likelihood hypothesis")
        return v

    @validator('strategies')
    def validate_strategies(cls, v):
        if not v or len(v) == 0:
            raise ValueError("Must have at least one query strategy")
        return v


class IntentAnalysis(BaseModel):
    """User intent analysis with validation"""
    intent_type: Literal['lookup', 'architectural', 'hybrid'] = Field(..., description="Type of intent")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    reasoning: str = Field(..., min_length=10, description="Reasoning for the classification")
    expected_result_type: str = Field(..., description="Expected type of results")
    
    @validator('confidence')
    def validate_confidence(cls, v):
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v


class SufficiencyEvaluation(BaseModel):
    """Sufficiency evaluation results with validation"""
    is_sufficient: bool = Field(..., description="Whether data is sufficient")
    decision: Literal['SUFFICIENT', 'NEED_MORE', 'NEED_BODY_EXPLORATION'] = Field(..., description="Decision type")
    gaps_summary: str = Field(..., min_length=5, description="Summary of data gaps")
    data_gaps: Dict[str, List[str]] = Field(default_factory=dict, description="Specific data gaps")
    body_exploration_needed: bool = Field(default=False, description="Whether body exploration is needed")
    entities_for_body_exploration: List[str] = Field(default_factory=list, description="Entities to explore")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in evaluation")
    reasoning: str = Field(..., min_length=10, description="Reasoning for the evaluation")

    @validator('confidence')
    def validate_confidence(cls, v):
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v

    @validator('entities_for_body_exploration')
    def validate_body_exploration_entities(cls, v, values):
        if values.get('body_exploration_needed', False) and not v:
            raise ValueError("Must specify entities for body exploration when body_exploration_needed=True")
        return v


class ScopeAnalysis(BaseModel):
    """Scope analysis result from Think step LLM call with validation"""
    scope: Literal['single_file', 'multi_file'] = Field(..., description="Scope type for this approach")
    reasoning: str = Field(..., min_length=10, description="Reasoning for scope decision")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in scope analysis")
    retrieval_strategy: Dict[str, Any] = Field(..., description="Retrieval strategy details")
    
    @validator('confidence')
    def validate_confidence(cls, v):
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v
    
    @validator('retrieval_strategy')
    def validate_retrieval_strategy(cls, v):
        required_fields = ['limit', 'focus', 'context_window']
        for field in required_fields:
            if field not in v:
                raise ValueError(f"Retrieval strategy must include '{field}'")
        
        # Validate limit is reasonable
        limit = v.get('limit')
        if not isinstance(limit, int) or limit < 1 or limit > 500:
            raise ValueError("Retrieval limit must be an integer between 1 and 500")
        
        # Validate focus values
        if v.get('focus') not in ['targeted', 'comprehensive']:
            raise ValueError("Focus must be 'targeted' or 'comprehensive'")
        
        # Validate context_window values
        if v.get('context_window') not in ['small', 'large']:
            raise ValueError("Context window must be 'small' or 'large'")
        
        return v


class RethinkAnalysis(BaseModel):
    """Rethink analysis after executing queries for an approach"""
    approach_index: int = Field(..., ge=0, description="Index of approach that was executed")
    approach_name: str = Field(..., min_length=5, description="Name of approach that was executed")
    
    # Analysis of current approach results
    approach_effectiveness: float = Field(..., ge=0.0, le=1.0, description="How effective was this approach")
    key_findings: List[str] = Field(default_factory=list, description="Key findings from this approach")
    data_gaps_identified: List[str] = Field(default_factory=list, description="What data gaps were identified")
    
    # Cumulative analysis across all iterations so far
    sufficiency_assessment: SufficiencyEvaluation = Field(..., description="Assessment of current sufficiency")
    iteration_summary: str = Field(..., min_length=20, description="Summary of this iteration for progressive context management")
    
    # Summary for workflow context (LLM analysis only - workflow makes decisions)
    next_step_reasoning: str = Field(..., min_length=10, description="Analysis of what might be needed next based on data quality")
    
    @validator('approach_effectiveness')
    def validate_effectiveness(cls, v):
        return max(0.0, min(1.0, v))  # Ensure 0.0 <= v <= 1.0


class SingleQuery(BaseModel):
    """Single Cypher query with metadata"""
    cypher_query: str = Field(..., min_length=10, description="Generated Cypher query")
    reasoning: str = Field(..., min_length=10, description="How this query implements the approach strategy")
    query_purpose: str = Field(..., min_length=5, description="Specific aspect this query covers")
    
    @validator('cypher_query')
    def validate_cypher_query(cls, v):
        # Basic Cypher validation
        v_upper = v.upper().strip()
        if not v_upper.startswith('MATCH') and not v_upper.startswith('WITH') and not v_upper.startswith('CALL'):
            raise ValueError("Cypher query must start with MATCH, WITH, or CALL")
        
        if 'RETURN' not in v_upper:
            raise ValueError("Cypher query must include RETURN statement")
        
        # Check for basic Neo4j injection prevention
        dangerous_patterns = ['DELETE', 'DROP', 'CREATE ', 'MERGE ', 'SET ']
        for pattern in dangerous_patterns:
            if pattern in v_upper:
                raise ValueError(f"Query contains potentially dangerous operation: {pattern}")
        
        return v


class QueryGeneration(BaseModel):
    """Query generation result from Generate step LLM call with validation (supports multiple queries)"""
    queries: List[SingleQuery] = Field(..., min_items=1, max_items=8, description="1-8 generated queries implementing the approach (flexible limit)")
    approach_summary: str = Field(..., min_length=10, description="How these queries collectively implement the research approach")
    
    @validator('queries')
    def validate_queries_list(cls, v):
        if not v:
            raise ValueError("At least one query must be generated")
        if len(v) > 8:
            raise ValueError("Maximum 8 queries allowed per approach to prevent context explosion")
        return v


class DiagnosticQuery(BaseModel):
    """Single diagnostic query for empty result analysis with validation"""
    purpose: str = Field(..., min_length=10, description="Clear description of what this query investigates")
    query: str = Field(..., min_length=15, description="Executable Cypher query")
    
    @validator('query')
    def validate_diagnostic_query(cls, v):
        # Basic Cypher validation for diagnostic queries
        v_upper = v.upper().strip()
        if not v_upper.startswith('MATCH') and not v_upper.startswith('WITH') and not v_upper.startswith('CALL'):
            raise ValueError("Diagnostic query must start with MATCH, WITH, or CALL")
        
        if 'RETURN' not in v_upper:
            raise ValueError("Diagnostic query must include RETURN statement")
        
        # Check for dangerous operations
        dangerous_patterns = ['DELETE', 'DROP', 'CREATE ', 'MERGE ', 'SET ']
        for pattern in dangerous_patterns:
            if pattern in v_upper:
                raise ValueError(f"Diagnostic query contains potentially dangerous operation: {pattern}")
        
        return v


class DiagnosticQueryGeneration(BaseModel):
    """LLM response for diagnostic query generation with validation"""
    diagnostic_queries: List[DiagnosticQuery] = Field(..., min_items=2, max_items=6, 
                                                     description="List of diagnostic queries")
    diagnostic_strategy: str = Field(..., min_length=20, description="Overall diagnostic approach explanation")
    
    @validator('diagnostic_queries')
    def validate_diagnostic_queries(cls, v):
        if len(v) < 2:
            raise ValueError("Must generate at least 2 diagnostic queries")
        if len(v) > 6:
            raise ValueError("Should not generate more than 6 diagnostic queries for performance")
        
        # Check for duplicate purposes
        purposes = [query.purpose.lower() for query in v]
        if len(purposes) != len(set(purposes)):
            raise ValueError("Diagnostic queries must have unique purposes")
        
        return v


class EmptyResultConclusion(BaseModel):
    """LLM response for empty result conclusion analysis with validation"""
    conclusion: str = Field(..., min_length=20, description="Primary conclusion about why the query was empty")
    root_cause: str = Field(..., min_length=5, description="Specific root cause category")
    evidence: List[str] = Field(..., min_items=1, description="Evidence from diagnostic queries")
    findings: List[str] = Field(..., min_items=1, description="Detailed findings from analysis")
    recommendations: List[str] = Field(..., min_items=1, description="Actionable steps to fix the query")
    suggested_query_modifications: List[str] = Field(default_factory=list, description="Concrete query improvement suggestions")
    confidence_level: Literal['high', 'medium', 'low'] = Field(..., description="Confidence in the analysis")
    analysis_type: str = Field(default="llm_intelligent", description="Type of analysis performed")
    
    @validator('root_cause')
    def validate_root_cause(cls, v):
        valid_causes = [
            'missing_nodes', 'wrong_relationships', 'restrictive_filters', 
            'logical_error', 'missing_properties', 'incorrect_node_labels',
            'query_too_restrictive', 'data_structure_mismatch', 'unknown'
        ]
        if v not in valid_causes:
            # Allow custom root causes but log them
            pass  # Don't be too restrictive on root cause categories
        return v
    
    @validator('confidence_level')
    def validate_confidence(cls, v):
        if v not in ['high', 'medium', 'low']:
            raise ValueError("Confidence level must be high, medium, or low")
        return v


class QueryRefinement(BaseModel):
    """LLM response for refining failed queries using diagnostic findings"""
    refined_queries: List[Dict[str, Any]] = Field(..., description="List of refined queries with metadata")
    refinement_strategy: str = Field(..., description="Overall refinement approach explanation")
    approach_viability: Literal['high', 'medium', 'low'] = Field(..., description="Assessment of whether this approach can succeed")

    @validator('refined_queries')
    def validate_refined_queries(cls, v):
        if not v:
            raise ValueError("Must provide at least one refined query")

        # Validate each refined query has required fields
        for i, query in enumerate(v):
            required_fields = ['index', 'refined_query', 'changes_made', 'confidence']
            for field in required_fields:
                if field not in query:
                    raise ValueError(f"Refined query {i} missing required field: {field}")

            # Validate confidence is between 0 and 1
            confidence = query.get('confidence')
            if not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
                raise ValueError(f"Refined query {i} confidence must be between 0.0 and 1.0")

        return v

    @validator('approach_viability')
    def validate_viability(cls, v):
        if v not in ['high', 'medium', 'low']:
            raise ValueError("Approach viability must be high, medium, or low")
        return v


class SynthesisValidation(BaseModel):
    """Validation results for synthesis quality check"""
    is_valid: bool = Field(..., description="Overall validation result")
    faithfulness_score: float = Field(..., ge=0.0, le=1.0, description="Response based on actual findings (0.0-1.0)")
    completeness_score: float = Field(..., ge=0.0, le=1.0, description="All important data included (0.0-1.0)")
    accuracy_score: float = Field(..., ge=0.0, le=1.0, description="Actually answers the user's question (0.0-1.0)")
    quality_score: float = Field(..., ge=0.0, le=1.0, description="Overall response quality (0.0-1.0)")
    
    validation_issues: List[str] = Field(default_factory=list, description="Specific issues found")
    missing_entities: List[str] = Field(default_factory=list, description="Important entities not mentioned")
    hallucinated_content: List[str] = Field(default_factory=list, description="Content not supported by findings")
    
    overall_score: float = Field(..., ge=0.0, le=1.0, description="Combined validation score")
    decision: Literal['accept', 'retry', 'fallback'] = Field(..., description="What to do with this response")
    reasoning: str = Field(..., min_length=10, description="Detailed validation reasoning")
    
    @validator('overall_score')
    def validate_overall_score(cls, v, values):
        # Calculate overall score as average of component scores
        scores = [
            values.get('faithfulness_score', 0),
            values.get('completeness_score', 0), 
            values.get('accuracy_score', 0),
            values.get('quality_score', 0)
        ]
        calculated_score = sum(scores) / len(scores) if scores else 0
        # Allow some tolerance for manual override
        if abs(v - calculated_score) > 0.2:
            raise ValueError(f"Overall score {v} too different from calculated {calculated_score:.2f}")
        return v


class LLMCallMetrics(BaseModel):
    """Token usage and cost metrics for a single LLM call"""
    call_type: str = Field(..., description="Type of LLM call (think, generate, rethink, diagnostics, etc.)")
    timestamp: float = Field(..., description="Unix timestamp of call")
    model_name: str = Field(..., description="LLM model used")

    # Token usage
    input_tokens: int = Field(..., ge=0, description="Number of input tokens")
    output_tokens: int = Field(..., ge=0, description="Number of output tokens")
    total_tokens: int = Field(..., ge=0, description="Total tokens (input + output)")

    # Cost estimation (based on model pricing)
    input_cost_usd: float = Field(default=0.0, ge=0.0, description="Estimated input cost in USD")
    output_cost_usd: float = Field(default=0.0, ge=0.0, description="Estimated output cost in USD")
    total_cost_usd: float = Field(default=0.0, ge=0.0, description="Total estimated cost in USD")

    # Timing
    latency_seconds: Optional[float] = Field(default=None, ge=0.0, description="API call latency")

    # Context
    call_purpose: Optional[str] = Field(default=None, description="Specific purpose of this call")

    @validator('total_tokens')
    def validate_total_tokens(cls, v, values):
        input_tokens = values.get('input_tokens', 0)
        output_tokens = values.get('output_tokens', 0)
        expected = input_tokens + output_tokens
        if v != expected:
            return expected  # Auto-correct
        return v

    @validator('total_cost_usd')
    def validate_total_cost(cls, v, values):
        input_cost = values.get('input_cost_usd', 0.0)
        output_cost = values.get('output_cost_usd', 0.0)
        expected = input_cost + output_cost
        if abs(v - expected) > 0.000001:  # Floating point tolerance
            return expected  # Auto-correct
        return v


class ApproachExecutionTrace(BaseModel):
    """
    Complete execution trace for a single approach.
    Tracks the full journey: think → generate → execute → rethink (with refinement loops)
    """
    approach_index: int = Field(..., ge=0, description="Index of this approach")
    approach_name: str = Field(..., min_length=5, description="Name of this approach")
    approach_strategy: str = Field(..., description="High-level strategy for this approach")

    # Execution lifecycle tracking
    start_time: float = Field(..., description="Unix timestamp when approach started")
    end_time: Optional[float] = Field(default=None, description="Unix timestamp when approach completed")
    duration_seconds: Optional[float] = Field(default=None, description="Total execution time")

    # Step-by-step execution history
    think_step: Optional[Dict[str, Any]] = Field(default=None, description="Think step results")
    generate_cycles: List[Dict[str, Any]] = Field(default_factory=list, description="List of generate cycles (original + refinements)")
    execute_cycles: List[Dict[str, Any]] = Field(default_factory=list, description="List of execute cycles (original + refinements)")
    rethink_cycles: List[Dict[str, Any]] = Field(default_factory=list, description="List of rethink cycles")

    # Query tracking
    original_queries: List[Dict[str, Any]] = Field(default_factory=list, description="Original generated queries")
    refined_queries: List[Dict[str, Any]] = Field(default_factory=list, description="Refined queries from diagnostics")
    all_executed_queries: List[Dict[str, Any]] = Field(default_factory=list, description="All queries executed (original + refined)")

    # Results tracking
    successful_queries: List[Dict[str, Any]] = Field(default_factory=list, description="Queries that succeeded")
    failed_queries: List[Dict[str, Any]] = Field(default_factory=list, description="Queries that failed")
    diagnostic_results: List[Dict[str, Any]] = Field(default_factory=list, description="Diagnostic query results")

    # Refinement tracking
    refinement_attempts: int = Field(default=0, ge=0, description="Number of refinement cycles")
    refinement_history: List[Dict[str, Any]] = Field(default_factory=list, description="History of refinement attempts")

    # Final status
    status: Literal['success', 'partial', 'failed', 'in_progress'] = Field(default='in_progress', description="Final status")
    final_data: List[Dict[str, Any]] = Field(default_factory=list, description="Cleaned final data for citations")
    completion_reason: Optional[str] = Field(default=None, description="Why approach completed")

    # Effectiveness metrics
    effectiveness_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="LLM assessment of effectiveness")
    data_quality_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Quality of collected data")

    # Token utilization tracking
    llm_calls: List[Dict[str, Any]] = Field(default_factory=list, description="All LLM calls made during this approach")
    total_input_tokens: int = Field(default=0, ge=0, description="Total input tokens across all LLM calls")
    total_output_tokens: int = Field(default=0, ge=0, description="Total output tokens across all LLM calls")
    total_tokens: int = Field(default=0, ge=0, description="Total tokens (input + output)")
    total_cost_usd: float = Field(default=0.0, ge=0.0, description="Total estimated cost for this approach")

    # Token efficiency metrics
    tokens_per_query_generated: Optional[float] = Field(default=None, description="Average tokens per query generated")
    tokens_per_successful_result: Optional[float] = Field(default=None, description="Tokens spent per successful result")
    cost_per_data_point: Optional[float] = Field(default=None, description="Cost per data point collected")

    @validator('duration_seconds')
    def calculate_duration(cls, v, values):
        if v is None and 'start_time' in values and 'end_time' in values:
            start = values['start_time']
            end = values.get('end_time')
            if end is not None:
                return round(end - start, 2)
        return v

    @validator('total_tokens')
    def calculate_total_tokens(cls, v, values):
        input_tokens = values.get('total_input_tokens', 0)
        output_tokens = values.get('total_output_tokens', 0)
        return input_tokens + output_tokens


class AgentState(TypedDict):
    """
    State management for LangGraph workflow.

    No automatic reducers - we manually aggregate results from parallel branches
    in the execute_batch_approaches node.
    """

    # Core workflow data - overwrite on each update
    user_query: str
    intent: str
    current_query: Optional[str]
    current_iteration: int
    max_iterations: int
    should_continue: bool
    response: str
    current_node: str

    # Accumulated data - manually aggregated in execute_batch_approaches
    entities: List[str]  # Union of entities (manually merged)
    discovered_data: List[Dict[str, Any]]  # All discovered data (manually appended)
    raw_query_results: List[Dict[str, Any]]  # All raw results (manually appended)
    query_history: List[Dict[str, Any]]  # All queries (manually appended)
    final_results: List[Dict[str, Any]]  # Final results (manually appended)
    body_exploration_candidates: List[str]  # Union (manually merged)
    body_exploration_results: List[Dict[str, Any]]  # Append (manually appended)

    # Configuration and metadata - overwrite
    schema: Dict[str, Any]  # YAML schema for backward compatibility
    schema_manager: Optional[Any]  # DynamicSchemaManager with reconciled schema + path discovery
    llm_service: Any
    neo4j_config: Optional[str]
    neo4j_version: Optional[str]
    metadata: Optional[Dict[str, Any]]

    # Cypher server service for performance optimization - overwrite
    cypher_server_service: Optional[Any]  # CypherServerService instance for 99.3% performance improvement

    # Complex objects - overwrite on update
    disambiguated_entities: Dict[str, Any]
    vector_results: Optional[Dict[str, Any]]
    vector_collection_name: Optional[str]
    sufficiency_evaluation: Optional[Dict[str, Any]]
    organized_data: Optional[Dict[str, Any]]
    discovery_research: Optional[Dict[str, Any]]
    previous_audit_errors: Optional[List[str]]  # For research feedback loop

    # Think → Generate → Execute → Rethink workflow state - overwrite
    current_approach_index: int  # Which research approach we're currently trying (0-based)
    total_approaches: int  # Total number of research approaches available
    current_scope: Optional[str]  # "single_file" or "multi_file" for current approach
    current_approach_details: Optional[Dict[str, Any]]  # Details of current approach being tried
    thinking_results: Optional[Dict[str, Any]]  # Results from think step analysis
    rethinking_results: Optional[Dict[str, Any]]  # Results from rethink step analysis

    # Execute step state - accumulated and overwrite fields
    generated_queries: List[List[Dict[str, Any]]]  # List of query lists - one list per approach (managed manually)
    execution_results: List[Dict[str, Any]]  # Results from query execution (managed manually)
    execution_analysis: Optional[Dict[str, Any]]  # Analysis of execution results (overwrite)
    execution_status: Optional[str]  # Overall execution status (overwrite)
    total_results_found: int  # Total results found across all executions (overwrite)

    # Raw results tracking by approach - manually aggregated
    approach_raw_results: Dict[int, List[Tuple[str, List[Dict]]]]  # Manually merged
    iteration_summaries: List[str]  # Manually appended
    cumulative_findings: str  # Running summary (last write wins)

    # Rethink step state
    rethink_analysis: Optional[Dict[str, Any]]  # Current rethink analysis results
    sufficiency_check_history: List[Dict[str, Any]]  # Manually appended
    should_synthesize: bool  # Flag from rethink to determine if ready for synthesis

    # Flags - overwrite
    fallback_mode: Optional[bool]
    diverse_queries_generated: Optional[bool]
    synthesis_context_used: Optional[int]
    syntax_error_count: int  # Track syntax error retries to prevent infinite loops

    # Query refinement and approach failure tracking - manually merged
    failed_approaches: List[int]  # Union of failed approaches (manually merged)
    approach_statuses: Dict[int, str]  # Status per approach (manually merged)

    # ============================================================================
    # NEW: Per-Approach Execution Tracking for Parallel-Optimized Architecture
    # ============================================================================

    # Complete execution traces per approach - manually merged
    approach_execution_traces: Dict[int, Dict[str, Any]]  # Manually merged

    # Current approach refinement state (for active approach only)
    needs_refinement: bool  # Does current approach need query refinement?
    refinement_attempts: Dict[int, int]  # Manually merged
    refined_queries: List[Dict[str, Any]]  # Refined queries for current approach
    diagnostics: List[Dict[str, Any]]  # Diagnostic results for current approach

    # Sufficiency checking state (after batch completion)
    is_sufficient: bool  # Is accumulated data sufficient to answer query?
    sufficiency_confidence: float  # LLM confidence in sufficiency (0.0-1.0)
    sufficiency_reasoning: str  # Why data is/isn't sufficient

    # Batch execution tracking
    execution_mode: str  # 'sequential' or 'batch'
    batch_size: int  # Number of approaches per batch
    current_batch_number: int  # Which batch are we on (0-based)
    batches_completed: int  # Total batches completed so far
    more_batches_remaining: bool  # Are there more execution groups/batches to execute?
    max_workers: int  # Maximum concurrent workers for parallel approach execution (default: 3)

    # Cypher server pool for batch mode
    cypher_server_pool: Optional[Any]  # CypherServerPool instance for parallel execution

    # ============================================================================
    # Token Utilization Tracking - Global Metrics (Manually Aggregated)
    # ============================================================================

    # Per-node LLM call tracking - manually appended
    llm_call_history: List[Dict[str, Any]]  # All LLM calls (manually appended)

    # Global token metrics - manually summed
    total_input_tokens: int  # Sum input tokens (manually summed)
    total_output_tokens: int  # Sum output tokens (manually summed)
    total_tokens_used: int  # Sum total tokens (manually summed)
    total_estimated_cost_usd: float  # Sum costs (manually summed)

    # Per-step token breakdown - manually summed
    discovery_research_tokens: int  # Tokens used in discovery_research node (single execution)
    think_tokens: int  # Sum across all think steps (manually summed)
    generate_tokens: int  # Sum across all generate steps (manually summed)
    rethink_tokens: int  # Sum across all rethink steps (manually summed)
    diagnostics_tokens: int  # Sum diagnostic tokens (manually summed)
    refinement_tokens: int  # Sum refinement tokens (manually summed)
    sufficiency_check_tokens: int  # Sufficiency check (single execution after batch)
    synthesis_tokens: int  # Synthesis (single execution at end)

    # Efficiency metrics - manually merged
    tokens_per_approach: Dict[int, int]  # Token counts per approach (manually merged)
    cost_per_approach: Dict[int, float]  # Costs per approach (manually merged)
    tokens_per_data_point: Optional[float]  # Average (calculated at end)
    cost_per_data_point: Optional[float]  # Average (calculated at end)

    # Model usage tracking - manually merged
    models_used: List[str]  # Union of models (manually merged)
    primary_model: str  # Primary model (last write wins)

    # Feature flags - overwrite
    use_schema_tools: bool  # Enable tool-based schema discovery in generate step (V8)

    # ============================================================================
    # Phase 0: Query Decomposition and Approach Packet Management
    # ============================================================================

    # Phase 0 outputs - overwrite
    query_decomposition: Optional[Dict[str, Any]]  # Raw decomposition (logical_form, premises, subqueries)
    dependency_analysis: Optional[Dict[str, Any]]  # Dependency analysis with execution groups

    # Self-contained approach packets - overwrite
    approach_packets: Optional[Dict[str, Any]]  # ApproachPacketCollection (packets dict, worker pool executes all in parallel)

    # Execution tracking for approach packets
    completed_subqueries: List[str]  # IDs of completed subqueries (manually appended)
    subquery_results: Dict[str, Any]  # Results by subquery ID (manually merged)


# =====================================================================
# Query Decomposition Models (Phase 0) - Logical Reasoning Approach
# =====================================================================

class LogicalQueryDecomposition(BaseModel):
    """
    Structured logical interpretation of user query with retrieval subqueries.

    Uses formal logic and modal reasoning to express query structure,
    treating schema as possibilities rather than guarantees.
    """
    intent: str = Field(..., min_length=3, description="Intent type from classifier (lookup, exploratory, comparison, etc)")
    logical_form: str = Field(..., min_length=10, description="Formal logical/modal expression of query structure")
    premises: List[str] = Field(..., min_items=1, description="Logical or contextual assumptions")
    subqueries: List[str] = Field(..., min_items=1, description="Abstract retrieval-oriented subquery statements")

    @validator('logical_form')
    def validate_logical_form(cls, v):
        """Validate logical form contains meaningful reasoning"""
        if not v or len(v.strip()) < 10:
            raise ValueError("Logical form must be a meaningful expression")
        return v

    @validator('subqueries')
    def validate_subqueries(cls, v):
        """Validate subqueries are actionable"""
        if not v:
            raise ValueError("Must have at least one subquery")

        # Check for abstract retrieval verbs
        valid_verbs = ['locate', 'retrieve', 'count', 'collect', 'summarize', 'compare', 'find', 'get', 'check']
        for sq in v:
            if not any(verb in sq.lower() for verb in valid_verbs):
                # Allow through but log warning
                logger.warning(f"Subquery may not be retrieval-oriented: {sq}")

        return v


# =====================================================================
# Enhanced Dependency Mapping Models (Phase 0 Post-Processing)
# =====================================================================

class EnhancedPremise(BaseModel):
    """
    Enhanced premise with explicit dependency tracking.

    Maps which subqueries depend on this premise being valid.
    """
    id: str = Field(..., description="Premise identifier (P1, P2, etc)")
    text: str = Field(..., min_length=5, description="Original premise text")
    validates: List[str] = Field(default_factory=list, description="List of subquery IDs that depend on this premise (e.g., ['SQ1', 'SQ3'])")

    @validator('id')
    def validate_id(cls, v):
        """Validate premise ID format"""
        if not v.startswith('P'):
            raise ValueError("Premise ID must start with 'P' (e.g., 'P1', 'P2')")
        return v

    @validator('validates')
    def validate_references(cls, v):
        """Validate subquery references format"""
        for ref in v:
            if not ref.startswith('SQ'):
                raise ValueError(f"Subquery reference must start with 'SQ' (e.g., 'SQ1'), got: {ref}")
        return v


class EnhancedSubquery(BaseModel):
    """
    Enhanced subquery with explicit dependency tracking.

    Maps premise dependencies and subquery-to-subquery dependencies.
    """
    id: str = Field(..., description="Subquery identifier (SQ1, SQ2, etc)")
    text: str = Field(..., min_length=5, description="Original subquery text")
    depends_on_premises: List[str] = Field(default_factory=list, description="List of premise IDs needed (e.g., ['P1', 'P2'])")
    depends_on_subqueries: List[str] = Field(default_factory=list, description="List of subquery IDs that must execute first (e.g., ['SQ1', 'SQ2'])")

    @validator('id')
    def validate_id(cls, v):
        """Validate subquery ID format"""
        if not v.startswith('SQ'):
            raise ValueError("Subquery ID must start with 'SQ' (e.g., 'SQ1', 'SQ2')")
        return v

    @validator('depends_on_premises')
    def validate_premise_refs(cls, v):
        """Validate premise references format"""
        for ref in v:
            if not ref.startswith('P'):
                raise ValueError(f"Premise reference must start with 'P' (e.g., 'P1'), got: {ref}")
        return v

    @validator('depends_on_subqueries')
    def validate_subquery_refs(cls, v):
        """Validate subquery references format"""
        for ref in v:
            if not ref.startswith('SQ'):
                raise ValueError(f"Subquery reference must start with 'SQ' (e.g., 'SQ1'), got: {ref}")
        return v


class DependencyAnalysis(BaseModel):
    """
    Complete dependency analysis output from Phase 0 post-processing.

    Provides explicit mappings for:
    1. Which premises validate which subqueries
    2. Which subqueries depend on other subqueries (for synthesis)

    Note: Worker pool executes all subqueries in parallel. Dependencies are only used during synthesis.
    """
    premises: List[EnhancedPremise] = Field(..., min_items=1, description="Enhanced premises with dependency mappings")
    subqueries: List[EnhancedSubquery] = Field(..., min_items=1, description="Enhanced subqueries with dependency mappings")
    reasoning: str = Field(..., min_length=20, description="Explanation of dependency structure")

    @validator('premises')
    def validate_premises(cls, v):
        """Validate premise IDs are unique"""
        if not v:
            raise ValueError("Must have at least one premise")

        ids = [p.id for p in v]
        if len(ids) != len(set(ids)):
            duplicates = [id for id in ids if ids.count(id) > 1]
            raise ValueError(f"Duplicate premise IDs found: {set(duplicates)}")

        return v

    @validator('subqueries')
    def validate_subqueries_unique(cls, v):
        """Validate subquery IDs are unique"""
        if not v:
            raise ValueError("Must have at least one subquery")

        ids = [sq.id for sq in v]
        if len(ids) != len(set(ids)):
            duplicates = [id for id in ids if ids.count(id) > 1]
            raise ValueError(f"Duplicate subquery IDs found: {set(duplicates)}")

        return v


# =====================================================================
# Self-Contained Approach Packet (for Mini CoT Agent Execution)
# =====================================================================

class EmbeddedPremise(BaseModel):
    """
    Premise embedded in approach packet (no ID references).
    Full premise data for self-contained packet.
    """
    id: str = Field(..., description="Premise ID (P1, P2, etc)")
    text: str = Field(..., min_length=5, description="Premise text")


class ApproachPacket(BaseModel):
    """
    Self-contained approach packet for mini CoT agent execution.

    Contains EVERYTHING needed to execute this subquery independently:
    - Full subquery text
    - Complete logical form for context
    - All relevant premises (embedded, not references)
    - Dependencies (for scheduling)
    - Execution metadata and results

    Mini CoT agents receive ONE packet with no external lookups needed.
    """
    # Identity
    id: str = Field(..., description="Subquery ID (SQ1, SQ2, etc)")
    text: str = Field(..., min_length=5, description="Subquery text")

    # Full context (embedded for self-containment)
    logical_form: str = Field(..., min_length=10, description="Complete logical form from Phase 0")

    # Premise tracking (SEPARATE original and corrected)
    original_premises: List[EmbeddedPremise] = Field(
        default_factory=list,
        description="Original premises from Phase 0 (never modified, can be empty for aggregation subqueries)"
    )
    corrected_premises: List[EmbeddedPremise] = Field(
        default_factory=list,
        description="Corrected premises after APOC validation (if any corrections needed)"
    )
    active_premises: List[EmbeddedPremise] = Field(
        default_factory=list,
        description="Currently active premises (original or corrected) used for execution"
    )

    # Dependencies (for synthesis only - worker pool executes all in parallel)
    depends_on_subqueries: List[str] = Field(default_factory=list, description="Subquery IDs that must complete first (for synthesis)")

    # Execution metadata
    status: Literal['pending', 'ready', 'in_progress', 'completed', 'failed', 'retrying'] = Field(
        default='pending',
        description="Execution status"
    )

    # Input/Output data
    input_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Results from dependent subqueries (populated before execution)"
    )
    result: Optional[Any] = Field(default=None, description="Execution result")
    error: Optional[str] = Field(default=None, description="Error message if failed")

    # Sufficiency evaluation
    sufficiency_status: Optional[Literal['FOUND', 'NOT_FOUND', 'INSUFFICIENT_DATA']] = Field(
        default=None,
        description="Sufficiency status after execution"
    )
    sufficiency_reasoning: Optional[str] = Field(
        default=None,
        description="Why this status was determined"
    )

    # Metrics
    execution_time_ms: Optional[float] = Field(default=None, ge=0.0, description="Execution time in milliseconds")
    attempts: int = Field(default=0, ge=0, description="Number of execution attempts")

    @validator('id')
    def validate_id(cls, v):
        """Validate subquery ID format"""
        if not v.startswith('SQ'):
            raise ValueError("Subquery ID must start with 'SQ' (e.g., 'SQ1', 'SQ2')")
        return v


class ApproachPacketCollection(BaseModel):
    """
    Complete collection of approach packets for workflow execution.

    Worker pool executes all packets in parallel with limited concurrency.
    Provides O(1) lookup by packet ID.
    """
    packets: Dict[str, ApproachPacket] = Field(..., description="All approach packets by ID")
    total_subqueries: int = Field(..., ge=1, description="Total number of subqueries")

    @validator('packets')
    def validate_packets_not_empty(cls, v):
        """Validate packets dict is not empty"""
        if not v:
            raise ValueError("Must have at least one approach packet")
        return v

    @validator('total_subqueries')
    def validate_total_matches_packets(cls, v, values):
        """Validate total count matches packets"""
        packets = values.get('packets', {})
        if packets and v != len(packets):
            return len(packets)  # Auto-correct
        return v


# =====================================================================
# Citation and Premise Correction Models
# =====================================================================

class PremiseValidation(BaseModel):
    """
    Validation result for a single premise.

    Tracks whether premise was validated, invalidated, or corrected
    during subquery execution.
    """
    premise_id: str = Field(..., description="Premise ID (P1, P2, etc)")
    original_text: str = Field(..., min_length=5, description="Original premise text")
    status: Literal['validated', 'invalidated', 'corrected'] = Field(
        ...,
        description="Validation status"
    )

    # For 'corrected' status
    corrected_text: Optional[str] = Field(
        default=None,
        description="Corrected premise text (if correction was needed)"
    )
    correction_reasoning: Optional[str] = Field(
        default=None,
        description="Why the correction was needed"
    )

    # Evidence from execution
    validation_method: str = Field(
        ...,
        description="How was this validated (query_success, query_error, apoc_diagnostics)"
    )


class SubqueryCitation(BaseModel):
    """
    Complete citation for a single subquery execution.

    Includes full context, execution results, and premise validation
    for transparency and traceability.
    """
    # Identity
    subquery_id: str = Field(..., description="Subquery ID (SQ1, SQ2, etc)")
    subquery_text: str = Field(..., min_length=5, description="Subquery text")
    execution_group: int = Field(..., ge=1, description="Which execution group")

    # Full context (for transparency)
    logical_form: str = Field(..., min_length=10, description="Full logical form")

    # Premise tracking (SEPARATE original and corrected)
    original_premises: List[EmbeddedPremise] = Field(
        ...,
        description="Original premises from Phase 0"
    )
    premise_validations: List[PremiseValidation] = Field(
        default_factory=list,
        description="Validation status of each premise"
    )

    # Query execution
    cypher_query: str = Field(..., min_length=5, description="Generated Cypher query")
    execution_attempts: int = Field(default=1, ge=1, description="Number of attempts")

    # Results
    result_data: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Actual query results"
    )
    result_count: int = Field(default=0, ge=0, description="Number of results")

    # Sufficiency evaluation
    sufficiency_status: Literal['FOUND', 'NOT_FOUND', 'INSUFFICIENT_DATA'] = Field(
        ...,
        description="Sufficiency status"
    )
    confidence: Literal['high', 'medium', 'low'] = Field(
        ...,
        description="Confidence in result"
    )
    reasoning: str = Field(..., min_length=10, description="Sufficiency reasoning")

    # Error handling
    error: Optional[str] = Field(default=None, description="Error message if failed")
    apoc_diagnostics_used: bool = Field(
        default=False,
        description="Whether APOC diagnostics were run"
    )

    # Metrics
    execution_time_ms: Optional[float] = Field(default=None, ge=0.0)


class FinalCitation(BaseModel):
    """
    Complete citation chain for final answer.

    Aggregates all subquery citations and provides overall
    confidence and traceability.
    """
    # All subquery citations
    subquery_citations: List[SubqueryCitation] = Field(
        ...,
        min_items=1,
        description="All subquery executions in order"
    )

    # Execution flow
    execution_groups: List[List[str]] = Field(
        ...,
        min_items=1,
        description="Execution order (parallel groups)"
    )

    # Premise summary
    total_premises: int = Field(..., ge=1, description="Total premises from Phase 0")
    validated_premises: int = Field(..., ge=0, description="Premises confirmed valid")
    invalidated_premises: int = Field(..., ge=0, description="Premises found invalid")
    corrected_premises: int = Field(..., ge=0, description="Premises that needed correction")

    # Overall confidence
    overall_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall confidence (0.0-1.0)"
    )
    overall_sufficiency: Literal['SUFFICIENT', 'INSUFFICIENT', 'PARTIAL'] = Field(
        ...,
        description="Overall sufficiency status"
    )

    # Traceability
    corrected_premise_details: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Details of all premise corrections"
    )

    @validator('overall_confidence')
    def validate_confidence_range(cls, v):
        """Ensure confidence is between 0 and 1"""
        return max(0.0, min(1.0, v))