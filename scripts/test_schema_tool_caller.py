#!/usr/bin/env python3
"""
Test Schema Tool Caller

Verifies that the SchemaToolCaller can make LLM calls with tool support
and execute tools automatically.
"""

import asyncio
import json
from src.core.llm_service import LLMService
from src.core.workflow.schema_tools_langchain import create_schema_tools
from src.core.workflow.schema_tool_caller import SchemaToolCaller


async def main():
    print("=" * 80)
    print("SCHEMA TOOL CALLER TEST")
    print("=" * 80)

    # Load reconciled schema
    with open('/tmp/reconciled_schema_complete.json', 'r') as f:
        schema = json.load(f)

    # Create mock schema manager
    class MockSchemaManager:
        def __init__(self, schema):
            self._reconciled_schema = schema

    schema_manager = MockSchemaManager(schema)

    # Create schema tools
    schema_tools = create_schema_tools(schema_manager)
    print(f"✅ Created {len(schema_tools)} schema tools\n")

    # Initialize LLM service
    llm_service = LLMService()
    print("✅ LLM service initialized\n")

    # Create tool caller
    tool_caller = SchemaToolCaller(llm_service, schema_tools)
    print("✅ Tool caller ready\n")

    # Test prompt - ask LLM to build a query using tools
    system_prompt = """You are a Cypher query expert building queries for a Code Property Graph.

You have access to schema discovery tools. Use them to understand the schema before writing queries.

Your goal: Build a valid Cypher query based on the user's request by:
1. Using tools to discover what nodes and relationships exist
2. Verifying paths using get_valid_pairs
3. Checking properties with get_node_properties
4. Writing a query using only validated schema elements"""

    user_prompt = """Build a Cypher query to find the CreateWorkers function.

Steps:
1. Use get_node_labels() to see what node types exist
2. Use get_node_properties("Function") to see what properties Function has
3. Write a simple MATCH query to find the function

Don't write the query until you've verified the schema with tools!"""

    print("=" * 80)
    print("MAKING TOOL-ENABLED LLM CALL")
    print("=" * 80)
    print(f"\nPrompt: {user_prompt}\n")

    result = await tool_caller.generate_with_tools(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model_name="gpt-4o",
        max_iterations=10
    )

    print("\n" + "=" * 80)
    print("RESULT")
    print("=" * 80)
    print(f"\nIterations: {result['iterations']}")
    print(f"Tool calls made: {result['tool_calls_made']}")
    print(f"Total tokens: {result['total_tokens']}")

    print("\n" + "=" * 80)
    print("TOOL CALL HISTORY")
    print("=" * 80)
    for i, call in enumerate(result['tool_call_history'], 1):
        print(f"\n{i}. {call['tool']}({call['args']})")
        print(f"   Iteration: {call['iteration']}")
        result_str = json.dumps(call['result'], indent=2)
        if len(result_str) > 200:
            result_str = result_str[:200] + "..."
        print(f"   Result: {result_str}")

    print("\n" + "=" * 80)
    print("FINAL ANSWER")
    print("=" * 80)
    print(result['content'])

    print("\n" + "=" * 80)
    print("✅ TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
