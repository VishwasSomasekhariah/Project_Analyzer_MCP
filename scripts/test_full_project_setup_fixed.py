#!/usr/bin/env python3
"""
Simple test to run full_project_setup tool and verify it works correctly.
"""

import asyncio
import json
import tempfile
import time
from mcp_use import MCPClient

# MCP server configuration
MCP_SERVER_URL = "http://host.docker.internal:9000/sse"

async def test_full_project_setup():
    """Test the full_project_setup tool."""
    print("🧪 Testing full_project_setup tool")
    print("=" * 50)
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tf:
        cfg = {
            "mcpServers": {
                "mcp-analysis-server": {
                    "type": "http",
                    "url": MCP_SERVER_URL
                }
            }
        }
        json.dump(cfg, tf)
        config_path = tf.name

    try:
        client = MCPClient.from_config_file(config_path)
        session = await client.create_session("mcp-analysis-server")
        
        print("✅ Connected to MCP server")
        
        # Run full_project_setup
        print("🔧 Running full_project_setup...")
        print("   Project: /opt/HelloWorldApp")
        print("   Collection: helloworldapp-benchmarking")
        print("   LSP: enabled")
        print("   AI: enabled")
        print("⏳ Processing...")
        
        start_time = time.time()
        resp = await session.call_tool(
            "full_project_setup",
            {
                "project_path": "/opt/HelloWorldApp",
                "collection_name": "helloworldapp-benchmarking",
                "enable_lsp": True,
                "enable_ai": True
            }
        )
        duration = time.time() - start_time
        
        # Parse result
        result = json.loads(resp.content[0].text) if resp.content else {}
        
        print(f"⏱️  Completed in {duration:.2f} seconds")
        
        if result.get("status") == "success":
            print("✅ SUCCESS: full_project_setup completed successfully!")
            
            # Show detailed results
            if "capabilities" in result:
                print(f"📊 Capabilities: {result['capabilities']}")
            if "monitoring_mode" in result:
                print(f"📡 Monitoring mode: {result['monitoring_mode']}")
            
            # Show step results if available
            for step_key in ["1_vectorization", "2_cpg_analysis", "3_enable_monitoring"]:
                if step_key in result:
                    step_status = result[step_key]
                    print(f"   {step_key}: {step_status}")
            
            return True
        else:
            print("❌ FAILURE: full_project_setup failed")
            print(f"Error: {result.get('error', 'Unknown error')}")
            if 'traceback' in result:
                print(f"Traceback: {result['traceback']}")
            return False
        
    except Exception as e:
        print(f"❌ Exception occurred: {e}")
        return False
    finally:
        try:
            await client.close_session("mcp-analysis-server")
        except:
            pass
        import os
        try:
            os.unlink(config_path)
        except:
            pass

async def main():
    """Main function."""
    success = await test_full_project_setup()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 Test completed successfully!")
        print("✅ full_project_setup tool is working correctly")
    else:
        print("❌ Test failed!")
        print("🔧 Check the error messages above for details")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(main())