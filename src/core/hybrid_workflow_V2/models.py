"""
Hybrid Workflow Data Models

Pydantic models for the Hybrid RAG workflow that combines Vector and CPG retrievers
with sophisticated synthesis and validation.
"""
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, field_validator
from enum import Enum

logger = logging.getLogger(__name__)


class QueryIntent(str, Enum):
    """Query intent classifications for routing and weighting"""
    ARCHITECTURAL = "architectural"  # Vector-weighted
    DIRECT_LOOKUP = "direct_lookup"  # CPG-weighted
    STRUCTURAL = "structural"  # Balanced
    RELATIONAL = "relational"  # CPG-weighted
    SEMANTIC = "semantic"  # Vector-weighted
    QUANTITATIVE = "quantitative"  # CPG-weighted
    UNKNOWN = "unknown"  # Balanced


class RetrievalStatus(str, Enum):
    """Status of individual retrieval operations"""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class SynthesisStrategy(str, Enum):
    """Synthesis strategies based on retrieval results"""
    PAGEINDEX_PRIMARY = "pageindex_primary"          # PageIndex succeeded — used directly
    PAGEINDEX_FALLBACK_VECTOR_CPG = "pageindex_fallback_vector_cpg"  # PageIndex insufficient — vector+CPG used with learnings
    HYBRID_CONSENSUS = "hybrid_consensus"  # Both sources agree
    VECTOR_PRIMARY = "vector_primary"  # Vector response primary, CPG supports
    CPG_PRIMARY = "cpg_primary"  # CPG response primary, Vector supports
    CROSS_VALIDATION = "cross_validation"  # Each validates the other
    FALLBACK_VECTOR = "fallback_vector"  # Only vector succeeded
    FALLBACK_CPG = "fallback_cpg"  # Only CPG succeeded
    NO_RESULTS = "no_results"  # Both failed


class RetrieverCombination(str, Enum):
    """
    Controls which retrievers run after PageIndex and how.

    '->' combinations: PageIndex runs first, then the specified retrievers
    always run afterwards.  The query is reformulated when PageIndex surfaces
    uncovered_topics or unsupported_claims; otherwise the original query is
    forwarded unchanged.

    'and' combinations: PageIndex and the paired retriever run as independent
    parallel calls — no reformulation ever, original user query only.
    """
    PAGEINDEX_VECTOR_GRAPH = "pageindex_vector_graph"  # pageindex -> vector + graph
    PAGEINDEX_VECTOR       = "pageindex_vector"        # pageindex -> vector
    PAGEINDEX_GRAPH        = "pageindex_graph"         # pageindex -> graph
    PAGEINDEX_AND_GRAPH    = "pageindex_and_graph"     # pageindex and graph (parallel, no reformulation)
    PAGEINDEX_AND_VECTOR   = "pageindex_and_vector"    # pageindex and vector (parallel, no reformulation)


class IntentAnalysis(BaseModel):
    """Intent analysis result for query routing and weighting"""
    intent: QueryIntent = Field(description="Primary intent classification")
    confidence: float = Field(description="Confidence in intent classification", ge=0.0, le=1.0)
    vector_weight: float = Field(description="Recommended weight for vector retrieval", ge=0.0, le=1.0)
    cpg_weight: float = Field(description="Recommended weight for CPG retrieval", ge=0.0, le=1.0)
    reasoning: str = Field(description="Reasoning for the intent classification")
    
    @field_validator('cpg_weight')
    @classmethod
    def weights_sum_to_one(cls, v, info):
        if info.data.get('vector_weight') is not None:
            total = info.data['vector_weight'] + v
            if abs(total - 1.0) > 0.01:  # Allow small floating point errors
                raise ValueError(f"Vector and CPG weights must sum to 1.0, got {total}")
        return v


class RetrieverResult(BaseModel):
    """Result from a single retriever (Vector or CPG)"""
    retriever_type: str = Field(description="Type of retriever: 'vector' or 'cpg'")
    status: RetrievalStatus = Field(description="Status of the retrieval")
    raw_results: List[Dict[str, Any]] = Field(default=[], description="Raw results from the retriever")
    processed_results: List[Dict[str, Any]] = Field(default=[], description="Processed/normalized results")
    response_text: Optional[str] = Field(default=None, description="AI-generated response from retriever")
    metadata: Dict[str, Any] = Field(default={}, description="Retrieval metadata")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    execution_time: float = Field(default=0.0, description="Execution time in seconds")
    
    @property
    def succeeded(self) -> bool:
        """Check if retrieval succeeded"""
        return self.status in [RetrievalStatus.SUCCESS, RetrievalStatus.PARTIAL]
    
    @property
    def has_results(self) -> bool:
        """Check if retrieval has usable results"""
        return len(self.raw_results) > 0 or len(self.processed_results) > 0


class CrossValidationResult(BaseModel):
    """Result of cross-validation between retrievers"""
    vector_validates_cpg: bool = Field(description="Vector results validate CPG claims")
    cpg_validates_vector: bool = Field(description="CPG results validate Vector claims")
    conflicts_found: List[str] = Field(description="List of conflicts between retrievers")
    consensus_points: List[str] = Field(description="Points of agreement between retrievers")
    confidence_score: float = Field(description="Overall confidence in cross-validation", ge=0.0, le=1.0)
    validation_details: Dict[str, Any] = Field(description="Detailed validation analysis")


class SynthesisResult(BaseModel):
    """Result of synthesis with cross-validation"""
    strategy_used: SynthesisStrategy = Field(description="Synthesis strategy applied")
    answer: str = Field(description="Final synthesized answer")
    details: str = Field(description="Detailed explanation")
    confidence: float = Field(description="Confidence in synthesized answer", ge=0.0, le=1.0)
    status: str = Field(description="Synthesis status: found/not_found/partial")
    suggestions: List[str] = Field(description="Suggestions for further exploration")
    cross_validation: CrossValidationResult = Field(description="Cross-validation results")
    evidence: Dict[str, Any] = Field(description="Evidence from both retrievers")
    batch_metadata: Dict[str, Any] = Field(description="Metadata about batching and context management")


class CriticValidation(BaseModel):
    """Critic validation result for synthesis output"""
    decision: str = Field(description="Critic decision: accept/retry/reject")
    overall_score: float = Field(description="Overall quality score", ge=0.0, le=1.0)
    hallucination_score: float = Field(description="Hallucination detection score", ge=0.0, le=1.0)
    faithfulness_score: float = Field(description="Faithfulness to evidence score", ge=0.0, le=1.0)
    accuracy_score: float = Field(description="Accuracy assessment score", ge=0.0, le=1.0)
    validation_issues: List[str] = Field(description="List of validation issues found")
    reasoning: str = Field(description="Detailed reasoning for the validation")
    improvement_suggestions: List[str] = Field(description="Suggestions for improvement")
    evidence_grading: Dict[str, Any] = Field(description="Grading of evidence quality")


class HybridState(BaseModel):
    """Complete state for the Hybrid RAG workflow"""
    
    # Input
    user_query: str = Field(description="Original user query")
    llm_service: Any = Field(description="LLM service instance", exclude=True)
    
    # Intent Analysis
    intent_analysis: Optional[IntentAnalysis] = Field(description="Intent analysis result")
    
    # Retrieval Results
    pageindex_result: Optional[RetrieverResult] = Field(default=None, description="PageIndex retrieval result (primary)")
    vector_result: Optional[RetrieverResult] = Field(default=None, description="Vector retrieval result (fallback)")
    cpg_result: Optional[RetrieverResult] = Field(default=None, description="CPG retrieval result (fallback)")

    # Retriever combination selection
    retriever_combination: RetrieverCombination = Field(
        default=RetrieverCombination.PAGEINDEX_VECTOR_GRAPH,
        description="Which retrievers to activate after PageIndex"
    )

    # Fallback routing
    use_fallback: bool = Field(default=False, description="PageIndex was insufficient — route to vector+CPG fallback")
    pageindex_learnings: Dict[str, Any] = Field(default={}, description="Partial findings from PageIndex to guide fallback retrieval")
    enhanced_query: Optional[str] = Field(default=None, description="Query enhanced with pageindex learnings (uncovered topics / unsupported claims)")
    
    # Combined Results
    combined_raw_results: List[Dict[str, Any]] = Field(default=[], description="Combined raw results from both retrievers")
    batched_results: List[List[Dict[str, Any]]] = Field(default=[], description="Results organized in batches for processing")
    citation_lookup: Dict[str, Any] = Field(default={}, description="Deduped map of citation_id → raw result object, built in combine_results")

    # Multi-source synthesis (Issue #1)
    retriever_summaries: List[Any] = Field(default=[], description="Compressed per-retriever claim summaries (RetrieverSummary instances) produced in Stage 1")
    
    # Synthesis
    synthesis_result: Optional[SynthesisResult] = Field(description="Final synthesis result")
    
    # Validation
    critic_validation: Optional[CriticValidation] = Field(description="Critic validation of synthesis")
    
    # Context Management
    context_size: int = Field(default=0, description="Current context size in characters")
    batch_size: int = Field(default=5, description="Batch size for processing")
    max_context_limit: int = Field(default=100000, description="Maximum context size limit")
    
    # Execution Metadata
    execution_metadata: Dict[str, Any] = Field(default={}, description="Execution metadata")
    error_log: List[str] = Field(default=[], description="Error log for debugging")
    
    class Config:
        arbitrary_types_allowed = True


class BatchProcessingResult(BaseModel):
    """Result of batch processing for context management"""
    processed_batches: int = Field(description="Number of batches processed")
    total_items: int = Field(description="Total items processed")
    context_size_used: int = Field(description="Context size used")
    batch_summaries: List[str] = Field(description="Summary of each batch")
    synthesis_strategy: SynthesisStrategy = Field(description="Strategy used for synthesis")
    overflow_items: List[Dict[str, Any]] = Field(description="Items that didn't fit in context")


class ChainOfThoughtStep(BaseModel):
    """Individual step in chain-of-thought reasoning"""
    step_number: int = Field(description="Step number in the chain")
    step_type: str = Field(description="Type of reasoning step")
    input_data: Dict[str, Any] = Field(description="Input data for this step")
    reasoning: str = Field(description="Reasoning applied in this step")
    output_data: Dict[str, Any] = Field(description="Output from this step")
    confidence: float = Field(description="Confidence in this step", ge=0.0, le=1.0)
    evidence_sources: List[str] = Field(description="Sources of evidence used")


class ChainOfThoughtResult(BaseModel):
    """Complete chain-of-thought reasoning result"""
    steps: List[ChainOfThoughtStep] = Field(description="List of reasoning steps")
    final_conclusion: str = Field(description="Final conclusion from the chain")
    overall_confidence: float = Field(description="Overall confidence in the reasoning", ge=0.0, le=1.0)
    evidence_quality: str = Field(description="Assessment of evidence quality")
    reasoning_path: List[str] = Field(description="Summary of the reasoning path")


class IntentAnalysisRawResponse(BaseModel):
    """Raw response model for intent analysis LLM call"""
    intent: str = Field(description="Intent classification string")
    confidence: float = Field(description="Confidence score", ge=0.0, le=1.0)
    vector_weight: float = Field(description="Vector retrieval weight", ge=0.0, le=1.0)
    cpg_weight: float = Field(description="CPG retrieval weight", ge=0.0, le=1.0)
    reasoning: str = Field(description="Reasoning for classification")


class SynthesisRawResponse(BaseModel):
    """Raw response model for synthesis LLM call"""
    answer: str = Field(description="Final synthesized answer")
    details: str = Field(description="Detailed explanation")
    confidence: float = Field(description="Confidence in synthesis", ge=0.0, le=1.0)
    status: str = Field(description="Synthesis status")
    suggestions: List[str] = Field(description="Suggestions for further exploration")
    cross_validation: Dict[str, Any] = Field(description="Cross-validation results")
    batch_metadata: Optional[Dict[str, Any]] = Field(description="Batch metadata", default={})


class CriticValidationRawResponse(BaseModel):
    """Raw response model for critic validation LLM call"""
    decision: str = Field(description="Critic decision: accept/retry/reject")
    overall_score: float = Field(description="Overall quality score", ge=0.0, le=1.0)
    hallucination_score: float = Field(description="Hallucination detection score", ge=0.0, le=1.0)
    faithfulness_score: float = Field(description="Faithfulness to evidence score", ge=0.0, le=1.0)
    accuracy_score: float = Field(description="Accuracy assessment score", ge=0.0, le=1.0)
    validation_issues: List[str] = Field(description="List of validation issues found")
    reasoning: str = Field(description="Detailed reasoning for validation")
    improvement_suggestions: List[str] = Field(description="Suggestions for improvement")
    evidence_grading: Dict[str, Any] = Field(description="Grading of evidence quality")


class SynthesisImprovementRawResponse(BaseModel):
    """Raw response model for synthesis improvement LLM call"""
    answer: str = Field(description="Improved synthesized answer")
    details: str = Field(description="Improved detailed explanation")
    confidence: float = Field(description="Improved confidence", ge=0.0, le=1.0)
    status: str = Field(description="Improved status")
    suggestions: List[str] = Field(description="Improved suggestions")


# ---------------------------------------------------------------------------
# Multi-source synthesis models (Issue #1)
# ---------------------------------------------------------------------------

class EvidenceClaim(BaseModel):
    """A single claim extracted from a retriever's response.

    citation_ids reference the original raw result objects by their stable ID
    — the LLM never paraphrases or copies citation text, only points to IDs.
    """
    text: str = Field(description="The claim statement")
    confidence: float = Field(description="Confidence in this claim", ge=0.0, le=1.0)
    citation_ids: List[str] = Field(default=[], description="IDs of raw citations supporting this claim")


class RetrieverSummary(BaseModel):
    """Compressed per-retriever findings for multi-source synthesis.

    Produced by one focused LLM call per retriever (Stage 1 / Map).
    Raw citations stay untouched in state; claims reference them by ID only.
    """
    retriever: str = Field(description="Retriever name: pageindex, vector, or cpg")
    claims: List[EvidenceClaim] = Field(default=[], description="Extracted claims with citation ID references")
    gaps: List[str] = Field(default=[], description="Topics not covered or uncertain by this retriever")
    overall_confidence: float = Field(description="Overall confidence in this retriever's findings", ge=0.0, le=1.0)


class ClaimExtractionRawResponse(BaseModel):
    """Raw LLM response for per-retriever claim extraction"""
    claims: List[Dict[str, Any]] = Field(description="List of claims — each must have: text (str), confidence (float), citation_ids (list[str])")
    gaps: List[str] = Field(description="Topics not covered or uncertain")
    overall_confidence: float = Field(description="Overall confidence in retriever findings", ge=0.0, le=1.0)


class ReconciliationRawResponse(BaseModel):
    """Raw LLM response for cross-retriever claim reconciliation (Stage 2)"""
    agreements: List[str] = Field(description="Claims agreed upon across multiple retrievers")
    conflicts: List[str] = Field(description="Conflicting claims between retrievers, with which retrievers disagree")
    unique_per_retriever: Dict[str, List[str]] = Field(description="Claims unique to each retriever keyed by retriever name")
    confidence_score: float = Field(description="Overall reconciliation confidence", ge=0.0, le=1.0)