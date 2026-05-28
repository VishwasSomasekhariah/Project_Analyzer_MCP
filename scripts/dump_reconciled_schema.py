#!/usr/bin/env python3
"""
Simply dump the reconciled schema to a JSON file for reference.
"""
import asyncio
import yaml
import sys
import json
sys.path.insert(0, '/opt/genpod')

from src.core.workflow.cypher_server_pool import CypherServerInstance
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


async def main():
    print("Initializing schema manager...")

    # Use CypherServerInstance (same as workflow's single-server mode)
    server = CypherServerInstance(server_id=0, neo4j_config="neo4j_config.json")
    await server.start()

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/dump_schema_cache.json",
        yaml_schema=yaml_schema,
        embedding_model='all-MiniLM-L6-v2'
    )

    await schema_manager.initialize_background()
    print("✅ Schema manager initialized")

    # Get reconciled schema
    reconciled = schema_manager._reconciled_schema

    # Save to tmp
    output_file = '/tmp/reconciled_schema_complete.json'
    with open(output_file, 'w') as f:
        json.dump(reconciled, f, indent=2)

    print(f"\n✅ Reconciled schema saved to: {output_file}")

    # Print summary
    if reconciled:
        print(f"\nNode types ({len(reconciled['nodes'])}):")
        for node_type in reconciled['nodes'].keys():
            count = reconciled['nodes'][node_type].get('count', 0)
            print(f"  - {node_type} (count: {count})")

        print(f"\nRelationship types ({len(reconciled['relationships'])}):")
        for rel_type in reconciled['relationships'].keys():
            count = reconciled['relationships'][rel_type].get('count', 0)
            cardinality_count = len(reconciled['relationships'][rel_type].get('cardinality', []))
            print(f"  - {rel_type} (count: {count}, valid pairs: {cardinality_count})")

    # Cleanup
    await server.stop()
    print("\n✅ Server stopped")

if __name__ == "__main__":
    asyncio.run(main())
