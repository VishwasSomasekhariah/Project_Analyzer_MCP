"""
Unit tests for CypherCompiler.

Tests cover:
- Basic query compilation
- Filter compilation
- Aggregation compilation
- Security (escaping)
- Edge cases
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
    OrderSpec,
    SortOrder,
)
from src.core.graph_rag.ir.compiler import CypherCompiler


@pytest.fixture
def compiler():
    """Create a CypherCompiler instance."""
    return CypherCompiler(pretty_print=True)


class TestBasicCompilation:
    """Tests for basic query compilation."""

    def test_simple_match(self, compiler):
        """Test simple single-node match."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        cypher = compiler.compile(ir)
        assert "MATCH (fn:Function)" in cypher
        assert "RETURN fn.name AS name" in cypher

    def test_match_with_traversal(self, compiler):
        """Test match with traversal path."""
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
        cypher = compiler.compile(ir)
        assert "MATCH (p:Project)-[:CONTAINS]->(f:File)" in cypher
        assert "RETURN f.name AS file_name" in cypher

    def test_multi_step_traversal(self, compiler):
        """Test multi-step traversal."""
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
                Projection(source_alias="fn", property="name", output_name="function_name")
            ]
        )
        cypher = compiler.compile(ir)
        assert "(p:Project)-[:CONTAINS]->(f:File)-[:CONTAINS]->(fn:Function)" in cypher


class TestFilterCompilation:
    """Tests for filter compilation."""

    def test_equality_filter(self, compiler):
        """Test equality filter."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Project", alias="p")],
            filters=[
                FilterCondition(
                    source_alias="p",
                    property="name",
                    operator=FilterOperator.EQ,
                    value="HelloWorldApp"
                )
            ],
            projections=[
                Projection(source_alias="p", property="name", output_name="name")
            ]
        )
        cypher = compiler.compile(ir)
        assert "WHERE p.name = 'HelloWorldApp'" in cypher

    def test_numeric_comparison(self, compiler):
        """Test numeric comparison filter."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            filters=[
                FilterCondition(
                    source_alias="fn",
                    property="cyclomatic_complexity",
                    operator=FilterOperator.GT,
                    value=5
                )
            ],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        cypher = compiler.compile(ir)
        assert "WHERE fn.cyclomatic_complexity > 5" in cypher

    def test_multiple_filters(self, compiler):
        """Test multiple filters combined with AND."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            filters=[
                FilterCondition(
                    source_alias="fn",
                    property="cyclomatic_complexity",
                    operator=FilterOperator.GT,
                    value=5
                ),
                FilterCondition(
                    source_alias="fn",
                    property="name",
                    operator=FilterOperator.CONTAINS,
                    value="Main"
                )
            ],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        cypher = compiler.compile(ir)
        assert "fn.cyclomatic_complexity > 5" in cypher
        assert "AND" in cypher
        assert "fn.name CONTAINS 'Main'" in cypher

    def test_in_filter(self, compiler):
        """Test IN filter."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Statement", alias="s")],
            filters=[
                FilterCondition(
                    source_alias="s",
                    property="statement_type",
                    operator=FilterOperator.IN,
                    value=["if", "for", "while"]
                )
            ],
            projections=[
                Projection(source_alias="s", property="statement_type", output_name="type")
            ]
        )
        cypher = compiler.compile(ir)
        assert "s.statement_type IN ['if', 'for', 'while']" in cypher

    def test_case_insensitive_filter(self, compiler):
        """Test case insensitive filter."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Project", alias="p")],
            filters=[
                FilterCondition(
                    source_alias="p",
                    property="name",
                    operator=FilterOperator.EQ,
                    value="helloworld",
                    case_insensitive=True
                )
            ],
            projections=[
                Projection(source_alias="p", property="name", output_name="name")
            ]
        )
        cypher = compiler.compile(ir)
        assert "toLower(p.name)" in cypher
        assert "toLower('helloworld')" in cypher


class TestProjectionCompilation:
    """Tests for projection compilation."""

    def test_multiple_projections(self, compiler):
        """Test multiple projections."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="function_name"),
                Projection(source_alias="fn", property="cyclomatic_complexity", output_name="complexity")
            ]
        )
        cypher = compiler.compile(ir)
        assert "fn.name AS function_name" in cypher
        assert "fn.cyclomatic_complexity AS complexity" in cypher

    def test_count_aggregation(self, compiler):
        """Test COUNT aggregation."""
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
        cypher = compiler.compile(ir)
        assert "count(fn) AS total" in cypher

    def test_avg_aggregation(self, compiler):
        """Test AVG aggregation."""
        ir = QueryIR(
            intent=QueryIntent.AGGREGATE,
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
        cypher = compiler.compile(ir)
        assert "avg(fn.cyclomatic_complexity) AS avg_complexity" in cypher

    def test_distinct_projection(self, compiler):
        """Test DISTINCT projection."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(
                    source_alias="fn",
                    property="name",
                    output_name="unique_names",
                    distinct=True
                )
            ]
        )
        cypher = compiler.compile(ir)
        assert "RETURN DISTINCT fn.name AS unique_names" in cypher

    def test_collect_aggregation(self, compiler):
        """Test COLLECT aggregation."""
        ir = QueryIR(
            intent=QueryIntent.AGGREGATE,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(
                    source_alias="fn",
                    property="name",
                    output_name="all_names",
                    aggregation=AggregationType.COLLECT
                )
            ]
        )
        cypher = compiler.compile(ir)
        assert "collect(fn.name) AS all_names" in cypher


class TestOrderingAndLimits:
    """Tests for ordering and limits."""

    def test_order_by_desc(self, compiler):
        """Test ORDER BY DESC."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="cyclomatic_complexity", output_name="complexity")
            ],
            ordering=OrderSpec(field="complexity", direction=SortOrder.DESC)
        )
        cypher = compiler.compile(ir)
        assert "ORDER BY complexity DESC" in cypher

    def test_order_by_asc(self, compiler):
        """Test ORDER BY ASC."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ],
            ordering=OrderSpec(field="name", direction=SortOrder.ASC)
        )
        cypher = compiler.compile(ir)
        assert "ORDER BY name ASC" in cypher

    def test_limit(self, compiler):
        """Test LIMIT clause."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ],
            limit=10
        )
        cypher = compiler.compile(ir)
        assert "LIMIT 10" in cypher

    def test_skip_and_limit(self, compiler):
        """Test SKIP and LIMIT for pagination."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ],
            skip=20,
            limit=10
        )
        cypher = compiler.compile(ir)
        assert "SKIP 20" in cypher
        assert "LIMIT 10" in cypher


class TestSecurityEscaping:
    """Tests for security (value escaping)."""

    def test_single_quote_escaping(self, compiler):
        """Test that single quotes in values are escaped."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Project", alias="p")],
            filters=[
                FilterCondition(
                    source_alias="p",
                    property="name",
                    operator=FilterOperator.EQ,
                    value="Hello'World"
                )
            ],
            projections=[
                Projection(source_alias="p", property="name", output_name="name")
            ]
        )
        cypher = compiler.compile(ir)
        # Should escape the single quote
        assert "Hello\\'World" in cypher

    def test_backslash_escaping(self, compiler):
        """Test that backslashes are escaped."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="File", alias="f")],
            filters=[
                FilterCondition(
                    source_alias="f",
                    property="path",
                    operator=FilterOperator.EQ,
                    value="C:\\Users\\Test"
                )
            ],
            projections=[
                Projection(source_alias="f", property="path", output_name="path")
            ]
        )
        cypher = compiler.compile(ir)
        # Backslashes should be escaped
        assert "\\\\" in cypher

    def test_boolean_value(self, compiler):
        """Test boolean value handling."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            filters=[
                FilterCondition(
                    source_alias="fn",
                    property="is_public",
                    operator=FilterOperator.EQ,
                    value=True
                )
            ],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        cypher = compiler.compile(ir)
        assert "fn.is_public = true" in cypher

    def test_null_value(self, compiler):
        """Test null value handling."""
        ir = QueryIR(
            intent=QueryIntent.FIND,
            targets=[TargetEntity(node_label="Function", alias="fn")],
            filters=[
                FilterCondition(
                    source_alias="fn",
                    property="return_type",
                    operator=FilterOperator.IS_NULL,
                    value=None
                )
            ],
            projections=[
                Projection(source_alias="fn", property="name", output_name="name")
            ]
        )
        cypher = compiler.compile(ir)
        assert "fn.return_type IS NULL" in cypher


class TestComplexQueries:
    """Tests for complex, real-world queries."""

    def test_cyclomatic_complexity_query(self, compiler):
        """Test query for functions with high cyclomatic complexity."""
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
                Projection(source_alias="fn", property="cyclomatic_complexity", output_name="complexity"),
                Projection(source_alias="f", property="name", output_name="file_name")
            ],
            ordering=OrderSpec(field="complexity", direction=SortOrder.DESC),
            limit=100
        )
        cypher = compiler.compile(ir)

        # Verify structure
        assert "MATCH (p:Project)-[:CONTAINS]->(f:File)-[:CONTAINS]->(fn:Function)" in cypher
        assert "WHERE p.name = 'HelloWorldApp'" in cypher
        assert "fn.cyclomatic_complexity > 5" in cypher
        assert "ORDER BY complexity DESC" in cypher
        assert "LIMIT 100" in cypher


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
