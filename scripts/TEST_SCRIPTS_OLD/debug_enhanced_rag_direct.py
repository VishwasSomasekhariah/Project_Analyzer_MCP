#!/usr/bin/env python3

import asyncio
import json
from mcp_use import MCPClient

async def test_enhanced_rag_direct():
    """Direct test of Enhanced RAG with detailed logging"""
    
    print("🔍 Direct Enhanced RAG Debug Test")
    print("=" * 50)
    
    # Connect to MCP server
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    mcp_client = MCPClient(config_file)
    
    try:
        session = await mcp_client.create_session("mcp-analysis-server")
        print("✅ Connected to MCP server")
        
        # Test the Enhanced RAG workflow
        print(f"🚀 Sending Enhanced RAG request...")
        print(f"   Query: How many comment lines are in WorkerA.cs?")
        
        result = await session.call_tool(
            "query_cpg_only",
            {
                "user_query": "How many comment lines are in WorkerA.cs?",
                "enable_advanced_rag": True,
                "enable_synthesis": True,
                "max_results": 50,
                "config_path": "/opt/genpod/neo4j_config.json"
            }
        )
        
        # Parse result like in the test script
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
        
        try:
            response = json.loads(content_text)
        except json.JSONDecodeError:
            response = {"error": "JSON parsing failed", "raw_response": content_text}
        
        print(f"📊 Response received:")
        print(f"   Status: {response.get('status', 'unknown')}")
        print(f"   Workflow: {response.get('workflow', 'unknown')}")
        print(f"   Analysis type: {response.get('analysis_type', 'unknown')}")
        print(f"   Raw results count: {len(response.get('raw_results', []))}")
        print(f"   Synthesis length: {len(response.get('synthesis', ''))}")
        
        if response.get('entities_extracted'):
            entities = response.get('entities_extracted', {})
            print(f"   Entities found:")
            for key, values in entities.items():
                if values:
                    print(f"     {key}: {values}")
        
        # Check for error details
        if response.get('status') == 'error':
            print(f"❌ Error details: {response.get('error', 'No error details')}")
        
        if response.get('advanced_rag_metadata'):
            metadata = response['advanced_rag_metadata']
            print(f"   Advanced RAG metadata:")
            print(f"     Raw results count: {metadata.get('raw_results_count', 0)}")
            print(f"     Ranked results count: {metadata.get('ranked_results_count', 0)}")
            if metadata.get('query_execution'):
                exec_info = metadata['query_execution']
                print(f"     Query execution: {exec_info}")
        
        # Save full response for analysis
        with open('/opt/genpod/direct_enhanced_rag_debug.json', 'w') as f:
            json.dump(response, f, indent=2, default=str)
        
        print(f"📁 Full response saved to: direct_enhanced_rag_debug.json")
        
    except Exception as e:
        print(f"❌ Test failed with error: {str(e)}")
        import traceback
        print(f"🚨 Full traceback: {traceback.format_exc()}")
    
    finally:
        if 'session' in locals():
            await session.cleanup()
        await mcp_client.close()

if __name__ == "__main__":
    asyncio.run(test_enhanced_rag_direct())