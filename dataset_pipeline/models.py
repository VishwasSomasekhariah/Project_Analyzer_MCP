"""
Inter-stage data contracts for the RL training dataset pipeline.
Each dataclass represents the output of one pipeline stage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


# ---------------------------------------------------------------------------
# Stage 1 — Query Generation
# ---------------------------------------------------------------------------

@dataclass
class RawQuery:
    query_id: str
    query: str
    source: Literal["ground_truth_variant", "repo_generated", "ambiguous"]
    base_query_id: Optional[str]           # original GT query_id for variants
    query_type: Literal["factual", "structural", "behavioral", "cross_cutting", "modification", "ambiguous"]
    difficulty: Literal["easy", "medium", "hard"]
    expected_files: List[str]              # files a successful trace should cite
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Ambiguity fields (None for non-ambiguous queries)
    ambiguity_type: Optional[Literal["misspelled", "wrong_type", "nonexistent", "ambiguous_ref"]] = None
    expected_resolution: Optional[Any] = None  # str | List[str] | None


# ---------------------------------------------------------------------------
# Stage 2 — Routing Plan Generation
# ---------------------------------------------------------------------------

@dataclass
class StepInstruction:
    agent: Literal["pageindex", "vector", "graph"]
    what_to_look_for: str


@dataclass
class RoutingPlan:
    plan_id: str                           # e.g. "gen_001_plan_2"
    query_id: str
    agent_sequence: List[str]              # e.g. ["pageindex", "graph"]
    step_instructions: List[StepInstruction]
    llm_reasoning: str
    plan_index: int                        # 0-based index within query's plans


# ---------------------------------------------------------------------------
# Stage 3 — Plan Execution
# ---------------------------------------------------------------------------

@dataclass
class CitationRecord:
    citation_id: str
    agent: str
    file_path: str
    entity_name: str
    start_line: int
    end_line: int
    evidence_text: str
    relevance_score: float


@dataclass
class HopRecord:
    hop_number: int
    agent: str
    instruction: str
    raw_result_summary: str
    citation_ids: List[str] = field(default_factory=list)


@dataclass
class PlanExecutionTrace:
    trace_id: str                          # f"{query_id}_plan{plan_index}"
    query_id: str
    plan_id: str
    status: Literal["success", "error", "timeout"]
    hops: List[HopRecord] = field(default_factory=list)
    citations: List[CitationRecord] = field(default_factory=list)
    sufficiency_verdict: Optional[Literal["sufficient", "insufficient"]] = None
    sufficiency_reasoning: str = ""
    execution_time_ms: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Stage 4 — Validation
# ---------------------------------------------------------------------------

@dataclass
class ValidatedPlanResult:
    trace_id: str
    query_id: str
    plan_id: str
    is_valid: bool                         # True = plan successfully retrieved evidence
    rejection_reasons: List[str] = field(default_factory=list)
    citation_coverage: float = 0.0        # fraction of expected_files cited
    answer_quality_score: float = 0.0
    ambiguity_resolution_correct: Optional[bool] = None  # None for non-ambiguous queries


# ---------------------------------------------------------------------------
# Stage 5 — Augmentation
# ---------------------------------------------------------------------------

@dataclass
class AugmentedQuery:
    query_id: str                          # e.g. "gen_001_aug_2"
    parent_query_id: str
    query: str
    augmentation_type: Literal["rephrase", "formal_tone", "conversational_tone"]
    augment_index: int


# ---------------------------------------------------------------------------
# Stage 6 — Final Training Example (JSONL output)
# ---------------------------------------------------------------------------

@dataclass
class TrainingExample:
    id: str
    source: str
    query: str
    query_type: str
    difficulty: str
    routing_plan: Dict[str, Any]           # {agent_sequence, step_instructions, llm_reasoning}
    execution_trace: Dict[str, Any]        # {hops, citations}
    is_successful_plan: bool               # RL reward signal
    final_evidence_summary: str
    ambiguity_type: Optional[str]
    ambiguity_resolution_correct: Optional[bool]
    validation: Dict[str, Any]            # {citation_coverage, answer_quality_score}
    split: Literal["train", "val"]
