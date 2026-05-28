#!/usr/bin/env python3
"""
Deep investigation of can_use_tool behavior.

Questions to answer:
1. When does can_use_tool get called?
2. Does it work with external MCP servers only?
3. Can hooks intercept and modify tool execution?
"""

import asyncio
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
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
    HookMatcher,
    PreToolUseHookInput,
    HookContext,
)
from claude_agent_sdk.types import SyncHookJSONOutput


# =============================================================================
# Tool definition
# =============================================================================
@tool(
    name="multiply",
    description="Multiply two numbers",
    input_schema={"a": int, "b": int}
)
async def multiply(args: dict[str, Any]) -> dict[str, Any]:
    print(f"    [TOOL] multiply executed: {args['a']} * {args['b']}")
    result = args["a"] * args["b"]
    return {"content": [{"type": "text", "text": f"Result: {result}"}]}


# =============================================================================
# TEST: PreToolUse hook with BLOCK decision
# =============================================================================
async def test_hook_block():
    """Test if PreToolUse hook can BLOCK tool execution."""
    print("\n" + "=" * 70)
    print("TEST: PreToolUse Hook BLOCK")
    print("=" * 70)

    async def blocking_hook(
        hook_input: PreToolUseHookInput,
        tool_use_id: str | None,
        context: HookContext
    ) -> SyncHookJSONOutput:
        print(f"    [HOOK] Intercepted: {hook_input.get('tool_name')}")
        print(f"    [HOOK] BLOCKING tool execution!")
        return SyncHookJSONOutput(
            continue_=True,
            decision="block",
            reason="Blocked by test hook",
            systemMessage="Tool was blocked for testing purposes."
        )

    tools_server = create_sdk_mcp_server(
        name="math", version="1.0.0", tools=[multiply]
    )

    options = ClaudeAgentOptions(
        mcp_servers={"math": tools_server},
        allowed_tools=["mcp__math__multiply"],
        hooks={
            "PreToolUse": [HookMatcher(matcher=".*", hooks=[blocking_hook], timeout=30)]
        },
        max_turns=3
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Use multiply to calculate 7 * 8")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"    [RESPONSE] {block.text[:150]}")
                    elif isinstance(block, ToolUseBlock):
                        print(f"    [TOOL_USE] {block.name}({block.input})")
            elif isinstance(message, ResultMessage):
                print(f"    [RESULT] turns={message.num_turns}, is_error={message.is_error}")


# =============================================================================
# TEST: PreToolUse hook with modified input (via hook)
# =============================================================================
async def test_hook_modify():
    """Test if we can modify tool input via hook."""
    print("\n" + "=" * 70)
    print("TEST: PreToolUse Hook MODIFY Input")
    print("=" * 70)

    # Note: Looking at SyncHookJSONOutput, it doesn't have a way to modify input!
    # Let's verify this

    async def modifying_hook(
        hook_input: PreToolUseHookInput,
        tool_use_id: str | None,
        context: HookContext
    ) -> SyncHookJSONOutput:
        original_input = hook_input.get('tool_input', {})
        print(f"    [HOOK] Original input: {original_input}")

        # SyncHookJSONOutput fields - let's check what we can return
        # Looking at the structure, there's no way to modify input in hooks
        # Only can_use_tool has updated_input

        return SyncHookJSONOutput(
            continue_=True,
            # Can we add extra fields? Let's try
        )

    tools_server = create_sdk_mcp_server(
        name="math", version="1.0.0", tools=[multiply]
    )

    options = ClaudeAgentOptions(
        mcp_servers={"math": tools_server},
        allowed_tools=["mcp__math__multiply"],
        hooks={
            "PreToolUse": [HookMatcher(matcher=".*", hooks=[modifying_hook], timeout=30)]
        },
        max_turns=3
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Use multiply to calculate 3 * 4")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"    [RESPONSE] {block.text}")
            elif isinstance(message, ResultMessage):
                print(f"    [RESULT] turns={message.num_turns}")


# =============================================================================
# TEST: Check SyncHookJSONOutput fields
# =============================================================================
def inspect_hook_output():
    """Inspect what fields SyncHookJSONOutput has."""
    print("\n" + "=" * 70)
    print("INSPECT: SyncHookJSONOutput fields")
    print("=" * 70)

    import inspect

    # Check dataclass fields
    if hasattr(SyncHookJSONOutput, '__dataclass_fields__'):
        print("  Dataclass fields:")
        for name, field in SyncHookJSONOutput.__dataclass_fields__.items():
            default = getattr(field, 'default', 'N/A')
            print(f"    - {name}: {field.type} (default: {default})")

    # Check signature
    try:
        sig = inspect.signature(SyncHookJSONOutput)
        print(f"\n  Signature: {sig}")
    except:
        pass

    # Try creating one and see all attributes
    output = SyncHookJSONOutput(continue_=True)
    print(f"\n  Instance attributes: {vars(output) if hasattr(output, '__dict__') else 'N/A'}")


# =============================================================================
# TEST: can_use_tool with permission_mode variations
# =============================================================================
async def test_can_use_tool_with_modes():
    """Test can_use_tool with different permission modes."""
    print("\n" + "=" * 70)
    print("TEST: can_use_tool with different permission_mode settings")
    print("=" * 70)

    call_count = 0

    async def my_can_use_tool(tool_name: str, tool_input: dict, context: ToolPermissionContext):
        nonlocal call_count
        call_count += 1
        print(f"    [can_use_tool CALLED #{call_count}] {tool_name}")
        return PermissionResultAllow()

    tools_server = create_sdk_mcp_server(
        name="math", version="1.0.0", tools=[multiply]
    )

    # Try with permission_mode="default" (ask for permission)
    for mode in ["default", "acceptEdits", "bypassPermissions"]:
        call_count = 0
        print(f"\n  Testing with permission_mode='{mode}':")

        options = ClaudeAgentOptions(
            mcp_servers={"math": tools_server},
            allowed_tools=["mcp__math__multiply"],
            can_use_tool=my_can_use_tool,
            permission_mode=mode,
            max_turns=3
        )

        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query("Use multiply: 2 * 5")
                async for message in client.receive_response():
                    if isinstance(message, ResultMessage):
                        print(f"    Result: turns={message.num_turns}")
        except Exception as e:
            print(f"    Error: {e}")

        print(f"    can_use_tool called: {call_count} times")


# =============================================================================
# MAIN
# =============================================================================
async def main():
    print("\n" + "=" * 70)
    print("DEEP INVESTIGATION: can_use_tool vs Hooks")
    print("=" * 70)

    # First inspect the types
    inspect_hook_output()

    # Run tests
    await test_hook_block()
    await test_hook_modify()
    await test_can_use_tool_with_modes()

    print("\n" + "=" * 70)
    print("INVESTIGATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
