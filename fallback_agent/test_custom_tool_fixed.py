#!/usr/bin/env python3
"""
Test Claude Agent SDK with custom tools using ClaudeSDKClient.
"""

import asyncio
from typing import Any
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    tool,
    create_sdk_mcp_server,
    AssistantMessage,
    TextBlock,
    ToolUseBlock
)


# Define custom tools
@tool(
    name="get_project_info",
    description="Get information about the GenPod project",
    input_schema={"info_type": str}
)
async def get_project_info(args: dict[str, Any]) -> dict[str, Any]:
    """Return project information."""
    info_type = args.get("info_type", "name")

    project_data = {
        "name": "GenPod - Graph-RAG Code Analysis",
        "description": "Multi-agent RAG using CPG and vectors",
        "agents": "4-agent: Thinker, Validators, Executor"
    }

    result = project_data.get(info_type, f"Unknown: {info_type}")

    return {
        "content": [{
            "type": "text",
            "text": f"Project {info_type}: {result}"
        }]
    }


@tool(
    name="calculate",
    description="Calculate a math expression",
    input_schema={"expression": str}
)
async def calculate(args: dict[str, Any]) -> dict[str, Any]:
    """Safely evaluate math."""
    try:
        result = eval(args["expression"], {"__builtins__": {}}, {})
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
                "text": f"Error: {e}"
            }],
            "isError": True
        }


async def test_with_client():
    """Test using ClaudeSDKClient for better control."""
    print("=" * 70)
    print("Testing Custom Tools with ClaudeSDKClient")
    print("=" * 70)

    # Create SDK MCP server
    tools_server = create_sdk_mcp_server(
        name="custom",
        version="1.0.0",
        tools=[get_project_info, calculate]
    )

    # Configure options
    options = ClaudeAgentOptions(
        mcp_servers={"custom": tools_server},
        allowed_tools=[
            "mcp__custom__get_project_info",
            "mcp__custom__calculate"
        ]
    )

    print("\n✅ Custom tools registered\n")

    # Use ClaudeSDKClient for better connection handling
    async with ClaudeSDKClient(options=options) as client:
        # Test 1: Project info
        print("Test 1: Ask about project name")
        print("-" * 70)

        await client.query("What is the name of this project? Use get_project_info tool with info_type='name'")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"💬 Claude: {block.text}")
                    elif isinstance(block, ToolUseBlock):
                        print(f"🔧 Tool used: {block.name}({block.input})")

        # Test 2: Calculate
        print("\n\nTest 2: Calculate token cost")
        print("-" * 70)

        await client.query("Calculate 245586 * 0.000003")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"💬 Claude: {block.text}")
                    elif isinstance(block, ToolUseBlock):
                        print(f"🔧 Tool used: {block.name}({block.input})")

    print("\n" + "=" * 70)
    print("✅ Tests completed!")
    print("=" * 70)


async def main():
    try:
        await test_with_client()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
