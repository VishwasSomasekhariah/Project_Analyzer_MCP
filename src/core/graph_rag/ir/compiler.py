"""
Cypher Compiler - Deterministic IR to Cypher compilation.

This module compiles validated QueryIR to Cypher queries without any LLM.
The compilation is entirely deterministic and template-based.

Key Benefits:
- No LLM hallucinations in Cypher generation
- Consistent, predictable query output
- Security: No injection possible through IR
- Testable: Same IR always produces same Cypher

Security Considerations:
- All values are properly escaped
- String values are single-quoted with escape handling
- Identifiers are validated before compilation (in IR models)
- Read-only queries only (no CREATE/DELETE)

Usage:
    compiler = CypherCompiler()
    cypher = compiler.compile(validated_ir)
"""

import logging
from typing import Any, List, Optional

from .models import (
    QueryIR,
    TargetEntity,
    TraversalStep,
    TraversalPath,
    Projection,
    FilterCondition,
    OrderSpec,
    FilterOperator,
    AggregationType,
    RelationshipDirection,
)
from .context import IRContext


logger = logging.getLogger(__name__)


class CypherCompiler:
    """
    Compiles validated QueryIR to Cypher query string.

    This is a deterministic, template-based compiler. No LLM is involved.
    The IR must be validated before compilation.

    Usage:
        compiler = CypherCompiler()
        cypher = compiler.compile(ir)

        # With context for optimization
        ctx = IRContext.from_ir(ir, schema)
        cypher = compiler.compile(ir, ctx)

    Output Format:
        The compiler generates well-formatted Cypher:
        ```
        MATCH (p:Project)-[:CONTAINS]->(f:File)-[:CONTAINS]->(fn:Function)
        WHERE p.name = 'HelloWorldApp'
        RETURN fn.name AS method_name, fn.cyclomatic_complexity AS complexity
        ORDER BY complexity DESC
        LIMIT 100
        ```
    """

    # Maximum query complexity limits
    MAX_WHERE_CLAUSES = 50
    MAX_RETURN_ITEMS = 100

    def __init__(self, pretty_print: bool = True):
        """
        Initialize the Cypher compiler.

        Args:
            pretty_print: If True, format output with newlines; if False, single line
        """
        self._pretty_print = pretty_print
        self._logger = logger

    def compile(self, ir: QueryIR, ctx: Optional[IRContext] = None) -> str:
        """
        Compile QueryIR to Cypher query string.

        Args:
            ir: Validated QueryIR to compile
            ctx: Optional IRContext for optimization hints

        Returns:
            Cypher query string

        Raises:
            ValueError: If IR is invalid (should be pre-validated)
        """
        parts: List[str] = []

        # MATCH clause
        match_clause = self._compile_match(ir)
        parts.append(match_clause)

        # WHERE clause (optional)
        if ir.filters:
            where_clause = self._compile_where(ir)
            if where_clause:
                parts.append(where_clause)

        # RETURN clause
        return_clause = self._compile_return(ir)
        parts.append(return_clause)

        # ORDER BY (optional)
        if ir.ordering:
            order_clause = self._compile_order(ir.ordering)
            parts.append(order_clause)

        # SKIP (optional)
        if ir.skip:
            parts.append(f"SKIP {ir.skip}")

        # LIMIT (optional)
        if ir.limit:
            parts.append(f"LIMIT {ir.limit}")

        # Join parts
        separator = "\n" if self._pretty_print else " "
        query = separator.join(parts)

        self._logger.debug(f"Compiled Cypher:\n{query}")
        return query

    def _compile_match(self, ir: QueryIR) -> str:
        """
        Compile MATCH clause from targets and traversal.

        Examples:
            Single node: MATCH (fn:Function)
            With traversal: MATCH (p:Project)-[:CONTAINS]->(f:File)-[:CONTAINS]->(fn:Function)
        """
        if not ir.traversal or not ir.traversal.steps:
            # Single node match
            target = ir.targets[0]
            return f"MATCH ({target.alias}:{target.node_label})"

        # Build path pattern
        pattern_parts: List[str] = []

        # Start with first target
        first_target = ir.targets[0]
        pattern_parts.append(f"({first_target.alias}:{first_target.node_label})")

        # Add traversal steps
        for step in ir.traversal.steps:
            rel_pattern = self._compile_relationship(step)
            node_pattern = f"({step.to_alias}:{step.to_label})"
            pattern_parts.append(rel_pattern)
            pattern_parts.append(node_pattern)

        pattern = "".join(pattern_parts)
        return f"MATCH {pattern}"

    def _compile_relationship(self, step: TraversalStep) -> str:
        """
        Compile a relationship pattern.

        Examples:
            Outgoing: -[:CONTAINS]->
            Incoming: <-[:CONTAINS]-
            Both: -[:CONTAINS]-
            With alias: -[r:CONTAINS]->
        """
        # Build relationship part
        if step.relationship_alias:
            rel_inner = f"[{step.relationship_alias}:{step.relationship}]"
        else:
            rel_inner = f"[:{step.relationship}]"

        # Apply direction
        if step.direction == RelationshipDirection.OUTGOING:
            return f"-{rel_inner}->"
        elif step.direction == RelationshipDirection.INCOMING:
            return f"<-{rel_inner}-"
        else:  # BOTH
            return f"-{rel_inner}-"

    def _compile_where(self, ir: QueryIR) -> str:
        """
        Compile WHERE clause from filters.

        Examples:
            WHERE p.name = 'HelloWorldApp'
            WHERE p.name = 'HelloWorldApp' AND fn.cyclomatic_complexity > 2
        """
        if not ir.filters:
            return ""

        conditions: List[str] = []
        for f in ir.filters:
            condition = self._compile_filter(f)
            conditions.append(condition)

        # Limit number of conditions (security)
        if len(conditions) > self.MAX_WHERE_CLAUSES:
            self._logger.warning(
                f"WHERE clause has {len(conditions)} conditions, truncating to {self.MAX_WHERE_CLAUSES}"
            )
            conditions = conditions[:self.MAX_WHERE_CLAUSES]

        return "WHERE " + " AND ".join(conditions)

    def _compile_filter(self, f: FilterCondition) -> str:
        """
        Compile a single filter condition.

        Examples:
            p.name = 'HelloWorldApp'
            fn.cyclomatic_complexity > 2
            s.statement_type IN ['if', 'for', 'while']
            toLower(p.name) = toLower('helloworld')
        """
        # Build property reference
        if f.case_insensitive:
            prop_ref = f"toLower({f.source_alias}.{f.property})"
        else:
            prop_ref = f"{f.source_alias}.{f.property}"

        # Compile based on operator
        if f.operator == FilterOperator.EQ:
            value = self._escape_value(f.value, f.case_insensitive)
            return f"{prop_ref} = {value}"

        elif f.operator == FilterOperator.NEQ:
            value = self._escape_value(f.value, f.case_insensitive)
            return f"{prop_ref} <> {value}"

        elif f.operator == FilterOperator.GT:
            return f"{prop_ref} > {self._escape_value(f.value)}"

        elif f.operator == FilterOperator.GTE:
            return f"{prop_ref} >= {self._escape_value(f.value)}"

        elif f.operator == FilterOperator.LT:
            return f"{prop_ref} < {self._escape_value(f.value)}"

        elif f.operator == FilterOperator.LTE:
            return f"{prop_ref} <= {self._escape_value(f.value)}"

        elif f.operator == FilterOperator.CONTAINS:
            value = self._escape_value(f.value, f.case_insensitive)
            return f"{prop_ref} CONTAINS {value}"

        elif f.operator == FilterOperator.STARTS_WITH:
            value = self._escape_value(f.value, f.case_insensitive)
            return f"{prop_ref} STARTS WITH {value}"

        elif f.operator == FilterOperator.ENDS_WITH:
            value = self._escape_value(f.value, f.case_insensitive)
            return f"{prop_ref} ENDS WITH {value}"

        elif f.operator == FilterOperator.IN:
            values = self._escape_list(f.value)
            return f"{prop_ref} IN {values}"

        elif f.operator == FilterOperator.NOT_IN:
            values = self._escape_list(f.value)
            return f"NOT {prop_ref} IN {values}"

        elif f.operator == FilterOperator.IS_NULL:
            return f"{f.source_alias}.{f.property} IS NULL"

        elif f.operator == FilterOperator.IS_NOT_NULL:
            return f"{f.source_alias}.{f.property} IS NOT NULL"

        elif f.operator == FilterOperator.REGEX:
            # Regex value needs to be a string
            return f"{prop_ref} =~ '{self._escape_string(str(f.value))}'"

        else:
            raise ValueError(f"Unknown filter operator: {f.operator}")

    def _compile_return(self, ir: QueryIR) -> str:
        """
        Compile RETURN clause from projections.

        Examples:
            RETURN fn.name AS method_name
            RETURN fn.name AS name, fn.cyclomatic_complexity AS complexity
            RETURN count(fn) AS total
            RETURN DISTINCT fn.name AS name
        """
        items: List[str] = []

        # Check if any projection has DISTINCT
        has_distinct = any(p.distinct for p in ir.projections)

        for p in ir.projections:
            item = self._compile_projection(p)
            items.append(item)

        # Limit number of return items (security)
        if len(items) > self.MAX_RETURN_ITEMS:
            self._logger.warning(
                f"RETURN has {len(items)} items, truncating to {self.MAX_RETURN_ITEMS}"
            )
            items = items[:self.MAX_RETURN_ITEMS]

        # Apply DISTINCT at query level if any projection needs it
        distinct_prefix = "DISTINCT " if has_distinct else ""
        return f"RETURN {distinct_prefix}" + ", ".join(items)

    def _compile_projection(self, p: Projection) -> str:
        """
        Compile a single projection.

        Examples:
            fn.name AS method_name
            count(fn.name) AS total
            collect(fn.name) AS names
            fn AS node  (entire node)
        """
        # Build source reference
        if p.property:
            source_ref = f"{p.source_alias}.{p.property}"
        else:
            # Project entire node
            source_ref = p.source_alias

        # Apply aggregation if specified
        if p.aggregation:
            agg_fn = self._get_aggregation_function(p.aggregation)
            if p.aggregation == AggregationType.COUNT_DISTINCT:
                expr = f"count(DISTINCT {source_ref})"
            else:
                expr = f"{agg_fn}({source_ref})"
        else:
            expr = source_ref

        return f"{expr} AS {p.output_name}"

    def _get_aggregation_function(self, agg: AggregationType) -> str:
        """Map aggregation type to Cypher function name."""
        mapping = {
            AggregationType.COUNT: "count",
            AggregationType.COUNT_DISTINCT: "count",  # Handled specially
            AggregationType.SUM: "sum",
            AggregationType.AVG: "avg",
            AggregationType.MIN: "min",
            AggregationType.MAX: "max",
            AggregationType.COLLECT: "collect",
        }
        return mapping.get(agg, "count")

    def _compile_order(self, order: OrderSpec) -> str:
        """
        Compile ORDER BY clause.

        Examples:
            ORDER BY complexity DESC
            ORDER BY name ASC
        """
        direction = order.direction.value.upper()
        return f"ORDER BY {order.field} {direction}"

    def _escape_value(self, value: Any, case_insensitive: bool = False) -> str:
        """
        Escape a value for Cypher.

        Security: Properly escapes strings to prevent injection.
        """
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            escaped = self._escape_string(value)
            if case_insensitive:
                return f"toLower('{escaped}')"
            return f"'{escaped}'"
        else:
            return f"'{self._escape_string(str(value))}'"

    def _escape_string(self, s: str) -> str:
        """
        Escape a string for Cypher single quotes.

        Security: Prevents Cypher injection via string values.
        """
        # Escape backslashes first, then single quotes
        return s.replace("\\", "\\\\").replace("'", "\\'")

    def _escape_list(self, values: List[Any]) -> str:
        """
        Escape a list of values for Cypher IN clause.

        Example: ['if', 'for', 'while'] → ['if', 'for', 'while']
        """
        if not values:
            return "[]"

        escaped_items = [self._escape_value(v) for v in values]
        return "[" + ", ".join(escaped_items) + "]"

    def compile_with_params(self, ir: QueryIR) -> tuple[str, dict]:
        """
        Compile IR to parameterized Cypher for better performance.

        Returns:
            Tuple of (query_with_params, params_dict)

        Example:
            query: "MATCH (p:Project) WHERE p.name = $p_name RETURN p"
            params: {"p_name": "HelloWorldApp"}
        """
        # For now, return non-parameterized version
        # TODO: Implement parameterized compilation for production
        return self.compile(ir), {}


class CypherCompilationError(Exception):
    """Exception raised when Cypher compilation fails."""
    pass


__all__ = ['CypherCompiler', 'CypherCompilationError']
