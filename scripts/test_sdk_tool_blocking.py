#!/usr/bin/env python3
"""
Test if Claude Agent SDK 0.1.25+ supports blocking built-in tools via agent options.

This test checks:
1. Can we block built-in tools using allowed_tools parameter alone?
2. Is there a disallowed_tools parameter?
3. Is there a blocked_tools or similar parameter?
4. What's the behavior difference with/without pre-tool hooks?
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Built-in tools to test blocking
CLAUDE_BUILTIN_TOOLS = [
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "LS", "MultiEdit",
    "NotebookRead", "NotebookEdit", "WebFetch", "WebSearch",
    "TodoRead", "TodoWrite", "Task",
]


class SDKToolBlockingTest:
    """Test different methods of blocking built-in tools in Claude Agent SDK."""

    def __init__(self):
        self.test_results = {}

    async def test_allowed_tools_only(self):
        """
        Test 1: Can allowed_tools parameter block built-in tools without hooks?

        Expected behavior if fixed:
        - SDK should prevent built-in tools from being called when not in allowed_tools
        - No pre-tool hook should be needed
        """
        logger.info("\n" + "="*80)
        logger.info("TEST 1: allowed_tools parameter (without pre-tool hook)")
        logger.info("="*80)

        try:
            from claude_agent_sdk import (
                ClaudeSDKClient,
                ClaudeAgentOptions,
                AssistantMessage,
                ResultMessage,
                TextBlock,
                ToolUseBlock,
            )

            # Create simple options with ONLY allowed_tools (no hooks)
            # We allow NO tools, expecting built-in tools to be blocked
            options = ClaudeAgentOptions(
                model="claude-sonnet-4-20250514",
                system_prompt="You are a test assistant. Try to use the Read tool to read a file.",
                allowed_tools=[],  # Empty list - NO tools allowed
                max_turns=3,
            )

            tool_attempts = []
            response_text = ""

            async with ClaudeSDKClient(options=options) as client:
                await client.query("Please use the Read tool to read /etc/hostname")

                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                response_text += block.text
                            elif isinstance(block, ToolUseBlock):
                                tool_attempts.append({
                                    "name": block.name,
                                    "id": block.id
                                })
                                logger.info(f"Tool called: {block.name}")

                    elif isinstance(message, ResultMessage):
                        logger.info(f"Query completed - cost: ${message.total_cost_usd:.4f}")

            # Check results
            read_tool_called = any(t["name"] == "Read" for t in tool_attempts)

            result = {
                "test": "allowed_tools_only",
                "tools_attempted": [t["name"] for t in tool_attempts],
                "read_tool_called": read_tool_called,
                "response_preview": response_text[:200] if response_text else None,
                "verdict": "FAIL - Read tool was called" if read_tool_called else "PASS - Read tool blocked",
            }

            self.test_results["allowed_tools_only"] = result
            logger.info(f"Result: {result['verdict']}")
            logger.info(f"Tools attempted: {result['tools_attempted']}")

            return result

        except Exception as e:
            logger.error(f"Test failed with error: {e}", exc_info=True)
            self.test_results["allowed_tools_only"] = {"error": str(e)}
            return {"error": str(e)}

    async def test_disallowed_tools_parameter(self):
        """
        Test 2: Check if there's a disallowed_tools parameter.

        This would be the ideal solution - explicitly list tools to block.
        """
        logger.info("\n" + "="*80)
        logger.info("TEST 2: disallowed_tools parameter (if it exists)")
        logger.info("="*80)

        try:
            from claude_agent_sdk import ClaudeAgentOptions
            import inspect

            # Check ClaudeAgentOptions signature
            sig = inspect.signature(ClaudeAgentOptions)
            params = list(sig.parameters.keys())

            logger.info(f"ClaudeAgentOptions parameters: {params}")

            has_disallowed = "disallowed_tools" in params
            has_blocked = "blocked_tools" in params
            has_denied = "denied_tools" in params

            result = {
                "test": "parameter_inspection",
                "has_disallowed_tools": has_disallowed,
                "has_blocked_tools": has_blocked,
                "has_denied_tools": has_denied,
                "all_parameters": params,
            }

            if has_disallowed or has_blocked or has_denied:
                logger.info("✓ Found tool blocking parameter(s)!")
                result["verdict"] = "FOUND"

                # Try to use it
                if has_disallowed:
                    await self._test_disallowed_parameter()
            else:
                logger.info("✗ No disallowed/blocked/denied_tools parameter found")
                result["verdict"] = "NOT_FOUND"

            self.test_results["disallowed_tools_parameter"] = result
            return result

        except Exception as e:
            logger.error(f"Test failed with error: {e}", exc_info=True)
            self.test_results["disallowed_tools_parameter"] = {"error": str(e)}
            return {"error": str(e)}

    async def _test_disallowed_parameter(self):
        """Test using disallowed_tools parameter if it exists."""
        logger.info("\nTesting disallowed_tools parameter...")

        try:
            from claude_agent_sdk import (
                ClaudeSDKClient,
                ClaudeAgentOptions,
                AssistantMessage,
                ResultMessage,
                ToolUseBlock,
            )

            # Try to use disallowed_tools
            options = ClaudeAgentOptions(
                model="claude-sonnet-4-20250514",
                system_prompt="You are a test assistant. Try to use the Read tool.",
                disallowed_tools=CLAUDE_BUILTIN_TOOLS,  # Block all built-in tools
                max_turns=3,
            )

            tool_attempts = []

            async with ClaudeSDKClient(options=options) as client:
                await client.query("Please use the Read tool to read /etc/hostname")

                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, ToolUseBlock):
                                tool_attempts.append(block.name)
                                logger.info(f"Tool called: {block.name}")

            read_tool_called = "Read" in tool_attempts

            result = {
                "test": "disallowed_tools_usage",
                "tools_attempted": tool_attempts,
                "read_tool_called": read_tool_called,
                "verdict": "FAIL - Read still called" if read_tool_called else "PASS - Read blocked",
            }

            logger.info(f"Result: {result['verdict']}")
            self.test_results["disallowed_tools_usage"] = result

        except TypeError as e:
            # Parameter doesn't exist or wrong type
            logger.warning(f"disallowed_tools parameter test failed: {e}")
            self.test_results["disallowed_tools_usage"] = {
                "error": "Parameter not supported",
                "details": str(e)
            }

    async def test_with_pre_tool_hook(self):
        """
        Test 3: Verify pre-tool hook still works (current workaround).

        This is the current approach - just verify it still works.
        """
        logger.info("\n" + "="*80)
        logger.info("TEST 3: Pre-tool hook (current workaround)")
        logger.info("="*80)

        try:
            from claude_agent_sdk import (
                ClaudeSDKClient,
                ClaudeAgentOptions,
                AssistantMessage,
                ResultMessage,
                ToolUseBlock,
                HookMatcher,
            )
            from claude_agent_sdk.types import SyncHookJSONOutput

            blocked_tools = []

            async def pre_tool_hook(hook_input, tool_use_id, context):
                """Hook to block built-in tools."""
                tool_name = hook_input.get("tool_name", "")

                if tool_name in CLAUDE_BUILTIN_TOOLS:
                    logger.info(f"Pre-tool hook: BLOCKING {tool_name}")
                    blocked_tools.append(tool_name)
                    return SyncHookJSONOutput(
                        continue_=True,
                        hookSpecificOutput={
                            'hookEventName': 'PreToolUse',
                            'permissionDecision': 'deny',
                            'permissionDecisionReason': f"Built-in tool '{tool_name}' is blocked in test"
                        }
                    )

                logger.info(f"Pre-tool hook: ALLOWING {tool_name}")
                return SyncHookJSONOutput(continue_=True)

            hooks = {
                "PreToolUse": [
                    HookMatcher(matcher=".*", hooks=[pre_tool_hook])
                ]
            }

            options = ClaudeAgentOptions(
                model="claude-sonnet-4-20250514",
                system_prompt="You are a test assistant. Try to use the Read tool.",
                hooks=hooks,
                max_turns=3,
            )

            tool_attempts = []
            response_text = ""

            async with ClaudeSDKClient(options=options) as client:
                await client.query("Please use the Read tool to read /etc/hostname")

                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, ToolUseBlock):
                                tool_attempts.append(block.name)

            result = {
                "test": "pre_tool_hook",
                "tools_attempted": tool_attempts,
                "tools_blocked": blocked_tools,
                "hook_worked": len(blocked_tools) > 0,
                "verdict": "PASS - Hook blocked tools" if blocked_tools else "FAIL - Hook didn't block",
            }

            logger.info(f"Result: {result['verdict']}")
            logger.info(f"Blocked: {blocked_tools}")

            self.test_results["pre_tool_hook"] = result
            return result

        except Exception as e:
            logger.error(f"Test failed with error: {e}", exc_info=True)
            self.test_results["pre_tool_hook"] = {"error": str(e)}
            return {"error": str(e)}

    async def run_all_tests(self):
        """Run all tests and generate report."""
        logger.info("="*80)
        logger.info("Claude Agent SDK Tool Blocking Test Suite")
        logger.info(f"SDK Version: 0.1.25")
        logger.info("="*80)

        # Run tests
        await self.test_disallowed_tools_parameter()
        await self.test_allowed_tools_only()
        await self.test_with_pre_tool_hook()

        # Generate report
        self._generate_report()

    def _generate_report(self):
        """Generate final test report."""
        logger.info("\n" + "="*80)
        logger.info("TEST REPORT SUMMARY")
        logger.info("="*80)

        # Check if we can avoid pre-tool hooks
        param_check = self.test_results.get("disallowed_tools_parameter", {})
        has_native_blocking = (
            param_check.get("has_disallowed_tools") or
            param_check.get("has_blocked_tools") or
            param_check.get("has_denied_tools")
        )

        allowed_test = self.test_results.get("allowed_tools_only", {})
        allowed_blocks_properly = not allowed_test.get("read_tool_called", True)

        hook_test = self.test_results.get("pre_tool_hook", {})
        hook_works = hook_test.get("hook_worked", False)

        logger.info(f"\n1. Native blocking parameter exists: {'✓ YES' if has_native_blocking else '✗ NO'}")
        logger.info(f"2. allowed_tools blocks built-ins: {'✓ YES' if allowed_blocks_properly else '✗ NO'}")
        logger.info(f"3. Pre-tool hook works (workaround): {'✓ YES' if hook_works else '✗ NO'}")

        logger.info("\n" + "-"*80)
        logger.info("RECOMMENDATION:")
        logger.info("-"*80)

        if has_native_blocking:
            logger.info("✓ Use the native disallowed_tools/blocked_tools parameter!")
            logger.info("  You can remove the pre-tool hook workaround.")
        elif allowed_blocks_properly:
            logger.info("✓ allowed_tools parameter now properly blocks built-in tools!")
            logger.info("  You can simplify by just using allowed_tools without a pre-tool hook.")
        else:
            logger.info("✗ Still need pre-tool hook workaround")
            logger.info("  The SDK doesn't yet support blocking built-in tools natively.")

        # Save results to file
        output_file = Path("/opt/genpod/sdk_tool_blocking_test_results.json")
        with open(output_file, "w") as f:
            json.dump(self.test_results, f, indent=2)

        logger.info(f"\nDetailed results saved to: {output_file}")


async def main():
    """Main test runner."""
    tester = SDKToolBlockingTest()
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
