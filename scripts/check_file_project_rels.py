"""Check if Neo4j database has File -> Project relationships"""
import asyncio
import sys
sys.path.insert(0, '/opt/genpod')

from src.core.workflow.cypher_server_service import create_cypher_server_service

async def check_relationships():
    server = await create_cypher_server_service("neo4j_config.json")
    
    # Check File -> Project relationships
    query1 = """
    MATCH (f:File)-[:CONTAINS]->(p:Project)
    RETURN count(*) as count
    """
    result1 = await server.execute_query(query1)
    file_to_project = result1.get('data', [{}])[0].get('count', 0)
    
    # Check Project -> File relationships
    query2 = """
    MATCH (p:Project)-[:CONTAINS]->(f:File)
    RETURN count(*) as count
    """
    result2 = await server.execute_query(query2)
    project_to_file = result2.get('data', [{}])[0].get('count', 0)
    
    print("=" * 80)
    print("CHECKING ACTUAL NEO4J DATABASE")
    print("=" * 80)
    print(f"\nFile → Project (CONTAINS): {file_to_project} {'❌ (WRONG!)' if file_to_project > 0 else '✅ (correct)'}")
    print(f"Project → File (CONTAINS): {project_to_file} {'✅ (correct)' if project_to_file > 0 else '❌ (missing!)'}")
    
    if file_to_project > 0:
        # Show examples
        query3 = """
        MATCH (f:File)-[:CONTAINS]->(p:Project)
        RETURN f.name as file_name, p.name as project_name
        LIMIT 5
        """
        result3 = await server.execute_query(query3)
        print(f"\n🔍 Example File → Project relationships:")
        for row in result3.get('data', []):
            print(f"   {row['file_name']} → {row['project_name']}")

asyncio.run(check_relationships())
