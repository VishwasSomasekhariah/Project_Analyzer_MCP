"""
Schema Discovery Tools for LangChain Agents

Defines the 7 schema discovery tools using LangChain's @tool decorator.
These tools allow LLM agents to interactively discover schema information
instead of having the entire schema embedded in prompts.

Usage:
    schema_manager = DynamicSchemaManager(...)
    tools = create_schema_tools(schema_manager)
    # Pass tools to your LangChain agent
"""

from typing import Dict, Any, List, Optional
from langchain_core.tools import tool
from pydantic import BaseModel, Field


class GetValidPairsInput(BaseModel):
    """Input schema for get_valid_pairs tool"""
    relationship_type: str = Field(
        description="Name of relationship (e.g., 'REFERENCES', 'CONTAINS', 'CALLS', 'IMPLEMENTS')"
    )


class ValidateRelationshipTripletInput(BaseModel):
    """Input schema for validate_relationship_triplet tool"""
    from_label: str = Field(
        description="Source node label (e.g., 'Statement', 'Function', 'Variable')"
    )
    relationship_type: str = Field(
        description="Relationship type (e.g., 'REFERENCES', 'CONTAINS', 'CALLS')"
    )
    to_label: str = Field(
        description="Target node label (e.g., 'Type', 'Function', 'Block')"
    )


class GetNodePropertiesInput(BaseModel):
    """Input schema for get_node_properties tool"""
    label: str = Field(
        description="Node label (e.g., 'Function', 'Type', 'Variable', 'Statement', 'Block')"
    )


class GetOutgoingRelationshipsInput(BaseModel):
    """Input schema for get_outgoing_relationships tool"""
    label: str = Field(
        description="Node label to find outgoing relationships from (e.g., 'Function', 'Block')"
    )


class GetIncomingRelationshipsInput(BaseModel):
    """Input schema for get_incoming_relationships tool"""
    label: str = Field(
        description="Node label to find incoming relationships to (e.g., 'Type', 'Statement')"
    )


class GetChildrenTypesInput(BaseModel):
    """Input schema for get_children_types tool"""
    label: str = Field(
        description="Node label to find children types for (e.g., 'Block', 'Function', 'Type')"
    )


class SearchCodebaseInput(BaseModel):
    """Input schema for search_codebase tool"""
    search_term: str = Field(
        description="Code element to search for (e.g., 'WorkerZ', 'Helper.FormatMessage', 'ProcessData()'). "
                    "Can include dots, parentheses - they will be handled automatically."
    )


def _preprocess_fuzzy_term(term: str) -> str:
    """
    Preprocess search term for fuzzy fulltext search.

    Handles:
    - Dots: "Helper.FormatMessage" -> "Helper~ AND FormatMessage~"
    - Parentheses: "ProcessData()" -> "ProcessData~"
    - Spaces: "some func" -> "some~ AND func~"
    - Special chars: removed

    Args:
        term: Raw search term from user/LLM

    Returns:
        Processed query string for Lucene fulltext search
    """
    import re

    # Remove parentheses and brackets
    term = re.sub(r'[(){}\[\]]', '', term)

    # Split on dots, spaces, underscores, and other delimiters
    parts = re.split(r'[.\s_\-:]+', term)

    # Filter empty parts and strip whitespace
    parts = [p.strip() for p in parts if p.strip()]

    if not parts:
        return ""

    # Create fuzzy search terms with AND
    fuzzy_parts = [f"{p}~" for p in parts]

    return " AND ".join(fuzzy_parts)


def create_schema_tools(schema_manager, cypher_server=None) -> List:
    """
    Create LangChain tools for schema discovery and entity search.

    Args:
        schema_manager: DynamicSchemaManager instance with reconciled schema
        cypher_server: Optional CypherServerPool for executing queries (enables fuzzy search)

    Returns:
        List of LangChain tools for schema discovery (+ fuzzy search if cypher_server provided)
    """
    from src.core.workflow.schema_tools import SchemaTools

    # Create SchemaTools wrapper
    schema_tools = SchemaTools(schema_manager)

    @tool
    def get_node_labels() -> Dict[str, Any]:
        """Get all valid node labels in the schema.

        Use this to check if a node type exists before using it in a query.
        Prevents hallucinated labels like 'StatementNode', 'ExpressionStatement', 'Method'.

        Returns dictionary with:
        - labels: List of valid node label strings
        - count: Total number of node types

        Example:
        >>> get_node_labels()
        {"labels": ["Function", "Type", "Variable", "Statement", ...], "count": 9}
        """
        return schema_tools.get_node_labels()

    @tool(args_schema=GetValidPairsInput)
    def get_valid_pairs(relationship_type: str) -> Dict[str, Any]:
        """Get valid (from, to) node type pairs for a relationship type.

        This is the CORE enforcement tool - prevents invalid relationship usage.
        Use this to verify if a specific relationship between two node types is allowed.

        Args:
            relationship_type: Name of relationship (e.g., 'REFERENCES', 'CONTAINS')

        Returns dictionary with:
        - relationship: The relationship type queried
        - exists: Whether the relationship exists in schema
        - valid_pairs: List of {from: str, to: str} dictionaries
        - pair_count: Number of valid pairs
        - description: Human-readable description of the relationship

        Example:
        >>> get_valid_pairs("CONTAINS")
        {
            "relationship": "CONTAINS",
            "exists": true,
            "valid_pairs": [
                {"from": "Function", "to": "Block"},
                {"from": "Block", "to": "Statement"},
                ...
            ],
            "pair_count": 13
        }

        ALWAYS call this before using a relationship in your query!
        """
        return schema_tools.get_valid_pairs(relationship_type)

    @tool(args_schema=ValidateRelationshipTripletInput)
    def validate_relationship_triplet(from_label: str, relationship_type: str, to_label: str) -> Dict[str, Any]:
        """Validate if a SPECIFIC relationship triplet (source-[rel]->target) exists in the schema.

        This is the MOST PRECISE validation tool. While get_valid_pairs() returns ALL valid pairs
        for a relationship type, this tool checks if ONE SPECIFIC combination is valid.

        CRITICAL: Do NOT assume a relationship works just because the relationship type exists!
        Example: REFERENCES exists for Variable->Type and Function->Type, but NOT Statement->Type.

        Args:
            from_label: Source node label (e.g., 'Statement')
            relationship_type: Relationship name (e.g., 'REFERENCES')
            to_label: Target node label (e.g., 'Type')

        Returns when VALID:
            {
                "triplet": "Variable-[:REFERENCES]->Type",
                "is_valid": true
            }

        Returns when INVALID:
            {
                "triplet": "Statement-[:REFERENCES]->Type",
                "is_valid": false,
                "from_alternatives": [
                    "Statement-[:CONTAINS]->Literal",
                    "Statement-[:CONTAINS]->Variable"
                ],
                "to_alternatives": [
                    "Variable-[:REFERENCES]->Type",
                    "Function-[:REFERENCES]->Type"
                ]
            }

        Use this BEFORE including any relationship in your query plan!
        If is_valid is false, use the alternatives to find valid paths.
        """
        return schema_tools.validate_relationship_triplet(from_label, relationship_type, to_label)

    @tool(args_schema=GetOutgoingRelationshipsInput)
    def get_outgoing_relationships(label: str) -> Dict[str, Any]:
        """Get all relationships where the specified label appears as 'from' (source node).

        Allows planning valid traversal paths from a starting node.
        Returns a map of relationship_type -> [target_node_types].

        Args:
            label: Node label (e.g., 'Function', 'Statement', 'Type')

        Returns dictionary with:
        - label: The node label queried
        - exists: Whether the label exists in schema
        - outgoing: Map of relationship_type -> list of target labels
        - relationship_count: Number of different relationship types
        - can_traverse_to: All unique target nodes reachable

        Example:
        >>> get_outgoing_relationships("Function")
        {
            "label": "Function",
            "exists": true,
            "outgoing": {
                "CONTAINS": ["Block", "Variable"],
                "CALLS": ["Function"],
                "REFERENCES": ["Type", "Block"]
            },
            "relationship_count": 3,
            "can_traverse_to": ["Block", "Variable", "Function", "Type"]
        }
        """
        return schema_tools.get_outgoing_relationships(label)

    @tool(args_schema=GetNodePropertiesInput)
    def get_node_properties(label: str) -> Dict[str, Any]:
        """Get valid properties and indexed fields for a node label.

        Prevents property hallucinations like 'fileName', 'method', 'class'.
        Returns list of valid properties and which ones are indexed for efficient queries.

        Args:
            label: Node label (e.g., 'Function', 'Type', 'Variable')

        Returns dictionary with:
        - label: The node label queried
        - exists: Whether the label exists in schema
        - properties: List of all valid property names
        - indexed: List of properties that have indexes (efficient for WHERE clauses)
        - property_count: Total number of properties
        - description: Human-readable description of this node type

        Example:
        >>> get_node_properties("Function")
        {
            "label": "Function",
            "exists": true,
            "properties": ["name", "body", "file_path", "start_byte", "end_byte", ...],
            "indexed": ["name", "body", "file_path"],
            "property_count": 12,
            "description": "Represents a function, method, or procedure..."
        }

        ALWAYS call this before filtering on properties!
        """
        return schema_tools.get_node_properties(label)

    @tool(args_schema=GetChildrenTypesInput)
    def get_children_types(label: str) -> Dict[str, Any]:
        """Get node types that can be children (targets) of the specified label.

        Useful for understanding what a Statement, Block, or Type can contain.
        Returns children grouped by relationship type.

        Args:
            label: Node label (e.g., 'Block', 'Function', 'Type')

        Returns dictionary with:
        - label: The node label queried
        - exists: Whether the label exists in schema
        - children: Map of "via_<REL_TYPE>" -> list of child labels
        - all_children: All unique child node types
        - child_count: Total number of unique children types

        Example:
        >>> get_children_types("Block")
        {
            "label": "Block",
            "exists": true,
            "children": {
                "via_CONTAINS": ["Statement", "Variable", "Block", "Literal"]
            },
            "all_children": ["Statement", "Variable", "Block", "Literal"],
            "child_count": 4
        }
        """
        return schema_tools.get_children_types(label)

    @tool(args_schema=GetIncomingRelationshipsInput)
    def get_incoming_relationships(label: str) -> Dict[str, Any]:
        """Get relationships where the specified label is 'to' (target node).

        Useful for 'find parents' logic:
        - Which nodes can contain a Block?
        - Which nodes can reference a Type?

        Returns a map of relationship_type -> [source_node_types].

        Args:
            label: Node label (e.g., 'Type', 'Block', 'Statement')

        Returns dictionary with:
        - label: The node label queried
        - exists: Whether the label exists in schema
        - incoming: Map of relationship_type -> list of source labels
        - relationship_count: Number of different relationship types
        - can_be_reached_from: All unique source nodes that can reach this node

        Example:
        >>> get_incoming_relationships("Type")
        {
            "label": "Type",
            "exists": true,
            "incoming": {
                "CONTAINS": ["File", "Namespace"],
                "REFERENCES": ["Function", "Variable", "Type"],
                "IMPLEMENTS": ["Type", "Function"]
            },
            "relationship_count": 3,
            "can_be_reached_from": ["File", "Namespace", "Function", "Variable", "Type"]
        }
        """
        return schema_tools.get_incoming_relationships(label)

    @tool
    def get_leaf_nodes() -> Dict[str, Any]:
        """Get true leaf nodes - nodes with NO outgoing relationships of ANY kind.

        A true leaf node is a terminal node in the property graph that NEVER appears as 'from'
        in ANY relationship (not just CONTAINS). These are the absolute endpoints of graph traversal.

        Returns dictionary with:
        - leaf_nodes: List of node labels that are true leaves (no outgoing relationships)
        - non_leaf_nodes: List of node labels that have outgoing relationships
        - leaf_count: Number of leaf node types
        - explanation: Description of what makes a node a leaf

        Example:
        >>> get_leaf_nodes()
        {
            "leaf_nodes": ["Literal", "Statement"],
            "non_leaf_nodes": ["Block", "Function", "Type", "File", "Project", "Namespace", "Variable"],
            "leaf_count": 2,
            "explanation": "Leaf nodes have no outgoing relationships of any kind..."
        }

        Use this to identify terminal nodes that can only be targets, never sources of relationships.
        """
        return schema_tools.get_leaf_nodes()

    # Build tools list
    tools = [
        get_node_labels,
        get_valid_pairs,
        validate_relationship_triplet,
        get_outgoing_relationships,
        get_node_properties,
        get_children_types,
        get_incoming_relationships,
        get_leaf_nodes
    ]

    # Add fuzzy search tool if cypher_server is available
    if cypher_server is not None:
        import asyncio
        import logging
        _logger = logging.getLogger(__name__)

        @tool(args_schema=SearchCodebaseInput)
        def search_codebase(search_term: str) -> Dict[str, Any]:
            """Search the codebase for a code element (class, method, variable, type, etc.) by name.

            - Input: one string `search_term` (e.g. "SomeClass.MethodName" or "FooBarzzz").
            - Behavior: searches across name, body, value, text fields to find matching code elements.
            - Important: do NOT decompose `search_term` into substrings for separate searches — a single search call is sufficient and preferable.
            - Output: a result object containing:
                - original search_term,
                - processed query string,
                - boolean `found`,
                - integer `result_count`,
                - list `results` (each with node id, labels, name property if present, score, and some properties snippet),
                - possibly an `error` if query failed or input was invalid.

            Use this tool to check if code elements exist in the codebase and get their details. Treat returned items as **candidates** and verify context before assuming a match.
            """
            processed_term = _preprocess_fuzzy_term(search_term)

            if not processed_term:
                return {
                    "search_term": search_term,
                    "processed_query": "",
                    "found": False,
                    "result_count": 0,
                    "results": [],
                    "error": "Could not parse search term"
                }

            # Fuzzy search query - truncate body to 150 chars for readability
            cypher_query = f"""
            CALL db.index.fulltext.queryNodes('FuzzySearchIdx', '{processed_term}')
            YIELD node, score
            WITH node, score,
                 [p IN ['name','text','value','body']
                  WHERE node[p] IS NOT NULL
                  | p + ': ' + substring(toString(node[p]), 0, 150)
                 ] AS presentProps
            WHERE score >= 0.5
            RETURN
              labels(node) AS labels,
              presentProps,
              id(node) AS id,
              score
            ORDER BY score DESC
            LIMIT 15
            """

            try:
                # Execute the async query using nest_asyncio to handle nested event loops
                import nest_asyncio
                nest_asyncio.apply()

                # Now we can safely run async code even in a running event loop
                loop = asyncio.get_event_loop()
                response = loop.run_until_complete(
                    cypher_server.execute_query(cypher_query)
                )

                # Note: CypherServerPool returns results in 'data' field, not 'results'
                raw_results = response.get('data', []) or response.get('results', [])

                # Parse results into cleaner format for LLM
                parsed_results = []
                for r in raw_results:
                    props = r.get('presentProps', [])
                    # Extract name from presentProps
                    name = None
                    for p in props:
                        if p.startswith('name:'):
                            name = p.split(':', 1)[1].strip()
                            break

                    parsed_results.append({
                        "labels": r.get('labels', []),
                        "name": name,
                        "properties": props,
                        "id": r.get('id'),
                        "score": round(r.get('score', 0), 2)
                    })

                return {
                    "search_term": search_term,
                    "processed_query": processed_term,
                    "found": len(parsed_results) > 0,
                    "result_count": len(parsed_results),
                    "results": parsed_results
                }

            except Exception as e:
                _logger.error(f"Fuzzy search failed: {e}")
                return {
                    "search_term": search_term,
                    "processed_query": processed_term,
                    "found": False,
                    "result_count": 0,
                    "results": [],
                    "error": str(e)
                }

        tools.append(search_codebase)

    return tools


def get_schema_tools_instructions() -> str:
    """
    Get instructions for using schema tools in prompts.

    Returns:
        Markdown-formatted instructions for LLM
    """
    return """# SCHEMA DISCOVERY TOOLS

You have access to 8 tools for interactive schema discovery. Instead of having the entire schema embedded in this prompt, you can query it as needed.

## Available Tools

1. **get_node_labels()** - Get all valid node labels
   - Check if a node type exists before using it
   - Prevents hallucinations like "StatementNode", "Method"

2. **get_valid_pairs(relationship_type)** - Get valid (from, to) pairs for a relationship
   - ⭐ **CORE TOOL**: ALWAYS check before using a relationship
   - Example: `get_valid_pairs("CONTAINS")` returns all valid X-[:CONTAINS]->Y patterns
   - Prevents invalid paths like Statement-[:CALLS]->Type

3. **validate_relationship_triplet(from_label, relationship_type, to_label)** - Validate SPECIFIC triplet
   - 🎯 **MOST PRECISE VALIDATION**: Check if ONE specific (source-[rel]->target) combination exists
   - CRITICAL: Don't assume relationships work just because the type exists!
   - Example: REFERENCES exists for Variable->Type but NOT Statement->Type
   - Returns is_valid + alternatives if invalid
   - USE THIS BEFORE every relationship in your query plan!

4. **get_outgoing_relationships(label)** - Get relationships FROM a node
   - Plan traversal paths: "From Function, where can I go?"
   - Returns map of relationship_type -> [target_labels]

5. **get_node_properties(label)** - Get properties for a node
   - Check which properties exist before filtering
   - Returns properties[] and indexed[] fields
   - Prevents hallucinations like {fileName: "..."} or {method: "..."}

6. **get_children_types(label)** - Get nodes that can be children
   - Understand containment: "What can a Block contain?"
   - Returns children grouped by relationship

7. **get_incoming_relationships(label)** - Get relationships TO a node
   - Find parents: "What can contain a Statement?"
   - Returns map of relationship_type -> [source_labels]

8. **get_leaf_nodes()** - Get terminal nodes that cannot contain others
   - Identifies nodes like Literal, Parameter
   - These are endpoints, not containers

## Recommended Workflow

**Step 1: Check node existence**
```
get_node_labels()  // Does "Function" exist?
get_node_properties("Function")  // What properties does it have?
```

**Step 2: Discover traversal paths**
```
get_outgoing_relationships("Function")  // Where can Function go?
get_valid_pairs("CONTAINS")  // All valid X-[:CONTAINS]->Y pairs
```

**Step 3: Validate SPECIFIC relationships BEFORE using them**
```
validate_relationship_triplet("Function", "CONTAINS", "Block")  // Verify this exact combo
validate_relationship_triplet("Statement", "REFERENCES", "Type")  // Is THIS valid?
```

**Step 4: Build query incrementally**
```
get_node_properties("Block")  // Check Block properties
get_outgoing_relationships("Block")  // What's next from Block?
```

**Step 5: Write validated Cypher**
Now write your query using only verified nodes, relationships, and properties.

## Important Rules

- 🎯 **ALWAYS use `validate_relationship_triplet()` for EVERY relationship in your query**
- ✅ Use `get_valid_pairs()` to explore options, then validate with `validate_relationship_triplet()`
- ✅ ALWAYS check properties with `get_node_properties()` before filtering
- ✅ Use tools incrementally to discover the schema as you plan
- ✅ Make multiple tool calls if needed - understanding the schema is critical
- ❌ NEVER assume a triplet works just because the relationship type exists
- ❌ NEVER use properties without verifying they exist
- ❌ NEVER make up node labels"""
