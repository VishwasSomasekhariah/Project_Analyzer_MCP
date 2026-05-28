#!/usr/bin/env python3
"""Quick test to check actual paths in the database."""
import asyncio
from src.core.graph_rag.ir import MultiAgentIRCoT
from src.core.graph_rag.core.config import SystemConfig

async def check_paths():
    config = SystemConfig(
        mcp_config_path="neo4j_config.json",
        yaml_schema_path="/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml",
        llm_model="gpt-4o",
    )

    system = MultiAgentIRCoT(config)
    await system.initialize()

    # Query actual paths to Type nodes (classes)
    queries = [
        # Path to Type
        """
        MATCH path = (p:Project)-[:CONTAINS*1..5]->(t:Type)
        WHERE p.name = "HelloWorldApp"
        WITH path, [n in nodes(path) | labels(n)[0]] as node_labels, [r in relationships(path) | type(r)] as rel_types
        RETURN DISTINCT node_labels, rel_types, length(path) as depth
        ORDER BY depth
        LIMIT 15
        """,
        # Path to Function
        """
        MATCH path = (p:Project)-[:CONTAINS*1..6]->(f:Function)
        WHERE p.name = "HelloWorldApp"
        WITH path, [n in nodes(path) | labels(n)[0]] as node_labels, [r in relationships(path) | type(r)] as rel_types
        RETURN DISTINCT node_labels, rel_types, length(path) as depth
        ORDER BY depth
        LIMIT 15
        """,
        # Check what's directly in Project
        """
        MATCH (p:Project {name: "HelloWorldApp"})-[r]->(child)
        RETURN labels(child)[0] as child_type, type(r) as rel_type, count(*) as count
        """,
        # Check what's in Files
        """
        MATCH (p:Project {name: "HelloWorldApp"})-[:CONTAINS]->(f:File)-[r]->(child)
        RETURN labels(child)[0] as child_type, type(r) as rel_type, count(*) as count
        """,
        # Check if there ARE any Type nodes with classes
        """
        MATCH (p:Project {name: "HelloWorldApp"})-[:CONTAINS*1..5]->(t:Type)
        RETURN t.name as type_name, t.type_kind as kind, t.full_qualified_name as fqn
        LIMIT 10
        """,
    ]

    for i, query in enumerate(queries, 1):
        print(f"\n{'='*60}")
        print(f"Query {i}:")
        print(f"{'='*60}")
        result = await system._tool_manager.execute_tool('neo4j_execute_query', {'query': query.strip()})
        print(result)

    await system.shutdown()

if __name__ == '__main__':
    asyncio.run(check_paths())
