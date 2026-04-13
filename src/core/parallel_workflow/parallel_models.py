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


# NEW: Models for parallel execution support

class BatchConfiguration(BaseModel):
    """Configuration for parallel batch processing"""
    batch_size: int = Field(default=2, ge=1, le=5, description="Number of approaches per batch (resource-conscious)")
    max_concurrent_think: int = Field(default=3, ge=1, le=5, description="Max concurrent think operations")
    max_concurrent_rethink: int = Field(default=3, ge=1, le=5, description="Max concurrent rethink operations") 
    enable_batch_execution: bool = Field(default=True, description="Whether to use batch query execution")
    
    @validator('batch_size')
    def validate_batch_size(cls, v):
        if v > 5:
            raise ValueError("Batch size cannot exceed 5 approaches (resource limit)")
        return v


class ApproachBatch(BaseModel):
    """A batch of approaches for parallel processing"""
    batch_index: int = Field(..., ge=0, description="Index of this batch")
    approach_indices: List[int] = Field(..., min_items=1, max_items=5, description="Approach indices in this batch")
    batch_size: int = Field(..., ge=1, le=5, description="Number of approaches in this batch")
    total_approaches: int = Field(..., ge=1, description="Total approaches across all batches")
    
    @validator('approach_indices')
    def validate_approach_indices(cls, v, values):
        batch_size = values.get('batch_size', len(v))
        if len(v) != batch_size:
            raise ValueError(f"Approach indices length ({len(v)}) must match batch_size ({batch_size})")
        return v


class ParallelExecutionState(BaseModel):
    """State tracking for parallel approach execution"""
    approach_index: int = Field(..., ge=0, description="Index of the approach")
    approach_name: str = Field(..., min_length=5, description="Name of the approach")
    
    # Phase completion tracking
    think_complete: bool = Field(default=False, description="Think phase completed")
    generate_complete: bool = Field(default=False, description="Generate phase completed")
    execute_complete: bool = Field(default=False, description="Execute phase completed")
    rethink_complete: bool = Field(default=False, description="Rethink phase completed")
    
    # Results storage
    think_result: Optional[Dict[str, Any]] = Field(default=None, description="Think phase result")
    generate_result: Optional[Dict[str, Any]] = Field(default=None, description="Generate phase result") 
    execute_result: Optional[Dict[str, Any]] = Field(default=None, description="Execute phase result")
    rethink_result: Optional[Dict[str, Any]] = Field(default=None, description="Rethink phase result")
    
    # Error tracking
    errors: List[str] = Field(default_factory=list, description="Errors encountered during execution")
    retry_count: int = Field(default=0, ge=0, le=3, description="Number of retries attempted")
    
    @property
    def is_complete(self) -> bool:
        """Check if all phases are complete for this approach"""
        return self.think_complete and self.generate_complete and self.execute_complete and self.rethink_complete
    
    @property
    def next_phase(self) -> Optional[str]:
        """Determine the next phase to execute"""
        if not self.think_complete:
            return "think"
        elif not self.generate_complete:
            return "generate" 
        elif not self.execute_complete:
            return "execute"
        elif not self.rethink_complete:
            return "rethink"
        return None


class BatchExecutionSummary(BaseModel):
    """Summary of batch execution results"""
    batch_index: int = Field(..., ge=0, description="Index of completed batch")
    total_approaches: int = Field(..., ge=1, description="Number of approaches in batch")
    successful_approaches: int = Field(..., ge=0, description="Number of successful approaches")
    failed_approaches: int = Field(..., ge=0, description="Number of failed approaches") 
    total_queries_executed: int = Field(..., ge=0, description="Total queries executed in batch")
    total_results_found: int = Field(..., ge=0, description="Total results found across batch")
    execution_time_seconds: float = Field(..., ge=0.0, description="Total execution time for batch")
    
    # Approach summaries
    approach_summaries: List[Dict[str, Any]] = Field(default_factory=list, description="Summary for each approach")
    
    @validator('successful_approaches', 'failed_approaches')
    def validate_approach_counts(cls, v, values):
        total = values.get('total_approaches', 0)
        if 'successful_approaches' in values:
            successful = values['successful_approaches']
            if v + successful != total:
                raise ValueError(f"Successful ({successful}) + failed ({v}) must equal total ({total})")
        return v


class AgentState(TypedDict):
    """State management for LangGraph workflow with proper reducers"""
    
    # Core workflow data - overwrite on each update
    user_query: str
    intent: str  
    current_query: Optional[str]
    current_iteration: int
    max_iterations: int
    should_continue: bool
    response: str
    current_node: str
    
    # Accumulated data - managed manually to prevent duplication (never None, start as empty lists)
    entities: List[str]
    discovered_data: List[Dict[str, Any]]
    raw_query_results: List[Dict[str, Any]]
    query_history: List[Dict[str, Any]]
    final_results: List[Dict[str, Any]]
    body_exploration_candidates: List[str]
    body_exploration_results: List[Dict[str, Any]]
    
    # Configuration and metadata - overwrite
    schema: Dict[str, Any]
    llm_service: Any
    neo4j_config: Optional[str]
    neo4j_version: Optional[str]
    metadata: Optional[Dict[str, Any]]
    
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
    
    # NEW: Parallel execution state management
    current_batch_index: int  # Current batch being processed (0-based)
    total_batches: int  # Total number of approach batches
    batch_size: int  # Number of approaches per batch (default: 2-3)
    current_batch_approaches: List[int]  # Approach indices in current batch
    batch_results: Dict[int, Dict[str, Any]]  # Results by approach index for current batch
    
    # Parallel approach state tracking
    parallel_thinking_results: Dict[int, Dict[str, Any]]  # Think results by approach index
    parallel_generation_results: Dict[int, Dict[str, Any]]  # Generate results by approach index  
    parallel_execution_results: Dict[int, Dict[str, Any]]  # Execute results by approach index
    parallel_rethinking_results: Dict[int, Dict[str, Any]]  # Rethink results by approach index
    
    # Batch execution tracking
    batch_query_payload: Optional[List[Dict[str, Any]]]  # Prepared batch queries for CLI execution
    batch_execution_complete: bool  # Flag indicating if current batch execution is done
    
    # Execute step state - accumulated and overwrite fields
    generated_queries: List[List[Dict[str, Any]]]  # List of query lists - one list per approach (managed manually)
    execution_results: List[Dict[str, Any]]  # Results from query execution (managed manually) 
    execution_analysis: Optional[Dict[str, Any]]  # Analysis of execution results (overwrite)
    execution_status: Optional[str]  # Overall execution status (overwrite)
    total_results_found: int  # Total results found across all executions (overwrite)
    
    # NEW: Raw results tracking by approach - for rethink analysis and context management
    approach_raw_results: Dict[int, List[Tuple[str, List[Dict]]]]  # Dict[approach_index, [(query, results), ...]]
    iteration_summaries: List[str]  # Progressive summaries of each iteration to prevent context explosion
    cumulative_findings: str  # Running summary of findings across all iterations
    
    # NEW: Rethink step state
    rethink_analysis: Optional[Dict[str, Any]]  # Current rethink analysis results
    sufficiency_check_history: List[Dict[str, Any]]  # History of sufficiency checks across iterations
    should_synthesize: bool  # Flag from rethink to determine if ready for synthesis
    
    # Flags - overwrite
    fallback_mode: Optional[bool]
    diverse_queries_generated: Optional[bool]
    synthesis_context_used: Optional[int]
    syntax_error_count: int  # Track syntax error retries to prevent infinite loops