#!/usr/bin/env python3
"""
Deep dive test: Try different ways to use disallowed_tools parameter.

Test various formats and combinations to see if we're missing something.
"""

import asyncio
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_variation(variation_name: str, **options_kwargs):
    """Test a specific variation of options."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Testing: {variation_name}")
    logger.info(f"Options: {options_kwargs}")
    logger.info(f"{'='*60}")

    try:
        from claude_agent_sdk import (
            ClaudeSDKClient,
            ClaudeAgentOptions,
            AssistantMessage,
            ToolUseBlock,
        )

        # Base options
        base_options = {
            "model": "claude-sonnet-4-20250514",
            "system_prompt": "Try to use the Read tool.",
            "max_turns": 2,
        }

        # Merge with test-specific options
        base_options.update(options_kwargs)

        options = ClaudeAgentOptions(**base_options)

        tool_attempts = []

        async with ClaudeSDKClient(options=options) as client:
            await client.query("Use Read tool to read /etc/hostname")

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            tool_attempts.append(block.name)
                            logger.info(f"  Tool called: {block.name}")

        read_called = "Read" in tool_attempts
        result = "❌ FAIL - Read called" if read_called else "✅ PASS - Read blocked"

        logger.info(f"Result: {result}")
        logger.info(f"Tools attempted: {tool_attempts}")

        return {
            "variation": variation_name,
            "read_called": read_called,
            "tools_attempted": tool_attempts,
            "verdict": result,
        }

    except Exception as e:
        logger.error(f"Error: {e}")
        return {
            "variation": variation_name,
            "error": str(e),
        }


async def main():
    """Test different variations of disallowed_tools parameter."""

    results = []

    # Test 1: Empty allowed_tools (should block everything)
    result = await test_variation(
        "Empty allowed_tools",
        allowed_tools=[]
    )
    results.append(result)

    # Test 2: disallowed_tools with single tool
    result = await test_variation(
        "disallowed_tools = ['Read']",
        disallowed_tools=["Read"]
    )
    results.append(result)

    # Test 3: disallowed_tools with all built-in tools
    builtin_tools = [
        "Bash", "Read", "Write", "Edit", "Glob", "Grep", "LS",
        "MultiEdit", "NotebookRead", "NotebookEdit", "WebFetch",
        "WebSearch", "TodoRead", "TodoWrite", "Task",
    ]
    result = await test_variation(
        "disallowed_tools = [all built-in tools]",
        disallowed_tools=builtin_tools
    )
    results.append(result)

    # Test 4: Combination of allowed_tools and disallowed_tools
    result = await test_variation(
        "allowed_tools=[] + disallowed_tools=['Read']",
        allowed_tools=[],
        disallowed_tools=["Read"]
    )
    results.append(result)

    # Test 5: Try can_use_tool callback (if it exists)
    try:
        def cannot_use_read(tool_name: str) -> bool:
            """Return False to block tool."""
            should_block = tool_name == "Read"
            logger.info(f"can_use_tool callback: {tool_name} -> {'BLOCK' if should_block else 'ALLOW'}")
            return not should_block

        result = await test_variation(
            "can_use_tool callback",
            can_use_tool=cannot_use_read
        )
        results.append(result)
    except Exception as e:
        logger.error(f"can_use_tool test failed: {e}")
        results.append({
            "variation": "can_use_tool callback",
            "error": str(e)
        })

    # Test 6: Check if tools parameter overrides
    result = await test_variation(
        "tools = [] (empty tools list)",
        tools=[]
    )
    results.append(result)

    # Generate report
    logger.info("\n" + "="*80)
    logger.info("SUMMARY OF ALL VARIATIONS")
    logger.info("="*80)

    working_methods = []
    for r in results:
        verdict = r.get("verdict", r.get("error", "UNKNOWN"))
        logger.info(f"{r['variation']}: {verdict}")

        if "✅ PASS" in verdict:
            working_methods.append(r["variation"])

    logger.info("\n" + "-"*80)
    if working_methods:
        logger.info(f"✅ WORKING METHODS: {working_methods}")
        logger.info("You can replace the pre-tool hook with one of these!")
    else:
        logger.info("❌ NO NATIVE BLOCKING METHODS WORK")
        logger.info("You must continue using the pre-tool hook workaround.")

    # Save results
    output_file = Path("/opt/genpod/sdk_disallowed_tools_variations_results.json")
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    logger.info(f"\nDetailed results saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
