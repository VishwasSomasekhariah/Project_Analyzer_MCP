"""
DEPRECATED - Original Monolithic Adaptive CPG Agent Workflow (3000+ lines)

This file has been modularized into the workflow/ package for better maintainability.
This file is kept for reference but should not be used in production.

New modular structure:
- workflow/models.py: Pydantic data models with validation
- workflow/research_engine.py: Intelligent discovery research  
- workflow/context_manager.py: Data organization and context management
- workflow/nodes.py: LangGraph workflow node implementations
- workflow/adaptive_cpg_workflow.py: Main workflow orchestrator

Use the new modular workflow instead:
    from src.core.workflow import execute_adaptive_cpg_workflow
    
Or for backwards compatibility:
    from src.core.adaptive_cpg_agent_workflow_v2 import execute_adaptive_cpg_workflow
"""

import warnings

def _deprecated_warning():
    """Issue deprecation warning."""
    warnings.warn(
        "The monolithic adaptive_cpg_agent_workflow.py is deprecated. "
        "Use 'from src.core.workflow import AdaptiveCPGAgentWorkflow' instead. "
        "The old file was 3000+ lines and has been modularized for better maintainability.",
        DeprecationWarning,
        stacklevel=3
    )

# Redirect all imports to the new modular workflow
def __getattr__(name):
    """Redirect attribute access to new modular workflow."""
    _deprecated_warning()
    
    from .workflow import (
        AgentState, AdaptiveCPGAgentWorkflow, 
        create_adaptive_cpg_workflow, execute_adaptive_cpg_workflow
    )
    
    module_dict = {
        'AgentState': AgentState,
        'AdaptiveCPGAgentWorkflow': AdaptiveCPGAgentWorkflow,
        'create_adaptive_cpg_workflow': create_adaptive_cpg_workflow,
        'execute_adaptive_cpg_workflow': execute_adaptive_cpg_workflow
    }
    
    if name in module_dict:
        return module_dict[name]
    
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

# Main execution redirect
async def main():
    """Redirect main execution to new modular workflow."""
    _deprecated_warning()
    from .workflow.adaptive_cpg_workflow import main
    return await main()