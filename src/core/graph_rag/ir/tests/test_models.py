"""
Unit tests for IR models.

Tests cover:
- QueryIR construction and validation
- Security constraints (max depth, filters, injection prevention)
- Enum handling
- Edge cases
"""

import pytest
from pydantic import ValidationError

from src.core.graph_rag.ir.models import (
    QueryIR,
    QueryIntent,
    TargetEntity,
    TraversalStep,
    TraversalPath,
    Projection,
    FilterCondition,
    FilterOperator,
    AggregationType,
    RelationshipDirection,
    OrderSpec,
    SortOrder,
    OutputFormat,
    OutputFormatType,
    ValidationError as IRValidationError,
    ValidationResult,
    MAX_TRAVERSAL_DEPTH,
    MAX_FILTERS,
    MAX_PROJECTIONS,
)


class TestTargetEntity:
    """Tests for TargetEntity model."""

    def test_valid_target(self):
        """Test creating a valid target entity."""
        target = TargetEntity(node_label="Function", alias="fn")
        assert target.node_label == "Function"
        assert target.alias == "fn"

    def test_invalid_label_injection(self):
        """Test that injection attempts in label are rejected."""
        with pytest.raises(ValidationError):
            TargetEntity(node_label="Function); DROP", alias="fn")

    def test_invalid_alias_injection(self):
        """Test that injection attempts in alias are rejected."""
        with pytest.raises(ValidationError):
            TargetEntity(node_label="Function", alias="fn; DELETE")

    def test_empty_label_rejected(self):
        """Test that empty label is rejected."""
        with pytest.raises(ValidationError):
            TargetEntity(node_label="", alias="fn")


class TestTraversalStep:
    """Tests for TraversalStep model."""

    def test_valid_step(self):
        """Test creating a valid traversal step."""
        step = TraversalStep(
            from_alias="p",
            relationship="CONTAINS",
            to_label="File",
            to_alias="f",
            direction=RelationshipDirection.OUTGOING
        )
        assert step.from_alias == "p"
        assert step.relationship == "CONTAINS"
        assert step.to_label == "File"
        assert step.to_alias == "f"
        assert step.direction == RelationshipDirection.OUTGOING

    def test_optional_relationship_alias(self):
        """Test traversal step with relationship alias."""
        step = TraversalStep(
            from_alias="p",
            relationship="CONTAINS",
            to_label="File",
            to_alias="f",
            direction=RelationshipDirection.OUTGOING,
            relationship_alias="r1"
        )
        assert step.relationship_alias == "r1"

    def test_incoming_direction(self):
        """Test incoming direction."""
        step = TraversalStep(
            from_alias="fn",
            relationship="CALLS",
            to_label="Function",
            to_alias="caller",
            direction=RelationshipDirection.INCOMING
        )
        assert step.direction == RelationshipDirection.INCOMING


class TestFilterCondition:
    """Tests for FilterCondition model."""

    def test_equality_filter(self):
        """Test equality filter."""
        f = FilterCondition(
            source_alias="p",
            property="name",
            operator=FilterOperator.EQ,
            value="HelloWorldApp"
        )
        assert f.operator == FilterOperator.EQ
        assert f.value == "HelloWorldApp"

    def test_comparison_filter(self):
        """Test comparison filter."""
        f = FilterCondition(
            source_alias="fn",
            property="cyclomatic_complexity",
            operator=FilterOperator.GT,
            value=5
        )
        assert f.operator == FilterOperator.GT
        assert f.value == 5

    def test_case_insensitive_filter(self):
        """Test case insensitive filter."""
        f = FilterCondition(
            source_alias="p",
            property="name",
            operator=FilterOperator.EQ,
            value="helloworld",
            case_insensitive=True
        )
        assert f.case_insensitive is True

    def test_in_filter(self):
        """Test IN filter with list value."""
        f = FilterCondition(
            source_alias="s",
            property="statement_type",
            operator=FilterOperator.IN,
            value=["if", "for", "while"]
        )
        assert f.operator == FilterOperator.IN
        assert f.value == ["if", "for", "while"]


class TestProjection:
    """Tests for Projection model."""

    def test_simple_projection(self):
        """Test simple property projection."""
        p = Projection(
            source_alias="fn",
            property="name",
            output_name="function_name"
        )
        assert p.source_alias == "fn"
        assert p.property == "name"
        assert p.output_name == "function_name"

    def test_aggregation_projection(self):
        """Test aggregation projection."""
        p = Projection(
            source_alias="fn",
            property="name",
            output_name="count",
            aggregation=AggregationType.COUNT
        )
        assert p.aggregation == AggregationType.COUNT

    def test_distinct_projection(self):
        """Test distinct projection."""
        p = Projection(
            source_alias="fn",
            property="name",
            output_name="unique_names",
            distinct=True
        )
        assert p.distinct is True

    def test_whole_node_projection(self):
        """Test projecting entire node (no property)."""
        p = Projection(
            source_alias="fn",
            property=None,
            output_name="node"
        )
        assert p.property is None


class TestQueryIR:
    """Tests for QueryIR model."""

    def test_minimal_query(self):
        """Test minimal valid QueryIR."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        assert ir.intent == QueryIntent.FIND
        assert len(ir.targets) == 1
        assert len(ir.projections) == 1

    def test_full_query(self):
        """Test full QueryIR with all fields."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            intent_subtype="by_property",
            targets=[TargetEntity(node_label="Project", alias="p")],
            traversal=TraversalPath(steps=[
                TraversalStep(
                    from_alias="p",
                    relationship="CONTAINS",
                    to_label="File",
                    to_alias="f",
                    direction=RelationshipDirection.OUTGOING
                ),
                TraversalStep(
                    from_alias="f",
                    relationship="CONTAINS",
                    to_label="Function",
                    to_alias="fn",
                    direction=RelationshipDirection.OUTGOING
                )
            ]),
            filters=[
                FilterCondition(
                    source_alias="p",
                    property="name",
                    operator=FilterOperator.EQ,
                    value="HelloWorldApp"
                ),
                FilterCondition(
                    source_alias="fn",
                    property="cyclomatic_complexity",
                    operator=FilterOperator.GT,
                    value=5
                )
            ],
            projections=[
                Projection(source_alias="fn", property="name", output_name="function_name"),
                Projection(source_alias="fn", property="cyclomatic_complexity", output_name="complexity")
            ],
            ordering=OrderSpec(field="complexity", direction=SortOrder.DESC),
            limit=100,
            skip=0
        )
        assert ir.intent_subtype == "by_property"
        assert len(ir.traversal.steps) == 2
        assert len(ir.filters) == 2
        assert ir.ordering.direction == SortOrder.DESC
        assert ir.limit == 100

    def test_count_intent(self):
        """Test COUNT intent query."""
        ir = QueryIR(
            intent=QueryIntent.COUNT,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(
                    source_alias="fn",
                    property=None,
                    output_name="total",
                    aggregation=AggregationType.COUNT
                )
            ]
        )
        assert ir.intent == QueryIntent.COUNT

    def test_aggregate_intent(self):
        """Test AGGREGATE intent query."""
        ir = QueryIR(
            intent=QueryIntent.AGGREGATE,
            intent_subtype="cyclomatic_complexity",
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(
                    source_alias="fn",
                    property="cyclomatic_complexity",
                    output_name="avg_complexity",
                    aggregation=AggregationType.AVG
                )
            ]
        )
        assert ir.intent == QueryIntent.AGGREGATE

    def test_max_traversal_depth_enforced(self):
        """Test that max traversal depth is enforced."""
        # Create steps exceeding max depth
        steps = [
            TraversalStep(
                from_alias=f"n{i}",
                relationship="REL",
                to_label="Node",
                to_alias=f"n{i+1}",
                direction=RelationshipDirection.OUTGOING
            )
            for i in range(MAX_TRAVERSAL_DEPTH + 2)
        ]

        with pytest.raises(ValidationError):
            QueryIR(
                intent=QueryIntent.FIND,
                targets=[TargetEntity(node_label="Node", alias="n0")],
                traversal=TraversalPath(steps=steps),
                projections=[Projection(source_alias="n0", property="name", output_name="name")]
            )

    def test_max_filters_enforced(self):
        """Test that max filters is enforced."""
        filters = [
            FilterCondition(
                source_alias="fn",
                property=f"prop{i}",
                operator=FilterOperator.EQ,
                value=i
            )
            for i in range(MAX_FILTERS + 2)
        ]

        with pytest.raises(ValidationError):
            QueryIR(
                intent=QueryIntent.FIND,
                targets=[TargetEntity(node_label="Function", alias="fn")],
                filters=filters,
                projections=[Projection(source_alias="fn", property="name", output_name="name")]
            )

    def test_alias_uniqueness(self):
        """Test that aliases must be unique."""
        with pytest.raises(ValidationError):
            QueryIR(
                intent=QueryIntent.FIND,
                targets=[
                    TargetEntity(node_label="Function", alias="fn"),
                    TargetEntity(node_label="Class", alias="fn")  # Duplicate alias
                ],
                projections=[Projection(source_alias="fn", property="name", output_name="name")]
            )

    def test_filter_references_valid_alias(self):
        """Test that filter must reference valid alias."""
        with pytest.raises(ValidationError):
            QueryIR(
                intent=QueryIntent.FIND,
                targets=[TargetEntity(node_label="Function", alias="fn")],
                filters=[
                    FilterCondition(
                        source_alias="invalid_alias",  # Not defined
                        property="name",
                        operator=FilterOperator.EQ,
                        value="test"
                    )
                ],
                projections=[Projection(source_alias="fn", property="name", output_name="name")]
            )

    def test_projection_references_valid_alias(self):
        """Test that projection must reference valid alias."""
        with pytest.raises(ValidationError):
            QueryIR(
                intent=QueryIntent.FIND,
                targets=[TargetEntity(node_label="Function", alias="fn")],
                projections=[
                    Projection(
                        source_alias="invalid_alias",  # Not defined
                        property="name",
                        output_name="name"
                    )
                ]
            )


class TestValidationResult:
    """Tests for ValidationResult model."""

    def test_valid_result(self):
        """Test valid result."""
        result = ValidationResult(valid=True, errors=[], warnings=[])
        assert result.valid is True

    def test_invalid_result_with_errors(self):
        """Test invalid result with errors."""
        error = IRValidationError(
            layer="schema",
            code="UNKNOWN_NODE_LABEL",
            message="Unknown node label: 'InvalidLabel'",
            field_path="targets[0].node_label"
        )
        result = ValidationResult(valid=False, errors=[error], warnings=[])
        assert result.valid is False
        assert len(result.errors) == 1

    def test_to_feedback(self):
        """Test converting validation result to feedback string."""
        error = IRValidationError(
            layer="schema",
            code="UNKNOWN_NODE_LABEL",
            message="Unknown node label: 'InvalidLabel'",
            field_path="targets[0].node_label",
            suggestion="Valid labels: Function, Class, File"
        )
        result = ValidationResult(valid=False, errors=[error], warnings=[])
        feedback = result.to_feedback()
        assert "Unknown node label" in feedback
        assert "schema" in feedback


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
