#!/usr/bin/env python3
"""
Comprehensive Claude Agent SDK Exploration

This script systematically tests SDK features to understand actual behavior.
Results will be used for documentation.
"""

import asyncio
import json
from typing import Any
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    tool,
    create_sdk_mcp_server,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ThinkingBlock,
    SystemMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
    HookMatcher,
    PreToolUseHookInput,
    PostToolUseHookInput,
    HookContext,
)
from claude_agent_sdk.types import SyncHookJSONOutput

# Track what happens during execution
execution_log = []

def log(msg: str):
    print(f"[LOG] {msg}")
    execution_log.append(msg)


# =============================================================================
# TEST 1: Basic inference (no tools)
# =============================================================================
async def test_basic_inference():
    """Test simple inference without tools."""
    log("=" * 70)
    log("TEST 1: Basic Inference (no tools)")
    log("=" * 70)

    options = ClaudeAgentOptions(
        allowed_tools=[],
        max_turns=1
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("What is 2 + 2? Reply with just the number.")

        async for message in client.receive_response():
            log(f"Message type: {type(message).__name__}")
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        log(f"  TextBlock: {block.text[:100]}")
            elif isinstance(message, ResultMessage):
                log(f"  ResultMessage: turns={message.num_turns}, cost=${message.total_cost_usd}")

    log("TEST 1 COMPLETE\n")


# =============================================================================
# TEST 2: Custom tool with @tool decorator
# =============================================================================
@tool(
    name="add_numbers",
    description="Add two numbers together",
    input_schema={"a": int, "b": int}
)
async def add_numbers(args: dict[str, Any]) -> dict[str, Any]:
    """Tool that adds two numbers."""
    log(f"  [TOOL EXECUTED] add_numbers called with args: {args}")
    a = args.get("a", 0)
    b = args.get("b", 0)
    result = a + b
    log(f"  [TOOL RESULT] {a} + {b} = {result}")
    return {
        "content": [{"type": "text", "text": f"The sum is {result}"}]
    }


async def test_custom_tool():
    """Test custom tool execution."""
    log("=" * 70)
    log("TEST 2: Custom Tool with @tool decorator")
    log("=" * 70)

    tools_server = create_sdk_mcp_server(
        name="math",
        version="1.0.0",
        tools=[add_numbers]
    )

    options = ClaudeAgentOptions(
        mcp_servers={"math": tools_server},
        allowed_tools=["mcp__math__add_numbers"],
        max_turns=5
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Use the add_numbers tool to add 15 and 27. Tell me the result.")

        async for message in client.receive_response():
            log(f"Message type: {type(message).__name__}")
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        log(f"  TextBlock: {block.text[:100]}")
                    elif isinstance(block, ToolUseBlock):
                        log(f"  ToolUseBlock: {block.name}({block.input})")
                    elif isinstance(block, ToolResultBlock):
                        log(f"  ToolResultBlock: {block.content}")
            elif isinstance(message, ResultMessage):
                log(f"  ResultMessage: turns={message.num_turns}")

    log("TEST 2 COMPLETE\n")


# =============================================================================
# TEST 3: can_use_tool callback
# =============================================================================
async def test_can_use_tool():
    """Test can_use_tool callback behavior."""
    log("=" * 70)
    log("TEST 3: can_use_tool callback")
    log("=" * 70)

    tool_calls_received = []

    async def my_can_use_tool(
        tool_name: str,
        tool_input: dict,
        context: ToolPermissionContext
    ):
        log(f"  [can_use_tool CALLED]")
        log(f"    tool_name: {tool_name}")
        log(f"    tool_input: {tool_input}")
        log(f"    context.signal: {context.signal}")
        log(f"    context.suggestions: {context.suggestions}")
        tool_calls_received.append({"name": tool_name, "input": tool_input})

        # Try modifying input
        modified_input = tool_input.copy()
        if "a" in modified_input:
            modified_input["a"] = modified_input["a"] * 10  # Multiply by 10
            log(f"    [MODIFYING INPUT] a -> {modified_input['a']}")

        return PermissionResultAllow(updated_input=modified_input)

    tools_server = create_sdk_mcp_server(
        name="math",
        version="1.0.0",
        tools=[add_numbers]
    )

    options = ClaudeAgentOptions(
        mcp_servers={"math": tools_server},
        allowed_tools=["mcp__math__add_numbers"],
        can_use_tool=my_can_use_tool,
        max_turns=5
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Use add_numbers to add 5 and 3.")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        log(f"  TextBlock: {block.text[:100]}")
                    elif isinstance(block, ToolUseBlock):
                        log(f"  ToolUseBlock: {block.name}({block.input})")
            elif isinstance(message, ResultMessage):
                log(f"  ResultMessage: turns={message.num_turns}")

    log(f"  [SUMMARY] can_use_tool was called {len(tool_calls_received)} times")
    log("TEST 3 COMPLETE\n")


# =============================================================================
# TEST 4: can_use_tool DENY
# =============================================================================
async def test_can_use_tool_deny():
    """Test denying tool execution."""
    log("=" * 70)
    log("TEST 4: can_use_tool DENY")
    log("=" * 70)

    async def deny_all(tool_name: str, tool_input: dict, context: ToolPermissionContext):
        log(f"  [can_use_tool DENYING] {tool_name}")
        return PermissionResultDeny(message="Tool execution blocked for testing", interrupt=False)

    tools_server = create_sdk_mcp_server(
        name="math",
        version="1.0.0",
        tools=[add_numbers]
    )

    options = ClaudeAgentOptions(
        mcp_servers={"math": tools_server},
        allowed_tools=["mcp__math__add_numbers"],
        can_use_tool=deny_all,
        max_turns=3
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Use add_numbers to add 5 and 3.")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        log(f"  TextBlock: {block.text[:150]}")
            elif isinstance(message, ResultMessage):
                log(f"  ResultMessage: turns={message.num_turns}, is_error={message.is_error}")

    log("TEST 4 COMPLETE\n")


# =============================================================================
# TEST 5: PreToolUse Hook
# =============================================================================
async def test_pre_tool_use_hook():
    """Test PreToolUse hook behavior."""
    log("=" * 70)
    log("TEST 5: PreToolUse Hook")
    log("=" * 70)

    hook_calls = []

    async def my_pre_hook(
        hook_input: PreToolUseHookInput,
        tool_use_id: str | None,
        context: HookContext
    ) -> SyncHookJSONOutput:
        log(f"  [PreToolUse HOOK CALLED]")
        log(f"    hook_input: {dict(hook_input) if hasattr(hook_input, 'items') else hook_input}")
        log(f"    tool_use_id: {tool_use_id}")
        hook_calls.append({"input": hook_input, "id": tool_use_id})

        # Allow execution
        return SyncHookJSONOutput(continue_=True)

    tools_server = create_sdk_mcp_server(
        name="math",
        version="1.0.0",
        tools=[add_numbers]
    )

    options = ClaudeAgentOptions(
        mcp_servers={"math": tools_server},
        allowed_tools=["mcp__math__add_numbers"],
        hooks={
            "PreToolUse": [HookMatcher(matcher=".*", hooks=[my_pre_hook], timeout=30)]
        },
        max_turns=5
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Use add_numbers to add 10 and 20.")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        log(f"  TextBlock: {block.text[:100]}")
            elif isinstance(message, ResultMessage):
                log(f"  ResultMessage: turns={message.num_turns}")

    log(f"  [SUMMARY] PreToolUse hook called {len(hook_calls)} times")
    log("TEST 5 COMPLETE\n")


# =============================================================================
# TEST 6: PostToolUse Hook
# =============================================================================
async def test_post_tool_use_hook():
    """Test PostToolUse hook behavior."""
    log("=" * 70)
    log("TEST 6: PostToolUse Hook")
    log("=" * 70)

    hook_calls = []

    async def my_post_hook(
        hook_input: PostToolUseHookInput,
        tool_use_id: str | None,
        context: HookContext
    ) -> SyncHookJSONOutput:
        log(f"  [PostToolUse HOOK CALLED]")
        log(f"    hook_input: {dict(hook_input) if hasattr(hook_input, 'items') else hook_input}")
        log(f"    tool_use_id: {tool_use_id}")
        hook_calls.append({"input": hook_input, "id": tool_use_id})
        return SyncHookJSONOutput(continue_=True)

    tools_server = create_sdk_mcp_server(
        name="math",
        version="1.0.0",
        tools=[add_numbers]
    )

    options = ClaudeAgentOptions(
        mcp_servers={"math": tools_server},
        allowed_tools=["mcp__math__add_numbers"],
        hooks={
            "PostToolUse": [HookMatcher(matcher=".*", hooks=[my_post_hook], timeout=30)]
        },
        max_turns=5
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Use add_numbers to add 100 and 200.")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        log(f"  TextBlock: {block.text[:100]}")
            elif isinstance(message, ResultMessage):
                log(f"  ResultMessage: turns={message.num_turns}")

    log(f"  [SUMMARY] PostToolUse hook called {len(hook_calls)} times")
    log("TEST 6 COMPLETE\n")


# =============================================================================
# TEST 7: Structured Output
# =============================================================================
async def test_structured_output():
    """Test structured output format."""
    log("=" * 70)
    log("TEST 7: Structured Output")
    log("=" * 70)

    output_schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "integer"},
            "explanation": {"type": "string"}
        },
        "required": ["answer", "explanation"]
    }

    options = ClaudeAgentOptions(
        allowed_tools=[],
        max_turns=1,
        output_format={
            "type": "json_schema",
            "json_schema": {
                "name": "math_result",
                "schema": output_schema
            }
        }
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("What is 15 * 4? Provide answer and explanation.")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        log(f"  TextBlock: {block.text}")
            elif isinstance(message, ResultMessage):
                log(f"  ResultMessage: structured_output={message.structured_output}")

    log("TEST 7 COMPLETE\n")


# =============================================================================
# TEST 8: Multi-turn conversation
# =============================================================================
async def test_multi_turn():
    """Test multi-turn conversation with context retention."""
    log("=" * 70)
    log("TEST 8: Multi-turn Conversation")
    log("=" * 70)

    options = ClaudeAgentOptions(
        allowed_tools=[],
        max_turns=10
    )

    async with ClaudeSDKClient(options=options) as client:
        # First query
        log("  Query 1: Setting context...")
        await client.query("Remember this number: 42. Just say OK.")
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        log(f"    Response 1: {block.text[:50]}")

        # Second query - should remember
        log("  Query 2: Testing memory...")
        await client.query("What number did I ask you to remember?")
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        log(f"    Response 2: {block.text[:100]}")

    log("TEST 8 COMPLETE\n")


# =============================================================================
# MAIN
# =============================================================================
async def main():
    print("\n" + "=" * 70)
    print("CLAUDE AGENT SDK COMPREHENSIVE EXPLORATION")
    print("=" * 70 + "\n")

    tests = [
        ("Basic Inference", test_basic_inference),
        ("Custom Tool", test_custom_tool),
        ("can_use_tool Allow + Modify", test_can_use_tool),
        ("can_use_tool Deny", test_can_use_tool_deny),
        ("PreToolUse Hook", test_pre_tool_use_hook),
        ("PostToolUse Hook", test_post_tool_use_hook),
        ("Structured Output", test_structured_output),
        ("Multi-turn Conversation", test_multi_turn),
    ]

    results = {}

    for name, test_func in tests:
        try:
            await test_func()
            results[name] = "PASS"
        except Exception as e:
            log(f"ERROR in {name}: {e}")
            import traceback
            traceback.print_exc()
            results[name] = f"FAIL: {e}"

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    for name, result in results.items():
        status = "✅" if result == "PASS" else "❌"
        print(f"  {status} {name}: {result}")

    # Save log
    with open("/opt/genpod/fallback_agent/sdk_exploration/test_results.log", "w") as f:
        f.write("\n".join(execution_log))
    print(f"\nLog saved to test_results.log")


if __name__ == "__main__":
    asyncio.run(main())
