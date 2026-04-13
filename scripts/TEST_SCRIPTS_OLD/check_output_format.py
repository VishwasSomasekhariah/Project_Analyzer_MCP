#!/usr/bin/env python3
"""
Check Current Output Format of query_cpg_only
"""

import asyncio
import json
from mcp_use import MCPClient

async def check_output_formats():
    """Check both basic Cypher and advanced RAG output formats"""
    
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    client = MCPClient.from_config_file(config_file)
    session = await client.create_session("mcp-analysis-server")
    
    print("🔍 Testing Current Output Formats...\n")
    
    # Test 1: Basic Cypher query (should match original format)
    print("1️⃣ Basic Cypher Query:")
    try:
        response = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": 'MATCH (n:Type) RETURN n.name LIMIT 1',
                "enable_synthesis": False,
                "enable_advanced_rag": False
            }
        )
        
        response_data = json.loads(response.content[0].text)
        print("Keys:", list(response_data.keys()))
        print("Status:", response_data.get("status"))
        print("Has 'results' field:", "results" in response_data)
        print("Has 'cypher_query' field:", "cypher_query" in response_data)
        print("Sample structure:", {k: type(v).__name__ for k, v in response_data.items()})
        
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n" + "="*50 + "\n")
    
    # Test 2: Advanced RAG query (new format)  
    print("2️⃣ Advanced RAG Query:")
    try:
        response = await session.call_tool(
            "query_cpg_only",
            {
                "user_query": "How many comment lines are in WorkerA.cs?",
                "enable_synthesis": True,
                "enable_advanced_rag": True
            }
        )
        
        response_data = json.loads(response.content[0].text)
        print("Keys:", list(response_data.keys()))
        print("Status:", response_data.get("status"))
        print("Workflow:", response_data.get("workflow"))
        print("Has 'results' field:", "results" in response_data)
        print("Has 'cypher_query' field:", "cypher_query" in response_data)
        print("Has 'raw_results' field:", "raw_results" in response_data)
        print("Has 'synthesis' field:", "synthesis" in response_data)
        print("Sample structure:", {k: type(v).__name__ for k, v in response_data.items()})
        
    except Exception as e:
        print(f"Error: {e}")
        
    print("\n" + "="*50 + "\n")
    
    # Test 3: Basic Cypher with synthesis (should match original synthesis format)
    print("3️⃣ Basic Cypher with Synthesis:")
    try:
        response = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": 'MATCH (n:Type) RETURN n.name LIMIT 2',
                "user_query": "What are the type names?",
                "enable_synthesis": True,
                "enable_advanced_rag": False
            }
        )
        
        response_data = json.loads(response.content[0].text)
        print("Keys:", list(response_data.keys()))
        print("Status:", response_data.get("status"))
        print("Has 'results' field:", "results" in response_data)
        print("Has 'raw_results' field:", "raw_results" in response_data)
        print("Has 'cypher_query' field:", "cypher_query" in response_data)
        print("Has 'synthesis' field:", "synthesis" in response_data)
        print("Sample structure:", {k: type(v).__name__ for k, v in response_data.items()})
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_output_formats())