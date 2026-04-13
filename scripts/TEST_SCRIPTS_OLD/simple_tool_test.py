#!/usr/bin/env python3
"""Simple test to debug tool calling."""

import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'project_analyzer_cli'))

from project_analyzer.utils.mcp.mcp_client import MCPClient

async def test_simple_tool_call():
    """Test a simple tool call."""
    print("Testing simple tool call...")
    
    try:
        # Test the main MCP server
        client = MCPClient.from_config_file("file_watcher_mcp_config.json")
        session = await client.create_session("mcp-analysis-server")
        
        print("✅ Session created")
        
        # Try calling get_file_monitor_config (should be simple)
        try:
            result = await session.call_tool("get_file_monitor_config", {})
            print(f"✅ Tool call succeeded: {result}")
        except Exception as e:
            print(f"❌ Tool call failed: {e}")
            import traceback
            traceback.print_exc()
        
        await client.close_session("mcp-analysis-server")
        print("✅ Session closed")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_simple_tool_call())