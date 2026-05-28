"""
IR Context for efficient alias resolution and schema lookup.

The IRContext is built from a QueryIR and provides O(1) lookups for:
- Alias → Node label mapping
- Alias → Available properties mapping
- Relationship validation between node types

This module is used by IRValidator and CypherCompiler to avoid
repeated traversal of the IR structure.

Security Considerations:
- Context is immutable after construction
- All schema lookups use validated identifiers
"""

import logging
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .models import QueryIR, RelationshipDirection


logger = logging.getLogger(__name__)


class SchemaInfo(BaseModel):
    """
    Schema information extracted from DynamicSchemaManager.

    This is a snapshot of schema data needed for IR validation,
    isolated from the full schema manager to enable testing.
    """
    model_config = ConfigDict(frozen=True)

    # Node labels and their properties
    node_labels: FrozenSet[str] = Field(
        default_factory=frozenset,
        description="All valid node labels in the schema"
    )
    node_properties: Dict[str, FrozenSet[str]] = Field(
        default_factory=dict,
        description="Mapping of node label -> available properties"
    )

    # Relationship types and their properties
    relationship_types: FrozenSet[str] = Field(
        default_factory=frozenset,
        description="All valid relationship types"
    )
    relationship_properties: Dict[str, FrozenSet[str]] = Field(
        default_factory=dict,
        description="Mapping of relationship type -> properties"
    )

    # Valid connections (source_label, rel_type, target_label)
    valid_connections: FrozenSet[Tuple[str, str, str]] = Field(
        default_factory=frozenset,
        description="Set of (from_label, rel_type, to_label) tuples"
    )

    def has_node_label(self, label: str) -> bool:
        """Check if a node label exists in schema."""
        return label in self.node_labels

    def has_relationship_type(self, rel_type: str) -> bool:
        """Check if a relationship type exists in schema."""
        return rel_type in self.relationship_types

    def has_property(self, label: str, property_name: str) -> bool:
        """Check if a property exists on a node label."""
        props = self.node_properties.get(label, frozenset())
        return property_name in props

    def has_relationship_property(self, rel_type: str, property_name: str) -> bool:
        """Check if a property exists on a relationship type."""
        props = self.relationship_properties.get(rel_type, frozenset())
        return property_name in props

    def is_valid_connection(
        self,
        from_label: str,
        rel_type: str,
        to_label: str,
        direction: RelationshipDirection = RelationshipDirection.OUTGOING
    ) -> bool:
        """
        Check if a connection is valid in the schema.

        For BOTH direction, checks either direction.
        """
        if direction == RelationshipDirection.OUTGOING:
            return (from_label, rel_type, to_label) in self.valid_connections
        elif direction == RelationshipDirection.INCOMING:
            return (to_label, rel_type, from_label) in self.valid_connections
        else:  # BOTH
            return (
                (from_label, rel_type, to_label) in self.valid_connections or
                (to_label, rel_type, from_label) in self.valid_connections
            )

    def get_properties(self, label: str) -> FrozenSet[str]:
        """Get all properties for a node label."""
        return self.node_properties.get(label, frozenset())

    def get_all_labels_with_property(self, property_name: str) -> List[str]:
        """Find all node labels that have a specific property."""
        return [
            label for label, props in self.node_properties.items()
            if property_name in props
        ]

    @classmethod
    def from_schema_manager(cls, schema_manager: Any) -> "SchemaInfo":
        """
        Build SchemaInfo from a DynamicSchemaManager.

        Args:
            schema_manager: The DynamicSchemaManager instance

        Returns:
            Immutable SchemaInfo snapshot
        """
        try:
            # Prefer reconciled schema (actual CPG representation) over full_schema
            reconciled = getattr(schema_manager, '_reconciled_schema', None)
            full_schema = reconciled if reconciled else schema_manager.get_full_schema()

            if not full_schema:
                logger.warning("No schema available from schema manager")
                return cls()

            node_labels: Set[str] = set()
            node_properties: Dict[str, FrozenSet[str]] = {}
            relationship_types: Set[str] = set()
            relationship_properties: Dict[str, FrozenSet[str]] = {}
            valid_connections: Set[Tuple[str, str, str]] = set()

            # Extract node information
            if 'nodes' in full_schema:
                for node_name, node_info in full_schema['nodes'].items():
                    node_labels.add(node_name)
                    props = set()
                    if isinstance(node_info, dict):
                        # Handle properties list (from reconciled schema)
                        if 'properties' in node_info:
                            prop_data = node_info['properties']
                            if isinstance(prop_data, list):
                                # Reconciled schema: properties is a list
                                for prop_name in prop_data:
                                    props.add(prop_name)
                            elif isinstance(prop_data, dict):
                                # YAML schema: properties is a dict
                                for prop_name in prop_data.keys():
                                    props.add(prop_name)
                    node_properties[node_name] = frozenset(props)

            # Extract relationship information
            if 'relationships' in full_schema:
                for rel_name, rel_info in full_schema['relationships'].items():
                    relationship_types.add(rel_name)
                    props = set()
                    if isinstance(rel_info, dict):
                        # Extract valid_pairs (from reconciled schema)
                        # Format: [{'from': 'Project', 'to': 'File'}, ...]
                        if 'valid_pairs' in rel_info:
                            for pair in rel_info['valid_pairs']:
                                if isinstance(pair, dict):
                                    from_l = pair.get('from')
                                    to_l = pair.get('to')
                                    if from_l and to_l:
                                        valid_connections.add((from_l, rel_name, to_l))

                        # Also handle 'connections' format (legacy/alternate structure)
                        if 'connections' in rel_info:
                            for conn in rel_info['connections']:
                                if isinstance(conn, dict):
                                    from_l = conn.get('from', conn.get('source'))
                                    to_l = conn.get('to', conn.get('target'))
                                    if from_l and to_l:
                                        valid_connections.add((from_l, rel_name, to_l))

                        # Handle from_labels/to_labels (from APOC schema)
                        # This creates cartesian product of all valid pairs
                        if 'from_labels' in rel_info and 'to_labels' in rel_info:
                            from_labels = rel_info['from_labels']
                            to_labels = rel_info['to_labels']
                            if isinstance(from_labels, list) and isinstance(to_labels, list):
                                for from_l in from_labels:
                                    for to_l in to_labels:
                                        valid_connections.add((from_l, rel_name, to_l))

                        # Extract properties
                        if 'properties' in rel_info:
                            prop_data = rel_info['properties']
                            if isinstance(prop_data, list):
                                for prop_name in prop_data:
                                    props.add(prop_name)
                            elif isinstance(prop_data, dict):
                                for prop_name in prop_data.keys():
                                    props.add(prop_name)
                    relationship_properties[rel_name] = frozenset(props)

            # Also use _valid_rel_pairs directly if available (most accurate source)
            if hasattr(schema_manager, '_valid_rel_pairs') and schema_manager._valid_rel_pairs:
                for rel_type, pairs in schema_manager._valid_rel_pairs.items():
                    relationship_types.add(rel_type)
                    for pair in pairs:
                        if isinstance(pair, dict):
                            from_l = pair.get('from')
                            to_l = pair.get('to')
                            if from_l and to_l:
                                valid_connections.add((from_l, rel_type, to_l))

            logger.debug(
                f"SchemaInfo built: {len(node_labels)} nodes, "
                f"{len(relationship_types)} relationships, "
                f"{len(valid_connections)} valid connections"
            )

            return cls(
                node_labels=frozenset(node_labels),
                node_properties=node_properties,
                relationship_types=frozenset(relationship_types),
                relationship_properties=relationship_properties,
                valid_connections=frozenset(valid_connections)
            )

        except Exception as e:
            logger.error(f"Failed to build SchemaInfo from schema manager: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Return empty schema on error (validation will catch missing elements)
            return cls()

    @classmethod
    def empty(cls) -> "SchemaInfo":
        """Create an empty schema info (for testing)."""
        return cls()


class IRContext(BaseModel):
    """
    Runtime context for IR validation and compilation.

    Provides O(1) lookups for:
    - Alias → label mapping
    - Alias → available properties
    - Projection output names

    This is built once per IR and reused across validation layers.

    Example:
        ir = QueryIR(...)
        schema = SchemaInfo.from_schema_manager(manager)
        ctx = IRContext.from_ir(ir, schema)

        label = ctx.get_label_for_alias("fn")  # "Function"
        props = ctx.get_properties_for_alias("fn")  # {"name", "cyclomatic_complexity", ...}
    """
    model_config = ConfigDict(frozen=True)

    # Alias resolution table
    alias_to_label: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of alias → node label"
    )

    # Properties available for each alias (from schema)
    alias_to_properties: Dict[str, FrozenSet[str]] = Field(
        default_factory=dict,
        description="Mapping of alias → available properties"
    )

    # Relationship alias resolution
    rel_alias_to_type: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of relationship alias → relationship type"
    )

    # Output projection names
    output_names: FrozenSet[str] = Field(
        default_factory=frozenset,
        description="All projection output names"
    )

    # Reference to schema info (named schema_info to avoid shadowing BaseModel.schema)
    schema_info: SchemaInfo = Field(
        default_factory=SchemaInfo.empty,
        description="Schema information for validation"
    )

    def get_label_for_alias(self, alias: str) -> Optional[str]:
        """
        Get the node label for an alias.

        Args:
            alias: The alias to look up

        Returns:
            Node label or None if alias not found
        """
        return self.alias_to_label.get(alias)

    def get_properties_for_alias(self, alias: str) -> FrozenSet[str]:
        """
        Get available properties for an alias.

        Args:
            alias: The alias to look up

        Returns:
            Set of property names (empty if alias not found)
        """
        return self.alias_to_properties.get(alias, frozenset())

    def has_alias(self, alias: str) -> bool:
        """Check if an alias is defined."""
        return alias in self.alias_to_label

    def has_output_name(self, name: str) -> bool:
        """Check if an output projection name exists."""
        return name in self.output_names

    def get_relationship_type(self, rel_alias: str) -> Optional[str]:
        """Get relationship type for a relationship alias."""
        return self.rel_alias_to_type.get(rel_alias)

    def is_property_valid(self, alias: str, property_name: str) -> bool:
        """
        Check if a property is valid for an alias.

        Args:
            alias: The alias to check
            property_name: The property name to check

        Returns:
            True if the property exists on the alias's node type
        """
        return property_name in self.alias_to_properties.get(alias, frozenset())

    @classmethod
    def from_ir(cls, ir: QueryIR, schema: SchemaInfo) -> "IRContext":
        """
        Build IRContext from a QueryIR and schema.

        Args:
            ir: The QueryIR to build context for
            schema: Schema information for property lookup

        Returns:
            Immutable IRContext
        """
        alias_to_label: Dict[str, str] = {}
        alias_to_properties: Dict[str, FrozenSet[str]] = {}
        rel_alias_to_type: Dict[str, str] = {}

        # Process targets
        for target in ir.targets:
            alias_to_label[target.alias] = target.node_label
            alias_to_properties[target.alias] = schema.get_properties(target.node_label)

        # Process traversal steps
        if ir.traversal:
            for step in ir.traversal.steps:
                alias_to_label[step.to_alias] = step.to_label
                alias_to_properties[step.to_alias] = schema.get_properties(step.to_label)
                if step.relationship_alias:
                    rel_alias_to_type[step.relationship_alias] = step.relationship

        # Collect output names
        output_names = frozenset(p.output_name for p in ir.projections)

        return cls(
            alias_to_label=alias_to_label,
            alias_to_properties=alias_to_properties,
            rel_alias_to_type=rel_alias_to_type,
            output_names=output_names,
            schema_info=schema
        )

    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the context for debugging.

        Returns:
            Dict with context information
        """
        return {
            "aliases": dict(self.alias_to_label),
            "relationship_aliases": dict(self.rel_alias_to_type),
            "output_names": list(self.output_names),
            "schema_nodes": list(self.schema_info.node_labels),
            "schema_relationships": list(self.schema_info.relationship_types)
        }


__all__ = [
    'SchemaInfo',
    'IRContext',
]
