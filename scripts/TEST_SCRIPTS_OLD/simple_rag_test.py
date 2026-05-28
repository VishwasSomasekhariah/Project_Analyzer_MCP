#!/usr/bin/env python3
"""
Simple Enhanced Graph RAG Test to check response format
"""

import asyncio
import json
from mcp_use import MCPClient

async def test_response_format():
    """Test to understand MCP response format"""
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    
    print("🔍 Testing MCP Response Format...")
    
    client = MCPClient.from_config_file(config_file)
    session = await client.create_session("mcp-analysis-server")
    
    # Test basic Cypher query
    print("\n1️⃣ Testing Basic Cypher Query:")
    try:
        response = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": 'MATCH (n:Type) RETURN n.name LIMIT 1',
                "enable_synthesis": False,
                "enable_advanced_rag": False
            }
        )
        
        print(f"Response type: {type(response)}")
        print(f"Response attributes: {dir(response)}")
        
        if hasattr(response, 'content'):
            print(f"Content type: {type(response.content)}")
            if response.content:
                print(f"First content item: {type(response.content[0])}")
                print(f"Content text: {response.content[0].text[:200]}...")
        
        # Try to parse as JSON
        if hasattr(response, 'content') and response.content:
            content_text = response.content[0].text
            try:
                parsed = json.loads(content_text)
                print(f"✅ Successfully parsed JSON")
                print(f"Keys: {list(parsed.keys())}")
                print(f"Status: {parsed.get('status')}")
            except Exception as e:
                print(f"❌ JSON parse failed: {e}")
                
    except Exception as e:
        print(f"❌ Test failed: {e}")
    
    # Test natural language query
    print("\n2️⃣ Testing Natural Language Query:")
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
                print(f"Workflow: {parsed.get('workflow')}")
                print(f"Intent: {parsed.get('intent_detected', {}).get('type')}")
                print(f"Entities: {list(parsed.get('entities_extracted', {}).keys())}")
            except Exception as e:
                print(f"❌ JSON parse failed: {e}")
                print(f"Raw content (first 300 chars): {content_text[:300]}")
                
    except Exception as e:
        print(f"❌ Test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_response_format())