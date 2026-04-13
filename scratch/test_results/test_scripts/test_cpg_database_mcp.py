#!/usr/bin/env python3
"""
Test CPG database queries using MCP approach
"""

import asyncio
import json
import sys
import os
from pathlib import Path

# Add the test scripts directory to the path
sys.path.insert(0, str(Path(__file__).parent / "test_results" / "test_scripts"))

from mcp_use import MCPClient

async def test_cpg_queries():
    """Test various CPG queries to understand database structure."""
    
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    neo4j_config = "/opt/genpod/neo4j_config.json"
    
    # Test queries to understand database structure
    test_queries = [
        {
            "name": "Find all node types",
            "query": "MATCH (n) RETURN DISTINCT labels(n) AS node_types LIMIT 10"
        },
        {
            "name": "Find all relationship types", 
            "query": "MATCH ()-[r]->() RETURN DISTINCT type(r) AS relationship_types LIMIT 10"
        },
        {
            "name": "Find all Type nodes",
            "query": "MATCH (t:Type) RETURN t.name, t.type_kind, t.file_path LIMIT 10"
        },
        {
            "name": "Find all File nodes",
            "query": "MATCH (f:File) RETURN f.name, f.file_path LIMIT 10"
        },
        {
            "name": "Find WorkerFactory specifically",
            "query": "MATCH (t:Type) WHERE t.name = 'WorkerFactory' RETURN t.name, t.file_path, t.type_kind"
        },
        {
            "name": "Find all Factory-related types",
            "query": "MATCH (t:Type) WHERE t.name CONTAINS 'Factory' OR t.name CONTAINS 'Worker' RETURN t.name, t.file_path LIMIT 10"
        },
        {
            "name": "Find Manager class",
            "query": "MATCH (t:Type) WHERE t.name = 'Manager' RETURN t.name, t.file_path, t.type_kind"
        },
        {
            "name": "Find all interfaces",
            "query": "MATCH (t:Type) WHERE t.type_kind = 'interface' RETURN t.name, t.file_path"
        },
        {
            "name": "Find all methods",
            "query": "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 10"
        },
        {
            "name": "Find relationships between types",
            "query": "MATCH (t1:Type)-[r]->(t2:Type) RETURN t1.name, type(r), t2.name LIMIT 10"
        }
    ]
    
    try:
        # Connect to MCP server
        client = MCPClient.from_config_file(config_file)
        session = await client.create_session("project-analyzer-server")
        
        print("Testing CPG Database Queries via MCP")
        print("=" * 80)
        
        for test in test_queries:
            print(f"\n🔍 {test['name']}:")
            print(f"Query: {test['query']}")
            
            try:
                result = await session.call_tool(
                    "query_cpg_only",
                    {
                        "cypher_query": test["query"],
                        "config_path": neo4j_config,
                        "max_results": 20
                    }
                )
                
                result_content = result.content[0] if isinstance(result.content, list) else result.content
                content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
                
                print(f"✅ Result: {content_text}")
                print("-" * 40)
                
            except Exception as e:
                print(f"❌ Error: {e}")
                print("-" * 40)
        
        await session.close()
        await client.close()
        
    except Exception as e:
        print(f"❌ Connection error: {e}")

if __name__ == "__main__":
    asyncio.run(test_cpg_queries())