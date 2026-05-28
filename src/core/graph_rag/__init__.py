"""
Graph RAG Multi-Agent System for Code Analysis.

A pip-installable package providing Tree-of-Thought (ToT) and Chain-of-Thought (CoT)
multi-agent orchestration for querying Code Property Graphs (CPG) stored in Neo4j.

Quick Start:
    from src.core.graph_rag import MultiAgentCoT, SystemConfig

    config = SystemConfig(
        mcp_config_path="neo4j_config.json",
        yaml_schema_path="schema.yaml",
        llm_model="gpt-4o"
    )

    system = MultiAgentCoT(config)
    await system.initialize()
    response = await system.run("What classes are in the project?")
    print(response.answer)

Modules:
    - core: Exceptions, enums, models, config, metrics
    - agents: BaseAgent, CoTAgent, VerificationAgent, EntityResolutionAgent, CPGObserverAgent
    - orchestrators: ToTOrchestrator, MultiAgentCoT
    - schema: DynamicSchemaManager, SchemaTools
    - tools: ToolManager, retry utilities
    - validators: InputPromptValidator, CypherQueryValidator
    - adapters: MCPCypherAdapter, MCPSessionPool
    - prompts: Centralized prompt templates
"""

# Version
__version__ = "0.1.0"

# Core components
from src.core.graph_rag.core.config import (
    LLMConfig,
    MCPConfig,
    MCPServerConfig,
    SystemConfig,
)
from src.core.graph_rag.core.enums import (
    AgentRole,
    ConfidenceLevel,
    VerificationStatus,
)
from src.core.graph_rag.core.exceptions import (
    AgentExecutionError,
    ConfigurationError,
    CypherSecurityError,
    LLMResponseError,
    MultiAgentError,
    QueryDecompositionError,
    ToolExecutionError,
    VerificationError,
)
from src.core.graph_rag.core.models import (
    Citation,
    CodeEntity,
    EntityCorrection,
    EntityResolutionResult,
    Finding,
    FinalAnswer,
    ProductionResponse,
    QueryDecomposition,
    SubQuery,
    VerificationResult,
    VerifierResponse,
    WorkerResponse,
)
from src.core.graph_rag.core.metrics import (
    AggregatedTokenUsage,
    TokenUsage,
)

# Orchestrators (main entry points)
from src.core.graph_rag.orchestrators import (
    MultiAgentCoT,
    ToTOrchestrator,
)

# Agents
from src.core.graph_rag.agents import (
    BaseAgent,
    CoTAgent,
    CPGObserverAgent,
    EntityResolutionAgent,
    VerificationAgent,
)

# Schema management
from src.core.graph_rag.schema import (
    APOCCacheTool,
    DynamicSchemaManager,
    create_schema_tools,
)

# Tools
from src.core.graph_rag.tools import (
    ToolManager,
    retry_with_backoff,
)

# Validators
from src.core.graph_rag.validators import (
    CypherQueryValidator,
    InputPromptValidator,
)

# Adapters
from src.core.graph_rag.adapters import (
    MCPCypherAdapter,
    MCPSessionPool,
)

# Prompts
from src.core.graph_rag.prompts import (
    PromptTemplates,
)


__all__ = [
    # Version
    '__version__',

    # Main entry points
    'MultiAgentCoT',
    'ToTOrchestrator',

    # Configuration
    'SystemConfig',
    'LLMConfig',
    'MCPConfig',
    'MCPServerConfig',

    # Agents
    'BaseAgent',
    'CoTAgent',
    'VerificationAgent',
    'EntityResolutionAgent',
    'CPGObserverAgent',

    # Schema
    'DynamicSchemaManager',
    'create_schema_tools',
    'APOCCacheTool',

    # Tools
    'ToolManager',
    'retry_with_backoff',

    # Validators
    'InputPromptValidator',
    'CypherQueryValidator',

    # Adapters
    'MCPCypherAdapter',
    'MCPSessionPool',

    # Models
    'ProductionResponse',
    'Citation',
    'Finding',
    'FinalAnswer',
    'SubQuery',
    'QueryDecomposition',
    'VerificationResult',
    'VerifierResponse',
    'WorkerResponse',
    'CodeEntity',
    'EntityCorrection',
    'EntityResolutionResult',

    # Enums
    'ConfidenceLevel',
    'VerificationStatus',
    'AgentRole',

    # Metrics
    'TokenUsage',
    'AggregatedTokenUsage',

    # Exceptions
    'MultiAgentError',
    'AgentExecutionError',
    'ConfigurationError',
    'CypherSecurityError',
    'LLMResponseError',
    'QueryDecompositionError',
    'ToolExecutionError',
    'VerificationError',

    # Prompts
    'PromptTemplates',
]
