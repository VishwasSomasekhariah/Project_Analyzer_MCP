#!/usr/bin/env python3
"""
Test Claude Agent SDK with a custom tool.

This demonstrates:
1. Creating custom tools with @tool decorator
2. Building an SDK MCP server
3. Using tools with Claude Agent SDK
"""

import asyncio
from typing import Any
from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    tool,
    create_sdk_mcp_server,
    AssistantMessage,
    TextBlock
)


# Define a simple custom tool
@tool(
    name="get_project_info",
    description="Get information about the current project",
    input_schema={"info_type": str}
)
async def get_project_info(args: dict[str, Any]) -> dict[str, Any]:
    """Return project information based on info_type."""
    info_type = args.get("info_type", "name")

    project_data = {
        "name": "GenPod - Graph-RAG Code Analysis",
        "location": "/opt/genpod",
        "description": "A multi-agent RAG system using CPG and vector embeddings",
        "models": "Currently using GPT-4o, testing Claude migration",
        "agents": "4-agent workflow: Thinker, ThinkingValidator, CypherValidator, ExecutorVerifier"
    }

    result = project_data.get(info_type, f"Unknown info type: {info_type}")

    return {
        "content": [{
            "type": "text",
            "text": f"Project {info_type}: {result}"
        }]
    }


# Define a calculator tool
@tool(
    name="calculate",
    description="Perform basic arithmetic calculations",
    input_schema={"expression": str}
)
async def calculate(args: dict[str, Any]) -> dict[str, Any]:
    """Safely evaluate a mathematical expression."""
    expression = args.get("expression", "")

    try:
        # Safe evaluation (only math operations)
        allowed_names = {
            "abs": abs, "round": round, "min": min, "max": max,
            "sum": sum, "pow": pow
        }
        result = eval(expression, {"__builtins__": {}}, allowed_names)

        return {
            "content": [{
                "type": "text",
                "text": f"Result: {result}"
            }]
        }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Calculation error: {str(e)}"
            }],
            "isError": True
        }


async def test_custom_tools():
    """Test Claude with custom tools."""
    print("=" * 70)
    print("Testing Claude Agent SDK with Custom Tools")
    print("=" * 70)

    # Create SDK MCP server with our custom tools
    my_tools_server = create_sdk_mcp_server(
        name="custom_tools",
        version="1.0.0",
        tools=[get_project_info, calculate]
    )

    # Configure Claude with the custom tools
    options = ClaudeAgentOptions(
        mcp_servers={"tools": my_tools_server},
        allowed_tools=[
            "mcp__tools__get_project_info",
            "mcp__tools__calculate"
        ]
    )

    print("\n📋 Available custom tools:")
    print("  • get_project_info - Get project information")
    print("  • calculate - Perform calculations")
    print()

    # Test 1: Ask Claude to use the project info tool
    print("=" * 70)
    print("Test 1: Project Information Tool")
    print("=" * 70)

    async for message in query(
        prompt="What is the name of this project? Use the get_project_info tool.",
        options=options
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"\n💬 Claude: {block.text}\n")

    # Test 2: Ask Claude to calculate something
    print("=" * 70)
    print("Test 2: Calculator Tool")
    print("=" * 70)

    async for message in query(
        prompt="Calculate 245586 * 0.000003 + 60847 * 0.000015 using the calculate tool",
        options=options
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"\n💬 Claude: {block.text}\n")

    print("=" * 70)
    print("✅ Custom tool tests completed!")
    print("=" * 70)


async def main():
    """Run the test."""
    print("\n🚀 Starting Custom Tool Test\n")

    try:
        await test_custom_tools()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure Claude Code CLI is installed")
        print("2. Check that you're logged in: claude auth login")
        print("3. Verify Claude Code is in PATH")
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
