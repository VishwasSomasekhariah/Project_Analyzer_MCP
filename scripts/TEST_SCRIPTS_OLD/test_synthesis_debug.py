#!/usr/bin/env python3

"""
Quick test to debug the synthesis issue in comprehensive analysis.
"""

import asyncio
import json
import sys
import os
from datetime import datetime

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, '/opt/genpod')

from mcp_use import MCPClient

async def test_synthesis_debug():
    """Test the synthesis in comprehensive analysis"""
    print("🧪 Testing synthesis in comprehensive analysis...")
    
    # Use the existing MCP server configuration
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    
    if not os.path.exists(config_file):
        print(f"❌ Config file not found: {config_file}")
        return False
    
    try:
        async with MCPClient(config_file) as client:
            print("🔌 MCP Client connected successfully")
            
            # Test comprehensive_code_analysis with detailed logging
            test_result = await client.call_tool(
                "comprehensive_code_analysis",
                {
                    "user_query": "Analyze the structure of WorkerA.cs",
                    "project_path": "/opt/HelloWorldApp", 
                    "collection_name": "helloworldapp-benchmarking",
                    "use_hybrid_retrieval": True,
                    "max_final_results": 5  # Smaller for easier debugging
                }
            )
            
            print("\n📊 Test Results:")
            print(f"Status: {test_result.get('status', 'unknown')}")
            print(f"Analysis Type: {test_result.get('analysis_type', 'unknown')}")
            
            # Check synthesis
            synthesis = test_result.get("synthesis", "")
            print(f"\n🔍 Synthesis:")
            print(f"Length: {len(synthesis)}")
            print(f"Content: {synthesis[:200]}...")
            
            # Check if synthesis metadata shows any errors
            synthesis_metadata = test_result.get("synthesis_metadata", {})
            if "synthesis_error" in synthesis_metadata:
                print(f"❌ Synthesis Error: {synthesis_metadata['synthesis_error']}")
            elif "hybrid_analysis" in synthesis_metadata:
                print(f"✅ Hybrid analysis metadata found")
                print(f"   Vector sources: {synthesis_metadata['hybrid_analysis'].get('vector_sources', 0)}")
                print(f"   Graph sources: {synthesis_metadata['hybrid_analysis'].get('graph_sources', 0)}")
            
            # Check hybrid results
            hybrid_results = test_result.get("hybrid_results", [])
            print(f"\n📈 Hybrid Results: {len(hybrid_results)} items")
            if hybrid_results:
                print(f"First result source: {hybrid_results[0].get('source', 'unknown')}")
                print(f"First result content preview: {str(hybrid_results[0].get('content', ''))[:100]}...")
            
            return "Analyze the structure" in synthesis or len(synthesis) > 100
            
    except Exception as e:
        print(f"❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_synthesis_debug())
    if success:
        print("\n✅ Synthesis appears to be working properly")
    else:
        print("\n❌ Synthesis may have issues")