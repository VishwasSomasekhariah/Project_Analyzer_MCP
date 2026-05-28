"""
Core business logic modules for the MCP Server project.

This package provides the core functionality including:
- Modular adaptive CPG agent workflow
- LLM service integration
- MCP manager functionality
- Entity extraction and analysis services
"""

# Export the main workflow components for easy access
from .workflow import (
    AdaptiveCPGAgentWorkflow,
    execute_adaptive_cpg_workflow,
    create_adaptive_cpg_workflow,
    AgentState,
    SchemaAnalysis,
    ExplorationHypothesis,
    QueryStrategy,
    ExecutionPlan
)

# Also maintain backwards compatibility by exposing through adaptive_cpg_agent_workflow
from .adaptive_cpg_agent_workflow import (
    AdaptiveCPGAgentWorkflow as BackwardsCompatAdaptiveCPGAgentWorkflow,
    execute_adaptive_cpg_workflow as BackwardsCompatExecuteWorkflow,
    main
)

# Export hybrid workflow components (V2: PageIndex primary + vector/CPG fallback)
from .hybrid_workflow_V2 import (
    HybridRAGWorkflow, HybridRAGTool, run_hybrid_analysis,
    HybridState, QueryIntent, SynthesisStrategy
)

# Export other core services
from .llm_service import LLMService, LLMModel, LLMProvider
from .entity_extraction_service import EntityExtractionService

__all__ = [
    # Main CPG workflow (preferred)
    "AdaptiveCPGAgentWorkflow",
    "execute_adaptive_cpg_workflow", 
    "create_adaptive_cpg_workflow",
    
    # Hybrid RAG workflow
    "HybridRAGWorkflow",
    "HybridRAGTool",
    "run_hybrid_analysis",
    "HybridState",
    "QueryIntent",
    "SynthesisStrategy",
    
    # Data models
    "AgentState",
    "SchemaAnalysis",
    "ExplorationHypothesis", 
    "QueryStrategy",
    "ExecutionPlan",
    
    # Backwards compatibility
    "BackwardsCompatAdaptiveCPGAgentWorkflow",
    "BackwardsCompatExecuteWorkflow",
    "main",
    
    # Core services
    "LLMService",
    "LLMModel", 
    "LLMProvider",
    "EntityExtractionService"
]