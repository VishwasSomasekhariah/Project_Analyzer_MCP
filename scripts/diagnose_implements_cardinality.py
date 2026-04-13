#!/usr/bin/env python3
"""
Diagnostic script to check IMPLEMENTS relationship cardinality in Neo4j.

This will help us understand what the DynamicSchemaManager would have built
for the IMPLEMENTS relationship and why the LLM thought (Function, Type) wasn't valid.
"""
import asyncio
import sys
sys.path.append('/opt/genpod/test_results/test_scripts')

from mcp_use import MCPClient, MCPSession


async def check_implements_cardinality():
    """Check what cardinality pairs exist for IMPLEMENTS in Neo4j."""

    print("="*100)
    print("DIAGNOSING IMPLEMENTS RELATIONSHIP CARDINALITY")
    print("="*100)

    # Connect to Neo4j MCP server
    config_path = '/opt/genpod/neo4j_config.json'

    async with MCPClient() as client:
        async with MCPSession(client, config_path) as session:
            # Query all IMPLEMENTS pairs (this is what DynamicSchemaManager does)
            query = """
            MATCH (s)-[r:IMPLEMENTS]->(t)
            WITH labels(s)[0] AS source, labels(t)[0] AS target
            RETURN source, target, count(*) AS count
            ORDER BY count DESC
            """

            print("\n📊 Querying Neo4j for all IMPLEMENTS relationship pairs...")
            result = await session.execute_query(query)

            if 'data' in result and result['data']:
                print(f"\n✅ Found {len(result['data'])} unique IMPLEMENTS pairs:\n")
                print(f"{'Source':<20} → {'Target':<20} {'Count':<10}")
                print("-" * 100)

                for row in result['data']:
                    source = row['source']
                    target = row['target']
                    count = row['count']

                    marker = " ⭐" if source == 'Function' and target == 'Type' else ""
                    print(f"{source:<20} → {target:<20} {count:<10}{marker}")

                # Check specifically for (Function, Type)
                func_to_type = [row for row in result['data']
                               if row['source'] == 'Function' and row['target'] == 'Type']

                print("\n" + "="*100)
                if func_to_type:
                    count = func_to_type[0]['count']
                    print(f"✅ (Function)-[:IMPLEMENTS]->(Type) EXISTS with {count} instances")
                    print("\n💡 This pair SHOULD be in the reconciled schema cardinality!")
                else:
                    print("❌ (Function)-[:IMPLEMENTS]->(Type) NOT FOUND")
                    print("\n⚠️  This would explain why LLM couldn't use it!")

            else:
                print("\n❌ No results found for IMPLEMENTS relationship")
                print("Result:", result)

            # Now check what the reconciled schema format would look like
            print("\n" + "="*100)
            print("SIMULATING RECONCILED SCHEMA FORMAT")
            print("="*100)

            if 'data' in result and result['data']:
                cardinality = []
                for row in result['data']:
                    cardinality.append({
                        'from': row['source'],
                        'to': row['target']
                    })

                print("\nreconciled_schema['relationships']['IMPLEMENTS'] would contain:")
                print("{")
                print("  'description': '...',")
                print(f"  'cardinality': {cardinality[:10]}...")  # Show first 10
                print("  'properties': [...],")
                print("  'count': ...")
                print("}")

                # Check if Function→Type is in cardinality
                has_func_type = any(c['from'] == 'Function' and c['to'] == 'Type'
                                   for c in cardinality)

                print(f"\n(Function, Type) in cardinality list: {has_func_type}")


if __name__ == '__main__':
    asyncio.run(check_implements_cardinality())
