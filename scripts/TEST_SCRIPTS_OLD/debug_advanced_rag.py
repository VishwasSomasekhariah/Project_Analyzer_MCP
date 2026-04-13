#!/usr/bin/env python3
"""
Debug Advanced RAG Test
"""

import asyncio
import json
from mcp_use import MCPClient

async def debug_advanced_rag():
    """Debug why advanced RAG is not working"""
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    
    print("🔧 Debugging Advanced RAG Implementation...")
    
    client = MCPClient.from_config_file(config_file)
    session = await client.create_session("mcp-analysis-server")
    
    # Test with explicit enable_advanced_rag=True
    print("\n1️⃣ Testing with explicit advanced RAG enabled:")
    try:
        response = await session.call_tool(
            "query_cpg_only",
            {
                "user_query": "How many comment lines are in WorkerA.cs?",
                "enable_synthesis": True,
                "enable_advanced_rag": True
            }
        )
        
        if hasattr(response, 'content') and response.content:
            content_text = response.content[0].text
            try:
                parsed = json.loads(content_text)
                print(f"✅ Successfully parsed JSON")
                print(f"Keys: {list(parsed.keys())}")
                print(f"Status: {parsed.get('status')}")
                print(f"Workflow: {parsed.get('workflow', 'NOT_SET')}")
                print(f"Intent: {parsed.get('intent_detected', {})}")
                print(f"Entities: {parsed.get('entities_extracted', {})}")
                
                # Check if we have advanced RAG fields
                advanced_fields = ['workflow', 'entities_extracted', 'retrieval_plan', 'intent_detected']
                found_fields = [field for field in advanced_fields if field in parsed]
                print(f"Advanced RAG fields found: {found_fields}")
                
                if parsed.get('workflow') == 'advanced_rag':
                    print("🎉 ADVANCED RAG IS WORKING!")
                else:
                    print("❌ Advanced RAG not triggered")
                    if 'error' in parsed:
                        print(f"Error: {parsed['error']}")
                
            except Exception as e:
                print(f"❌ JSON parse failed: {e}")
                print(f"Raw content (first 500 chars): {content_text[:500]}")
                
    except Exception as e:
        print(f"❌ Test failed: {e}")

    # Test 2: Just Cypher query to verify basic functionality
    print("\n2️⃣ Testing basic Cypher (should work):")
    try:
        response = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": 'MATCH (n:Type) WHERE n.name = "WorkerA" RETURN n.name, n.body LIMIT 1',
                "enable_synthesis": False,
                "enable_advanced_rag": False
            }
        )
        
        if hasattr(response, 'content') and response.content:
            content_text = response.content[0].text
            try:
                parsed = json.loads(content_text)
                print(f"✅ Basic Cypher working - Status: {parsed.get('status')}")
                has_results = bool(parsed.get('results', {}).get('results'))
                print(f"Has results: {has_results}")
            except Exception as e:
                print(f"❌ Basic Cypher failed: {e}")
                
    except Exception as e:
        print(f"❌ Basic test failed: {e}")

if __name__ == "__main__":
    asyncio.run(debug_advanced_rag())