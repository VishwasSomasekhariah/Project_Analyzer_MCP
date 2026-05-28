#!/usr/bin/env python3
"""
Test script to verify deterministic behavior of project analysis.
Runs the same analysis twice and compares Neo4j node/relationship counts.
"""

import asyncio
import json
import tempfile
import time
from mcp_use import MCPClient

# MCP server configuration
MCP_SERVER_URL = "http://localhost:9000/sse"
NEO4J_MCP_URL = "http://host.docker.internal:8000/sse"

async def get_neo4j_stats():
    """Get current Neo4j database statistics."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tf:
        cfg = {
            "mcpServers": {
                "neo4j_memory": {
                    "type": "http", 
                    "url": NEO4J_MCP_URL
                }
            }
        }
        json.dump(cfg, tf)
        config_path = tf.name

    try:
        client = MCPClient.from_config_file(config_path)
        session = await client.create_session("neo4j_memory")
        
        # Query database stats
        query = """
        MATCH (n) 
        OPTIONAL MATCH (n)-[r]-() 
        RETURN count(DISTINCT n) as nodes, count(DISTINCT r) as relationships
        """
        
        resp = await session.call_tool(
            "neo4j_cypher_query",
            {"cypher": query}
        )
        
        result = resp.content[0].text if resp.content else "{}"
        data = json.loads(result)
        
        if data.get("success") and data.get("results"):
            records = data["results"]
            if records:
                return {
                    "nodes": records[0].get("nodes", 0),
                    "relationships": records[0].get("relationships", 0)
                }
        
        return {"nodes": 0, "relationships": 0}
        
    except Exception as e:
        print(f"Error getting Neo4j stats: {e}")
        return {"nodes": 0, "relationships": 0}
    finally:
        try:
            await client.close_session("neo4j_memory")
        except:
            pass
        import os
        try:
            os.unlink(config_path)
        except:
            pass

async def clear_neo4j_database():
    """Clear the Neo4j database."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tf:
        cfg = {
            "mcpServers": {
                "neo4j_memory": {
                    "type": "http", 
                    "url": NEO4J_MCP_URL
                }
            }
        }
        json.dump(cfg, tf)
        config_path = tf.name

    try:
        client = MCPClient.from_config_file(config_path)
        session = await client.create_session("neo4j_memory")
        
        # Clear database
        resp = await session.call_tool(
            "neo4j_cypher_query",
            {"cypher": "MATCH (n) DETACH DELETE n"}
        )
        
        print("✓ Database cleared")
        return True
        
    except Exception as e:
        print(f"Error clearing database: {e}")
        return False
    finally:
        try:
            await client.close_session("neo4j_memory")
        except:
            pass
        import os
        try:
            os.unlink(config_path)
        except:
            pass

async def run_full_project_setup():
    """Run full_project_setup tool only."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tf:
        cfg = {
            "mcpServers": {
                "project-analyzer-server": {
                    "type": "http",
                    "url": MCP_SERVER_URL
                }
            }
        }
        json.dump(cfg, tf)
        config_path = tf.name

    try:
        client = MCPClient.from_config_file(config_path)
        session = await client.create_session("project-analyzer-server")
        
        print("   🔧 Running full_project_setup...")
        
        # Run full_project_setup (vectorization + CPG analysis + monitoring)
        resp = await session.call_tool(
            "full_project_setup",
            {
                "project_path": "/opt/HelloWorldApp",
                "collection_name": "helloworldapp-test",
                "enable_lsp": True,
                "enable_ai": True
            }
        )
        
        result = json.loads(resp.content[0].text) if resp.content else {}
        
        if result.get("status") == "success":
            print("   ✅ full_project_setup completed successfully")
            return True
        else:
            print(f"   ❌ full_project_setup failed: {result.get('error', 'Unknown error')}")
            return False
        
    except Exception as e:
        print(f"   ❌ full_project_setup exception: {e}")
        return False
    finally:
        try:
            await client.close_session("project-analyzer-server")
        except:
            pass
        import os
        try:
            os.unlink(config_path)
        except:
            pass

async def main():
    """Main test function."""
    print("🧪 Testing Deterministic Behavior of Project Analysis")
    print("=" * 60)
    
    # Test 1: Run analysis twice and compare results
    results = []
    
    for run_num in range(1, 3):
        print(f"\n📊 Run {run_num}: Clearing database and running analysis...")
        
        # Clear database
        if not await clear_neo4j_database():
            print("❌ Failed to clear database")
            return
        
        # Wait a moment for database to stabilize
        await asyncio.sleep(2)
        
        # Verify database is empty
        stats_before = await get_neo4j_stats()
        print(f"   Database before: {stats_before['nodes']} nodes, {stats_before['relationships']} relationships")
        
        if stats_before['nodes'] != 0 or stats_before['relationships'] != 0:
            print("⚠️  Database not properly cleared!")
        
        # Run analysis
        start_time = time.time()
        success = await run_analysis()
        duration = time.time() - start_time
        
        if not success:
            print(f"❌ Analysis failed on run {run_num}")
            return
        
        # Get final stats
        stats_after = await get_neo4j_stats()
        print(f"   Analysis completed in {duration:.2f}s")
        print(f"   Database after: {stats_after['nodes']} nodes, {stats_after['relationships']} relationships")
        
        results.append({
            "run": run_num,
            "nodes": stats_after['nodes'],
            "relationships": stats_after['relationships'],
            "duration": duration
        })
    
    # Compare results
    print("\n" + "=" * 60)
    print("📋 DETERMINISTIC BEHAVIOR TEST RESULTS")
    print("=" * 60)
    
    run1 = results[0]
    run2 = results[1]
    
    print(f"Run 1: {run1['nodes']} nodes, {run1['relationships']} relationships")
    print(f"Run 2: {run2['nodes']} nodes, {run2['relationships']} relationships")
    
    nodes_match = run1['nodes'] == run2['nodes']
    rels_match = run1['relationships'] == run2['relationships']
    
    if nodes_match and rels_match:
        print("✅ SUCCESS: Results are deterministic!")
        print("✅ File ordering fixes resolved the non-deterministic behavior")
    else:
        print("❌ FAILURE: Results are still non-deterministic")
        print(f"   Node difference: {abs(run1['nodes'] - run2['nodes'])}")
        print(f"   Relationship difference: {abs(run1['relationships'] - run2['relationships'])}")
        print("   Further investigation needed into other sources of non-determinism")
    
    print(f"\nPerformance: Run 1: {run1['duration']:.2f}s, Run 2: {run2['duration']:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())