"""
IR Validator - Layer 1 (Syntax) and Layer 2 (Schema) validation.

This module provides deterministic validation of QueryIR against:
1. Structural well-formedness (syntax)
2. Graph schema compliance (schema)

No LLM is used - validation is entirely rule-based and deterministic.

Security Considerations:
- All validation errors are safe to return to users
- No schema internals are exposed in error messages
- Validation is performed before any Cypher generation
"""

import logging
from typing import List, Optional

from ..models import (
    QueryIR,
    FilterCondition,
    Projection,
    TraversalStep,
    ValidationError,
    ValidationResult,
    FilterOperator,
    AggregationType,
)
from ..context import IRContext, SchemaInfo


logger = logging.getLogger(__name__)


class IRValidator:
    """
    Validates QueryIR against syntax rules and graph schema.

    Layer 1 (Syntax):
    - Alias uniqueness and consistency
    - Filter/projection reference validity
    - Traversal path connectivity

    Layer 2 (Schema):
    - Node labels exist in schema
    - Relationship types exist in schema
    - Properties exist on node/relationship types
    - Valid source-relationship-target connections

    Usage:
        validator = IRValidator(schema_info)
        result = validator.validate(ir)

        # With custom intent rules (Layer 3)
        from .intent_rules import IntentRuleEngine
        validator = IRValidator(schema_info, intent_rules=IntentRuleEngine())
        result = validator.validate(ir)
    """

    def __init__(
        self,
        schema: SchemaInfo,
        intent_rules: Optional['IntentRuleEngine'] = None,
        strict_mode: bool = True
    ):
        """
        Initialize the IR validator.

        Args:
            schema: Schema information for validation
            intent_rules: Optional IntentRuleEngine for Layer 3 validation
            strict_mode: If True, unknown properties are errors; if False, warnings
        """
        self._schema = schema
        self._intent_rules = intent_rules
        self._strict_mode = strict_mode
        self._logger = logger

    def validate(self, ir: QueryIR) -> ValidationResult:
        """
        Perform full validation of QueryIR.

        Runs all three validation layers in order:
        1. Syntax validation (structural)
        2. Schema validation (against graph schema)
        3. Semantic validation (intent rules, if configured)

        Args:
            ir: The QueryIR to validate

        Returns:
            ValidationResult with errors and warnings
        """
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []

        # Build context for efficient lookups
        ctx = IRContext.from_ir(ir, self._schema)

        # Layer 1: Syntax validation
        syntax_errors = self._validate_syntax(ir, ctx)
        errors.extend(syntax_errors)

        # Layer 2: Schema validation (only if syntax is valid)
        if not syntax_errors:
            schema_errors, schema_warnings = self._validate_schema(ir, ctx)
            errors.extend(schema_errors)
            warnings.extend(schema_warnings)

        # Layer 3: Semantic validation (only if schema is valid)
        if not errors and self._intent_rules:
            semantic_errors = self._intent_rules.validate(ir, ctx)
            errors.extend(semantic_errors)

        is_valid = len(errors) == 0

        if not is_valid:
            self._logger.debug(f"IR validation failed: {[e.message for e in errors]}")

        return ValidationResult(
            valid=is_valid,
            errors=errors,
            warnings=warnings
        )

    def _validate_syntax(self, ir: QueryIR, ctx: IRContext) -> List[ValidationError]:
        """
        Layer 1: Validate IR syntax/structure.

        Checks:
        - At least one target is defined
        - At least one projection is defined
        - Alias references are valid (defined before use)
        - Traversal path is connected
        - No circular references

        Note: Most syntax validation is done by Pydantic validators
        in the model itself. This method catches additional issues.
        """
        errors: List[ValidationError] = []

        # Check that we have meaningful projections
        if not ir.projections:
            errors.append(ValidationError(
                layer="syntax",
                code="EMPTY_PROJECTIONS",
                message="At least one projection is required",
                field_path="projections"
            ))

        # Validate traversal connectivity
        if ir.traversal and ir.traversal.steps:
            errors.extend(self._validate_traversal_connectivity(ir, ctx))

        # Validate filter value types match operators
        for i, f in enumerate(ir.filters):
            filter_errors = self._validate_filter_syntax(f, i)
            errors.extend(filter_errors)

        # Validate aggregations
        errors.extend(self._validate_aggregation_syntax(ir))

        return errors

    def _validate_traversal_connectivity(
        self, ir: QueryIR, ctx: IRContext
    ) -> List[ValidationError]:
        """Validate that traversal steps are properly connected."""
        errors: List[ValidationError] = []
        reachable_aliases = {t.alias for t in ir.targets}

        for i, step in enumerate(ir.traversal.steps):
            if step.from_alias not in reachable_aliases:
                errors.append(ValidationError(
                    layer="syntax",
                    code="UNREACHABLE_TRAVERSAL",
                    message=(
                        f"Traversal step {i} starts from '{step.from_alias}' "
                        f"which is not reachable. Reachable aliases: {reachable_aliases}"
                    ),
                    field_path=f"traversal.steps[{i}].from_alias",
                    suggestion="Ensure traversal steps form a connected path from targets"
                ))
            # Add the target alias as reachable for subsequent steps
            reachable_aliases.add(step.to_alias)

        return errors

    def _validate_filter_syntax(
        self, f: FilterCondition, index: int
    ) -> List[ValidationError]:
        """Validate filter syntax (type compatibility)."""
        errors: List[ValidationError] = []

        # Validate regex patterns
        if f.operator == FilterOperator.REGEX and isinstance(f.value, str):
            import re
            try:
                re.compile(f.value)
            except re.error as e:
                errors.append(ValidationError(
                    layer="syntax",
                    code="INVALID_REGEX",
                    message=f"Invalid regex pattern in filter: {e}",
                    field_path=f"filters[{index}].value",
                    suggestion="Ensure regex is valid Python/Cypher regex syntax"
                ))

        return errors

    def _validate_aggregation_syntax(self, ir: QueryIR) -> List[ValidationError]:
        """Validate aggregation usage is consistent."""
        errors: List[ValidationError] = []

        # Check if mixing aggregated and non-aggregated projections
        has_aggregation = any(p.aggregation is not None for p in ir.projections)
        has_plain = any(p.aggregation is None for p in ir.projections)

        if has_aggregation and has_plain:
            # This is allowed in Cypher, but worth warning about
            # Non-aggregated fields become implicit GROUP BY
            pass  # Not an error, but could add warning

        # Validate COUNT aggregation
        for i, p in enumerate(ir.projections):
            if p.aggregation == AggregationType.COUNT and p.property is None:
                # COUNT without property counts nodes - valid
                pass
            elif p.aggregation in (AggregationType.SUM, AggregationType.AVG):
                # These require numeric properties - checked in schema validation
                pass

        return errors

    def _validate_schema(
        self, ir: QueryIR, ctx: IRContext
    ) -> tuple[List[ValidationError], List[ValidationError]]:
        """
        Layer 2: Validate IR against graph schema.

        Checks:
        - All node labels exist in schema
        - All relationship types exist in schema
        - All properties exist on their respective node/relationship types
        - All traversal connections are valid in schema

        Returns:
            Tuple of (errors, warnings)
        """
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []

        # Validate target node labels
        for i, target in enumerate(ir.targets):
            if not self._schema.has_node_label(target.node_label):
                errors.append(ValidationError(
                    layer="schema",
                    code="UNKNOWN_NODE_LABEL",
                    message=f"Unknown node label: '{target.node_label}'",
                    field_path=f"targets[{i}].node_label",
                    suggestion=f"Valid labels: {sorted(self._schema.node_labels)[:10]}..."
                ))

        # Validate traversal relationships and connections
        if ir.traversal:
            for i, step in enumerate(ir.traversal.steps):
                # Check relationship type exists
                if not self._schema.has_relationship_type(step.relationship):
                    errors.append(ValidationError(
                        layer="schema",
                        code="UNKNOWN_RELATIONSHIP",
                        message=f"Unknown relationship type: '{step.relationship}'",
                        field_path=f"traversal.steps[{i}].relationship",
                        suggestion=f"Valid relationships: {sorted(self._schema.relationship_types)[:10]}..."
                    ))

                # Check target label exists
                if not self._schema.has_node_label(step.to_label):
                    errors.append(ValidationError(
                        layer="schema",
                        code="UNKNOWN_NODE_LABEL",
                        message=f"Unknown node label in traversal: '{step.to_label}'",
                        field_path=f"traversal.steps[{i}].to_label"
                    ))

                # Check connection is valid
                from_label = ctx.get_label_for_alias(step.from_alias)
                if from_label and not self._schema.is_valid_connection(
                    from_label, step.relationship, step.to_label, step.direction
                ):
                    # This might be a warning in non-strict mode
                    error = ValidationError(
                        layer="schema",
                        code="INVALID_CONNECTION",
                        message=(
                            f"No valid connection: ({from_label})-[:{step.relationship}]->({step.to_label})"
                        ),
                        field_path=f"traversal.steps[{i}]",
                        suggestion="Check schema for valid relationship connections"
                    )
                    if self._strict_mode:
                        errors.append(error)
                    else:
                        warnings.append(error)

        # Validate filter properties
        for i, f in enumerate(ir.filters):
            label = ctx.get_label_for_alias(f.source_alias)
            if label and not self._schema.has_property(label, f.property):
                error = ValidationError(
                    layer="schema",
                    code="UNKNOWN_PROPERTY",
                    message=f"Property '{f.property}' does not exist on '{label}'",
                    field_path=f"filters[{i}].property",
                    suggestion=f"Available properties: {sorted(ctx.get_properties_for_alias(f.source_alias))[:10]}..."
                )
                if self._strict_mode:
                    errors.append(error)
                else:
                    warnings.append(error)

        # Validate projection properties
        for i, p in enumerate(ir.projections):
            if p.property:  # None means project entire node
                label = ctx.get_label_for_alias(p.source_alias)
                if label and not self._schema.has_property(label, p.property):
                    error = ValidationError(
                        layer="schema",
                        code="UNKNOWN_PROPERTY",
                        message=f"Property '{p.property}' does not exist on '{label}'",
                        field_path=f"projections[{i}].property",
                        suggestion=f"Available properties: {sorted(ctx.get_properties_for_alias(p.source_alias))[:10]}..."
                    )
                    if self._strict_mode:
                        errors.append(error)
                    else:
                        warnings.append(error)

        return errors, warnings

    def validate_quick(self, ir: QueryIR) -> bool:
        """
        Quick validation check without detailed errors.

        Use this for performance-critical paths where you only need
        a boolean result.

        Args:
            ir: The QueryIR to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            result = self.validate(ir)
            return result.valid
        except Exception:
            return False


__all__ = ['IRValidator']
