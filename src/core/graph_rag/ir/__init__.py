"""
Intermediate Representation (IR) Module for Graph RAG.

This module provides a structured, validatable intermediate representation
between natural language queries and Cypher execution.

Architecture:
    User Query → [IRPlannerAgent] → QueryIR → [IRValidator] → [CypherCompiler] → Cypher

Components:
    - models: Pydantic models for IR structure (QueryIR, TargetEntity, etc.)
    - context: IRContext for efficient alias/schema lookups
    - validators: 3-layer validation (syntax, schema, semantic)
    - compiler: Deterministic IR → Cypher compilation

Usage:
    from src.core.graph_rag.ir import (
        QueryIR,
        QueryIntent,
        IRValidator,
        IntentRuleEngine,
        CypherCompiler,
        SchemaInfo,
        IRContext,
    )

    # Build IR (typically from IRPlannerAgent)
    ir = QueryIR(
        intent=QueryIntent.FIND,
        targets=[TargetEntity(node_label="Function", alias="fn")],
        projections=[
            Projection(source_alias="fn", property="name", output_name="name"),
            Projection(source_alias="fn", property="cyclomatic_complexity", output_name="complexity")
        ]
    )

    # Validate
    schema = SchemaInfo.from_schema_manager(schema_manager)
    validator = IRValidator(schema, intent_rules=IntentRuleEngine())
    result = validator.validate(ir)

    if result.valid:
        # Compile to Cypher
        compiler = CypherCompiler()
        cypher = compiler.compile(ir)
        # Execute cypher...
    else:
        # Return errors to IRPlanner for correction
        feedback = result.to_feedback()
"""

# Core models
from .models import (
    # Enums
    QueryIntent,
    FilterOperator,
    AggregationType,
    RelationshipDirection,
    OutputFormatType,
    SortOrder,
    # Core IR models
    TargetEntity,
    TraversalStep,
    TraversalPath,
    Projection,
    FilterCondition,
    OrderSpec,
    OutputFormat,
    QueryIR,
    # Validation result models
    ValidationError,
    ValidationResult,
)

# Context
from .context import (
    SchemaInfo,
    IRContext,
)

# Validators
from .validators import (
    IRValidator,
    IntentRuleEngine,
)

# Compiler
from .compiler import (
    CypherCompiler,
    CypherCompilationError,
)

# Planner Agent
from .planner_agent import (
    IRPlannerAgent,
    IRPlanningResult,
)

# Multi-Agent IR CoT Orchestrator (integrates with existing system)
from .multi_agent_ir_cot import (
    MultiAgentIRCoT,
)


__all__ = [
    # Enums
    'QueryIntent',
    'FilterOperator',
    'AggregationType',
    'RelationshipDirection',
    'OutputFormatType',
    'SortOrder',
    # Core IR models
    'TargetEntity',
    'TraversalStep',
    'TraversalPath',
    'Projection',
    'FilterCondition',
    'OrderSpec',
    'OutputFormat',
    'QueryIR',
    # Validation models
    'ValidationError',
    'ValidationResult',
    # Context
    'SchemaInfo',
    'IRContext',
    # Validators
    'IRValidator',
    'IntentRuleEngine',
    # Compiler
    'CypherCompiler',
    'CypherCompilationError',
    # Planner Agent
    'IRPlannerAgent',
    'IRPlanningResult',
    # Multi-Agent IR CoT
    'MultiAgentIRCoT',
]
