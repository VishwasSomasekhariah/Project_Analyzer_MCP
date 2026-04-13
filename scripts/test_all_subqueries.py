#!/usr/bin/env python3
"""
Generate separate JSON outputs for each subquery from the approach packet.
"""
import asyncio
import yaml
import sys
import json
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


async def main():
    # Test subqueries from approach packet
    subqueries = [
        {
            "id": "SQ1",
            "text": "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'",
            "output_file": "/tmp/subquery_SQ1_output.json"
        },
        {
            "id": "SQ2",
            "text": "collect all CALLS edges from F to constructor Functions ctorFn and for each ctorFn locate its declaring Type node C and retrieve C.name",
            "output_file": "/tmp/subquery_SQ2_output.json"
        },
        {
            "id": "SQ3",
            "text": "locate all return-statement Statement nodes within F and for each returned expression that is a new instantiation, resolve the constructor call and retrieve the associated Type name",
            "output_file": "/tmp/subquery_SQ3_output.json"
        },
        {
            "id": "SQ4",
            "text": "locate Variable nodes V declared in F whose initial_value expressions include new instantiations and for each instantiation identify the Type node C and retrieve C.name",
            "output_file": "/tmp/subquery_SQ4_output.json"
        }
    ]

    print("=" * 80)
    print("GENERATING JSON OUTPUTS FOR ALL SUBQUERIES")
    print("=" * 80)
    print()

    # Initialize schema manager once
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/all_subqueries_cache.json",
        yaml_schema=yaml_schema
    )

    print("Initializing schema manager...")
    await schema_manager.initialize_background()
    print("✅ Initialized\n")

    # Process each subquery
    for sq in subqueries:
        print(f"{'='*80}")
        print(f"Processing {sq['id']}")
        print(f"{'='*80}")
        print(f"Text: {sq['text'][:80]}...")
        print()

        # Call API
        result = await schema_manager.get_schema_for_subquery(
            subquery_text=sq['text'],
            format='text',
            max_path_depth=5
        )

        # Save to JSON
        json_result = {
            'subquery_id': sq['id'],
            'subquery_text': sq['text'],
            'node_types': result['node_types'],
            'relationship_types': result['relationship_types'],
            'node_schemas': result['node_schemas'],
            'relationship_schemas': result['relationship_schemas'],
            'paths': result['paths'],
            'schema_text': result['schema_text'],
            'extraction_method': result['extraction_method'],
            'extraction_params': result['extraction_params'],
            'cache_stats': result['cache_stats']
        }

        with open(sq['output_file'], 'w') as f:
            json.dump(json_result, f, indent=2)

        print(f"✅ Saved to: {sq['output_file']}")
        print(f"   • Extracted {len(result['node_types'])} node types: {result['node_types']}")
        print(f"   • Extracted {len(result['relationship_types'])} relationship types: {result['relationship_types']}")
        print(f"   • Discovered {len(result['paths'])} path patterns")
        print()

    print("=" * 80)
    print("ALL SUBQUERIES PROCESSED")
    print("=" * 80)
    print()
    print("Output files:")
    for sq in subqueries:
        print(f"  • {sq['id']}: {sq['output_file']}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
