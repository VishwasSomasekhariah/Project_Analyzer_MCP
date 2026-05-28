"""
Unit tests for IR context module.

Tests cover:
- SchemaInfo creation and lookups
- IRContext building and alias resolution
- Edge cases and empty schemas
"""

import pytest

from src.core.graph_rag.ir.models import (
    QueryIR,
    QueryIntent,
    TargetEntity,
    TraversalStep,
    TraversalPath,
    Projection,
    RelationshipDirection,
)
from src.core.graph_rag.ir.context import SchemaInfo, IRContext


class TestSchemaInfo:
    """Tests for SchemaInfo model."""

    def test_empty_schema(self):
        """Test creating an empty schema."""
        schema = SchemaInfo.empty()
        assert len(schema.node_labels) == 0
        assert len(schema.relationship_types) == 0
        assert not schema.has_node_label("Function")

    def test_has_node_label(self):
        """Test node label checking."""
        schema = SchemaInfo(
            node_labels=frozenset({"Function", "Class", "File"})
        )
        assert schema.has_node_label("Function") is True
        assert schema.has_node_label("Class") is True
        assert schema.has_node_label("InvalidLabel") is False

    def test_has_relationship_type(self):
        """Test relationship type checking."""
        schema = SchemaInfo(
            relationship_types=frozenset({"CONTAINS", "CALLS", "EXTENDS"})
        )
        assert schema.has_relationship_type("CONTAINS") is True
        assert schema.has_relationship_type("CALLS") is True
        assert schema.has_relationship_type("UNKNOWN") is False

    def test_has_property(self):
        """Test property checking on node labels."""
        schema = SchemaInfo(
            node_labels=frozenset({"Function"}),
            node_properties={
                "Function": frozenset({"name", "cyclomatic_complexity", "line_count"})
            }
        )
        assert schema.has_property("Function", "name") is True
        assert schema.has_property("Function", "cyclomatic_complexity") is True
        assert schema.has_property("Function", "unknown_prop") is False
        assert schema.has_property("InvalidLabel", "name") is False

    def test_has_relationship_property(self):
        """Test property checking on relationship types."""
        schema = SchemaInfo(
            relationship_types=frozenset({"CALLS"}),
            relationship_properties={
                "CALLS": frozenset({"count", "line_number"})
            }
        )
        assert schema.has_relationship_property("CALLS", "count") is True
        assert schema.has_relationship_property("CALLS", "unknown") is False
        assert schema.has_relationship_property("UNKNOWN_REL", "count") is False

    def test_is_valid_connection_outgoing(self):
        """Test outgoing connection validation."""
        schema = SchemaInfo(
            valid_connections=frozenset({
                ("Project", "CONTAINS", "File"),
                ("File", "CONTAINS", "Function"),
            })
        )
        assert schema.is_valid_connection(
            "Project", "CONTAINS", "File", RelationshipDirection.OUTGOING
        ) is True
        assert schema.is_valid_connection(
            "File", "CONTAINS", "Project", RelationshipDirection.OUTGOING
        ) is False

    def test_is_valid_connection_incoming(self):
        """Test incoming connection validation."""
        schema = SchemaInfo(
            valid_connections=frozenset({
                ("Project", "CONTAINS", "File"),
            })
        )
        # For INCOMING, we check if (to, rel, from) exists
        assert schema.is_valid_connection(
            "File", "CONTAINS", "Project", RelationshipDirection.INCOMING
        ) is True
        assert schema.is_valid_connection(
            "Project", "CONTAINS", "File", RelationshipDirection.INCOMING
        ) is False

    def test_is_valid_connection_both(self):
        """Test BOTH direction connection validation."""
        schema = SchemaInfo(
            valid_connections=frozenset({
                ("Class", "EXTENDS", "Class"),
            })
        )
        # For BOTH, either direction should work
        assert schema.is_valid_connection(
            "Class", "EXTENDS", "Class", RelationshipDirection.BOTH
        ) is True

    def test_get_properties(self):
        """Test getting all properties for a label."""
        schema = SchemaInfo(
            node_properties={
                "Function": frozenset({"name", "complexity"})
            }
        )
        props = schema.get_properties("Function")
        assert "name" in props
        assert "complexity" in props

        # Unknown label returns empty set
        assert schema.get_properties("Unknown") == frozenset()

    def test_get_all_labels_with_property(self):
        """Test finding labels that have a specific property."""
        schema = SchemaInfo(
            node_labels=frozenset({"Function", "Class", "File"}),
            node_properties={
                "Function": frozenset({"name", "cyclomatic_complexity"}),
                "Class": frozenset({"name", "namespace"}),
                "File": frozenset({"name", "path"}),
            }
        )
        # All have "name"
        labels_with_name = schema.get_all_labels_with_property("name")
        assert set(labels_with_name) == {"Function", "Class", "File"}

        # Only Function has cyclomatic_complexity
        labels_with_cc = schema.get_all_labels_with_property("cyclomatic_complexity")
        assert labels_with_cc == ["Function"]

        # None have unknown_prop
        labels_with_unknown = schema.get_all_labels_with_property("unknown_prop")
        assert labels_with_unknown == []

    def test_immutability(self):
        """Test that SchemaInfo is immutable (frozen)."""
        schema = SchemaInfo(
            node_labels=frozenset({"Function"})
        )
        # Should raise an error when trying to modify
        with pytest.raises(Exception):  # Pydantic raises various exceptions
            schema.node_labels = frozenset({"Class"})


class TestIRContext:
    """Tests for IRContext model."""

    @pytest.fixture
    def sample_schema(self):
        """Create a sample schema for context tests."""
        return SchemaInfo(
            node_labels=frozenset({"Function", "Class", "File", "Project"}),
            node_properties={
                "Function": frozenset({"name", "cyclomatic_complexity"}),
                "Class": frozenset({"name", "namespace"}),
                "File": frozenset({"name", "path"}),
                "Project": frozenset({"name", "version"}),
            },
            relationship_types=frozenset({"CONTAINS", "CALLS"}),
            valid_connections=frozenset({
                ("Project", "CONTAINS", "File"),
                ("File", "CONTAINS", "Function"),
                ("Function", "CALLS", "Function"),
            })
        )

    def test_from_ir_simple(self, sample_schema):
        """Test building context from simple IR."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="function_name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)

        assert ctx.get_label_for_alias("fn") == "Function"
        assert ctx.has_alias("fn") is True
        assert ctx.has_alias("unknown") is False
        assert ctx.has_output_name("function_name") is True

    def test_from_ir_with_traversal(self, sample_schema):
        """Test building context from IR with traversal."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
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
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)

        # All aliases should be resolvable
        assert ctx.get_label_for_alias("p") == "Project"
        assert ctx.get_label_for_alias("f") == "File"
        assert ctx.get_label_for_alias("fn") == "Function"

        # Properties should be available
        assert "name" in ctx.get_properties_for_alias("fn")
        assert "cyclomatic_complexity" in ctx.get_properties_for_alias("fn")
        assert "path" in ctx.get_properties_for_alias("f")

    def test_from_ir_with_relationship_alias(self, sample_schema):
        """Test context with relationship alias."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            traversal=TraversalPath(steps=[
                TraversalStep(
                    from_alias="fn",
                    relationship="CALLS",
                    to_label="Function",
                    to_alias="called",
                    direction=RelationshipDirection.OUTGOING,
                    relationship_alias="call_rel"
                )
            ]),
            projections=[
                Projection(source_alias="called", property="name", output_name="called_name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)

        assert ctx.get_relationship_type("call_rel") == "CALLS"

    def test_get_label_for_alias(self, sample_schema):
        """Test alias to label resolution."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)

        assert ctx.get_label_for_alias("fn") == "Function"
        assert ctx.get_label_for_alias("nonexistent") is None

    def test_get_properties_for_alias(self, sample_schema):
        """Test getting properties for an alias."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)

        props = ctx.get_properties_for_alias("fn")
        assert "name" in props
        assert "cyclomatic_complexity" in props

        # Unknown alias returns empty
        assert ctx.get_properties_for_alias("unknown") == frozenset()

    def test_is_property_valid(self, sample_schema):
        """Test property validation for an alias."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)

        assert ctx.is_property_valid("fn", "name") is True
        assert ctx.is_property_valid("fn", "cyclomatic_complexity") is True
        assert ctx.is_property_valid("fn", "invalid_prop") is False
        assert ctx.is_property_valid("invalid_alias", "name") is False

    def test_has_output_name(self, sample_schema):
        """Test checking for projection output names."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="function_name"),
                Projection(source_alias="fn", property="cyclomatic_complexity", output_name="complexity")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)

        assert ctx.has_output_name("function_name") is True
        assert ctx.has_output_name("complexity") is True
        assert ctx.has_output_name("nonexistent") is False

    def test_get_summary(self, sample_schema):
        """Test getting context summary for debugging."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Project", alias="p")],
            traversal=TraversalPath(steps=[
                TraversalStep(
                    from_alias="p",
                    relationship="CONTAINS",
                    to_label="File",
                    to_alias="f",
                    direction=RelationshipDirection.OUTGOING
                )
            ]),
            projections=[
                Projection(source_alias="f", property="name", output_name="file_name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)
        summary = ctx.get_summary()

        assert "aliases" in summary
        assert summary["aliases"]["p"] == "Project"
        assert summary["aliases"]["f"] == "File"
        assert "output_names" in summary
        assert "file_name" in summary["output_names"]
        assert "schema_nodes" in summary
        assert "schema_relationships" in summary

    def test_immutability(self, sample_schema):
        """Test that IRContext is immutable."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        ctx = IRContext.from_ir(ir, sample_schema)

        # Should raise when trying to modify
        with pytest.raises(Exception):
            ctx.alias_to_label = {"new": "value"}


class TestSchemaInfoFromManager:
    """Tests for SchemaInfo.from_schema_manager."""

    def test_from_mock_manager(self):
        """Test building schema from a mock schema manager."""
        # Create a mock schema manager
        class MockSchemaManager:
            def get_full_schema(self):
                return {
                    "nodes": {
                        "Function": {
                            "properties": {
                                "name": {"type": "string"},
                                "complexity": {"type": "int"}
                            }
                        },
                        "Class": {
                            "properties": {
                                "name": {"type": "string"}
                            }
                        }
                    },
                    "relationships": {
                        "CONTAINS": {
                            "connections": [
                                {"from": "Class", "to": "Function"}
                            ]
                        }
                    }
                }

        manager = MockSchemaManager()
        schema = SchemaInfo.from_schema_manager(manager)

        assert schema.has_node_label("Function")
        assert schema.has_node_label("Class")
        assert schema.has_relationship_type("CONTAINS")
        assert schema.has_property("Function", "name")
        assert schema.has_property("Function", "complexity")
        assert ("Class", "CONTAINS", "Function") in schema.valid_connections

    def test_from_manager_with_error(self):
        """Test handling errors when building from manager."""
        class BrokenManager:
            def get_full_schema(self):
                raise RuntimeError("Schema unavailable")

        manager = BrokenManager()
        schema = SchemaInfo.from_schema_manager(manager)

        # Should return empty schema on error
        assert len(schema.node_labels) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
