"""
THIS MODULE IS STILL UNTESTED AND UNDER DEVELOPMENT. DO NOT USE. YOU MAY BE LOOKING FOR src.core.workflow.adaptive_cpg_workflow INSTEAD.
Modular Adaptive CPG Agent Workflow Package.

This package provides a clean, modular implementation of the Adaptive CPG Agent Workflow
that was previously contained in a single large file. The modular structure improves:

- Maintainability: Clear separation of concerns
- Testability: Individual components can be tested
- Readability: Focused modules with specific responsibilities  
- Extensibility: Easy to add new features or modify existing ones
- Error Handling: Pydantic validation and proper error propagation

Main Components:
- models.py: Pydantic data models with validation
- research_engine.py: Intelligent discovery research system
- context_manager.py: Data organization and context management
- nodes.py: LangGraph workflow node implementations  
- adaptive_cpg_workflow.py: Main workflow orchestrator

Usage:
    from src.core.parallel_workflow import AdaptiveCPGAgentWorkflow, execute_adaptive_cpg_workflow
    
    # Option 1: Direct execution
    results = await execute_adaptive_cpg_workflow("Your query here")
    
    # Option 2: Create workflow instance
    workflow = AdaptiveCPGAgentWorkflow()
    await workflow.initialize_services() 
    results = await workflow.run_workflow("Your query here")
"""

from .parallel_models import (
    AgentState,
    SchemaAnalysis,
    ExplorationHypothesis, 
    QueryStrategy,
    ExecutionPlan,
    DiscoveryResearch,
    IntentAnalysis,
    SufficiencyEvaluation
)

from .parallel_research_engine import ResearchEngine
from .parallel_context_manager import ContextManager
from .parallel_nodes import WorkflowNodes

from .parallel_adaptive_cpg_workflow import (
    AdaptiveCPGAgentWorkflow,
    create_adaptive_cpg_workflow,
    execute_adaptive_cpg_workflow
)

__all__ = [
    # Data Models
    "AgentState",
    "SchemaAnalysis", 
    "ExplorationHypothesis",
    "QueryStrategy", 
    "ExecutionPlan",
    "DiscoveryResearch",
    "IntentAnalysis",
    "SufficiencyEvaluation",
    
    # Core Components
    "ResearchEngine",
    "ContextManager", 
    "WorkflowNodes",
    
    # Main Workflow
    "AdaptiveCPGAgentWorkflow",
    "create_adaptive_cpg_workflow",
    "execute_adaptive_cpg_workflow"
]

# Version info
__version__ = "2.0.0"
__author__ = "Claude Code Assistant"  
__description__ = "Modular Adaptive CPG Agent Workflow with LangGraph orchestration"