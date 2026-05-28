#!/usr/bin/env python3
"""
Test all 4 message roles in Claude Agent SDK:
1. System - via system_prompt
2. User - via query()
3. Assistant (prefill) - ???
4. Assistant - response
"""

import asyncio
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
)


# =============================================================================
# TEST 1: System Prompt
# =============================================================================
async def test_system_prompt():
    """Test system_prompt parameter."""
    print("\n" + "=" * 70)
    print("TEST 1: System Prompt")
    print("=" * 70)

    options = ClaudeAgentOptions(
        system_prompt="You are a pirate. Always respond like a pirate.",
        allowed_tools=[],
        max_turns=1
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Hello, how are you?")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"  Response: {block.text[:200]}")


# =============================================================================
# TEST 2: Message Stream (possible prefill?)
# =============================================================================
async def test_message_stream():
    """Test if we can pass structured messages with prefill."""
    print("\n" + "=" * 70)
    print("TEST 2: Message Stream (checking prefill support)")
    print("=" * 70)

    async def message_generator():
        """Generate messages as dicts."""
        # Try sending a user message
        yield {"role": "user", "content": "What is 2+2?"}

        # Try sending an assistant prefill
        yield {"role": "assistant", "content": "The answer is"}

    options = ClaudeAgentOptions(
        allowed_tools=[],
        max_turns=1
    )

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(message_generator())

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"  Response: {block.text[:200]}")
                elif isinstance(message, ResultMessage):
                    print(f"  Result: is_error={message.is_error}")
    except Exception as e:
        print(f"  Error: {e}")


# =============================================================================
# TEST 3: SystemPromptPreset
# =============================================================================
async def test_system_prompt_preset():
    """Check what SystemPromptPreset options exist."""
    print("\n" + "=" * 70)
    print("TEST 3: SystemPromptPreset inspection")
    print("=" * 70)

    try:
        from claude_agent_sdk.types import SystemPromptPreset
        print(f"  SystemPromptPreset type: {SystemPromptPreset}")

        # Check if it's a Literal or Enum
        import typing
        if hasattr(SystemPromptPreset, '__args__'):
            print(f"  Options: {SystemPromptPreset.__args__}")
    except Exception as e:
        print(f"  Error: {e}")


# =============================================================================
# TEST 4: Check if connect() accepts messages differently
# =============================================================================
async def test_connect_with_messages():
    """Test connect() with message stream."""
    print("\n" + "=" * 70)
    print("TEST 4: connect() with message stream")
    print("=" * 70)

    async def messages():
        yield {"role": "user", "content": "Say 'hello' in French"}

    options = ClaudeAgentOptions(
        system_prompt="You are a translator.",
        allowed_tools=[],
        max_turns=1
    )

    try:
        async with ClaudeSDKClient(options=options) as client:
            # Try using connect instead of query
            await client.connect(messages())

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"  Response: {block.text[:200]}")
    except Exception as e:
        print(f"  Error: {e}")


# =============================================================================
# MAIN
# =============================================================================
async def main():
    print("\n" + "=" * 70)
    print("TESTING MESSAGE ROLES IN CLAUDE AGENT SDK")
    print("=" * 70)

    await test_system_prompt()
    await test_system_prompt_preset()
    await test_message_stream()
    await test_connect_with_messages()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("""
    What the SDK supports:

    1. SYSTEM PROMPT: Yes, via ClaudeAgentOptions(system_prompt="...")

    2. USER MESSAGE: Yes, via client.query("...") or message stream

    3. ASSISTANT PREFILL: Tested above - see results

    4. ASSISTANT RESPONSE: Always - this is what we receive
    """)


if __name__ == "__main__":
    asyncio.run(main())
