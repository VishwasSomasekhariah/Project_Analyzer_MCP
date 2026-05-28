"""
Schema Discovery Tools for LLM Query Generation

These tools allow the LLM to interactively discover schema information
instead of having the entire schema embedded in prompts.

Usage:
    tools = SchemaTools(dynamic_schema_manager)
    result = tools.get_node_labels()
    result = tools.get_valid_pairs("REFERENCES")
"""

from typing import Dict, List, Any, Optional
import logging
from difflib import get_close_matches

logger = logging.getLogger(__name__)


class SchemaTools:
    """
    Provides 8 essential schema discovery tools for LLM query generation.

    All methods return JSON-serializable dictionaries that can be used
    directly in LLM tool responses.
    """

    def __init__(self, dynamic_schema_manager):
        """
        Initialize schema tools with a DynamicSchemaManager instance.

        Args:
            dynamic_schema_manager: Instance of DynamicSchemaManager with reconciled schema
        """
        self.schema_manager = dynamic_schema_manager
        self._reconciled_schema = dynamic_schema_manager._reconciled_schema

    def get_node_labels(self) -> Dict[str, Any]:
        """
        Tool 1: Get all valid node labels in the schema.

        Prevents hallucinated labels like "StatementNode", "ExpressionStatement", "Method".

        Returns:
            {
                "labels": ["Variable", "Literal", "Type", "Function", ...],
                "count": 9
            }
        """
        labels = list(self._reconciled_schema.get('nodes', {}).keys())
        return {
            "labels": sorted(labels),
            "count": len(labels)
        }

    def get_valid_pairs(self, relationship_type: str) -> Dict[str, Any]:
        """
        Tool 2: Get valid (from, to) pairs for a relationship type.

        This is the CORE enforcement tool - prevents invalid relationship usage.

        Args:
            relationship_type: Name of relationship (e.g., "REFERENCES", "CONTAINS")

        Returns:
            {
                "relationship": "REFERENCES",
                "exists": true,
                "valid_pairs": [
                    {"from": "Variable", "to": "Type"},
                    {"from": "Function", "to": "Type"}
                ],
                "pair_count": 2,
                "description": "..."
            }

        If relationship doesn't exist:
            {
                "relationship": "INVALID_REL",
                "exists": false,
                "error": "Relationship not found in schema",
                "available_relationships": ["CALLS", "CONTAINS", ...]
            }
        """
        relationships = self._reconciled_schema.get('relationships', {})

        if relationship_type not in relationships:
            return {
                "relationship": relationship_type,
                "exists": False,
                "error": f"Relationship '{relationship_type}' not found in schema",
                "available_relationships": sorted(relationships.keys()),
                "suggestion": f"Did you mean one of: {', '.join(sorted(relationships.keys()))}?"
            }

        rel_data = relationships[relationship_type]
        valid_pairs = rel_data.get('valid_pairs', [])

        return {
            "relationship": relationship_type,
            "exists": True,
            "valid_pairs": valid_pairs,
            "pair_count": len(valid_pairs),
            "description": rel_data.get('description', ''),
            "total_instances": rel_data.get('count', 0)
        }

    def validate_relationship_triplet(self, from_label: str, relationship_type: str, to_label: str) -> Dict[str, Any]:
        """
        Tool: Validate if a SPECIFIC relationship triplet exists in the schema.

        Prevents LLM from assuming relationships work just because the relationship
        type exists. Example: REFERENCES exists for Variable->Type and Function->Type,
        but NOT for Statement->Type.

        Args:
            from_label: Source node label (e.g., "Statement")
            relationship_type: Relationship name (e.g., "REFERENCES")
            to_label: Target node label (e.g., "Type")

        Returns (when VALID):
            {
                "triplet": "Variable-[:REFERENCES]->Type",
                "is_valid": true
            }

        Returns (when INVALID):
            {
                "triplet": "Statement-[:REFERENCES]->Type",
                "is_valid": false,
                "from_alternatives": [
                    "Statement-[:CONTAINS]->Literal",
                    "Statement-[:REFERENCES]->Function"
                ],
                "to_alternatives": [
                    "Variable-[:REFERENCES]->Type",
                    "Function-[:REFERENCES]->Type"
                ]
            }
        """
        relationships = self._reconciled_schema.get('relationships', {})

        if relationship_type not in relationships:
            return {
                "triplet": f"{from_label}-[:{relationship_type}]->{to_label}",
                "is_valid": False,
                "error": f"Relationship type '{relationship_type}' does not exist",
                "available_relationships": sorted(relationships.keys())
            }

        rel_data = relationships[relationship_type]
        valid_pairs = rel_data.get('valid_pairs', [])

        # Check if this specific triplet exists
        is_valid = any(
            p.get('from') == from_label and p.get('to') == to_label
            for p in valid_pairs
        )

        triplet_str = f"{from_label}-[:{relationship_type}]->{to_label}"

        if is_valid:
            return {
                "triplet": triplet_str,
                "is_valid": True
            }

        # INVALID - Return ALL alternatives (no slicing, no hardcoding, no suggestions)
        from_alternatives = []
        for rel_name, rel_info in relationships.items():
            for p in rel_info.get('valid_pairs', []):
                if p.get('from') == from_label:
                    from_alternatives.append(f"{p['from']}-[:{rel_name}]->{p['to']}")

        to_alternatives = []
        for rel_name, rel_info in relationships.items():
            for p in rel_info.get('valid_pairs', []):
                if p.get('to') == to_label:
                    to_alternatives.append(f"{p['from']}-[:{rel_name}]->{p['to']}")

        return {
            "triplet": triplet_str,
            "is_valid": False,
            "from_alternatives": from_alternatives,
            "to_alternatives": to_alternatives
        }

    def get_outgoing_relationships(self, label: str) -> Dict[str, Any]:
        """
        Tool 3: Get all relationships where label appears as "from".

        Allows LLM to plan valid traversal paths from a starting node.

        Args:
            label: Node label (e.g., "Function", "Statement")

        Returns:
            {
                "label": "Function",
                "exists": true,
                "outgoing": {
                    "CONTAINS": ["Block", "Variable", "Parameter"],
                    "REFERENCES": ["Type"],
                    "CALLS": ["Function"]
                },
                "relationship_count": 3
            }

        If label doesn't exist:
            {
                "label": "InvalidNode",
                "exists": false,
                "error": "...",
                "available_labels": [...]
            }
        """
        nodes = self._reconciled_schema.get('nodes', {})

        if label not in nodes:
            return {
                "label": label,
                "exists": False,
                "error": f"Node label '{label}' not found in schema",
                "available_labels": sorted(nodes.keys()),
                "suggestion": f"Did you mean: {self._suggest_similar(label, nodes.keys())}?"
            }

        # Build outgoing relationships map
        relationships = self._reconciled_schema.get('relationships', {})
        outgoing = {}

        for rel_type, rel_data in relationships.items():
            valid_pairs = rel_data.get('valid_pairs', [])
            targets = []

            for pair in valid_pairs:
                if pair.get('from') == label:
                    target = pair.get('to')
                    if target not in targets:
                        targets.append(target)

            if targets:
                outgoing[rel_type] = sorted(targets)

        return {
            "label": label,
            "exists": True,
            "outgoing": outgoing,
            "relationship_count": len(outgoing),
            "can_traverse_to": sorted(set(
                target for targets in outgoing.values() for target in targets
            ))
        }

    def get_node_properties(self, label: str) -> Dict[str, Any]:
        """
        Tool 4: Get valid properties and indexed fields for a node label.

        Prevents property hallucinations like "fileName", "method", "class".

        Args:
            label: Node label (e.g., "Function", "Type")

        Returns:
            {
                "label": "Function",
                "exists": true,
                "properties": ["name", "file_path", "start_byte", "end_byte", ...],
                "indexed": ["name", "file_path"],
                "property_count": 8,
                "description": "..."
            }
        """
        nodes = self._reconciled_schema.get('nodes', {})

        if label not in nodes:
            return {
                "label": label,
                "exists": False,
                "error": f"Node label '{label}' not found in schema",
                "available_labels": sorted(nodes.keys())
            }

        node_data = nodes[label]
        properties = node_data.get('properties', [])
        indexed = node_data.get('indexed', [])

        return {
            "label": label,
            "exists": True,
            "properties": sorted(properties),
            "indexed": sorted(indexed),
            "property_count": len(properties),
            "indexed_count": len(indexed),
            "description": node_data.get('description', ''),
            "total_instances": node_data.get('count', 0)
        }

    def get_children_types(self, label: str) -> Dict[str, Any]:
        """
        Tool 6: Get node types that can be children (targets of relationships).

        Useful for understanding what a Statement, Block, or Type can contain.

        Args:
            label: Node label (e.g., "Block", "Function")

        Returns:
            {
                "label": "Block",
                "exists": true,
                "children": {
                    "via_CONTAINS": ["Statement", "Variable", "Block", "Literal"],
                    "via_REFERENCES": ["Type"]
                },
                "all_children": ["Statement", "Variable", "Block", "Literal", "Type"]
            }
        """
        # This is the same as get_outgoing_relationships but formatted differently
        outgoing = self.get_outgoing_relationships(label)

        if not outgoing.get('exists'):
            return outgoing

        # Reformat as "children via relationship"
        children_by_rel = {}
        all_children = set()

        for rel_type, targets in outgoing.get('outgoing', {}).items():
            children_by_rel[f"via_{rel_type}"] = targets
            all_children.update(targets)

        return {
            "label": label,
            "exists": True,
            "children": children_by_rel,
            "all_children": sorted(all_children),
            "child_count": len(all_children)
        }

    def get_incoming_relationships(self, label: str) -> Dict[str, Any]:
        """
        Tool 7: Get relationships where label is "to" (incoming edges).

        Useful for "find parents" logic:
        - Which nodes can contain a Block?
        - Which nodes can reference a Type?

        Args:
            label: Node label (e.g., "Type", "Block")

        Returns:
            {
                "label": "Type",
                "exists": true,
                "incoming": {
                    "CONTAINS": ["Namespace", "File", "Type"],
                    "REFERENCES": ["Variable", "Function", "Type", "Statement"]
                },
                "relationship_count": 2,
                "can_be_reached_from": ["Namespace", "File", "Type", "Variable", ...]
            }
        """
        nodes = self._reconciled_schema.get('nodes', {})

        if label not in nodes:
            return {
                "label": label,
                "exists": False,
                "error": f"Node label '{label}' not found in schema",
                "available_labels": sorted(nodes.keys())
            }

        # Build incoming relationships map
        relationships = self._reconciled_schema.get('relationships', {})
        incoming = {}

        for rel_type, rel_data in relationships.items():
            valid_pairs = rel_data.get('valid_pairs', [])
            sources = []

            for pair in valid_pairs:
                if pair.get('to') == label:
                    source = pair.get('from')
                    if source not in sources:
                        sources.append(source)

            if sources:
                incoming[rel_type] = sorted(sources)

        return {
            "label": label,
            "exists": True,
            "incoming": incoming,
            "relationship_count": len(incoming),
            "can_be_reached_from": sorted(set(
                source for sources in incoming.values() for source in sources
            ))
        }

    def get_leaf_nodes(self) -> Dict[str, Any]:
        """
        Tool 8: Get true leaf nodes - nodes with NO outgoing relationships of ANY kind.

        A true leaf node is a terminal node in the property graph that NEVER
        appears as 'from' in ANY relationship (not just CONTAINS).
        These are the absolute endpoints of graph traversal.

        Returns:
            {
                "leaf_nodes": ["Literal", "Statement"],
                "non_leaf_nodes": ["Function", "Type", "Block", "Variable", ...],
                "leaf_count": 2,
                "explanation": "Leaf nodes have no outgoing relationships - true terminals"
            }
        """
        nodes = self._reconciled_schema.get('nodes', {})
        relationships = self._reconciled_schema.get('relationships', {})

        # Find nodes that have ANY outgoing relationships (appear as 'from' in any relationship)
        nodes_with_outgoing = set()

        for rel_type, rel_data in relationships.items():
            valid_pairs = rel_data.get('valid_pairs', [])
            for pair in valid_pairs:
                # Any node that appears as 'from' has an outgoing relationship
                nodes_with_outgoing.add(pair.get('from'))

        all_nodes = set(nodes.keys())
        # True leaf nodes = nodes that NEVER appear as 'from' in ANY relationship
        leaf_nodes = all_nodes - nodes_with_outgoing
        non_leaf_nodes = nodes_with_outgoing

        return {
            "leaf_nodes": sorted(leaf_nodes),
            "non_leaf_nodes": sorted(non_leaf_nodes),
            "leaf_count": len(leaf_nodes),
            "non_leaf_count": len(non_leaf_nodes),
            "explanation": "Leaf nodes have no outgoing relationships of any kind - they are true terminal nodes in the graph"
        }

    # Helper methods

    def get_all_tools_info(self) -> Dict[str, Any]:
        """
        Get information about all available tools.

        Useful for debugging and documentation.

        Returns:
            Dictionary with tool names, descriptions, and signatures
        """
        return {
            "tools": [
                {
                    "name": "get_node_labels",
                    "description": "Get all valid node labels",
                    "parameters": [],
                    "returns": "List of node labels"
                },
                {
                    "name": "get_valid_pairs",
                    "description": "Get valid (from, to) pairs for a relationship",
                    "parameters": ["relationship_type: str"],
                    "returns": "Valid pairs and metadata"
                },
                {
                    "name": "get_outgoing_relationships",
                    "description": "Get relationships where label is 'from'",
                    "parameters": ["label: str"],
                    "returns": "Map of relationship_type -> target_labels"
                },
                {
                    "name": "get_node_properties",
                    "description": "Get properties for a node label",
                    "parameters": ["label: str"],
                    "returns": "Properties, indexed fields, and metadata"
                },
                {
                    "name": "get_children_types",
                    "description": "Get node types that can be children",
                    "parameters": ["label: str"],
                    "returns": "Children grouped by relationship"
                },
                {
                    "name": "get_incoming_relationships",
                    "description": "Get relationships where label is 'to'",
                    "parameters": ["label: str"],
                    "returns": "Map of relationship_type -> source_labels"
                },
                {
                    "name": "get_leaf_nodes",
                    "description": "Get nodes that cannot contain others",
                    "parameters": [],
                    "returns": "List of leaf nodes"
                }
            ],
            "total_tools": 7
        }
