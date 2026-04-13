#!/usr/bin/env python3
"""
Test LangChain Schema Tools

Verifies that the 7 schema tools work correctly with LangChain's @tool decorator.
"""

import asyncio
import json


async def main():
    print("=" * 80)
    print("LANGCHAIN SCHEMA TOOLS TEST")
    print("=" * 80)

    print("\n📊 Loading reconciled schema...")

    # Load reconciled schema
    with open('/tmp/reconciled_schema_complete.json', 'r') as f:
        reconciled_schema = json.load(f)

    # Create mock schema manager
    class MockSchemaManager:
        def __init__(self, reconciled_schema):
            self._reconciled_schema = reconciled_schema

    schema_manager = MockSchemaManager(reconciled_schema)

    # Create LangChain tools
    from src.core.workflow.schema_tools_langchain import create_schema_tools

    tools = create_schema_tools(schema_manager)

    print(f"✅ Created {len(tools)} LangChain tools\n")

    # Test each tool
    print("=" * 80)
    print("TESTING TOOLS")
    print("=" * 80)

    for tool in tools:
        print(f"\n📌 Tool: {tool.name}")
        print(f"   Description: {tool.description[:100]}...")
        print(f"   Args Schema: {tool.args_schema if hasattr(tool, 'args_schema') and tool.args_schema else 'None'}")

    print("\n" + "=" * 80)
    print("TOOL 1: get_node_labels()")
    print("=" * 80)
    result = tools[0].invoke({})
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("TOOL 2: get_valid_pairs('CONTAINS')")
    print("=" * 80)
    result = tools[1].invoke({"relationship_type": "CONTAINS"})
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("TOOL 3: get_outgoing_relationships('Function')")
    print("=" * 80)
    result = tools[2].invoke({"label": "Function"})
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("TOOL 4: get_node_properties('Statement')")
    print("=" * 80)
    result = tools[3].invoke({"label": "Statement"})
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("TOOL 5: get_children_types('Block')")
    print("=" * 80)
    result = tools[4].invoke({"label": "Block"})
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("TOOL 6: get_incoming_relationships('Type')")
    print("=" * 80)
    result = tools[5].invoke({"label": "Type"})
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("TOOL 7: get_leaf_nodes()")
    print("=" * 80)
    result = tools[6].invoke({})
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("✅ ALL TOOLS TESTED SUCCESSFULLY")
    print("=" * 80)

    # Test tool conversion to OpenAI format (for LLM calling)
    print("\n" + "=" * 80)
    print("CONVERTING TO OPENAI FUNCTION CALLING FORMAT")
    print("=" * 80)

    # LangChain tools can be converted to OpenAI format
    from langchain_core.utils.function_calling import convert_to_openai_tool

    openai_tools = [convert_to_openai_tool(tool) for tool in tools]

    print(f"\n✅ Converted {len(openai_tools)} tools to OpenAI format\n")

    for i, tool_def in enumerate(openai_tools):
        print(f"\nTool {i+1}: {tool_def['function']['name']}")
        print(f"  Parameters: {list(tool_def['function'].get('parameters', {}).get('properties', {}).keys())}")

    print("\n" + "=" * 80)
    print("EXAMPLE: OpenAI Tool Definition for get_valid_pairs")
    print("=" * 80)
    print(json.dumps(openai_tools[1], indent=2))

    print("\n" + "=" * 80)
    print("✅ TEST COMPLETE - Tools are ready for LLM use")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
