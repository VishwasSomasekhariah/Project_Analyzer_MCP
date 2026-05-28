import asyncio
import sys
sys.path.insert(0, '/opt/genpod')

from src.core.workflow.cypher_server_pool import CypherServerInstance

async def test():
    server = CypherServerInstance(server_id=0, neo4j_config="neo4j_config.json")
    await server.start()
    
    print("=" * 80)
    print("Test 1: Valid property (Function.name)")
    print("=" * 80)
    result1 = await server.execute_query(
        "MATCH (f:Function) WHERE f.name = 'CreateWorkers' RETURN f.name LIMIT 1"
    )
    print(f"Status: {result1.get('status')}")
    print(f"Data: {result1.get('data')}")
    print(f"Error: {result1.get('error')}")

    print("\n" + "=" * 80)
    print("Test 2: Invalid property (Function.invalid_property)")
    print("=" * 80)
    result2 = await server.execute_query(
        "MATCH (f:Function) WHERE f.invalid_property = 'test' RETURN f.name"
    )
    print(f"Status: {result2.get('status')}")
    print(f"Data: {result2.get('data')}")
    print(f"Error: {result2.get('error')}")

    print("\n" + "=" * 80)
    print("Test 3: Return invalid property")
    print("=" * 80)
    result3 = await server.execute_query(
        "MATCH (f:Function) RETURN f.invalid_property LIMIT 3"
    )
    print(f"Status: {result3.get('status')}")
    print(f"Data: {result3.get('data')}")
    print(f"Error: {result3.get('error')}")
    
    await server.stop()

asyncio.run(test())
