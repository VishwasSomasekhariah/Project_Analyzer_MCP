#!/usr/bin/env python3
"""
Test combining tools, allowed_tools, and disallowed_tools parameters.

The CLI receives these as:
- --tools "tool1,tool2" (base set of tools)
- --allowedTools "tool1,tool2" (whitelist)
- --disallowedTools "tool1,tool2" (blacklist)

We'll test if we can block built-in tools by:
1. Setting tools to only MCP tools (not including built-ins)
2. Combining tools + allowed_tools
3. Combining tools + disallowed_tools
"""

import asyncio
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BUILTIN_TOOLS = [
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "LS",
    "MultiEdit", "NotebookRead", "NotebookEdit", "WebFetch",
    "WebSearch", "TodoRead", "TodoWrite", "Task",
]


async def test_combination(name: str, description: str, **options):
    """Test a specific combination of tool parameters."""
    logger.info(f"\n{'='*80}")
    logger.info(f"Test: {name}")
    logger.info(f"Description: {description}")
    logger.info(f"Options: {json.dumps({k: v for k, v in options.items() if v is not None}, indent=2)}")
    logger.info(f"{'='*80}")

    try:
        from claude_agent_sdk import (
            ClaudeSDKClient,
            ClaudeAgentOptions,
            AssistantMessage,
            ToolUseBlock,
        )

        # Load MCP config if available
        mcp_config_path = Path("/opt/genpod/neo4j_config.json")
        if mcp_config_path.exists():
            with open(mcp_config_path) as f:
                config = json.load(f)
                mcp_servers = config.get("mcpServers", config)
        else:
            mcp_servers = {}

        # Build options
        base_options = {
            "model": "claude-sonnet-4-20250514",
            "system_prompt": "You are a test assistant. Try to use the Read tool.",
            "max_turns": 2,
            "mcp_servers": mcp_servers,
        }
        base_options.update(options)

        agent_options = ClaudeAgentOptions(**base_options)

        tool_attempts = []

        async with ClaudeSDKClient(options=agent_options) as client:
            await client.query("Use the Read tool to read /etc/hostname")

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            tool_attempts.append(block.name)
                            logger.info(f"  Tool called: {block.name}")

        read_called = "Read" in tool_attempts
        bash_called = "Bash" in tool_attempts
        builtin_called = any(t in BUILTIN_TOOLS for t in tool_attempts)

        result = {
            "test": name,
            "read_called": read_called,
            "bash_called": bash_called,
            "builtin_tool_called": builtin_called,
            "tools_attempted": tool_attempts,
            "verdict": (
                "✅ PASS - No built-in tools called" if not builtin_called
                else "❌ FAIL - Built-in tools still called"
            ),
        }

        logger.info(f"\nResult: {result['verdict']}")
        logger.info(f"Tools attempted: {tool_attempts}")

        return result

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        return {
            "test": name,
            "error": str(e),
        }


async def main():
    """Run all test combinations."""
    logger.info("="*80)
    logger.info("Testing tools + allowed_tools + disallowed_tools combinations")
    logger.info("SDK Version: 0.1.25")
    logger.info("="*80)

    results = []

    # Test 1: tools with only MCP tools (no built-ins declared)
    mcp_tools = [
        "mcp__neo4j_memory__neo4j_execute_query",
        "mcp__neo4j_memory__neo4j_fuzzy_search",
    ]

    result = await test_combination(
        "tools_mcp_only",
        "Set tools to only MCP tools (exclude built-ins from base set)",
        tools=mcp_tools
    )
    results.append(result)

    # Test 2: tools=[] + allowed_tools with MCP tools only
    result = await test_combination(
        "empty_tools_with_allowed_mcp",
        "Empty tools + allowed_tools with MCP tools",
        tools=[],
        allowed_tools=mcp_tools
    )
    results.append(result)

    # Test 3: tools with MCP + allowed_tools with same MCP tools
    result = await test_combination(
        "tools_mcp_with_allowed_mcp",
        "Set tools to MCP + allowed_tools to same MCP tools",
        tools=mcp_tools,
        allowed_tools=mcp_tools
    )
    results.append(result)

    # Test 4: tools with MCP + disallowed_tools with built-ins
    result = await test_combination(
        "tools_mcp_with_disallowed_builtins",
        "Set tools to MCP + disallowed_tools with all built-ins",
        tools=mcp_tools,
        disallowed_tools=BUILTIN_TOOLS
    )
    results.append(result)

    # Test 5: tools=[] + disallowed_tools with built-ins
    result = await test_combination(
        "empty_tools_with_disallowed_builtins",
        "Empty tools + disallowed_tools with all built-ins",
        tools=[],
        disallowed_tools=BUILTIN_TOOLS
    )
    results.append(result)

    # Test 6: tools with MCP + allowed_tools=MCP + disallowed_tools=built-ins
    result = await test_combination(
        "triple_combination",
        "All three: tools=MCP, allowed_tools=MCP, disallowed_tools=built-ins",
        tools=mcp_tools,
        allowed_tools=mcp_tools,
        disallowed_tools=BUILTIN_TOOLS
    )
    results.append(result)

    # Test 7: Check what happens with tools="default" (preset)
    # This is what {"type": "preset", "preset": "claude_code"} maps to
    result = await test_combination(
        "tools_preset_with_allowed",
        "Tools preset (default) + allowed_tools with MCP only",
        tools={"type": "preset", "preset": "claude_code"},
        allowed_tools=mcp_tools
    )
    results.append(result)

    # Test 8: Only allowed_tools (no tools parameter)
    result = await test_combination(
        "only_allowed_tools",
        "Only allowed_tools parameter (no tools)",
        allowed_tools=mcp_tools
    )
    results.append(result)

    # Test 9: Only disallowed_tools (no tools parameter)
    result = await test_combination(
        "only_disallowed_tools",
        "Only disallowed_tools parameter (no tools)",
        disallowed_tools=BUILTIN_TOOLS
    )
    results.append(result)

    # Generate summary
    logger.info("\n" + "="*80)
    logger.info("SUMMARY - Which combinations block built-in tools?")
    logger.info("="*80)

    working = []
    for r in results:
        verdict = r.get("verdict", r.get("error", "ERROR"))
        logger.info(f"\n{r['test']}")
        logger.info(f"  {verdict}")
        if "tools_attempted" in r:
            logger.info(f"  Tools: {r['tools_attempted']}")

        if "✅ PASS" in verdict:
            working.append(r["test"])

    logger.info("\n" + "="*80)
    logger.info("WORKING COMBINATIONS:")
    logger.info("="*80)
    if working:
        for w in working:
            logger.info(f"  ✅ {w}")
        logger.info("\n🎉 You can use one of these instead of pre-tool hook!")
    else:
        logger.info("  ❌ None of the combinations work")
        logger.info("  👉 Continue using pre-tool hook")

    # Save results
    output_file = Path("/opt/genpod/sdk_tools_combinations_results.json")
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    logger.info(f"\n📄 Full results saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
