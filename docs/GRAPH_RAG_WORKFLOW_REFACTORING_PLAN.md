# Graph RAG Workflow Refactoring Plan

## Overview

Migrate from the old workflow system to a new modular Multi-Agent ToT/CoT architecture.

## Current State

### Old Workflow (`src/core/workflow/`) - TO BE DEPRECATED
```
src/core/workflow/
├── adaptive_cpg_workflow.py      # Old LangGraph workflow
├── adaptive_query_agent.py       # Old query agent
├── apoc_cache_tool.py           # KEEP - Cache utilities
├── approach_validation_agent_v2.py
├── context_manager.py
├── cpg_discovery_agent.py
├── cypher_query_validator.py    # KEEP - Security validation
├── cypher_server_pool.py
├── dynamic_schema_manager.py    # KEEP - Schema management
├── models.py                    # Old models
├── nodes.py / nodes_v0.py       # Old LangGraph nodes
├── prompts.py                   # Old prompts
├── research_engine.py           # Old engine
├── schema_tools.py              # KEEP - Schema tools
├── schema_tools_langchain.py    # KEEP - LangChain integration
├── schema_tool_caller.py
└── __init__.py
```

### New System (`test_multi_agent_cot.py`) - 3237 lines, 46 classes

**Classes to extract:**

| Class | Lines | Purpose | Target Module |
|-------|-------|---------|---------------|
| MultiAgentError (+ 7 subclasses) | 78-119 | Exceptions | `exceptions.py` |
| ConfidenceLevel, VerificationStatus, AgentRole | 122-143 | Enums | `enums.py` |
| CodeEntity, Finding, VerificationResult, SubQuery, etc. | 145-365 | Data models | `models.py` |
| MCPServerConfig, MCPConfig, LLMConfig, SystemConfig | 368-573 | Configuration | `config.py` |
| TokenUsage, AggregatedTokenUsage | 575-613 | Metrics | `metrics.py` |
| InputPromptValidator | 643-750 | Input validation | `validators.py` |
| CypherQueryValidator | 752-926 | Cypher security | `validators.py` |
| MCPCypherAdapter | 928-953 | MCP adapter | `adapters.py` |
| MCPSessionPool | 955-1033 | Session pooling | `adapters.py` |
| BaseAgent | 1035-1117 | Abstract base | `agents/base.py` |
| ToolManager | 1119-1308 | Tool management | `tools/manager.py` |
| CoTAgent | 1310-1494 | Chain-of-Thought | `agents/cot_agent.py` |
| VerificationAgent | 1496-1638 | Verification | `agents/verification_agent.py` |
| EntityResolutionAgent | 1640-1900 | Entity resolution | `agents/entity_resolution_agent.py` |
| CPGObserverAgent | 1902-2515 | CPG Observer | `agents/cpg_observer_agent.py` |
| ToTOrchestrator | 2517-2690 | Tree-of-Thought | `orchestrators/tot_orchestrator.py` |
| MultiAgentCoT | 2692-3167 | Main orchestrator | `orchestrators/multi_agent_cot.py` |

## Proposed New Structure

```
src/core/
├── workflow_deprecated/          # Renamed from workflow/
│   └── ... (all old files)
│
└── graph_rag/                    # NEW - Multi-Agent Graph RAG
    ├── __init__.py
    │
    ├── core/                     # Core components
    │   ├── __init__.py
    │   ├── exceptions.py         # All custom exceptions
    │   ├── enums.py              # Enums (ConfidenceLevel, etc.)
    │   ├── models.py             # Pydantic models
    │   ├── config.py             # Configuration classes
    │   └── metrics.py            # Token tracking, timing
    │
    ├── validators/               # Validation components
    │   ├── __init__.py
    │   ├── input_validator.py    # InputPromptValidator
    │   └── cypher_validator.py   # CypherQueryValidator
    │
    ├── adapters/                 # MCP and external adapters
    │   ├── __init__.py
    │   ├── mcp_adapter.py        # MCPCypherAdapter
    │   └── session_pool.py       # MCPSessionPool
    │
    ├── tools/                    # Tool management
    │   ├── __init__.py
    │   ├── manager.py            # ToolManager
    │   └── discovery.py          # Dynamic MCP tool discovery
    │
    ├── schema/                   # Schema management (from old workflow)
    │   ├── __init__.py
    │   ├── dynamic_schema_manager.py  # MOVED from workflow/
    │   ├── schema_tools.py            # MOVED from workflow/
    │   └── schema_tools_langchain.py  # MOVED from workflow/
    │
    ├── agents/                   # Agent implementations
    │   ├── __init__.py
    │   ├── base.py               # BaseAgent ABC
    │   ├── cot_agent.py          # CoTAgent
    │   ├── verification_agent.py # VerificationAgent
    │   ├── entity_resolution_agent.py  # EntityResolutionAgent
    │   └── cpg_observer_agent.py       # CPGObserverAgent
    │
    ├── orchestrators/            # High-level orchestration
    │   ├── __init__.py
    │   ├── tot_orchestrator.py   # ToTOrchestrator
    │   └── multi_agent_cot.py    # MultiAgentCoT (main entry)
    │
    └── prompts/                  # Prompt templates
        ├── __init__.py
        ├── decomposition.py      # DECOMPOSITION_PROMPT
        ├── cot_prompts.py        # COT_SYSTEM_PROMPT, COT_ANSWER_PROMPT
        ├── verification.py       # VERIFICATION_PROMPT
        ├── entity_resolution.py  # ENTITY_RESOLUTION_PROMPT
        ├── synthesis.py          # SYNTHESIS_PROMPT
        └── observer.py           # ANALYSIS_PROMPT
```

## Migration Steps

### Phase 1: Prepare (No breaking changes)

1. **Rename old workflow directory**
   ```bash
   mv src/core/workflow src/core/workflow_deprecated
   ```

2. **Create new directory structure**
   ```bash
   mkdir -p src/core/graph_rag/{core,validators,adapters,tools,schema,agents,orchestrators,prompts}
   touch src/core/graph_rag/__init__.py
   touch src/core/graph_rag/{core,validators,adapters,tools,schema,agents,orchestrators,prompts}/__init__.py
   ```

3. **Create backward-compatible imports in workflow_deprecated**
   ```python
   # src/core/workflow_deprecated/__init__.py
   import warnings
   warnings.warn(
       "src.core.workflow is deprecated. Use src.core.graph_rag instead.",
       DeprecationWarning,
       stacklevel=2
   )
   # Re-export for backward compatibility
   from src.core.graph_rag.schema.dynamic_schema_manager import DynamicSchemaManager
   ```

### Phase 2: Extract Core Components

| Step | Source (test_multi_agent_cot.py) | Target |
|------|----------------------------------|--------|
| 2.1 | Lines 78-119 (Exceptions) | `core/exceptions.py` |
| 2.2 | Lines 122-143 (Enums) | `core/enums.py` |
| 2.3 | Lines 145-365 (Models) | `core/models.py` |
| 2.4 | Lines 368-573 (Config) | `core/config.py` |
| 2.5 | Lines 575-640 (Metrics) | `core/metrics.py` |

### Phase 3: Extract Validators and Adapters

| Step | Source | Target |
|------|--------|--------|
| 3.1 | Lines 643-750 (InputPromptValidator) | `validators/input_validator.py` |
| 3.2 | Lines 752-926 (CypherQueryValidator) | `validators/cypher_validator.py` |
| 3.3 | Lines 928-953 (MCPCypherAdapter) | `adapters/mcp_adapter.py` |
| 3.4 | Lines 955-1033 (MCPSessionPool) | `adapters/session_pool.py` |

### Phase 4: Move Schema Components

```bash
# Move from workflow_deprecated to new location
cp src/core/workflow_deprecated/dynamic_schema_manager.py src/core/graph_rag/schema/
cp src/core/workflow_deprecated/schema_tools.py src/core/graph_rag/schema/
cp src/core/workflow_deprecated/schema_tools_langchain.py src/core/graph_rag/schema/
```

### Phase 5: Extract Tools

| Step | Source | Target |
|------|--------|--------|
| 5.1 | Lines 1119-1308 (ToolManager) | `tools/manager.py` |
| 5.2 | New code (from design doc) | `tools/discovery.py` |

### Phase 6: Extract Agents

| Step | Source | Target |
|------|--------|--------|
| 6.1 | Lines 1035-1117 (BaseAgent) | `agents/base.py` |
| 6.2 | Lines 1310-1494 (CoTAgent) | `agents/cot_agent.py` |
| 6.3 | Lines 1496-1638 (VerificationAgent) | `agents/verification_agent.py` |
| 6.4 | Lines 1640-1900 (EntityResolutionAgent) | `agents/entity_resolution_agent.py` |
| 6.5 | Lines 1902-2515 (CPGObserverAgent) | `agents/cpg_observer_agent.py` |

### Phase 7: Extract Orchestrators

| Step | Source | Target |
|------|--------|--------|
| 7.1 | Lines 2517-2690 (ToTOrchestrator) | `orchestrators/tot_orchestrator.py` |
| 7.2 | Lines 2692-3167 (MultiAgentCoT) | `orchestrators/multi_agent_cot.py` |

### Phase 8: Extract Prompts

Extract all prompt constants from the file into dedicated prompt modules.

### Phase 9: Create Main Entry Point

```python
# src/core/graph_rag/__init__.py
"""
Graph RAG - Multi-Agent Tree-of-Thought Code Analysis

Usage:
    from src.core.graph_rag import MultiAgentCoT, SystemConfig

    config = SystemConfig(...)
    agent = MultiAgentCoT(config)
    await agent.initialize()
    response = await agent.analyze("What is the architecture?")
"""

from .orchestrators.multi_agent_cot import MultiAgentCoT
from .core.config import SystemConfig, LLMConfig, MCPConfig
from .core.models import ProductionResponse, Citation
from .core.exceptions import MultiAgentError

__all__ = [
    'MultiAgentCoT',
    'SystemConfig',
    'LLMConfig',
    'MCPConfig',
    'ProductionResponse',
    'Citation',
    'MultiAgentError',
]
```

## Import Updates Required

### Before (current)
```python
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
from src.core.workflow.schema_tools_langchain import create_schema_tools
```

### After (new)
```python
from src.core.graph_rag.schema import DynamicSchemaManager, create_schema_tools
# OR
from src.core.graph_rag import MultiAgentCoT  # High-level API
```

## Files That Need Import Updates

After refactoring, these files will need import path updates:

```bash
grep -r "from src.core.workflow" --include="*.py" | grep -v __pycache__
```

Expected files:
- `test_multi_agent_cot.py`
- CLI tools that use workflow
- Any notebooks or scripts

## Testing Strategy

1. **Unit tests** for each new module
2. **Integration test** comparing old vs new workflow outputs
3. **Regression test** ensuring same results for benchmark queries

## Rollback Plan

If issues arise:
1. `workflow_deprecated/` still exists with all original code
2. Backward-compatible imports allow gradual migration
3. Feature flag to switch between old and new

## Timeline Estimate

| Phase | Effort |
|-------|--------|
| Phase 1: Prepare | 1 hour |
| Phase 2: Core | 2 hours |
| Phase 3: Validators/Adapters | 1 hour |
| Phase 4: Schema | 30 min |
| Phase 5: Tools | 1 hour |
| Phase 6: Agents | 2 hours |
| Phase 7: Orchestrators | 1 hour |
| Phase 8: Prompts | 30 min |
| Phase 9: Integration | 2 hours |
| Testing | 2 hours |
| **Total** | ~13 hours |

## Dependencies to Keep

These components from old workflow are still needed and will be **COPIED** (not moved):
- `dynamic_schema_manager.py` - Schema management
- `schema_tools.py` - Schema query tools
- `schema_tools_langchain.py` - LangChain integration
- `apoc_cache_tool.py` - APOC cache utilities

**NOTE**: We COPY these files to preserve the old workflow intact. The old `workflow/`
directory remains unchanged and functional. This allows:
1. Parallel development without breaking existing code
2. Easy rollback if needed
3. Gradual migration of dependent code

## Components to Deprecate

These are replaced by the new multi-agent system:
- `adaptive_cpg_workflow.py`
- `adaptive_query_agent.py`
- `research_engine.py`
- `nodes.py` / `nodes_v0.py`
- `prompts.py` (replaced by new prompt modules)
- `models.py` (replaced by new models)
