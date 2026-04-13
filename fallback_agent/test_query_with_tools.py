#!/usr/bin/env python3
"""
Test: Why did custom tools fail with query() but work with ClaudeSDKClient?
"""

import asyncio
from typing import Any
from claude_agent_sdk import (
    query,
    ClaudeSDKClient,
    ClaudeAgentOptions,
    tool,
    create_sdk_mcp_server,
    AssistantMessage,
    TextBlock
)


@tool("greet", "Say hello to someone", {"name": str})
async def greet(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{
            "type": "text",
            "text": f"Hello, {args['name']}!"
        }]
    }


async def test_with_query():
    """Try using query() with custom tools."""
    print("=" * 70)
    print("Test 1: Custom tools with query() function")
    print("=" * 70)

    tools_server = create_sdk_mcp_server(
        name="tools",
        version="1.0.0",
        tools=[greet]
    )

    options = ClaudeAgentOptions(
        mcp_servers={"tools": tools_server},
        allowed_tools=["mcp__tools__greet"]
    )

    try:
        print("\nCalling query() with custom tool...\n")

        async for message in query(
            prompt="Use the greet tool to say hello to Alice",
            options=options
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"✅ Response: {block.text}")

        print("\n✅ SUCCESS with query()!")

    except Exception as e:
        print(f"\n❌ FAILED with query(): {e}")
        print(f"   Error type: {type(e).__name__}")


async def test_with_client():
    """Try using ClaudeSDKClient with custom tools."""
    print("\n" + "=" * 70)
    print("Test 2: Custom tools with ClaudeSDKClient")
    print("=" * 70)

    tools_server = create_sdk_mcp_server(
        name="tools",
        version="1.0.0",
        tools=[greet]
    )

    options = ClaudeAgentOptions(
        mcp_servers={"tools": tools_server},
        allowed_tools=["mcp__tools__greet"]
    )

    try:
        print("\nCalling ClaudeSDKClient with custom tool...\n")

        async with ClaudeSDKClient(options=options) as client:
            await client.query("Use the greet tool to say hello to Bob")

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"✅ Response: {block.text}")

        print("\n✅ SUCCESS with ClaudeSDKClient!")

    except Exception as e:
        print(f"\n❌ FAILED with ClaudeSDKClient: {e}")


async def main():
    # Test 1: query() function
    await test_with_query()

    # Test 2: ClaudeSDKClient
    await test_with_client()

    print("\n" + "=" * 70)
    print("EXPLANATION")
    print("=" * 70)
    print("""
SDK MCP servers (create_sdk_mcp_server) are IN-PROCESS.
They need the session to stay alive for tool execution.

query() behavior:
  1. Starts new session
  2. Sends prompt
  3. Closes session IMMEDIATELY after response
  4. ⚠️  SDK MCP server may not finish initializing

ClaudeSDKClient behavior:
  1. Starts session (connect)
  2. Keeps session OPEN
  3. Sends query
  4. Waits for response
  5. Session stays alive for more queries
  6. ✅ SDK MCP server has time to initialize

Conclusion:
- query() works for EXTERNAL MCP servers (stdio, http, sse)
- ClaudeSDKClient needed for IN-PROCESS SDK MCP servers
    """)


if __name__ == "__main__":
    asyncio.run(main())
