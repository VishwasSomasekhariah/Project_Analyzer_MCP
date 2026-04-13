"""
Backwards Compatibility Wrapper for Adaptive CPG Agent Workflow.

This file maintains backwards compatibility for the old monolithic workflow
while redirecting all functionality to the new modular implementation.

All existing imports and function calls will continue to work exactly as before,
but now benefit from the improved modular architecture with:
- Pydantic validation
- Better error handling  
- Cleaner code organization
- Enhanced maintainability

Usage (unchanged from before):
    from src.core.adaptive_cpg_agent_workflow import (
        AdaptiveCPGAgentWorkflow,
        create_adaptive_cpg_workflow,
        execute_adaptive_cpg_workflow
    )
"""

# Import everything from the new modular workflow
from .workflow import (
    # Data Models (now with Pydantic validation)
    AgentState,
    SchemaAnalysis,
    ExplorationHypothesis,
    QueryStrategy, 
    ExecutionPlan,
    DiscoveryResearch,
    IntentAnalysis,
    SufficiencyEvaluation,
    
    # Core Components
    ResearchEngine,
    ContextManager,
    WorkflowNodes,
    
    # Main Workflow Classes and Functions
    AdaptiveCPGAgentWorkflow,
    create_adaptive_cpg_workflow,
    execute_adaptive_cpg_workflow
)

# Maintain the original function signatures for backwards compatibility
async def main():
    """Main function - same signature as original."""
    from .workflow.adaptive_cpg_workflow import main
    return await main()

# Export everything that was available in the original file
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
    "execute_adaptive_cpg_workflow",
    
    # Functions
    "main"
]

# Add version info
__version__ = "2.0.0-compat"
__description__ = "Backwards compatibility wrapper for modular Adaptive CPG Agent Workflow"