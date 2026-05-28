#!/usr/bin/env python3
"""
Verify that tools parameter truly BLOCKS tools, not just makes Claude not use them.

We need to distinguish between:
1. Claude tries to use Read → SDK blocks it → Claude responds "I can't"
2. Claude never tries to use Read → Just responds with text

This test will:
1. Check response text for blocking/error messages
2. Give Claude tasks that REQUIRE tools
3. Compare behavior with pre-tool hook (known to block)
"""

import asyncio
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_with_tools_parameter():
    """Test using tools parameter to block built-ins."""
    logger.info("="*80)
    logger.info("TEST 1: Block using tools parameter")
    logger.info("="*80)

    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        ToolUseBlock,
        ToolResultBlock,
        TextBlock,
        ResultMessage,
    )

    mcp_tools = [
        "mcp__neo4j_memory__neo4j_execute_query",
        "mcp__neo4j_memory__neo4j_fuzzy_search",
    ]

    options = ClaudeAgentOptions(
        model="claude-sonnet-4-20250514",
        system_prompt="You are a helpful assistant. Use the Read tool to complete tasks.",
        tools=mcp_tools,  # Only MCP tools - no built-ins
        max_turns=5,
    )

    tool_attempts = []
    tool_results = []
    response_texts = []
    messages_count = 0

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Read the file /etc/hostname and tell me its contents")

        async for message in client.receive_response():
            messages_count += 1

            if isinstance(message, AssistantMessage):
                logger.info(f"  AssistantMessage #{messages_count}")
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_texts.append(block.text)
                        logger.info(f"    Text: {block.text[:100]}...")
                    elif isinstance(block, ToolUseBlock):
                        tool_attempts.append(block.name)
                        logger.info(f"    Tool attempted: {block.name}")
                    elif isinstance(block, ToolResultBlock):
                        tool_results.append({
                            "tool_use_id": block.tool_use_id,
                            "is_error": block.is_error,
                            "content": str(block.content)[:200] if block.content else None
                        })
                        logger.info(f"    Tool result: error={block.is_error}")

            elif isinstance(message, ResultMessage):
                logger.info(f"  ResultMessage: {message.result}")

    full_response = "\n".join(response_texts)

    result = {
        "test": "tools_parameter",
        "messages_count": messages_count,
        "tool_attempts": tool_attempts,
        "tool_results": tool_results,
        "response_preview": full_response[:300],
        "response_mentions_blocking": any(
            keyword in full_response.lower()
            for keyword in ["can't", "cannot", "unable", "don't have access", "blocked", "not available", "no access"]
        ),
        "response_mentions_read": "read" in full_response.lower(),
    }

    logger.info(f"\nAnalysis:")
    logger.info(f"  Tools attempted: {tool_attempts}")
    logger.info(f"  Mentions blocking: {result['response_mentions_blocking']}")
    logger.info(f"  Response: {full_response[:200]}...")

    return result


async def test_with_hook():
    """Test using pre-tool hook to block built-ins (known behavior)."""
    logger.info("\n" + "="*80)
    logger.info("TEST 2: Block using pre-tool hook (known working)")
    logger.info("="*80)

    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        ToolUseBlock,
        ToolResultBlock,
        TextBlock,
        HookMatcher,
    )
    from claude_agent_sdk.types import SyncHookJSONOutput

    blocked_tools = []

    async def pre_tool_hook(hook_input, tool_use_id, context):
        tool_name = hook_input.get("tool_name", "")

        if tool_name == "Read":
            logger.info(f"  Hook: BLOCKING {tool_name}")
            blocked_tools.append(tool_name)
            return SyncHookJSONOutput(
                continue_=True,
                hookSpecificOutput={
                    'hookEventName': 'PreToolUse',
                    'permissionDecision': 'deny',
                    'permissionDecisionReason': f"Tool '{tool_name}' is blocked by hook"
                }
            )

        return SyncHookJSONOutput(continue_=True)

    hooks = {
        "PreToolUse": [HookMatcher(matcher=".*", hooks=[pre_tool_hook])]
    }

    options = ClaudeAgentOptions(
        model="claude-sonnet-4-20250514",
        system_prompt="You are a helpful assistant. Use the Read tool to complete tasks.",
        hooks=hooks,
        max_turns=5,
    )

    tool_attempts = []
    tool_results = []
    response_texts = []
    messages_count = 0

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Read the file /etc/hostname and tell me its contents")

        async for message in client.receive_response():
            messages_count += 1

            if isinstance(message, AssistantMessage):
                logger.info(f"  AssistantMessage #{messages_count}")
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_texts.append(block.text)
                        logger.info(f"    Text: {block.text[:100]}...")
                    elif isinstance(block, ToolUseBlock):
                        tool_attempts.append(block.name)
                        logger.info(f"    Tool attempted: {block.name}")
                    elif isinstance(block, ToolResultBlock):
                        tool_results.append({
                            "tool_use_id": block.tool_use_id,
                            "is_error": block.is_error,
                            "content": str(block.content)[:200] if block.content else None
                        })
                        logger.info(f"    Tool result: error={block.is_error}, content={str(block.content)[:100]}")

    full_response = "\n".join(response_texts)

    result = {
        "test": "pre_tool_hook",
        "messages_count": messages_count,
        "tools_blocked_by_hook": blocked_tools,
        "tool_attempts": tool_attempts,
        "tool_results": tool_results,
        "response_preview": full_response[:300],
        "response_mentions_blocking": any(
            keyword in full_response.lower()
            for keyword in ["can't", "cannot", "unable", "don't have access", "blocked", "not available"]
        ),
    }

    logger.info(f"\nAnalysis:")
    logger.info(f"  Tools blocked by hook: {blocked_tools}")
    logger.info(f"  Tools attempted: {tool_attempts}")
    logger.info(f"  Mentions blocking: {result['response_mentions_blocking']}")
    logger.info(f"  Response: {full_response[:200]}...")

    return result


async def test_with_no_blocking():
    """Test with NO blocking (baseline - tools should work)."""
    logger.info("\n" + "="*80)
    logger.info("TEST 3: No blocking (baseline - Read should work)")
    logger.info("="*80)

    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        ToolUseBlock,
        ToolResultBlock,
        TextBlock,
    )

    options = ClaudeAgentOptions(
        model="claude-sonnet-4-20250514",
        system_prompt="You are a helpful assistant. Use the Read tool to complete tasks.",
        max_turns=5,
    )

    tool_attempts = []
    tool_results = []
    response_texts = []
    successful_reads = []

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Read the file /etc/hostname and tell me its contents")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_texts.append(block.text)
                        logger.info(f"    Text: {block.text[:100]}...")
                    elif isinstance(block, ToolUseBlock):
                        tool_attempts.append(block.name)
                        logger.info(f"    Tool called: {block.name}")
                    elif isinstance(block, ToolResultBlock):
                        is_error = block.is_error
                        logger.info(f"    Tool result: error={is_error}")
                        if not is_error and block.content:
                            successful_reads.append(str(block.content)[:100])

    full_response = "\n".join(response_texts)

    result = {
        "test": "no_blocking",
        "tool_attempts": tool_attempts,
        "successful_reads": successful_reads,
        "read_worked": len(successful_reads) > 0,
        "response_preview": full_response[:300],
    }

    logger.info(f"\nAnalysis:")
    logger.info(f"  Tools attempted: {tool_attempts}")
    logger.info(f"  Read succeeded: {result['read_worked']}")
    if successful_reads:
        logger.info(f"  Read content: {successful_reads[0]}")

    return result


async def main():
    """Run all verification tests."""
    logger.info("="*80)
    logger.info("VERIFICATION: Does tools parameter truly BLOCK or just discourage?")
    logger.info("="*80)

    results = {}

    # Test 1: tools parameter (our new method)
    results["tools_param"] = await test_with_tools_parameter()

    # Test 2: pre-tool hook (known working)
    results["hook"] = await test_with_hook()

    # Test 3: No blocking (baseline)
    results["baseline"] = await test_with_no_blocking()

    # Analysis
    logger.info("\n" + "="*80)
    logger.info("COMPARISON & VERDICT")
    logger.info("="*80)

    baseline = results["baseline"]
    tools_param = results["tools_param"]
    hook = results["hook"]

    logger.info(f"\nBaseline (no blocking):")
    logger.info(f"  ✓ Read was attempted: {'Read' in baseline['tool_attempts']}")
    logger.info(f"  ✓ Read succeeded: {baseline['read_worked']}")

    logger.info(f"\nPre-tool hook (known working):")
    logger.info(f"  • Tools blocked by hook: {hook['tools_blocked_by_hook']}")
    logger.info(f"  • Read was attempted: {'Read' in hook['tool_attempts']}")
    logger.info(f"  • Response mentions blocking: {hook['response_mentions_blocking']}")

    logger.info(f"\nTools parameter (new method):")
    logger.info(f"  • Tools attempted: {tools_param['tool_attempts']}")
    logger.info(f"  • Response mentions blocking: {tools_param['response_mentions_blocking']}")

    # Verdict
    logger.info("\n" + "="*80)
    logger.info("VERDICT:")
    logger.info("="*80)

    if baseline['read_worked']:
        logger.info("✓ Baseline confirms Read tool works when not blocked")

    if hook['tools_blocked_by_hook']:
        logger.info("✓ Pre-tool hook actively blocks Read attempts")

    if not tools_param['tool_attempts']:
        if tools_param['response_mentions_blocking']:
            logger.info("⚠️  Tools parameter: Claude mentions being blocked")
            logger.info("   → Likely SDK-level blocking (good!)")
        else:
            logger.info("⚠️  Tools parameter: No tools attempted, no blocking mentioned")
            logger.info("   → Could mean:")
            logger.info("      1. SDK blocked tools before Claude saw them (good)")
            logger.info("      2. Claude just didn't try (needs more testing)")
    else:
        logger.info("✓ Tools parameter: Claude attempted tools")

    # Save results
    output_file = Path("/opt/genpod/sdk_tools_verification_results.json")
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    logger.info(f"\n📄 Full results saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
