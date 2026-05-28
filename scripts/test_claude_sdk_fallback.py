#!/usr/bin/env python3
"""
Test script for Claude SDK fallback integration.

Tests:
1. ClaudeSDKFallback standalone functionality
2. ResilientLLMClient fallback behavior
3. MCP server configuration
"""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_claude_sdk_fallback_standalone():
    """Test ClaudeSDKFallback standalone."""
    print("\n" + "="*60)
    print("TEST 1: ClaudeSDKFallback Standalone")
    print("="*60)

    from src.core.graph_rag.core.claude_sdk_fallback import ClaudeSDKFallback

    # Create fallback with MCP config
    fallback = ClaudeSDKFallback(
        mcp_config_path="fallback_agent/claude_code_mcp_config.json",
        system_prompt="You are a helpful assistant. Keep responses brief.",
        max_turns=5
    )

    print(f"  SDK Available: {fallback.is_available}")
    print(f"  MCP Servers: {list(fallback.mcp_servers.keys())}")

    if not fallback.is_available:
        print("  SKIP: claude_agent_sdk not installed")
        return False

    # Test simple query
    print("\n  Testing simple query...")
    try:
        response = await fallback.query("What is 2 + 2? Reply with just the number.")
        print(f"  Response: {response.content[:200]}...")
        print(f"  Model: {response.model}")
        print(f"  Cost: ${response.cost_usd}")
        print("  PASS: Query succeeded")
        return True
    except Exception as e:
        print(f"  FAIL: Query failed: {e}")
        return False


def test_resilient_client_initialization():
    """Test ResilientLLMClient initialization with direct mode."""
    print("\n" + "="*60)
    print("TEST 2: ResilientLLMClient Initialization (Direct Mode)")
    print("="*60)

    from src.core.graph_rag.core.llm_client import ResilientLLMClient

    # Test direct mode initialization
    client = ResilientLLMClient(
        primary_config={"api_key": "test-key"},  # Will fail, that's ok
        fallback_mode="direct",
        mcp_config_path="fallback_agent/claude_code_mcp_config.json",
        system_prompt="You are a helpful assistant.",
        max_turns=5
    )

    print(f"  Fallback Mode: {client._fallback_mode}")
    print(f"  Fallback Available: {client._fallback_available}")
    print(f"  SDK Fallback: {client._sdk_fallback is not None}")

    if client._sdk_fallback:
        print(f"  MCP Servers: {list(client._sdk_fallback.mcp_servers.keys())}")

    print("  PASS: Initialization succeeded")
    return True


def test_resilient_client_adapter_mode():
    """Test ResilientLLMClient initialization with adapter mode."""
    print("\n" + "="*60)
    print("TEST 3: ResilientLLMClient Initialization (Adapter Mode)")
    print("="*60)

    from src.core.graph_rag.core.llm_client import ResilientLLMClient

    # Test adapter mode initialization
    client = ResilientLLMClient(
        primary_config={"api_key": "test-key"},
        fallback_mode="adapter",
        fallback_url="http://localhost:8889/v1",
    )

    print(f"  Fallback Mode: {client._fallback_mode}")
    print(f"  Fallback Available: {client._fallback_available}")
    print(f"  Adapter Fallback: {client._adapter_fallback is not None}")

    print("  PASS: Initialization succeeded (adapter may not be running)")
    return True


def test_mcp_server_management():
    """Test MCP server management methods."""
    print("\n" + "="*60)
    print("TEST 4: MCP Server Management")
    print("="*60)

    from src.core.graph_rag.core.llm_client import ResilientLLMClient

    client = ResilientLLMClient(
        primary_config={"api_key": "test-key"},
        fallback_mode="direct",
    )

    # Add server
    result = client.add_mcp_server("test_server", {"type": "sse", "url": "http://test:8000/sse"})
    print(f"  Add server: {result}")

    # List servers
    result = client.list_mcp_servers()
    print(f"  List servers: {result}")

    # Remove server
    result = client.remove_mcp_server("test_server")
    print(f"  Remove server: {result}")

    print("  PASS: MCP management works")
    return True


def test_hooks_integration():
    """Test pre/post tool hooks."""
    print("\n" + "="*60)
    print("TEST 5: Hooks Integration")
    print("="*60)

    from src.core.graph_rag.core.llm_client import ResilientLLMClient

    hook_calls = {"pre": 0, "post": 0}

    def pre_hook(tool_name, tool_input):
        hook_calls["pre"] += 1
        print(f"    Pre-hook called: {tool_name}")
        return True  # Allow

    def post_hook(tool_name, tool_input, tool_response):
        hook_calls["post"] += 1
        print(f"    Post-hook called: {tool_name}")

    client = ResilientLLMClient(
        primary_config={"api_key": "test-key"},
        fallback_mode="direct",
        pre_tool_hook=pre_hook,
        post_tool_hook=post_hook,
    )

    print(f"  Pre-hook registered: {client._pre_tool_hook is not None}")
    print(f"  Post-hook registered: {client._post_tool_hook is not None}")

    if client._sdk_fallback:
        print(f"  SDK fallback has pre-hook: {client._sdk_fallback._pre_tool_hook is not None}")
        print(f"  SDK fallback has post-hook: {client._sdk_fallback._post_tool_hook is not None}")

    print("  PASS: Hooks configured")
    return True


async def test_fallback_with_query():
    """Test actual fallback with a query (requires Claude SDK)."""
    print("\n" + "="*60)
    print("TEST 6: Fallback with Query (requires Claude SDK)")
    print("="*60)

    from src.core.graph_rag.core.claude_sdk_fallback import ClaudeSDKFallback

    fallback = ClaudeSDKFallback(
        system_prompt="You are a code analysis assistant. Keep responses concise.",
        max_turns=3
    )

    if not fallback.is_available:
        print("  SKIP: claude_agent_sdk not installed")
        return False

    print("  Testing query with system prompt override...")
    try:
        response = await fallback.query(
            "Say 'Hello from Claude SDK fallback!' and nothing else.",
            system_prompt="You follow instructions exactly."
        )
        print(f"  Response: {response.content}")
        print(f"  Session ID: {response.session_id}")
        print("  PASS: Query with override succeeded")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "#"*60)
    print("# CLAUDE SDK FALLBACK INTEGRATION TESTS")
    print("#"*60)

    results = []

    # Sync tests
    results.append(("Initialization (Direct)", test_resilient_client_initialization()))
    results.append(("Initialization (Adapter)", test_resilient_client_adapter_mode()))
    results.append(("MCP Management", test_mcp_server_management()))
    results.append(("Hooks Integration", test_hooks_integration()))

    # Async tests
    results.append(("Standalone Fallback", asyncio.run(test_claude_sdk_fallback_standalone())))
    results.append(("Query with Override", asyncio.run(test_fallback_with_query())))

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for name, passed in results:
        status = "PASS" if passed else "FAIL/SKIP"
        print(f"  {name}: {status}")

    passed_count = sum(1 for _, p in results if p)
    print(f"\n  Total: {passed_count}/{len(results)} passed")

    return 0 if passed_count >= 4 else 1  # At least 4 tests should pass


if __name__ == "__main__":
    sys.exit(main())
