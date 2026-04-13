import asyncio
import sys
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service

async def test():
    print("Testing Neo4j connection...")
    server = await create_cypher_server_service("neo4j_config.json")
    
    # Test simple query
    result = await server.execute_query("MATCH (n) RETURN count(n) as count LIMIT 1")
    print(f"Query result: {result}")
    
    # Test APOC schema
    apoc_result = await server.execute_query("CALL apoc.meta.schema()")
    print(f"APOC result status: {apoc_result.get('status')}")
    print(f"APOC result keys: {apoc_result.keys()}")
    if apoc_result.get('data'):
        print(f"APOC data type: {type(apoc_result['data'])}")
        print(f"APOC data: {apoc_result['data'][:200] if apoc_result['data'] else 'None'}")

asyncio.run(test())
