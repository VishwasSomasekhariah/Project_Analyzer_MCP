"""
Intermediate Representation (IR) Models for Graph RAG queries.

This module defines the IR schema that sits between natural language queries
and Cypher execution. The IR provides:
1. A structured, validatable representation of query intent
2. Schema-aware validation before Cypher generation
3. Deterministic compilation to Cypher (no LLM hallucinations)

Security Considerations:
- All string fields are validated to prevent injection attacks
- Alias names are restricted to alphanumeric characters
- Property and label names are validated against schema
- Maximum limits prevent resource exhaustion attacks

Architecture:
    User Query → [IRPlannerAgent] → QueryIR → [IRValidator] → [CypherCompiler] → Cypher
"""

import re
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =============================================================================
# SECURITY CONSTANTS
# =============================================================================

# Maximum limits to prevent resource exhaustion
MAX_ALIAS_LENGTH = 32
MAX_PROPERTY_NAME_LENGTH = 64
MAX_LABEL_LENGTH = 64
MAX_STRING_VALUE_LENGTH = 1000
MAX_TRAVERSAL_DEPTH = 10
MAX_FILTERS = 20
MAX_PROJECTIONS = 50
MAX_TARGETS = 15
MAX_LIST_ITEMS = 100

# Valid identifier pattern (alphanumeric + underscore, must start with letter)
IDENTIFIER_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*$')

# Forbidden patterns that could indicate injection attempts
FORBIDDEN_PATTERNS = [
    re.compile(r'[;\'"\\`]'),  # SQL/Cypher injection chars
    re.compile(r'\b(CREATE|MERGE|DELETE|REMOVE|SET|DROP|CALL)\b', re.IGNORECASE),
    re.compile(r'//|/\*|\*/'),  # Comment injection
    re.compile(r'\$\{|\{\{'),  # Template injection
]


# =============================================================================
# ENUMS
# =============================================================================

class QueryIntent(str, Enum):
    """
    High-level query intent classification.

    Each intent type has specific validation rules and compilation patterns.
    """
    FIND = "find"                    # Find entities matching criteria
    COUNT = "count"                  # Count entities
    AGGREGATE = "aggregate"          # Aggregate values (sum, avg, etc.)
    TRAVERSE = "traverse"            # Follow relationships
    COMPARE = "compare"              # Compare entities or values
    COMPUTE_METRIC = "compute_metric"  # Calculate derived metrics
    LIST = "list"                    # List all of something
    EXISTENCE = "existence"          # Check if something exists


class FilterOperator(str, Enum):
    """
    Supported filter operators.

    Maps to Cypher comparison operators with proper escaping.
    """
    EQ = "eq"                        # =
    NEQ = "neq"                      # <>
    GT = "gt"                        # >
    GTE = "gte"                      # >=
    LT = "lt"                        # <
    LTE = "lte"                      # <=
    CONTAINS = "contains"            # CONTAINS
    STARTS_WITH = "starts_with"      # STARTS WITH
    ENDS_WITH = "ends_with"          # ENDS WITH
    IN = "in"                        # IN [...]
    NOT_IN = "not_in"                # NOT IN [...]
    IS_NULL = "is_null"              # IS NULL
    IS_NOT_NULL = "is_not_null"      # IS NOT NULL
    REGEX = "regex"                  # =~ (regex match)


class AggregationType(str, Enum):
    """Supported aggregation functions."""
    COUNT = "count"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    COLLECT = "collect"              # Collect into list
    COUNT_DISTINCT = "count_distinct"


class RelationshipDirection(str, Enum):
    """Direction of relationship traversal."""
    OUTGOING = "outgoing"            # (a)-[r]->(b)
    INCOMING = "incoming"            # (a)<-[r]-(b)
    BOTH = "both"                    # (a)-[r]-(b)


class OutputFormatType(str, Enum):
    """How results should be formatted."""
    TABLE = "table"                  # Rows and columns
    LIST = "list"                    # List of items
    SCALAR = "scalar"                # Single value
    TREE = "tree"                    # Hierarchical structure
    GRAPH = "graph"                  # Nodes and edges


class SortOrder(str, Enum):
    """Sort direction."""
    ASC = "asc"
    DESC = "desc"


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def validate_identifier(value: str, field_name: str, max_length: int) -> str:
    """
    Validate an identifier (alias, property name, label).

    Security: Prevents injection attacks by enforcing strict naming.
    """
    if not value:
        raise ValueError(f"{field_name} cannot be empty")

    if len(value) > max_length:
        raise ValueError(f"{field_name} exceeds maximum length of {max_length}")

    if not IDENTIFIER_PATTERN.match(value):
        raise ValueError(
            f"{field_name} must be alphanumeric (starting with letter): '{value}'"
        )

    # Check for forbidden patterns
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(value):
            raise ValueError(f"{field_name} contains forbidden characters: '{value}'")

    return value


def validate_string_value(value: str, field_name: str) -> str:
    """
    Validate a string value for filter comparisons.

    Security: Prevents injection via filter values.
    """
    if len(value) > MAX_STRING_VALUE_LENGTH:
        raise ValueError(f"{field_name} exceeds maximum length of {MAX_STRING_VALUE_LENGTH}")

    # Check for obvious injection attempts (but allow normal strings)
    for pattern in FORBIDDEN_PATTERNS[1:3]:  # Only check CREATE/DELETE and comments
        if pattern.search(value):
            raise ValueError(f"{field_name} contains potentially dangerous content")

    return value


# =============================================================================
# CORE IR MODELS
# =============================================================================

class TargetEntity(BaseModel):
    """
    Represents a node to query in the graph.

    Example:
        {"node_label": "Function", "alias": "fn"}
        → Compiles to: (fn:Function)
    """
    model_config = ConfigDict(frozen=True, extra='forbid')

    node_label: str = Field(
        ...,
        description="Graph node label (must exist in schema)",
        min_length=1,
        max_length=MAX_LABEL_LENGTH
    )
    alias: str = Field(
        ...,
        description="Reference name used in IR (unique within query)",
        min_length=1,
        max_length=MAX_ALIAS_LENGTH
    )

    @field_validator('node_label')
    @classmethod
    def validate_label(cls, v: str) -> str:
        return validate_identifier(v, 'node_label', MAX_LABEL_LENGTH)

    @field_validator('alias')
    @classmethod
    def validate_alias(cls, v: str) -> str:
        return validate_identifier(v, 'alias', MAX_ALIAS_LENGTH)


class TraversalStep(BaseModel):
    """
    A single hop in a graph traversal.

    Example:
        {"from_alias": "f", "relationship": "CONTAINS", "direction": "outgoing",
         "to_label": "Function", "to_alias": "fn"}
        → Compiles to: (f)-[:CONTAINS]->(fn:Function)
    """
    model_config = ConfigDict(frozen=True, extra='forbid')

    from_alias: str = Field(
        ...,
        description="Source node alias (must be defined earlier)",
        min_length=1,
        max_length=MAX_ALIAS_LENGTH
    )
    relationship: str = Field(
        ...,
        description="Relationship type (must exist in schema)",
        min_length=1,
        max_length=MAX_LABEL_LENGTH
    )
    direction: RelationshipDirection = Field(
        default=RelationshipDirection.OUTGOING,
        description="Traversal direction"
    )
    to_label: str = Field(
        ...,
        description="Target node label",
        min_length=1,
        max_length=MAX_LABEL_LENGTH
    )
    to_alias: str = Field(
        ...,
        description="Target node alias (unique within query)",
        min_length=1,
        max_length=MAX_ALIAS_LENGTH
    )
    relationship_alias: Optional[str] = Field(
        default=None,
        description="Optional alias for the relationship itself",
        max_length=MAX_ALIAS_LENGTH
    )

    @field_validator('from_alias', 'to_alias')
    @classmethod
    def validate_alias(cls, v: str) -> str:
        return validate_identifier(v, 'alias', MAX_ALIAS_LENGTH)

    @field_validator('relationship', 'to_label')
    @classmethod
    def validate_label(cls, v: str) -> str:
        return validate_identifier(v, 'label', MAX_LABEL_LENGTH)

    @field_validator('relationship_alias')
    @classmethod
    def validate_rel_alias(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_identifier(v, 'relationship_alias', MAX_ALIAS_LENGTH)
        return v


class TraversalPath(BaseModel):
    """
    Complete traversal path through the graph.

    Example:
        Project -[CONTAINS]-> File -[CONTAINS]-> Function
    """
    model_config = ConfigDict(frozen=True, extra='forbid')

    steps: List[TraversalStep] = Field(
        default_factory=list,
        description="Ordered traversal steps",
        max_length=MAX_TRAVERSAL_DEPTH
    )

    @field_validator('steps')
    @classmethod
    def validate_steps(cls, v: List[TraversalStep]) -> List[TraversalStep]:
        if len(v) > MAX_TRAVERSAL_DEPTH:
            raise ValueError(f"Traversal depth exceeds maximum of {MAX_TRAVERSAL_DEPTH}")
        return v


class Projection(BaseModel):
    """
    Specifies what to return from the query.

    Example:
        {"source_alias": "fn", "property": "name", "output_name": "function_name"}
        → Compiles to: fn.name AS function_name

        {"source_alias": "fn", "property": "name", "aggregation": "count", "output_name": "total"}
        → Compiles to: count(fn.name) AS total
    """
    model_config = ConfigDict(frozen=True, extra='forbid')

    source_alias: str = Field(
        ...,
        description="Alias of the node/relationship to project from",
        min_length=1,
        max_length=MAX_ALIAS_LENGTH
    )
    property: Optional[str] = Field(
        default=None,
        description="Property name to project (None = entire node)",
        max_length=MAX_PROPERTY_NAME_LENGTH
    )
    output_name: str = Field(
        ...,
        description="Name for this projection in output",
        min_length=1,
        max_length=MAX_PROPERTY_NAME_LENGTH
    )
    aggregation: Optional[AggregationType] = Field(
        default=None,
        description="Optional aggregation function"
    )
    distinct: bool = Field(
        default=False,
        description="Apply DISTINCT to this projection"
    )

    @field_validator('source_alias', 'output_name')
    @classmethod
    def validate_alias(cls, v: str) -> str:
        return validate_identifier(v, 'alias', MAX_ALIAS_LENGTH)

    @field_validator('property')
    @classmethod
    def validate_property(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_identifier(v, 'property', MAX_PROPERTY_NAME_LENGTH)
        return v


class FilterCondition(BaseModel):
    """
    A filter condition for WHERE clause.

    Example:
        {"source_alias": "p", "property": "name", "operator": "eq", "value": "HelloWorldApp"}
        → Compiles to: p.name = 'HelloWorldApp'
    """
    model_config = ConfigDict(frozen=True, extra='forbid')

    source_alias: str = Field(
        ...,
        description="Alias of the node/relationship to filter",
        min_length=1,
        max_length=MAX_ALIAS_LENGTH
    )
    property: str = Field(
        ...,
        description="Property name to filter on",
        min_length=1,
        max_length=MAX_PROPERTY_NAME_LENGTH
    )
    operator: FilterOperator = Field(
        ...,
        description="Comparison operator"
    )
    value: Optional[Union[str, int, float, bool, List[Union[str, int, float]]]] = Field(
        default=None,
        description="Value to compare against (None for IS NULL/IS NOT NULL)"
    )
    case_insensitive: bool = Field(
        default=False,
        description="Use case-insensitive comparison (toLower)"
    )

    @field_validator('source_alias')
    @classmethod
    def validate_alias(cls, v: str) -> str:
        return validate_identifier(v, 'alias', MAX_ALIAS_LENGTH)

    @field_validator('property')
    @classmethod
    def validate_property(cls, v: str) -> str:
        return validate_identifier(v, 'property', MAX_PROPERTY_NAME_LENGTH)

    @field_validator('value')
    @classmethod
    def validate_value(cls, v: Any) -> Any:
        if v is None:
            return v
        if isinstance(v, str):
            return validate_string_value(v, 'value')
        if isinstance(v, list):
            if len(v) > MAX_LIST_ITEMS:
                raise ValueError(f"List exceeds maximum of {MAX_LIST_ITEMS} items")
            return [
                validate_string_value(item, 'value') if isinstance(item, str) else item
                for item in v
            ]
        return v

    @model_validator(mode='after')
    def validate_operator_value_compatibility(self) -> 'FilterCondition':
        """Ensure operator and value are compatible."""
        if self.operator in (FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL):
            if self.value is not None:
                raise ValueError(f"Operator {self.operator} should not have a value")
        elif self.operator in (FilterOperator.IN, FilterOperator.NOT_IN):
            if not isinstance(self.value, list):
                raise ValueError(f"Operator {self.operator} requires a list value")
        elif self.value is None:
            raise ValueError(f"Operator {self.operator} requires a value")
        return self


class OrderSpec(BaseModel):
    """
    Ordering specification for results.

    Example:
        {"field": "complexity", "direction": "desc"}
        → Compiles to: ORDER BY complexity DESC
    """
    model_config = ConfigDict(frozen=True, extra='forbid')

    field: str = Field(
        ...,
        description="Output field to sort by (must match a projection output_name)",
        min_length=1,
        max_length=MAX_PROPERTY_NAME_LENGTH
    )
    direction: SortOrder = Field(
        default=SortOrder.ASC,
        description="Sort direction"
    )

    @field_validator('field')
    @classmethod
    def validate_field(cls, v: str) -> str:
        return validate_identifier(v, 'field', MAX_PROPERTY_NAME_LENGTH)


class OutputFormat(BaseModel):
    """
    Specifies how to format and present results.

    This is metadata for post-processing, not Cypher generation.
    """
    model_config = ConfigDict(frozen=True, extra='forbid')

    type: OutputFormatType = Field(
        default=OutputFormatType.TABLE,
        description="Output format type"
    )
    group_by: Optional[List[str]] = Field(
        default=None,
        description="Fields to group by (output_names)"
    )
    include_nulls: bool = Field(
        default=False,
        description="Include results with null values"
    )
    flatten_nested: bool = Field(
        default=True,
        description="Flatten nested structures in output"
    )

    @field_validator('group_by')
    @classmethod
    def validate_group_by(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            for field in v:
                validate_identifier(field, 'group_by field', MAX_PROPERTY_NAME_LENGTH)
        return v


class QueryIR(BaseModel):
    """
    Intermediate Representation for a graph query.

    This is the core data structure that captures query intent in a
    structured, validatable format. It sits between natural language
    understanding and Cypher generation.

    Workflow:
        1. IRPlannerAgent generates QueryIR from natural language
        2. IRValidator validates against schema and domain rules
        3. CypherCompiler compiles validated IR to Cypher

    Example IR for "Find methods with complexity > 2 in HelloWorldApp":
        {
            "intent": "find",
            "intent_subtype": "find_by_property",
            "description": "Find methods with high cyclomatic complexity",
            "targets": [
                {"node_label": "Project", "alias": "p"},
                {"node_label": "Function", "alias": "fn"}
            ],
            "traversal": {
                "steps": [
                    {"from_alias": "p", "relationship": "CONTAINS", ...},
                    {"from_alias": "f", "relationship": "CONTAINS", ...}
                ]
            },
            "filters": [
                {"source_alias": "p", "property": "name", "operator": "eq", "value": "HelloWorldApp"},
                {"source_alias": "fn", "property": "cyclomatic_complexity", "operator": "gt", "value": 2}
            ],
            "projections": [
                {"source_alias": "fn", "property": "name", "output_name": "method_name"},
                {"source_alias": "fn", "property": "cyclomatic_complexity", "output_name": "complexity"}
            ],
            "ordering": {"field": "complexity", "direction": "desc"}
        }

    Security Notes:
        - All identifiers validated against injection patterns
        - Maximum limits on all collections prevent resource exhaustion
        - Frozen model prevents mutation after validation
    """
    model_config = ConfigDict(frozen=True, extra='forbid')

    # Query identification
    intent: QueryIntent = Field(
        ...,
        description="High-level query intent"
    )
    intent_subtype: Optional[str] = Field(
        default=None,
        description="Specific intent subtype for domain rule validation",
        max_length=64
    )
    description: str = Field(
        default="",
        description="Human-readable description of what this query does",
        max_length=500
    )

    # Core query structure
    targets: List[TargetEntity] = Field(
        ...,
        description="Nodes to query (at least one required)",
        min_length=1,
        max_length=MAX_TARGETS
    )
    traversal: Optional[TraversalPath] = Field(
        default=None,
        description="Path through relationships (optional for single-node queries)"
    )

    # Filtering and projection
    filters: List[FilterCondition] = Field(
        default_factory=list,
        description="WHERE conditions",
        max_length=MAX_FILTERS
    )
    projections: List[Projection] = Field(
        ...,
        description="RETURN clause (what to output)",
        min_length=1,
        max_length=MAX_PROJECTIONS
    )

    # Ordering and limits
    ordering: Optional[OrderSpec] = Field(
        default=None,
        description="ORDER BY specification"
    )
    limit: Optional[int] = Field(
        default=None,
        description="Maximum results to return",
        ge=1,
        le=10000
    )
    skip: Optional[int] = Field(
        default=None,
        description="Number of results to skip (pagination)",
        ge=0,
        le=100000
    )

    # Output formatting
    output_format: OutputFormat = Field(
        default_factory=OutputFormat,
        description="How to format results"
    )

    # Metadata
    original_query: Optional[str] = Field(
        default=None,
        description="Original natural language query (for tracing)",
        max_length=2000
    )

    @field_validator('intent_subtype')
    @classmethod
    def validate_intent_subtype(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            # Allow underscores and alphanumeric for subtypes
            if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', v):
                raise ValueError(f"Invalid intent_subtype format: '{v}'")
        return v

    @model_validator(mode='after')
    def validate_alias_consistency(self) -> 'QueryIR':
        """
        Ensure all aliases are defined before use.

        Security: Prevents reference to undefined aliases which could
        lead to unexpected query behavior.
        """
        defined_aliases: set = set()

        # Collect aliases from targets
        for target in self.targets:
            if target.alias in defined_aliases:
                raise ValueError(f"Duplicate alias: '{target.alias}'")
            defined_aliases.add(target.alias)

        # Validate and collect traversal aliases
        if self.traversal:
            for step in self.traversal.steps:
                if step.from_alias not in defined_aliases:
                    raise ValueError(
                        f"Traversal references undefined alias: '{step.from_alias}'"
                    )
                if step.to_alias in defined_aliases:
                    raise ValueError(f"Duplicate alias in traversal: '{step.to_alias}'")
                defined_aliases.add(step.to_alias)
                if step.relationship_alias:
                    if step.relationship_alias in defined_aliases:
                        raise ValueError(
                            f"Duplicate relationship alias: '{step.relationship_alias}'"
                        )
                    defined_aliases.add(step.relationship_alias)

        # Validate filter aliases
        for f in self.filters:
            if f.source_alias not in defined_aliases:
                raise ValueError(f"Filter references undefined alias: '{f.source_alias}'")

        # Validate projection aliases
        for p in self.projections:
            if p.source_alias not in defined_aliases:
                raise ValueError(
                    f"Projection references undefined alias: '{p.source_alias}'"
                )

        # Validate ordering field matches a projection
        if self.ordering:
            output_names = {p.output_name for p in self.projections}
            if self.ordering.field not in output_names:
                raise ValueError(
                    f"ORDER BY field '{self.ordering.field}' not in projections: "
                    f"{output_names}"
                )

        return self

    def get_all_aliases(self) -> Dict[str, str]:
        """
        Get mapping of alias -> node_label for all defined aliases.

        Returns:
            Dict mapping alias names to their node labels
        """
        aliases = {t.alias: t.node_label for t in self.targets}
        if self.traversal:
            for step in self.traversal.steps:
                aliases[step.to_alias] = step.to_label
        return aliases


# =============================================================================
# VALIDATION RESULT MODELS
# =============================================================================

class ValidationError(BaseModel):
    """A single validation error."""
    model_config = ConfigDict(frozen=True)

    layer: Literal["syntax", "schema", "semantic"] = Field(
        ...,
        description="Which validation layer caught this error"
    )
    code: str = Field(
        ...,
        description="Error code for programmatic handling"
    )
    message: str = Field(
        ...,
        description="Human-readable error message"
    )
    field_path: Optional[str] = Field(
        default=None,
        description="Path to the problematic field (e.g., 'filters[0].property')"
    )
    suggestion: Optional[str] = Field(
        default=None,
        description="Suggested fix"
    )


class ValidationResult(BaseModel):
    """Result of IR validation."""
    model_config = ConfigDict(frozen=True)

    valid: bool = Field(..., description="Whether IR passed validation")
    errors: List[ValidationError] = Field(
        default_factory=list,
        description="Validation errors (empty if valid)"
    )
    warnings: List[ValidationError] = Field(
        default_factory=list,
        description="Non-fatal warnings"
    )

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def error_messages(self) -> List[str]:
        return [e.message for e in self.errors]

    def to_feedback(self) -> str:
        """Convert validation result to feedback string for LLM."""
        if self.valid:
            return "IR is valid."

        lines = ["IR validation failed:"]
        for error in self.errors:
            lines.append(f"- [{error.layer}] {error.message}")
            if error.suggestion:
                lines.append(f"  Suggestion: {error.suggestion}")

        if self.warnings:
            lines.append("\nWarnings:")
            for warning in self.warnings:
                lines.append(f"- {warning.message}")

        return "\n".join(lines)


__all__ = [
    # Enums
    'QueryIntent',
    'FilterOperator',
    'AggregationType',
    'RelationshipDirection',
    'OutputFormatType',
    'SortOrder',
    # Core models
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
    # Constants (for testing/extension)
    'MAX_TRAVERSAL_DEPTH',
    'MAX_FILTERS',
    'MAX_PROJECTIONS',
]
