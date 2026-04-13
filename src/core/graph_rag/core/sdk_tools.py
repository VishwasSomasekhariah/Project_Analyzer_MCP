"""
SDK-Compatible Tools for Claude Agent SDK Fallback

Creates in-process MCP server tools that wrap schema discovery functionality
for use with Claude SDK direct fallback. These tools use the schema_manager
directly (synchronous Python calls) and work reliably in-process.

IMPORTANT: MCP-dependent tools (neo4j_execute_query, neo4j_fuzzy_search, etc.)
are NOT included here because they would require calling an external MCP server
via async calls, which doesn't work from the Claude SDK subprocess context.
Instead, Claude should access those tools directly through external MCP servers
configured via mcp_config_path or mcp_servers in PerAgentSDKClient.

Usage:
    from src.core.graph_rag.core.sdk_tools import create_sdk_tools_server

    # Create in-process schema tools
    tools_server = create_sdk_tools_server(
        schema_manager=schema_manager,
        name="schema_tools"
    )

    # Use with ClaudeAgentOptions
    options = ClaudeAgentOptions(
        mcp_servers={"schema_tools": tools_server},  # In-process schema tools
        # External MCP servers for neo4j_execute_query, fuzzy_search, etc.
        # are configured separately via mcp_config_path
    )
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def create_sdk_tools_server(
    schema_manager,
    name: str = "schema_tools",
    version: str = "1.0.0"
):
    """
    Create an in-process MCP server with schema discovery tools.

    These tools use the schema_manager directly (synchronous Python calls)
    and work reliably in the Claude SDK subprocess context.

    NOTE: MCP-dependent tools (neo4j_execute_query, neo4j_fuzzy_search) are
    NOT included because they require async calls to external MCP servers,
    which doesn't work from the subprocess context. Use external MCP servers
    for those tools instead.

    Args:
        schema_manager: DynamicSchemaManager instance for schema queries
        name: Name of the MCP server (default: "schema_tools")
        version: Version string

    Returns:
        MCP server instance compatible with ClaudeAgentOptions.mcp_servers
    """
    try:
        from claude_agent_sdk import tool, create_sdk_mcp_server
    except ImportError as e:
        logger.error(f"claude_agent_sdk not installed: {e}")
        raise RuntimeError(
            "claude_agent_sdk is required for SDK tools. "
            "Install with: pip install claude-agent-sdk"
        ) from e

    from src.core.workflow.schema_tools import SchemaTools

    # Create schema tools wrapper
    schema_tools = SchemaTools(schema_manager)

    # Define SDK-compatible tools
    tools = []

    # =========================================================================
    # Debug/Test Tool - Simple tool to verify in-process tools work
    # =========================================================================

    @tool(
        name="test_connection",
        description="Test tool to verify SDK tools are working. Returns a simple response.",
        input_schema={}
    )
    async def test_connection(args: Dict[str, Any]) -> Dict[str, Any]:
        """Simple test tool to verify connectivity."""
        logger.info("SDK test_connection tool called!")
        return {"content": [{"type": "text", "text": "SDK in-process tools are working correctly!"}]}

    tools.append(test_connection)

    # =========================================================================
    # Schema Discovery Tools
    # =========================================================================

    @tool(
        name="get_node_labels",
        description="Get all valid node labels in the schema. Use this to check if a node type exists before using it in a query.",
        input_schema={}
    )
    async def get_node_labels(args: Dict[str, Any]) -> Dict[str, Any]:
        """Get all valid node labels."""
        try:
            result = schema_tools.get_node_labels()
            return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    tools.append(get_node_labels)

    @tool(
        name="get_valid_pairs",
        description="Get valid (from, to) node type pairs for a relationship type. ALWAYS call this before using a relationship in your query!",
        input_schema={"relationship_type": str}
    )
    async def get_valid_pairs(args: Dict[str, Any]) -> Dict[str, Any]:
        """Get valid node pairs for a relationship."""
        try:
            rel_type = args.get("relationship_type", "")
            result = schema_tools.get_valid_pairs(rel_type)
            return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    tools.append(get_valid_pairs)

    @tool(
        name="validate_relationship_triplet",
        description="Validate if a specific (source)-[rel]->(target) triplet exists in the schema. Use this to check if a specific relationship between two node types is valid.",
        input_schema={"from_label": str, "relationship_type": str, "to_label": str}
    )
    async def validate_relationship_triplet(args: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a relationship triplet."""
        try:
            from_label = args.get("from_label", "")
            rel_type = args.get("relationship_type", "")
            to_label = args.get("to_label", "")
            result = schema_tools.validate_relationship_triplet(from_label, rel_type, to_label)
            return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    tools.append(validate_relationship_triplet)

    @tool(
        name="get_node_properties",
        description="Get properties available for a node type. Use this to know what properties you can query on a specific node label.",
        input_schema={"label": str}
    )
    async def get_node_properties(args: Dict[str, Any]) -> Dict[str, Any]:
        """Get properties for a node type."""
        try:
            label = args.get("label", "")
            result = schema_tools.get_node_properties(label)
            return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    tools.append(get_node_properties)

    @tool(
        name="get_outgoing_relationships",
        description="Get relationships that go out from a node type. Use this to discover what relationships are available from a specific node label.",
        input_schema={"label": str}
    )
    async def get_outgoing_relationships(args: Dict[str, Any]) -> Dict[str, Any]:
        """Get outgoing relationships for a node type."""
        try:
            label = args.get("label", "")
            result = schema_tools.get_outgoing_relationships(label)
            return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    tools.append(get_outgoing_relationships)

    @tool(
        name="get_incoming_relationships",
        description="Get relationships that come into a node type. Use this to discover what relationships point to a specific node label.",
        input_schema={"label": str}
    )
    async def get_incoming_relationships(args: Dict[str, Any]) -> Dict[str, Any]:
        """Get incoming relationships for a node type."""
        try:
            label = args.get("label", "")
            result = schema_tools.get_incoming_relationships(label)
            return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    tools.append(get_incoming_relationships)

    @tool(
        name="get_schema_overview",
        description="Get a high-level overview of the schema including all node types and their descriptions. Call this first to understand what's in the database.",
        input_schema={}
    )
    async def get_schema_overview(args: Dict[str, Any]) -> Dict[str, Any]:
        """Get schema overview."""
        try:
            result = schema_tools.get_schema_overview()
            return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    tools.append(get_schema_overview)

    # =========================================================================
    # NOTE: MCP-dependent tools (neo4j_execute_query, neo4j_fuzzy_search,
    # resolve_symbol) are NOT included here. They require async calls to
    # external MCP servers which doesn't work from the Claude SDK subprocess.
    #
    # Claude should access those tools directly via external MCP servers
    # configured in PerAgentSDKClient (e.g., mcp__neo4j_memory__execute_query).
    # =========================================================================

    logger.info(f"Created SDK schema tools server '{name}' with {len(tools)} tools")

    # Create and return the MCP server
    return create_sdk_mcp_server(
        name=name,
        version=version,
        tools=tools
    )


def get_schema_tool_names(server_name: str = "schema_tools") -> List[str]:
    """
    Get the list of in-process schema tool names for ClaudeAgentOptions.

    These are the tools that use schema_manager directly and work in-process.
    For MCP-dependent tools (neo4j_execute_query, etc.), configure external
    MCP servers via mcp_config_path or mcp_servers.

    Args:
        server_name: Name of the in-process MCP server

    Returns:
        List of fully-qualified tool names (e.g., "mcp__schema_tools__get_node_labels")
    """
    schema_tools = [
        "test_connection",  # Debug tool
        "get_node_labels",
        "get_valid_pairs",
        "validate_relationship_triplet",
        "get_node_properties",
        "get_outgoing_relationships",
        "get_incoming_relationships",
        "get_schema_overview",
    ]

    return [f"mcp__{server_name}__{tool}" for tool in schema_tools]


# Backwards compatibility alias
def get_allowed_tool_names(server_name: str = "schema_tools", include_mcp: bool = True) -> List[str]:
    """
    DEPRECATED: Use get_schema_tool_names() instead.

    MCP-dependent tools are no longer included in in-process SDK tools.
    They should be accessed via external MCP servers.
    """
    logger.warning(
        "get_allowed_tool_names() is deprecated. Use get_schema_tool_names() instead. "
        "MCP tools should be accessed via external MCP servers, not in-process tools."
    )
    return get_schema_tool_names(server_name)


__all__ = [
    'create_sdk_tools_server',
    'get_schema_tool_names',
    'get_allowed_tool_names',  # Deprecated, kept for backwards compatibility
]
