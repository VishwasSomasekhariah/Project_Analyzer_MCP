"""
State schema and data models for the Hybrid Fast Workflow.
"""
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


@dataclass
class Citation:
    """
    A structured, auditable reference to a piece of evidence found by an agent.

    Answers six questions for any consumer (orchestrator, synthesizer, auditor):
      What   — entity_name
      Where  — file_path, start_line, end_line
      Who    — agent
      How    — retrieval_method
      Why    — evidence_text
      How confident — relevance_score

    Plus full traceability: citation_id, hop_number, query_used, raw_metadata.
    """
    # Identity
    citation_id: str               # Stable unique ID (hash of agent+file+entity+hop)
    agent: str                     # "pageindex" | "vector" | "graph"
    retrieval_method: str          # "mcts" | "hybrid_bm25_rrf" | "cpg_cypher"
    hop_number: int                # Which orchestrator hop produced this

    # Location
    file_path: str                 # Relative path from project root
    entity_name: str               # Class / function / node name

    # Source range (best-effort, 0 if unavailable)
    start_line: int = 0
    end_line: int = 0

    # Evidence
    evidence_text: str = ""        # Relevant code/text snippet
    relevance_score: float = 0.0   # Agent-specific confidence (0.0–1.0)

    # Traceability
    query_used: str = ""           # Query or Cypher that produced this citation
    raw_metadata: Dict = field(default_factory=dict)  # Full unmodified agent data

    def format(self) -> str:
        """Human-readable one-liner for use in prompts."""
        loc = f"{self.file_path}"
        if self.start_line:
            loc += f":{self.start_line}"
            if self.end_line and self.end_line != self.start_line:
                loc += f"-{self.end_line}"
        return f"[{self.agent}/{self.retrieval_method}] {self.entity_name} ({loc}) score={self.relevance_score:.2f}"


def make_citation_id(agent: str, file_path: str, entity_name: str, hop_number: int) -> str:
    """Stable deterministic ID for deduplication."""
    raw = f"{agent}:{file_path}:{entity_name}:{hop_number}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


@dataclass
class HopEntry:
    agent: str                           # "pageindex" | "vector" | "graph"
    query: str                           # query sent to the agent
    result: str                          # agent's response as a formatted string
    citations: List[Citation] = field(default_factory=list)  # structured evidence
    raw: Dict = field(default_factory=dict)                  # full raw response


class OrchestratorState(TypedDict):
    user_query: str
    llm_service: Any
    config: Dict[str, Any]
    hop_history: List[HopEntry]
    final_answer: Optional[str]
    error_log: List[str]
    hop_count: int
    # Routing fields
    next_action: Optional[str]
    _pending_agent: Optional[str]
    _pending_query: Optional[str]
    _pending_reasoning: Optional[str]
    # Routing fields — set by orchestrate_step, consumed by conditional edge / call_agent
    next_action: Optional[str]       # "call_agent" | "synthesize"
    _pending_agent: Optional[str]    # "pageindex" | "vector" | "graph"
    _pending_query: Optional[str]
    _pending_reasoning: Optional[str]
