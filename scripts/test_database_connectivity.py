#!/usr/bin/env python3
"""Test Neo4j database connectivity and available nodes."""
import asyncio
from src.core.workflow.cypher_server_pool import CypherServerPool

async def test_db():
    """Test database connectivity and check what nodes exist."""

    pool = CypherServerPool(
        pool_size=1,
        neo4j_config="neo4j_config.json",
        query_timeout=10
    )

    try:
        await pool.initialize()
        print("✅ Pool initialized")

        # Get a server
        server = await pool.acquire()
        print(f"✅ Acquired server: {server.server_id}")

        # Test queries in order of complexity
        test_queries = [
            ("Count all nodes", "MATCH (n) RETURN count(n) as total"),
            ("List node labels", "MATCH (n) RETURN DISTINCT labels(n) as labels LIMIT 10"),
            ("Count Projects", "MATCH (p:Project) RETURN count(p) as count"),
            ("List Projects", "MATCH (p:Project) RETURN p.name LIMIT 5"),
            ("Count Functions", "MATCH (f:Function) RETURN count(f) as count"),
            ("List Functions", "MATCH (f:Function) RETURN f.name LIMIT 5"),
        ]

        for name, query in test_queries:
            print(f"\n🔍 {name}")
            print(f"   Query: {query}")
            try:
                result = await server.execute_query(
                    cypher_query=query
                )
                print(f"   ✅ Success: {result}")
            except Exception as e:
                print(f"   ❌ Failed: {e}")

        # Release server
        await pool.release(server)
        print("\n✅ Server released")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await pool.shutdown()
        print("✅ Pool shutdown")

if __name__ == '__main__':
    asyncio.run(test_db())
