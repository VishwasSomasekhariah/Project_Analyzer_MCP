"""Test if Function→Statement paths exist in the graph."""
import asyncio
import sys
sys.path.insert(0, '/opt/genpod')

from src.core.mcp_use.cypher_server import CypherServer

async def main():
    server = CypherServer('neo4j_config.json')
    await server.initialize()

    print("Testing paths from Function to Statement...\n")

    # Test 1: Direct REFERENCES path
    query1 = """
    MATCH path = (f:Function)-[:REFERENCES]->(s:Statement)
    RETURN count(path) as count
    """
    result1 = await server.execute_query(query1)
    direct_count = result1['data'][0]['count'] if result1.get('data') else 0
    print(f"1. Direct Function-[:REFERENCES]->Statement paths: {direct_count}")

    # Test 2: Via Block using CONTAINS
    query2 = """
    MATCH path = (f:Function)-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)
    RETURN count(path) as count
    """
    result2 = await server.execute_query(query2)
    via_block_count = result2['data'][0]['count'] if result2.get('data') else 0
    print(f"2. Function-[:CONTAINS]->Block-[:CONTAINS]->Statement paths: {via_block_count}")

    # Test 3: Use APOC to find ALL paths (same as discovery code)
    query3 = """
    MATCH (f:Function)
    WITH f LIMIT 10

    CALL apoc.path.expandConfig(f, {
        minLevel: 1,
        maxLevel: 5,
        relationshipFilter: 'REFERENCES>|<REFERENCES|CONTAINS>|IMPLEMENTS>|<IMPLEMENTS|CALLS>',
        uniqueness: 'RELATIONSHIP_PATH',
        bfs: true,
        limit: 100
    })
    YIELD path

    WHERE labels(nodes(path)[-1])[0] = 'Statement'

    WITH nodes(path) AS all_nodes,
         relationships(path) AS all_rels,
         length(path) AS depth

    WITH [rel IN all_rels | type(rel)] AS rels,
         CASE
            WHEN size(all_nodes) > 2
            THEN [node IN all_nodes[1..-1] | labels(node)[0]]
            ELSE []
         END AS via,
         depth

    RETURN DISTINCT rels, via, depth
    ORDER BY depth
    LIMIT 50
    """
    result3 = await server.execute_query(query3)
    print(f"\n3. APOC discovered paths from Function to Statement:")
    if result3.get('data'):
        for i, row in enumerate(result3['data'], 1):
            rels = row['rels']
            via = row['via']
            depth = row['depth']
            if depth == 1:
                print(f"   {i}. Direct: -[{rels[0]}]->")
            else:
                path_str = []
                for j, rel in enumerate(rels):
                    if j < len(via):
                        path_str.append(f"-[{rel}]-> {via[j]}")
                    else:
                        path_str.append(f"-[{rel}]->")
                print(f"   {i}. {depth}-hop: {' '.join(path_str)}")
    else:
        print("   No paths found!")

    await server.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
