#!/usr/bin/env python3
"""
Test script to call the main MCP analysis server's query_cpg_only tool
"""

import asyncio
import json
from mcp_use import MCPClient

async def test_main_server():
    """Test the main MCP analysis server query_cpg_only tool"""
    
    # Create MCP client - use localhost instead of host.docker.internal
    # config = {
    #     "mcpServers": {
    #         "mcp-analysis-server": {
    #             "type": "http",
    #             "url": "http://localhost:9000/sse"
    #         }
    #     }
    # }
    config = {
        "mcpServers": {
            "mcp-analysis-server": {
                "type": "http",
                "url": "http://localhost:9001/sse"
            }
        }
    }
    
    # Write temp config
    with open("/tmp/main_server_config.json", "w") as f:
        json.dump(config, f)
    
    client = MCPClient.from_config_file("/tmp/main_server_config.json")
    
    try:
        # Create session with the server name from config
        print("Creating session with mcp-analysis-server...")
        session = await client.create_session("mcp-analysis-server")
        
        # List available tools
        tools = session.tools
        print(f"Available tools: {[tool.name for tool in tools]}")
        
        # Test full_project_setup tool
        print("\nTesting full_project_setup tool...")
        result = await session.call_tool("full_project_setup", {
            "project_path": "/opt/HelloWorldApp",
            "collection_name": "helloworldapp-test-2025",
            "enable_lsp": True,
            "enable_ai": True
        })
        
        print(f"Query result: {result.content}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print("Closing session...")
        await client.close_session("mcp-analysis-server")

if __name__ == "__main__":
    asyncio.run(test_main_server())