#!/usr/bin/env python3
"""
Check if CONTAINS edges exist between Function and Type in the actual CPG
"""
import asyncio
import sys
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service

async def main():
    print("Checking CONTAINS edges in CPG...")
    print("=" * 80)

    cypher_server = await create_cypher_server_service("neo4j_config.json")

    # Check Function outgoing relationships
    query1 = """
    MATCH (f:Function)-[r]->(n)
    RETURN type(r) as rel_type, labels(n)[0] as target_label, count(*) as count
    ORDER BY count DESC
    """

    result1 = await cypher_server.execute_query(query1)
    print("\n📊 Function OUTGOING relationships:")
    if result1.get('success'):
        for row in result1['results'][:20]:
            print(f"   {row['rel_type']:20s} → {row['target_label']:15s} [{row['count']} edges]")

    # Specifically check Function-CONTAINS->Type
    query2 = """
    MATCH (f:Function)-[r:CONTAINS]->(t:Type)
    RETURN count(*) as count
    """

    result2 = await cypher_server.execute_query(query2)
    print("\n🔍 Function-CONTAINS->Type:")
    if result2.get('success') and result2['results']:
        count = result2['results'][0]['count']
        if count > 0:
            print(f"   ✅ Found {count} CONTAINS edges from Function to Type")
        else:
            print(f"   ❌ NO CONTAINS edges from Function to Type")

    # Check what Function DOES contain
    query3 = """
    MATCH (f:Function)-[r:CONTAINS]->(n)
    RETURN labels(n)[0] as target, count(*) as count
    ORDER BY count DESC
    """

    result3 = await cypher_server.execute_query(query3)
    print("\n📦 What Function CONTAINS:")
    if result3.get('success') and result3['results']:
        for row in result3['results']:
            print(f"   Function -CONTAINS-> {row['target']:15s} [{row['count']} edges]")
    else:
        print("   ❌ Function doesn't CONTAIN anything!")

    # Check reverse: Type-CONTAINS->Function
    query4 = """
    MATCH (t:Type)-[r:CONTAINS]->(f:Function)
    RETURN count(*) as count
    """

    result4 = await cypher_server.execute_query(query4)
    print("\n🔄 Type-CONTAINS->Function (reverse direction):")
    if result4.get('success') and result4['results']:
        count = result4['results'][0]['count']
        if count > 0:
            print(f"   ✅ Found {count} CONTAINS edges from Type to Function")
            print(f"   → This is the CORRECT direction for 'Type contains Function'")
        else:
            print(f"   ❌ NO CONTAINS edges from Type to Function")

    print("\n" + "=" * 80)
    print("CONCLUSION:")
    print("=" * 80)
    print("If Function-CONTAINS->Type doesn't exist but Type-CONTAINS->Function does,")
    print("then the query 'Function F is contained in Type T' should look for:")
    print("   Type -CONTAINS-> Function")
    print("NOT:")
    print("   Function -CONTAINS-> Type")
    print()

if __name__ == "__main__":
    asyncio.run(main())
