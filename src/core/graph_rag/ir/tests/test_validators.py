"""
Unit tests for IR validators.

Tests cover:
- IRValidator (Layer 1 & 2 validation)
- IntentRuleEngine (Layer 3 semantic validation)
- Schema-based validation
- Custom rule registration
"""

import pytest

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
)
from src.core.graph_rag.ir.context import SchemaInfo, IRContext
from src.core.graph_rag.ir.validators import IRValidator, IntentRuleEngine
from src.core.graph_rag.ir.validators.intent_rules import IntentRule


@pytest.fixture
def sample_schema():
    """Create a sample schema for testing."""
    return SchemaInfo(
        node_labels=frozenset({"Function", "Class", "File", "Project", "Statement"}),
        node_properties={
            "Function": frozenset({"name", "cyclomatic_complexity", "line_count", "is_public"}),
            "Class": frozenset({"name", "namespace", "is_abstract"}),
            "File": frozenset({"name", "path", "language"}),
            "Project": frozenset({"name", "version"}),
            "Statement": frozenset({"statement_type", "line_number"}),
        },
        relationship_types=frozenset({"CONTAINS", "CALLS", "EXTENDS", "IMPLEMENTS"}),
        relationship_properties={
            "CALLS": frozenset({"count", "line_number"}),
        },
        valid_connections=frozenset({
            ("Project", "CONTAINS", "File"),
            ("File", "CONTAINS", "Class"),
            ("File", "CONTAINS", "Function"),
            ("Class", "CONTAINS", "Function"),
            ("Function", "CONTAINS", "Statement"),
            ("Function", "CALLS", "Function"),
            ("Class", "EXTENDS", "Class"),
            ("Class", "IMPLEMENTS", "Class"),
        })
    )


@pytest.fixture
def validator(sample_schema):
    """Create an IRValidator with sample schema."""
    return IRValidator(sample_schema)


@pytest.fixture
def validator_with_rules(sample_schema):
    """Create an IRValidator with IntentRuleEngine."""
    intent_rules = IntentRuleEngine(sample_schema)
    return IRValidator(sample_schema, intent_rules=intent_rules)


class TestIRValidatorSyntax:
    """Tests for Layer 1 syntax validation."""

    def test_valid_simple_query(self, validator):
        """Test validation of a simple valid query."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        result = validator.validate(ir)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_empty_projections_rejected_by_model(self, validator):
        """Test that empty projections are rejected at model construction."""
        # The model itself validates minimum projections via Pydantic
        from pydantic import ValidationError as PydanticValidationError
        with pytest.raises(PydanticValidationError):
            QueryIR(
                intent=QueryIntent.FIND,
                targets=[TargetEntity(node_label="Function", alias="fn")],
                projections=[]
            )

    def test_traversal_connectivity_rejected_by_model(self, validator):
        """Test that disconnected traversal is caught at model construction."""
        # The model validates that traversal aliases reference defined aliases
        from pydantic import ValidationError as PydanticValidationError
        with pytest.raises(PydanticValidationError):
            QueryIR(
                intent=QueryIntent.FIND,
                targets=[TargetEntity(node_label="Project", alias="p")],
                traversal=TraversalPath(steps=[
                    TraversalStep(
                        from_alias="unknown_alias",  # Not defined
                        relationship="CONTAINS",
                        to_label="File",
                        to_alias="f",
                        direction=RelationshipDirection.OUTGOING
                    )
                ]),
                projections=[
                    Projection(source_alias="f", property="name", output_name="name")
                ]
            )

    def test_valid_connected_traversal(self, validator):
        """Test that connected traversal passes."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Project", alias="p")],
            traversal=TraversalPath(steps=[
                TraversalStep(
                    from_alias="p",  # Connected to target
                    relationship="CONTAINS",
                    to_label="File",
                    to_alias="f",
                    direction=RelationshipDirection.OUTGOING
                ),
                TraversalStep(
                    from_alias="f",  # Connected to previous step
                    relationship="CONTAINS",
                    to_label="Function",
                    to_alias="fn",
                    direction=RelationshipDirection.OUTGOING
                )
            ]),
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        result = validator.validate(ir)
        assert result.valid is True

    def test_invalid_regex_filter(self, validator):
        """Test that invalid regex patterns are caught."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            filters=[
                FilterCondition(
                    source_alias="fn",
                    property="name",
                    operator=FilterOperator.REGEX,
                    value="[invalid(regex"  # Invalid regex
                )
            ],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        result = validator.validate(ir)
        assert result.valid is False
        assert any(e.code == "INVALID_REGEX" for e in result.errors)


class TestIRValidatorSchema:
    """Tests for Layer 2 schema validation."""

    def test_unknown_node_label(self, validator):
        """Test that unknown node labels are rejected."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="InvalidLabel", alias="x")],
            projections=[
                Projection(source_alias="x", property="name", output_name="name")
            ]
        )
        result = validator.validate(ir)
        assert result.valid is False
        assert any(e.code == "UNKNOWN_NODE_LABEL" for e in result.errors)

    def test_unknown_relationship_type(self, validator):
        """Test that unknown relationship types are rejected."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Project", alias="p")],
            traversal=TraversalPath(steps=[
                TraversalStep(
                    from_alias="p",
                    relationship="UNKNOWN_REL",  # Not in schema
                    to_label="File",
                    to_alias="f",
                    direction=RelationshipDirection.OUTGOING
                )
            ]),
            projections=[
                Projection(source_alias="f", property="name", output_name="name")
            ]
        )
        result = validator.validate(ir)
        assert result.valid is False
        assert any(e.code == "UNKNOWN_RELATIONSHIP" for e in result.errors)

    def test_unknown_property_in_filter(self, validator):
        """Test that unknown properties in filters are rejected."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            filters=[
                FilterCondition(
                    source_alias="fn",
                    property="nonexistent_prop",  # Not on Function
                    operator=FilterOperator.EQ,
                    value="test"
                )
            ],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        result = validator.validate(ir)
        assert result.valid is False
        assert any(e.code == "UNKNOWN_PROPERTY" for e in result.errors)

    def test_unknown_property_in_projection(self, validator):
        """Test that unknown properties in projections are rejected."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="nonexistent", output_name="x")
            ]
        )
        result = validator.validate(ir)
        assert result.valid is False
        assert any(e.code == "UNKNOWN_PROPERTY" for e in result.errors)

    def test_invalid_connection(self, validator):
        """Test that invalid schema connections are caught."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            traversal=TraversalPath(steps=[
                TraversalStep(
                    from_alias="fn",
                    relationship="EXTENDS",  # Functions don't EXTEND
                    to_label="Class",
                    to_alias="c",
                    direction=RelationshipDirection.OUTGOING
                )
            ]),
            projections=[
                Projection(source_alias="c", property="name", output_name="name")
            ]
        )
        result = validator.validate(ir)
        assert result.valid is False
        assert any(e.code == "INVALID_CONNECTION" for e in result.errors)

    def test_valid_schema_connection(self, validator):
        """Test that valid schema connections pass."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Class", alias="c")],
            traversal=TraversalPath(steps=[
                TraversalStep(
                    from_alias="c",
                    relationship="EXTENDS",
                    to_label="Class",
                    to_alias="parent",
                    direction=RelationshipDirection.OUTGOING
                )
            ]),
            projections=[
                Projection(source_alias="parent", property="name", output_name="parent_name")
            ]
        )
        result = validator.validate(ir)
        assert result.valid is True


class TestIRValidatorNonStrict:
    """Tests for non-strict mode validation."""

    def test_unknown_property_as_warning(self, sample_schema):
        """Test that unknown properties become warnings in non-strict mode."""
        validator = IRValidator(sample_schema, strict_mode=False)
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="unknown_prop", output_name="x")
            ]
        )
        result = validator.validate(ir)
        # Non-strict mode: unknown properties are warnings (not errors), so valid=True
        assert result.valid is True
        assert len(result.warnings) > 0
        assert any("unknown_prop" in w.message.lower() for w in result.warnings)


class TestIRValidatorQuick:
    """Tests for quick validation."""

    def test_quick_valid(self, validator):
        """Test quick validation returns True for valid IR."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        assert validator.validate_quick(ir) is True

    def test_quick_invalid(self, validator):
        """Test quick validation returns False for invalid IR."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="InvalidLabel", alias="x")],
            projections=[
                Projection(source_alias="x", property="name", output_name="name")
            ]
        )
        assert validator.validate_quick(ir) is False


class TestIntentRuleEngine:
    """Tests for IntentRuleEngine (Layer 3)."""

    def test_no_subtype_skips_rules(self, sample_schema):
        """Test that queries without intent_subtype skip rule validation."""
        engine = IntentRuleEngine(sample_schema)
        ir = QueryIR(
            intent=QueryIntent.FIND,
            # No intent_subtype
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)
        errors = engine.validate(ir, ctx)
        assert len(errors) == 0

    def test_unmatched_subtype_logged(self, sample_schema):
        """Test that unmatched subtypes are logged for metrics."""
        engine = IntentRuleEngine(sample_schema)
        ir = QueryIR(
            intent=QueryIntent.FIND,
            intent_subtype="custom_unknown_subtype",
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)
        engine.validate(ir, ctx)

        # Check metrics
        stats = engine.get_unmatched_intent_stats()
        assert "custom_unknown_subtype" in stats
        assert stats["custom_unknown_subtype"] >= 1

    def test_register_custom_rule(self, sample_schema):
        """Test registering and using custom rules."""
        engine = IntentRuleEngine(sample_schema)

        # Register a rule that requires cyclomatic_complexity property
        rule = IntentRule(
            intent=QueryIntent.AGGREGATE,
            intent_subtype="compute_complexity",
            description="Complexity queries must project cyclomatic_complexity",
            check_has_properties=frozenset({"cyclomatic_complexity"})
        )
        engine.register_rule(rule)

        # IR without cyclomatic_complexity should get a suggestion
        ir = QueryIR(
            intent=QueryIntent.AGGREGATE,
            intent_subtype="compute_complexity",
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)
        errors = engine.validate(ir, ctx)

        assert len(errors) > 0
        assert any("cyclomatic_complexity" in e.message for e in errors)

    def test_rule_with_required_node_labels(self, sample_schema):
        """Test rule that requires specific node labels."""
        engine = IntentRuleEngine(sample_schema)

        rule = IntentRule(
            intent=QueryIntent.FIND,
            intent_subtype="find_statements",
            description="Must query Statement nodes",
            check_has_node_labels=frozenset({"Statement"})
        )
        engine.register_rule(rule)

        # IR without Statement nodes
        ir = QueryIR(
            intent=QueryIntent.FIND,
            intent_subtype="find_statements",
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)
        errors = engine.validate(ir, ctx)

        assert len(errors) > 0
        assert any("Statement" in e.message for e in errors)

    def test_rule_with_required_relationships(self, sample_schema):
        """Test rule that requires specific relationships."""
        engine = IntentRuleEngine(sample_schema)

        rule = IntentRule(
            intent=QueryIntent.FIND,
            intent_subtype="find_callers",
            description="Must use CALLS relationship",
            check_has_relationships=frozenset({"CALLS"})
        )
        engine.register_rule(rule)

        # IR without CALLS relationship
        ir = QueryIR(
            intent=QueryIntent.FIND,
            intent_subtype="find_callers",
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)
        errors = engine.validate(ir, ctx)

        assert len(errors) > 0
        assert any("CALLS" in e.message for e in errors)

    def test_available_rules(self, sample_schema):
        """Test getting list of available rules."""
        engine = IntentRuleEngine(sample_schema)

        rule = IntentRule(
            intent=QueryIntent.FIND,
            intent_subtype="test_rule",
            description="Test rule"
        )
        engine.register_rule(rule)

        rules = engine.get_available_rules()
        assert "test_rule" in rules

    def test_get_rule_description(self, sample_schema):
        """Test getting rule description."""
        engine = IntentRuleEngine(sample_schema)

        rule = IntentRule(
            intent=QueryIntent.FIND,
            intent_subtype="test_rule",
            description="This is a test rule"
        )
        engine.register_rule(rule)

        desc = engine.get_rule_description("test_rule")
        assert desc == "This is a test rule"

        assert engine.get_rule_description("nonexistent") is None

    def test_decision_point_types(self, sample_schema):
        """Test getting configured decision point types."""
        engine = IntentRuleEngine(sample_schema)
        types = engine.get_decision_point_types()

        assert "if" in types
        assert "for" in types
        assert "while" in types

    def test_reset_metrics(self, sample_schema):
        """Test resetting metrics."""
        engine = IntentRuleEngine(sample_schema)

        # Generate some unmatched intents
        ir = QueryIR(
            intent=QueryIntent.FIND,
            intent_subtype="test_unmatched",
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)
        engine.validate(ir, ctx)

        assert len(engine.get_unmatched_intent_stats()) > 0

        engine.reset_metrics()
        assert len(engine.get_unmatched_intent_stats()) == 0


class TestValidatorWithIntentRules:
    """Tests for IRValidator with IntentRuleEngine integration."""

    def test_full_validation_pipeline(self, sample_schema):
        """Test that all three layers run when integrated."""
        intent_rules = IntentRuleEngine(sample_schema)

        # Register a rule
        rule = IntentRule(
            intent=QueryIntent.AGGREGATE,
            intent_subtype="compute_complexity",
            description="Must project cyclomatic_complexity",
            check_has_properties=frozenset({"cyclomatic_complexity"})
        )
        intent_rules.register_rule(rule)

        validator = IRValidator(sample_schema, intent_rules=intent_rules)

        # Valid structure but missing required property
        ir = QueryIR(
            intent=QueryIntent.AGGREGATE,
            intent_subtype="compute_complexity",
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(
                    source_alias="fn",
                    property="name",  # Not cyclomatic_complexity
                    output_name="name"
                )
            ]
        )
        result = validator.validate(ir)

        # Should have semantic error from intent rules
        assert any(e.layer == "semantic" for e in result.errors)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
