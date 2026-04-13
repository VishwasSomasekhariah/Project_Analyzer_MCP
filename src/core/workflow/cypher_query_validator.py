"""
Cypher Query Validator Utility

Validates generated Cypher queries against the reconciled schema to ensure:
- Node labels exist in schema
- Relationship types exist and are valid between node types
- Properties exist on the correct node types
- Query structure is sensible

Can be used as a Pydantic validator or standalone validation function.
"""

import re
import json
from typing import Dict, List, Tuple, Optional, Set, Any
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ValidationSeverity(Enum):
    """Severity levels for validation issues"""
    ERROR = "error"  # Query will likely fail
    WARNING = "warning"  # Query might work but is suspicious
    INFO = "info"  # Informational, not necessarily a problem


@dataclass
class ValidationIssue:
    """Represents a validation issue found in a Cypher query"""
    severity: ValidationSeverity
    message: str
    location: str  # Where in the query the issue was found
    suggestion: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of validating a Cypher query"""
    is_valid: bool
    issues: List[ValidationIssue]
    extracted_nodes: List[Tuple[str, str, Optional[str]]]  # (alias, label, properties)
    extracted_relationships: List[Tuple[str, str, str]]  # (from_label, rel_type, to_label)
    extracted_properties: List[Tuple[str, str, str]]  # (alias, label, property)

    def get_errors(self) -> List[ValidationIssue]:
        """Get only ERROR severity issues"""
        return [i for i in self.issues if i.severity == ValidationSeverity.ERROR]

    def get_warnings(self) -> List[ValidationIssue]:
        """Get only WARNING severity issues"""
        return [i for i in self.issues if i.severity == ValidationSeverity.WARNING]

    def summary(self) -> str:
        """Generate a human-readable summary"""
        errors = self.get_errors()
        warnings = self.get_warnings()

        if self.is_valid:
            msg = "✅ Query validation passed"
        else:
            msg = f"❌ Query validation failed with {len(errors)} error(s)"

        if warnings:
            msg += f" and {len(warnings)} warning(s)"

        return msg


class CypherQueryValidator:
    """
    Validates Cypher queries against a reconciled schema.

    The schema should follow the reconciled schema format:
    {
        "nodes": {
            "NodeType": {
                "properties": ["prop1", "prop2", ...],
                "description": "...",
                "count": 123
            }
        },
        "relationships": {
            "REL_TYPE": {
                "valid_pairs": [{"from": "SourceNode", "to": "TargetNode"}, ...],
                "properties": ["prop1", "prop2"],
                "description": "...",
                "count": 123
            }
        }
    }
    """

    def __init__(self, schema: Dict[str, Any]):
        """
        Initialize validator with reconciled schema.

        Args:
            schema: Dictionary containing nodes and relationships with their properties
        """
        self.schema = schema
        self.node_types = set(schema.get("nodes", {}).keys())
        self.relationship_types = set(schema.get("relationships", {}).keys())

        # Build valid pairs lookup for faster validation
        self.valid_pairs = {}  # rel_type -> set of (from, to) tuples
        for rel_type, rel_info in schema.get("relationships", {}).items():
            pairs = set()
            for pair in rel_info.get("valid_pairs", []):
                pairs.add((pair["from"], pair["to"]))
            self.valid_pairs[rel_type] = pairs

    @classmethod
    def from_json_file(cls, schema_path: str) -> "CypherQueryValidator":
        """
        Create validator from a JSON schema file.

        Args:
            schema_path: Path to reconciled schema JSON file

        Returns:
            Configured CypherQueryValidator
        """
        with open(schema_path, 'r') as f:
            schema = json.load(f)
        return cls(schema)

    def extract_nodes(self, cypher: str) -> List[Tuple[str, str, Optional[str]]]:
        """
        Extract node patterns from Cypher query.

        Returns:
            List of (alias, label, properties_string) tuples
        """
        # Pattern: (alias:Label {prop: value}) or (:Label) or (alias:Label)
        node_pattern = re.findall(r'\((\w*):(\w+)(?:\s*\{([^}]+)\})?\)', cypher, re.IGNORECASE)
        return node_pattern

    def extract_relationships(self, cypher: str) -> List[str]:
        """
        Extract relationship types from Cypher query.

        Returns:
            List of relationship type names
        """
        # Pattern: -[:REL_TYPE]-> or -[r:REL_TYPE]->
        rel_pattern = re.findall(r'-\[(?:\w*):(\w+)\]->', cypher, re.IGNORECASE)
        return rel_pattern

    def extract_edges(self, cypher: str) -> List[Tuple[str, str, str]]:
        """
        Extract ordered edges (node-relationship-node triples).

        Returns:
            List of (from_label, rel_type, to_label) tuples
        """
        nodes = self.extract_nodes(cypher)
        rels = self.extract_relationships(cypher)

        edges = []
        for i in range(len(rels)):
            if i + 1 < len(nodes):
                from_label = nodes[i][1]
                to_label = nodes[i + 1][1]
                rel_type = rels[i]
                edges.append((from_label, rel_type, to_label))

        return edges

    def extract_properties(self, cypher: str, nodes: List[Tuple[str, str, Optional[str]]]) -> List[Tuple[str, str, str]]:
        """
        Extract property references from query.

        Returns:
            List of (alias, label, property_name) tuples
        """
        properties = []

        # Extract from inline property filters {name: 'value'}
        for alias, label, prop_blob in nodes:
            if prop_blob:
                props = re.findall(r'(\w+)\s*:', prop_blob)
                for p in props:
                    properties.append((alias or label, label, p))

        # Extract from WHERE and RETURN clauses (alias.property)
        prop_refs = re.findall(r'(\w+)\.(\w+)', cypher)

        # Map aliases to labels
        alias_to_label = {alias: label for alias, label, _ in nodes if alias}

        for alias, prop in prop_refs:
            if alias in alias_to_label:
                label = alias_to_label[alias]
                properties.append((alias, label, prop))

        # Deduplicate
        properties = list(dict.fromkeys(properties))

        return properties

    def validate_node_labels(self, nodes: List[Tuple[str, str, Optional[str]]]) -> List[ValidationIssue]:
        """Validate that all node labels exist in schema"""
        issues = []

        for alias, label, _ in nodes:
            if label not in self.node_types:
                location = f"Node: {alias if alias else '(anonymous)'}:{label}"
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    message=f"Unknown node label '{label}' not found in schema",
                    location=location,
                    suggestion=f"Valid node types: {', '.join(sorted(self.node_types))}"
                ))

        return issues

    def validate_relationship_types(self, rels: List[str]) -> List[ValidationIssue]:
        """Validate that all relationship types exist in schema"""
        issues = []

        for rel_type in set(rels):
            if rel_type not in self.relationship_types:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    message=f"Unknown relationship type '{rel_type}' not found in schema",
                    location=f"Relationship: [:{rel_type}]",
                    suggestion=f"Valid relationship types: {', '.join(sorted(self.relationship_types))}"
                ))

        return issues

    def validate_edges(self, edges: List[Tuple[str, str, str]]) -> List[ValidationIssue]:
        """Validate that edges (node-rel-node) are valid according to schema"""
        issues = []

        for from_label, rel_type, to_label in edges:
            # Skip if node labels or rel type are already invalid
            if from_label not in self.node_types or to_label not in self.node_types:
                continue
            if rel_type not in self.relationship_types:
                continue

            valid_pairs = self.valid_pairs.get(rel_type, set())

            # Check if this specific edge is valid
            if valid_pairs and (from_label, to_label) not in valid_pairs:
                location = f"Edge: ({from_label})-[:{rel_type}]->({to_label})"

                # Generate data-driven suggestions from schema
                valid_targets = sorted({t for s, t in valid_pairs if s == from_label})
                valid_sources = sorted({s for s, t in valid_pairs if t == to_label})

                suggestion_parts = []

                # Show what this source CAN connect to
                if valid_targets:
                    examples = [f"({from_label})-[:{rel_type}]->({t})" for t in valid_targets[:3]]
                    more = f" (+{len(valid_targets)-3} more)" if len(valid_targets) > 3 else ""
                    suggestion_parts.append(f"Valid patterns: {', '.join(examples)}{more}")

                # Show what CAN connect to this target (if source isn't already valid)
                if valid_sources and from_label not in valid_sources:
                    examples = [f"({s})-[:{rel_type}]->({to_label})" for s in valid_sources[:3]]
                    more = f" (+{len(valid_sources)-3} more)" if len(valid_sources) > 3 else ""
                    suggestion_parts.append(f"To reach {to_label}: {', '.join(examples)}{more}")

                suggestion = " | ".join(suggestion_parts) if suggestion_parts else f"Check schema for valid {rel_type} patterns"

                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    message=f"Invalid relationship: {rel_type} cannot connect {from_label} to {to_label}",
                    location=location,
                    suggestion=suggestion
                ))

        return issues

    def validate_properties(self, properties: List[Tuple[str, str, str]]) -> List[ValidationIssue]:
        """Validate that properties exist on the correct node types"""
        issues = []

        for alias, label, prop in properties:
            if label not in self.node_types:
                continue  # Already flagged in node validation

            node_schema = self.schema["nodes"].get(label, {})
            valid_props = node_schema.get("properties", [])

            if valid_props and prop not in valid_props:
                location = f"Property: {alias}.{prop} (on {label})"
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,  # Error because Neo4j returns wrong results (empty/null)
                    message=f"Property '{prop}' not found in schema for node type '{label}'",
                    location=location,
                    suggestion=f"Valid properties for {label}: {', '.join(sorted(valid_props[:10]))}{' ...' if len(valid_props) > 10 else ''}"
                ))

        return issues

    def validate_query_structure(self, cypher: str, nodes: List[Tuple[str, str, Optional[str]]]) -> List[ValidationIssue]:
        """Validate overall query structure for common issues"""
        issues = []

        # Check for empty query
        if not cypher.strip():
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                message="Empty query",
                location="Query"
            ))
            return issues

        # Check for MATCH clause
        if not re.search(r'\bMATCH\b', cypher, re.IGNORECASE):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                message="Query does not contain a MATCH clause",
                location="Query structure"
            ))

        # Check for RETURN clause
        if not re.search(r'\bRETURN\b', cypher, re.IGNORECASE):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                message="Query does not contain a RETURN clause",
                location="Query structure"
            ))

        # Check for unbalanced parentheses
        if cypher.count('(') != cypher.count(')'):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                message="Unbalanced parentheses in query",
                location="Query structure"
            ))

        # Check for unbalanced brackets
        if cypher.count('[') != cypher.count(']'):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                message="Unbalanced brackets in query",
                location="Query structure"
            ))

        # Check for duplicate aliases
        aliases = [alias for alias, _, _ in nodes if alias]
        if len(aliases) != len(set(aliases)):
            duplicates = {a for a in aliases if aliases.count(a) > 1}
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                message=f"Duplicate node aliases: {', '.join(duplicates)}",
                location="Node aliases"
            ))

        return issues

    def validate(self, cypher: str) -> ValidationResult:
        """
        Validate a Cypher query against the schema.

        Args:
            cypher: The Cypher query string to validate

        Returns:
            ValidationResult with detailed information about any issues found
        """
        issues = []

        # Extract components
        nodes = self.extract_nodes(cypher)
        rels = self.extract_relationships(cypher)
        edges = self.extract_edges(cypher)
        properties = self.extract_properties(cypher, nodes)

        # Run all validations
        issues.extend(self.validate_query_structure(cypher, nodes))
        issues.extend(self.validate_node_labels(nodes))
        issues.extend(self.validate_relationship_types(rels))
        issues.extend(self.validate_edges(edges))
        issues.extend(self.validate_properties(properties))

        # Determine if query is valid (no ERROR severity issues)
        errors = [i for i in issues if i.severity == ValidationSeverity.ERROR]
        is_valid = len(errors) == 0

        return ValidationResult(
            is_valid=is_valid,
            issues=issues,
            extracted_nodes=nodes,
            extracted_relationships=edges,
            extracted_properties=properties
        )


def create_default_validator(schema_path: str = "/tmp/reconciled_schema_complete.json") -> CypherQueryValidator:
    """
    Create a validator using the default reconciled schema location.

    Args:
        schema_path: Path to the reconciled schema JSON file

    Returns:
        Configured CypherQueryValidator
    """
    return CypherQueryValidator.from_json_file(schema_path)


# Pydantic validator function
def validate_cypher_query_field(validator: CypherQueryValidator, query: str) -> str:
    """
    Pydantic validator function for Cypher queries.

    Usage in Pydantic model:
        from pydantic import BaseModel, field_validator

        class QueryModel(BaseModel):
            cypher: str

            @field_validator('cypher')
            @classmethod
            def validate_cypher(cls, v):
                validator = create_default_validator()
                return validate_cypher_query_field(validator, v)

    Args:
        validator: CypherQueryValidator instance
        query: Cypher query string to validate

    Returns:
        The query string if valid

    Raises:
        ValueError: If query validation fails with errors
    """
    result = validator.validate(query)

    if not result.is_valid:
        errors = result.get_errors()
        error_msg = f"Cypher query validation failed:\n"
        for issue in errors:
            error_msg += f"  • {issue.location}: {issue.message}"
            if issue.suggestion:
                error_msg += f"\n    Suggestion: {issue.suggestion}"
            error_msg += "\n"
        raise ValueError(error_msg)

    # Log warnings but don't fail
    warnings = result.get_warnings()
    if warnings:
        import logging
        logger = logging.getLogger(__name__)
        for warning in warnings:
            logger.warning(f"{warning.location}: {warning.message}")

    return query
