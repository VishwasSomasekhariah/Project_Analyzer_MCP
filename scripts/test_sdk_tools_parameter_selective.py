#!/usr/bin/env python3
"""
Test if we can use the 'tools' parameter to selectively allow MCP tools
while blocking built-in tools.

If this works, it would be an alternative to the pre-tool hook.
"""

import asyncio
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_mcp_tools_config():
    """
    Test loading MCP config and checking if we can explicitly list allowed tools.

    The idea: If we provide an explicit tools list that only includes MCP tools,
    maybe built-in tools will be excluded automatically.
    """
    logger.info("="*80)
    logger.info("Testing: Explicit MCP tools via tools parameter")
    logger.info("="*80)

    try:
        from claude_agent_sdk import (
            ClaudeSDKClient,
            ClaudeAgentOptions,
            AssistantMessage,
            ToolUseBlock,
        )

        # Load Neo4j MCP config
        mcp_config_path = Path("/opt/genpod/neo4j_config.json")
        if not mcp_config_path.exists():
            logger.warning(f"Neo4j config not found at {mcp_config_path}")
            logger.info("Trying with empty MCP config...")
            mcp_servers = {}
        else:
            with open(mcp_config_path) as f:
                config = json.load(f)
                mcp_servers = config.get("mcpServers", config)
            logger.info(f"Loaded MCP servers: {list(mcp_servers.keys())}")

        # Test 1: Using MCP servers with allowed_tools (should only allow MCP tools)
        logger.info("\n--- Test 1: MCP servers + allowed_tools ---")

        # Get available MCP tool names from the servers
        # In practice, these would be like: mcp__neo4j_memory__neo4j_execute_query
        mcp_tool_names = [
            "mcp__neo4j_memory__neo4j_execute_query",
            "mcp__neo4j_memory__neo4j_fuzzy_search",
        ]

        options = ClaudeAgentOptions(
            model="claude-sonnet-4-20250514",
            system_prompt=(
                "You have access to Neo4j MCP tools. "
                "Try to use the Read tool first, then try neo4j_execute_query."
            ),
            mcp_servers=mcp_servers,
            allowed_tools=mcp_tool_names,  # Only allow MCP tools
            max_turns=3,
        )

        tool_attempts = []

        async with ClaudeSDKClient(options=options) as client:
            await client.query("Use Read tool to read /etc/hostname, then query Neo4j")

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            tool_attempts.append(block.name)
                            logger.info(f"  Tool called: {block.name}")

        read_called = "Read" in tool_attempts
        mcp_called = any("neo4j" in t.lower() or "mcp" in t.lower() for t in tool_attempts)

        result_1 = {
            "test": "mcp_servers_with_allowed_tools",
            "read_called": read_called,
            "mcp_tool_called": mcp_called,
            "tools_attempted": tool_attempts,
            "verdict": (
                "✅ PASS - Read blocked, MCP allowed" if not read_called and mcp_called
                else "⚠️  PARTIAL - Read blocked but no MCP" if not read_called
                else "❌ FAIL - Read not blocked"
            ),
        }

        logger.info(f"Result: {result_1['verdict']}")
        logger.info(f"Tools attempted: {tool_attempts}")

        # Test 2: Check if setting tools=None uses all available tools
        logger.info("\n--- Test 2: tools=None (should use all) ---")

        options = ClaudeAgentOptions(
            model="claude-sonnet-4-20250514",
            system_prompt="Try to use the Read tool.",
            tools=None,  # Explicitly None
            max_turns=2,
        )

        tool_attempts = []

        async with ClaudeSDKClient(options=options) as client:
            await client.query("Use Read tool to read /etc/hostname")

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            tool_attempts.append(block.name)
                            logger.info(f"  Tool called: {block.name}")

        result_2 = {
            "test": "tools_none",
            "read_called": "Read" in tool_attempts,
            "tools_attempted": tool_attempts,
            "verdict": "❌ FAIL - Read called" if "Read" in tool_attempts else "✅ PASS - Read blocked",
        }

        logger.info(f"Result: {result_2['verdict']}")

        # Generate report
        logger.info("\n" + "="*80)
        logger.info("ANALYSIS")
        logger.info("="*80)

        if not result_1["read_called"]:
            logger.info("✅ allowed_tools with MCP servers blocks built-in tools!")
            logger.info("   You can use: allowed_tools=[...MCP tool names...]")
            logger.info("   instead of pre-tool hook")
        else:
            logger.info("❌ allowed_tools doesn't block built-in tools")
            logger.info("   Pre-tool hook is still needed")

        # Save results
        results = {
            "test_1_mcp_allowed_tools": result_1,
            "test_2_tools_none": result_2,
        }

        output_file = Path("/opt/genpod/sdk_tools_parameter_test_results.json")
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)

        logger.info(f"\nResults saved to: {output_file}")

        return results

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        return {"error": str(e)}


async def main():
    await test_mcp_tools_config()


if __name__ == "__main__":
    asyncio.run(main())
