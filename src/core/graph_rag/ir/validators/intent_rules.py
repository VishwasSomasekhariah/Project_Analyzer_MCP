"""
.. deprecated::
    Not used by any active MCP tools. Part of the deprecated IR pipeline.

Intent Rule Engine - Schema-Introspective Semantic Validation.

This module provides OPTIONAL semantic validation that:
1. Uses schema introspection as the primary validation mechanism
2. Falls back to dynamic validation when rules don't exist
3. Loads domain rules from YAML configuration files
4. Logs unmatched intent_subtypes for metrics and improvement

Key Principles:
- Rules are CHECKS, not BLOCKERS
- Schema introspection is FIRST-CLASS
- Unknown intents still validate via schema (Layer 2)
- Rules enhance validation, they don't replace it

Security Considerations:
- Rules loaded from YAML are validated before use
- No arbitrary code execution from config files
- All semantic checks are statically defined
"""

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from ..models import (
    QueryIR,
    QueryIntent,
    ValidationError,
    FilterOperator,
    AggregationType,
)
from ..context import IRContext, SchemaInfo


logger = logging.getLogger(__name__)


# =============================================================================
# INTENT RULE DEFINITION
# =============================================================================

class IntentRule(BaseModel):
    """
    OPTIONAL semantic validation rule for a specific intent.

    Rules are CHECKS - they provide additional validation when matched,
    but unmatched intents still validate via schema introspection.

    Rules can be:
    - Built-in (defined in code)
    - Loaded from YAML configuration files
    - Registered at runtime
    """
    model_config = ConfigDict(frozen=True)

    intent: QueryIntent = Field(
        ...,
        description="Query intent this rule applies to"
    )
    intent_subtype: str = Field(
        ...,
        description="Specific subtype identifier"
    )
    description: str = Field(
        default="",
        description="Human-readable description"
    )

    # Structural checks (optional - checked against actual IR)
    check_has_node_labels: FrozenSet[str] = Field(
        default_factory=frozenset,
        description="Node labels that SHOULD be present (warns if missing)"
    )
    check_has_properties: FrozenSet[str] = Field(
        default_factory=frozenset,
        description="Properties that SHOULD be projected (warns if missing)"
    )
    check_has_relationships: FrozenSet[str] = Field(
        default_factory=frozenset,
        description="Relationships that SHOULD be traversed (warns if missing)"
    )
    check_has_filters_on: FrozenSet[str] = Field(
        default_factory=frozenset,
        description="Properties that SHOULD be filtered (warns if missing)"
    )

    # Semantic check function name (if more complex logic needed)
    semantic_check: Optional[str] = Field(
        default=None,
        description="Name of semantic check method to call"
    )

    # Is this rule a blocker or just a warning?
    is_blocking: bool = Field(
        default=False,
        description="If True, validation failures are errors; if False, warnings"
    )


# =============================================================================
# INTENT RULE ENGINE
# =============================================================================

# Type alias for semantic check functions
SemanticCheckFn = Callable[[QueryIR, IRContext, IntentRule, SchemaInfo], List[ValidationError]]


class IntentRuleEngine:
    """
    Schema-Introspective Intent Rule Engine.

    Philosophy:
    - Schema introspection is FIRST-CLASS
    - Rules are OPTIONAL enhancements
    - Unknown intents still validate via schema
    - Logs unmatched intents for metrics

    Usage:
        engine = IntentRuleEngine(schema_info)

        # Validate with optional rules
        errors = engine.validate(ir, ctx)

        # Load domain-specific rules
        engine.load_rules_from_yaml("my_domain_rules.yaml")

        # Get metrics on unmatched intents
        unmatched = engine.get_unmatched_intent_stats()
    """

    # Decision point types for cyclomatic complexity
    # These can be overridden via YAML configuration
    DEFAULT_DECISION_POINT_TYPES: FrozenSet[str] = frozenset({
        "if", "for", "foreach", "while", "switch", "case",
        "ternary", "catch", "conditional", "loop"
    })

    def __init__(
        self,
        schema: Optional[SchemaInfo] = None,
        rules_yaml_path: Optional[str] = None,
        strict_mode: bool = False
    ):
        """
        Initialize the intent rule engine.

        Args:
            schema: Schema info for introspection (can be set later)
            rules_yaml_path: Optional path to YAML rules file
            strict_mode: If True, rule failures are errors; if False, warnings
        """
        self._schema = schema
        self._strict_mode = strict_mode
        self._rules: Dict[str, IntentRule] = {}
        self._semantic_checks: Dict[str, SemanticCheckFn] = {}

        # Metrics: track unmatched intent_subtypes
        self._unmatched_intents: Counter = Counter()

        # Decision point types (configurable)
        self._decision_point_types = self.DEFAULT_DECISION_POINT_TYPES

        # Register built-in semantic checks
        self._register_builtin_checks()

        # Load rules from YAML if provided
        if rules_yaml_path:
            self.load_rules_from_yaml(rules_yaml_path)

        self._logger = logger

    def set_schema(self, schema: SchemaInfo) -> None:
        """Set or update the schema for introspection."""
        self._schema = schema

    def _register_builtin_checks(self) -> None:
        """Register built-in semantic check functions."""
        self._semantic_checks["validate_cyclomatic_complexity"] = self._validate_cyclomatic_complexity
        self._semantic_checks["validate_decision_point_filter"] = self._validate_decision_point_filter

    # =========================================================================
    # RULE MANAGEMENT
    # =========================================================================

    def register_rule(self, rule: IntentRule) -> None:
        """Register a rule at runtime."""
        self._rules[rule.intent_subtype] = rule
        self._logger.debug(f"Registered intent rule: {rule.intent_subtype}")

    def load_rules_from_yaml(self, path: str) -> int:
        """
        Load rules from a YAML configuration file.

        YAML Format:
            decision_point_types:  # Optional override
              - if
              - for
              - while

            rules:
              compute_cyclomatic_complexity:
                intent: compute_metric
                description: "Complexity must use cyclomatic_complexity property"
                check_has_properties:
                  - cyclomatic_complexity
                semantic_check: validate_cyclomatic_complexity
                is_blocking: false

        Returns:
            Number of rules loaded
        """
        try:
            import yaml
            with open(path, 'r') as f:
                data = yaml.safe_load(f)

            # Override decision point types if specified
            if 'decision_point_types' in data:
                self._decision_point_types = frozenset(data['decision_point_types'])
                self._logger.info(f"Updated decision point types: {self._decision_point_types}")

            # Load rules
            rules_loaded = 0
            for subtype, rule_data in data.get('rules', {}).items():
                try:
                    # Convert intent string to enum
                    intent_str = rule_data.get('intent', 'find')
                    rule_data['intent'] = QueryIntent(intent_str)
                    rule_data['intent_subtype'] = subtype

                    # Convert lists to frozensets
                    for key in ['check_has_node_labels', 'check_has_properties',
                                'check_has_relationships', 'check_has_filters_on']:
                        if key in rule_data and isinstance(rule_data[key], list):
                            rule_data[key] = frozenset(rule_data[key])

                    rule = IntentRule(**rule_data)
                    self._rules[subtype] = rule
                    rules_loaded += 1
                except Exception as e:
                    self._logger.warning(f"Failed to load rule '{subtype}': {e}")

            self._logger.info(f"Loaded {rules_loaded} rules from {path}")
            return rules_loaded

        except FileNotFoundError:
            self._logger.warning(f"Rules file not found: {path}")
            return 0
        except Exception as e:
            self._logger.error(f"Failed to load rules from {path}: {e}")
            return 0

    def load_rules_from_json(self, path: str) -> int:
        """Load rules from a JSON configuration file."""
        try:
            with open(path, 'r') as f:
                data = json.load(f)

            # Same format as YAML
            rules_loaded = 0
            for subtype, rule_data in data.get('rules', {}).items():
                try:
                    rule_data['intent'] = QueryIntent(rule_data.get('intent', 'find'))
                    rule_data['intent_subtype'] = subtype
                    for key in ['check_has_node_labels', 'check_has_properties',
                                'check_has_relationships', 'check_has_filters_on']:
                        if key in rule_data and isinstance(rule_data[key], list):
                            rule_data[key] = frozenset(rule_data[key])
                    self._rules[subtype] = IntentRule(**rule_data)
                    rules_loaded += 1
                except Exception as e:
                    self._logger.warning(f"Failed to load rule '{subtype}': {e}")

            return rules_loaded
        except Exception as e:
            self._logger.error(f"Failed to load rules from {path}: {e}")
            return 0

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def validate(self, ir: QueryIR, ctx: IRContext) -> List[ValidationError]:
        """
        Validate IR against intent rules.

        Process:
        1. If intent_subtype has a matching rule → apply rule checks
        2. If no matching rule → log for metrics, validate via schema only
        3. Run semantic checks if defined in rule

        Returns:
            List of ValidationErrors (may be warnings if not blocking)
        """
        errors: List[ValidationError] = []

        # If no intent_subtype, skip rule-based validation
        if not ir.intent_subtype:
            return errors

        # Look up rule
        rule = self._rules.get(ir.intent_subtype)

        if not rule:
            # No rule for this subtype - log for metrics
            self._unmatched_intents[ir.intent_subtype] += 1
            self._logger.debug(
                f"No rule for intent_subtype '{ir.intent_subtype}' - "
                f"falling back to schema validation only"
            )
            return errors

        # Apply rule checks
        is_blocking = rule.is_blocking or self._strict_mode

        # Check node labels
        if rule.check_has_node_labels:
            errors.extend(self._check_node_labels(ir, ctx, rule, is_blocking))

        # Check properties
        if rule.check_has_properties:
            errors.extend(self._check_properties(ir, ctx, rule, is_blocking))

        # Check relationships
        if rule.check_has_relationships:
            errors.extend(self._check_relationships(ir, rule, is_blocking))

        # Check filters
        if rule.check_has_filters_on:
            errors.extend(self._check_filters(ir, rule, is_blocking))

        # Run semantic check if defined
        if rule.semantic_check:
            check_fn = self._semantic_checks.get(rule.semantic_check)
            if check_fn and self._schema:
                errors.extend(check_fn(ir, ctx, rule, self._schema))
            elif not check_fn:
                self._logger.warning(
                    f"Semantic check '{rule.semantic_check}' not found "
                    f"for rule '{rule.intent_subtype}'"
                )

        return errors

    def _check_node_labels(
        self, ir: QueryIR, ctx: IRContext, rule: IntentRule, is_blocking: bool
    ) -> List[ValidationError]:
        """Check if required node labels are present."""
        errors: List[ValidationError] = []
        ir_labels = set(ctx.alias_to_label.values())

        for label in rule.check_has_node_labels:
            if label not in ir_labels:
                # Check if schema has this label (introspection)
                if self._schema and not self._schema.has_node_label(label):
                    # Label doesn't exist in schema - this might be a stale rule
                    self._logger.warning(
                        f"Rule '{rule.intent_subtype}' references non-existent "
                        f"label '{label}' - skipping check"
                    )
                    continue

                errors.append(ValidationError(
                    layer="semantic",
                    code="SUGGESTED_NODE_LABEL",
                    message=(
                        f"Intent '{rule.intent_subtype}' typically queries '{label}' nodes. "
                        f"Consider including {label} in your query."
                    ),
                    field_path="targets",
                    suggestion=f"Add target or traversal for '{label}' nodes"
                ))

        # Convert to warnings if not blocking
        if not is_blocking:
            for e in errors:
                e = ValidationError(
                    layer=e.layer,
                    code=f"WARNING_{e.code}",
                    message=f"[Warning] {e.message}",
                    field_path=e.field_path,
                    suggestion=e.suggestion
                )

        return errors

    def _check_properties(
        self, ir: QueryIR, ctx: IRContext, rule: IntentRule, is_blocking: bool
    ) -> List[ValidationError]:
        """Check if required properties are projected."""
        errors: List[ValidationError] = []
        ir_properties = {p.property for p in ir.projections if p.property}

        for prop in rule.check_has_properties:
            if prop not in ir_properties:
                errors.append(ValidationError(
                    layer="semantic",
                    code="SUGGESTED_PROPERTY",
                    message=(
                        f"Intent '{rule.intent_subtype}' typically projects '{prop}'. "
                        f"Consider including it in projections."
                    ),
                    field_path="projections",
                    suggestion=f"Add projection for '{prop}' property"
                ))

        return errors

    def _check_relationships(
        self, ir: QueryIR, rule: IntentRule, is_blocking: bool
    ) -> List[ValidationError]:
        """Check if required relationships are in traversal."""
        errors: List[ValidationError] = []

        ir_rels: Set[str] = set()
        if ir.traversal:
            ir_rels = {step.relationship for step in ir.traversal.steps}

        for rel in rule.check_has_relationships:
            if rel not in ir_rels:
                # Check if schema has this relationship
                if self._schema and not self._schema.has_relationship_type(rel):
                    self._logger.warning(
                        f"Rule '{rule.intent_subtype}' references non-existent "
                        f"relationship '{rel}' - skipping check"
                    )
                    continue

                errors.append(ValidationError(
                    layer="semantic",
                    code="SUGGESTED_RELATIONSHIP",
                    message=(
                        f"Intent '{rule.intent_subtype}' typically uses '{rel}' relationship. "
                        f"Consider adding traversal with {rel}."
                    ),
                    field_path="traversal",
                    suggestion=f"Add traversal step using '{rel}' relationship"
                ))

        return errors

    def _check_filters(
        self, ir: QueryIR, rule: IntentRule, is_blocking: bool
    ) -> List[ValidationError]:
        """Check if required filter properties are present."""
        errors: List[ValidationError] = []
        ir_filter_props = {f.property for f in ir.filters}

        for prop in rule.check_has_filters_on:
            if prop not in ir_filter_props:
                errors.append(ValidationError(
                    layer="semantic",
                    code="SUGGESTED_FILTER",
                    message=(
                        f"Intent '{rule.intent_subtype}' typically filters on '{prop}'. "
                        f"Consider adding a filter condition."
                    ),
                    field_path="filters",
                    suggestion=f"Add filter on '{prop}' property"
                ))

        return errors

    # =========================================================================
    # BUILT-IN SEMANTIC CHECKS
    # =========================================================================

    def _validate_cyclomatic_complexity(
        self, ir: QueryIR, ctx: IRContext, rule: IntentRule, schema: SchemaInfo
    ) -> List[ValidationError]:
        """
        Validate cyclomatic complexity query using schema introspection.

        Checks:
        1. If projecting 'cyclomatic_complexity' property → valid
        2. If counting Statements, must filter to decision point types
        """
        errors: List[ValidationError] = []

        # Check if using pre-computed property
        complexity_props = {'cyclomatic_complexity', 'complexity', 'cc'}
        uses_precomputed = any(
            p.property in complexity_props for p in ir.projections
        )

        if uses_precomputed:
            return []  # Valid approach

        # Check if counting statements without proper filter
        counts_statements = any(
            p.aggregation in (AggregationType.COUNT, AggregationType.COUNT_DISTINCT) and
            ctx.get_label_for_alias(p.source_alias) in ('Statement', 'Stmt')
            for p in ir.projections
        )

        if counts_statements:
            # Check for decision point filter
            has_decision_filter = False
            for f in ir.filters:
                if f.property in ('statement_type', 'type', 'kind') and f.operator == FilterOperator.IN:
                    if isinstance(f.value, list):
                        filter_values = set(str(v).lower() for v in f.value)
                        if filter_values.issubset(self._decision_point_types):
                            has_decision_filter = True
                            break

            if not has_decision_filter:
                errors.append(ValidationError(
                    layer="semantic",
                    code="INVALID_COMPLEXITY_CALCULATION",
                    message=(
                        "Cyclomatic complexity should count only decision points "
                        "(if, for, while, switch), not all statements. "
                        "Use the 'cyclomatic_complexity' property directly, "
                        "or filter statements to decision point types."
                    ),
                    field_path="filters",
                    suggestion=(
                        "Use: fn.cyclomatic_complexity property on Function nodes, "
                        f"OR filter statement_type IN {list(self._decision_point_types)[:5]}..."
                    )
                ))

        return errors

    def _validate_decision_point_filter(
        self, ir: QueryIR, ctx: IRContext, rule: IntentRule, schema: SchemaInfo
    ) -> List[ValidationError]:
        """Validate decision point filter values."""
        errors: List[ValidationError] = []

        for i, f in enumerate(ir.filters):
            if f.property in ('statement_type', 'type', 'kind') and f.operator == FilterOperator.IN:
                if isinstance(f.value, list):
                    filter_values = set(str(v).lower() for v in f.value)
                    invalid_types = filter_values - self._decision_point_types

                    if invalid_types:
                        errors.append(ValidationError(
                            layer="semantic",
                            code="INVALID_DECISION_POINT_TYPES",
                            message=(
                                f"Possibly invalid decision point types: {invalid_types}. "
                                f"Expected types like: {sorted(self._decision_point_types)[:5]}..."
                            ),
                            field_path=f"filters[{i}].value",
                            suggestion=f"Use decision point types: {sorted(self._decision_point_types)}"
                        ))

        return errors

    # =========================================================================
    # METRICS AND INTROSPECTION
    # =========================================================================

    def get_unmatched_intent_stats(self) -> Dict[str, int]:
        """
        Get statistics on unmatched intent_subtypes.

        Use this to identify which intents need rules added.
        """
        return dict(self._unmatched_intents)

    def get_available_rules(self) -> List[str]:
        """Get list of available intent_subtype rules."""
        return list(self._rules.keys())

    def get_rule_description(self, intent_subtype: str) -> Optional[str]:
        """Get description for a specific rule."""
        rule = self._rules.get(intent_subtype)
        return rule.description if rule else None

    def get_decision_point_types(self) -> FrozenSet[str]:
        """Get the configured decision point types."""
        return self._decision_point_types

    def reset_metrics(self) -> None:
        """Reset the unmatched intent counter."""
        self._unmatched_intents.clear()


__all__ = ['IntentRule', 'IntentRuleEngine']
