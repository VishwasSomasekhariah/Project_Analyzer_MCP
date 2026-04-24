"""
State schema and data models for the Hybrid Fast Workflow.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


@dataclass
class HopEntry:
    agent: str          # "pageindex" | "vector" | "graph"
    query: str          # query sent to the agent
    result: str         # agent's response as a formatted string
    raw: Dict = field(default_factory=dict)  # raw data for downstream use


class OrchestratorState(TypedDict):
    user_query: str
    llm_service: Any
    config: Dict[str, Any]
    hop_history: List[HopEntry]
    final_answer: Optional[str]
    error_log: List[str]
    hop_count: int
