#!/usr/bin/env python3
"""
Compare query() vs ClaudeSDKClient responses.

Key differences:
1. query() - Creates NEW session each call
2. ClaudeSDKClient - Maintains SAME session across calls
"""

import asyncio
from claude_agent_sdk import (
    query,
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    SystemMessage,
    ResultMessage,
    TextBlock
)


async def test_with_query_function():
    """Using query() - new session each time."""
    print("=" * 70)
    print("Test 1: Using query() function")
    print("=" * 70)

    # First query
    print("\nQuery 1: What's 5 + 3?")
    print("-" * 70)

    async for message in query(
        prompt="What's 5 + 3? Just answer with the number.",
        options=ClaudeAgentOptions(allowed_tools=[])
    ):
        print(f"Message type: {type(message).__name__}")

        if isinstance(message, SystemMessage):
            print(f"  SystemMessage subtype: {message.subtype}")

        elif isinstance(message, AssistantMessage):
            print(f"  AssistantMessage content blocks: {len(message.content)}")
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"    Text: {block.text}")

        elif isinstance(message, ResultMessage):
            print(f"  ResultMessage subtype: {message.subtype}")
            print(f"  Duration: {message.duration_ms}ms")
            print(f"  Turns: {message.num_turns}")
            print(f"  Session ID: {message.session_id}")
            if message.total_cost_usd:
                print(f"  Cost: ${message.total_cost_usd}")

    # Second query - NEW SESSION (won't remember previous)
    print("\n\nQuery 2: What was the previous number? (NEW SESSION)")
    print("-" * 70)

    async for message in query(
        prompt="What was the previous number I asked about?",
        options=ClaudeAgentOptions(allowed_tools=[])
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"  Text: {block.text}")

        elif isinstance(message, ResultMessage):
            print(f"  Session ID: {message.session_id}")


async def test_with_client():
    """Using ClaudeSDKClient - same session, remembers context."""
    print("\n\n" + "=" * 70)
    print("Test 2: Using ClaudeSDKClient (continuous session)")
    print("=" * 70)

    options = ClaudeAgentOptions(allowed_tools=[])

    async with ClaudeSDKClient(options=options) as client:
        # First query
        print("\nQuery 1: What's 5 + 3?")
        print("-" * 70)

        await client.query("What's 5 + 3? Just answer with the number.")

        async for message in client.receive_response():
            print(f"Message type: {type(message).__name__}")

            if isinstance(message, SystemMessage):
                print(f"  SystemMessage subtype: {message.subtype}")

            elif isinstance(message, AssistantMessage):
                print(f"  AssistantMessage content blocks: {len(message.content)}")
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"    Text: {block.text}")

            elif isinstance(message, ResultMessage):
                print(f"  ResultMessage subtype: {message.subtype}")
                print(f"  Duration: {message.duration_ms}ms")
                print(f"  Turns: {message.num_turns}")
                print(f"  Session ID: {message.session_id}")
                if message.total_cost_usd:
                    print(f"  Cost: ${message.total_cost_usd}")

        # Second query - SAME SESSION (will remember!)
        print("\n\nQuery 2: What was the previous number? (SAME SESSION)")
        print("-" * 70)

        await client.query("What was the previous number I asked about?")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"  Text: {block.text}")

            elif isinstance(message, ResultMessage):
                print(f"  Session ID: {message.session_id}")


async def test_message_structure():
    """Show the detailed structure of messages."""
    print("\n\n" + "=" * 70)
    print("Test 3: Detailed Message Structure")
    print("=" * 70)

    print("\nAsking simple question...\n")

    async for message in query(
        prompt="Say 'Hello!'",
        options=ClaudeAgentOptions(allowed_tools=[])
    ):
        print(f"\n{type(message).__name__}:")
        print(f"  Attributes: {vars(message)}")


async def main():
    """Run all comparisons."""
    print("\n🔍 Comparing query() vs ClaudeSDKClient\n")

    # Test 1: query() function (new session each time)
    await test_with_query_function()

    # Test 2: ClaudeSDKClient (maintains session)
    await test_with_client()

    # Test 3: Message structure
    await test_message_structure()

    # Summary
    print("\n\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("""
┌────────────────────────────────────────────────────────────────────┐
│ Feature              │ query()           │ ClaudeSDKClient        │
├────────────────────────────────────────────────────────────────────┤
│ Session              │ NEW each call     │ CONTINUOUS             │
│ Context memory       │ ❌ None           │ ✅ Remembers           │
│ Message format       │ Same iterator     │ Same messages          │
│ Use case             │ One-off queries   │ Multi-turn RAG         │
│ Custom tools         │ ⚠️  Issues        │ ✅ Works great         │
│ Interrupts           │ ❌ Not supported  │ ✅ Supported           │
└────────────────────────────────────────────────────────────────────┘

Key Insight: Both return the SAME message types (SystemMessage,
AssistantMessage, ResultMessage). The difference is session continuity.

For RAG workflows with multiple steps (like your 4-agent system):
→ Use ClaudeSDKClient for context retention across reasoning steps
    """)


if __name__ == "__main__":
    asyncio.run(main())
